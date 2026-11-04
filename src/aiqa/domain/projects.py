"""Project create, composite scope, and the per-project commit clock."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from uuid import UUID, uuid4

from aiqa.store.database import Store
from aiqa.store.models import Actor, ProjectCreate, ProjectView, Transaction

_store: ContextVar[Store] = ContextVar("aiqa_project_store")


class ProjectConflict(Exception):
    """A unique project key is already stored."""


class ProjectScopeDenied(Exception):
    """The child row is not in the project named by the request."""


class ProjectValidationError(Exception):
    def __init__(self, fields: dict[str, list[str]]) -> None:
        super().__init__("invalid project")
        self.fields = fields


class MembershipDenied(Exception):
    """The actor has no active membership for the requested capability."""


MEMBERSHIP_ROLES = frozenset({"viewer", "operator", "admin"})
CAPABILITY_ROLES = {
    "project_view": frozenset({"viewer", "operator", "admin"}),
    "evidence_download": frozenset({"viewer", "operator", "admin"}),
    "approve": frozenset({"admin"}),
    "worker_manage": frozenset({"admin"}),
}


@contextmanager
def bind_store(store: Store) -> Iterator[None]:
    token = _store.set(store)
    try:
        yield
    finally:
        _store.reset(token)


def create_project(actor: Actor, project: ProjectCreate) -> ProjectView:
    _require_text(project.name, "name")
    _require_text(project.key, "key")
    _require_text(project.target, "target")
    if type(project.description) is not str:
        raise ProjectValidationError({"description": ["required"]})
    store = _bound_store()
    project_id = uuid4()
    audit_id = uuid4()
    created_at = datetime.now(timezone.utc).isoformat()
    try:
        with store.transaction() as connection:
            tx = Transaction(connection)
            connection.execute(
                """
                INSERT INTO projects (
                    project_id, key, name, description, target, created_at,
                    actor_id, actor_project_scope, actor_is_local_owner
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(project_id),
                    project.key,
                    project.name,
                    project.description,
                    project.target,
                    created_at,
                    str(actor.actor_id),
                    None if actor.project_scope is None else str(actor.project_scope),
                    1 if actor.is_local_owner else 0,
                ),
            )
            connection.execute(
                "INSERT INTO project_commit_clock (project_id, commit_seq) VALUES (?, 0)",
                (str(project_id),),
            )
            commit_seq = next_commit_seq(tx, project_id)
            connection.execute(
                """
                INSERT INTO project_audits (
                    project_id, audit_id, commit_seq, actor_id, action, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(project_id),
                    str(audit_id),
                    commit_seq,
                    str(actor.actor_id),
                    "create",
                    created_at,
                ),
            )
    except sqlite3.IntegrityError as exc:
        raise ProjectConflict("project key already exists") from exc
    return ProjectView(
        project_id=project_id,
        name=project.name,
        key=project.key,
        description=project.description,
        target=project.target,
        commit_seq=commit_seq,
        audit_id=audit_id,
    )


def list_projects(archived: bool, query: str) -> tuple[ProjectView, ...]:
    """Active projects by default. A search matches the name or the key."""

    store = _bound_store()
    needle = f"%{_plain(query)}%"
    flag = 1 if archived else 0
    with store.transaction() as connection:
        rows = connection.execute(
            """
            SELECT project_id
            FROM projects
            WHERE ((? = 0 AND archived_at IS NULL) OR (? = 1 AND archived_at IS NOT NULL))
              AND (? = '' OR name LIKE ? OR key LIKE ?)
            ORDER BY name, key
            """,
            (flag, flag, query, needle, needle),
        ).fetchall()
        return tuple(_project_view(connection, UUID(str(row[0]))) for row in rows)


def get_project(project_id: UUID) -> ProjectView | None:
    store = _bound_store()
    with store.transaction() as connection:
        row = connection.execute(
            "SELECT project_id FROM projects WHERE project_id = ?",
            (str(project_id),),
        ).fetchone()
        if row is None:
            return None
        return _project_view(connection, project_id)


def archive_project(actor: Actor, project_id: UUID) -> ProjectView:
    """Keep history and refuse while a recording or job is still active."""

    return _set_archive(actor, project_id, archived=True)


def restore_project(actor: Actor, project_id: UUID) -> ProjectView:
    """Return an archived project to the active list and record the audit."""

    return _set_archive(actor, project_id, archived=False)


def grant_membership(
    tx: Transaction,
    project_id: UUID,
    actor_id: UUID,
    role: str,
    *,
    now: datetime | None = None,
) -> None:
    if role not in MEMBERSHIP_ROLES:
        raise ProjectValidationError({"role": ["unsupported"]})
    moment = (now or datetime.now(timezone.utc)).isoformat()
    tx.connection.execute(
        """
        INSERT INTO project_memberships (project_id, actor_id, role, created_at, revoked_at)
        VALUES (?, ?, ?, ?, NULL)
        ON CONFLICT(project_id, actor_id) DO UPDATE SET
            role = excluded.role,
            created_at = excluded.created_at,
            revoked_at = NULL
        """,
        (str(project_id), str(actor_id), role, moment),
    )


def revoke_membership(
    tx: Transaction,
    project_id: UUID,
    actor_id: UUID,
    *,
    now: datetime | None = None,
) -> None:
    moment = (now or datetime.now(timezone.utc)).isoformat()
    updated = tx.connection.execute(
        """
        UPDATE project_memberships
        SET revoked_at = ?
        WHERE project_id = ? AND actor_id = ? AND revoked_at IS NULL
        """,
        (moment, str(project_id), str(actor_id)),
    )
    if updated.rowcount != 1:
        raise MembershipDenied("membership was not found")


def active_membership_role(tx: Transaction, project_id: UUID, actor_id: UUID) -> str | None:
    row = tx.connection.execute(
        """
        SELECT role FROM project_memberships
        WHERE project_id = ? AND actor_id = ? AND revoked_at IS NULL
        """,
        (str(project_id), str(actor_id)),
    ).fetchone()
    return None if row is None else str(row[0])


def require_project_capability(
    tx: Transaction,
    actor: Actor,
    project_id: UUID,
    capability: str,
) -> str:
    """Return the effective role or raise. Local owners keep full access in their scope."""

    if capability not in CAPABILITY_ROLES:
        raise MembershipDenied("capability is unknown")
    if actor.is_local_owner and actor.project_scope == project_id:
        return "admin"
    if actor.is_local_owner and actor.project_scope is None:
        return "admin"
    role = active_membership_role(tx, project_id, actor.actor_id)
    if role is None or role not in CAPABILITY_ROLES[capability]:
        raise MembershipDenied(f"{capability} was denied")
    return role


def next_commit_seq(tx: Transaction, project_id: UUID) -> int:
    row = tx.connection.execute(
        "SELECT commit_seq FROM project_commit_clock WHERE project_id = ?",
        (str(project_id),),
    ).fetchone()
    if row is None:
        raise ProjectScopeDenied("project clock is missing")
    commit_seq = int(row[0]) + 1
    tx.connection.execute(
        "UPDATE project_commit_clock SET commit_seq = ? WHERE project_id = ?",
        (commit_seq, str(project_id)),
    )
    return commit_seq


def get_audit(project_id: UUID, audit_id: UUID) -> dict[str, object] | None:
    store = _bound_store()
    with store.transaction() as connection:
        row = connection.execute(
            """
            SELECT audit_id, commit_seq, action
            FROM project_audits
            WHERE project_id = ? AND audit_id = ?
            """,
            (str(project_id), str(audit_id)),
        ).fetchone()
    if row is None:
        return None
    return {"audit_id": str(row[0]), "commit_seq": int(row[1]), "action": str(row[2])}


def link_audit(project_id: UUID, audit_id: UUID, note: str) -> None:
    _require_text(note, "note")
    store = _bound_store()
    try:
        with store.transaction() as connection:
            commit_seq = next_commit_seq(Transaction(connection), project_id)
            connection.execute(
                """
                INSERT INTO project_audit_links (project_id, audit_id, note, commit_seq)
                VALUES (?, ?, ?, ?)
                """,
                (str(project_id), str(audit_id), note, commit_seq),
            )
    except ProjectScopeDenied:
        raise
    except sqlite3.IntegrityError as exc:
        raise ProjectScopeDenied("audit is outside this project") from exc


def _set_archive(actor: Actor, project_id: UUID, archived: bool) -> ProjectView:
    store = _bound_store()
    moment = datetime.now(timezone.utc).isoformat()
    audit_id = uuid4()
    action = "archive" if archived else "restore"
    try:
        with store.transaction() as connection:
            row = connection.execute(
                "SELECT archived_at FROM projects WHERE project_id = ?",
                (str(project_id),),
            ).fetchone()
            if row is None:
                raise ProjectScopeDenied("project is missing")
            current = row[0]
            if archived and current is not None:
                raise ProjectConflict("project is already archived")
            if not archived and current is None:
                raise ProjectConflict("project is active")
            if archived and _work_is_active(connection, project_id):
                raise ProjectConflict("project has active work")
            connection.execute(
                "UPDATE projects SET archived_at = ? WHERE project_id = ?",
                (moment if archived else None, str(project_id)),
            )
            commit_seq = next_commit_seq(Transaction(connection), project_id)
            connection.execute(
                """
                INSERT INTO project_audits (
                    project_id, audit_id, commit_seq, actor_id, action, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (str(project_id), str(audit_id), commit_seq, str(actor.actor_id), action, moment),
            )
            return _project_view(connection, project_id, audit_id, commit_seq)
    except sqlite3.IntegrityError as exc:
        raise ProjectConflict("project archive was rejected") from exc


def _work_is_active(connection: sqlite3.Connection, project_id: UUID) -> bool:
    row = connection.execute(
        """
        SELECT 1 FROM jobs
        WHERE project_id = ?
          AND status IN ('queued', 'preparing', 'running', 'finalizing', 'cancel_requested')
        UNION ALL
        SELECT 1 FROM recordings
        WHERE project_id = ? AND stop_status = 'running'
        LIMIT 1
        """,
        (str(project_id), str(project_id)),
    ).fetchone()
    return row is not None


def _project_view(
    connection: sqlite3.Connection,
    project_id: UUID,
    audit_id: UUID | None = None,
    commit_seq: int | None = None,
) -> ProjectView:
    row = connection.execute(
        """
        SELECT name, key, description, target, archived_at
        FROM projects WHERE project_id = ?
        """,
        (str(project_id),),
    ).fetchone()
    if row is None:
        raise ProjectScopeDenied("project is missing")
    if commit_seq is None:
        clock = connection.execute(
            "SELECT commit_seq FROM project_commit_clock WHERE project_id = ?",
            (str(project_id),),
        ).fetchone()
        commit_seq = 0 if clock is None else int(clock[0])
    if audit_id is None:
        latest = connection.execute(
            """
            SELECT audit_id FROM project_audits
            WHERE project_id = ? ORDER BY commit_seq DESC LIMIT 1
            """,
            (str(project_id),),
        ).fetchone()
        audit_id = uuid4() if latest is None else UUID(str(latest[0]))
    cases = connection.execute(
        """
        SELECT COUNT(*) FROM automation_cases
        WHERE project_id = ? AND archived_at IS NULL
        """,
        (str(project_id),),
    ).fetchone()
    reviews = connection.execute(
        "SELECT COUNT(*) FROM reviews WHERE project_id = ?",
        (str(project_id),),
    ).fetchone()
    runs = connection.execute(
        """
        SELECT COUNT(*) FROM jobs
        WHERE project_id = ? AND purpose IN ('trial', 'regression')
        """,
        (str(project_id),),
    ).fetchone()
    return ProjectView(
        project_id=project_id,
        name=str(row[0]),
        key=str(row[1]),
        description=str(row[2]),
        target=str(row[3]),
        commit_seq=commit_seq,
        audit_id=audit_id,
        archived_at=None if row[4] is None else str(row[4]),
        case_count=0 if cases is None else int(cases[0]),
        review_count=0 if reviews is None else int(reviews[0]),
        run_count=0 if runs is None else int(runs[0]),
    )


def _plain(query: str) -> str:
    if type(query) is not str:
        return ""
    return query.replace("%", "").replace("_", "")


def _bound_store() -> Store:
    try:
        return _store.get()
    except LookupError as exc:
        raise RuntimeError("project store is not bound") from exc


def _require_text(value: str, field: str) -> None:
    if type(value) is not str or value.strip() == "":
        raise ProjectValidationError({field: ["required"]})
