"""Case classification, cursor list, clone, and archive. This does not store a recording."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from aiqa.domain.hashing import execution_snapshot_hash
from aiqa.domain.versions import definition_from_document, persist_projection, ensure_projection_tables

from aiqa.store.database import Store
from aiqa.store.models import Actor, CaseListQuery, CaseListRow, CaseView, CloneCaseInput, CursorPage

_store: ContextVar[Store] = ContextVar("aiqa_catalog_store")
_actor: ContextVar[Actor] = ContextVar("aiqa_catalog_actor")
_SORTS = {"name": "automation_cases.name", "priority": "COALESCE(automation_cases.priority, '')", "case_id": "automation_cases.case_id"}
_PRIORITIES = {"low", "normal", "high"}


class CatalogNotFound(Exception):
    """The case or folder is not in this project."""


class FolderCycle(Exception):
    """The folder parent would form a cycle."""


class StaleRevision(Exception):
    """The case lock changed."""


class ActiveRecording(Exception):
    """An open recording still belongs to this case."""


@dataclass(frozen=True, slots=True)
class ProjectOverview:
    """Counts read from stored rows. This view has no pass rate."""

    project_id: UUID
    incomplete_recordings: int
    reviews_waiting: int
    unclassified_failures: int
    running_runs: int
    queued_runs: int
    blocked_environments: int
    draft_cases: int
    approved_cases: int
    recent_scope: str | None
    recent_result: str | None
    new_recording_href: str
    saved_cases_href: str
    bundle_href: str


@contextmanager
def bind_catalog_store(store: Store) -> Iterator[None]:
    token = _store.set(store)
    try:
        yield
    finally:
        _store.reset(token)


@contextmanager
def bind_catalog_actor(actor: Actor) -> Iterator[None]:
    token = _actor.set(actor)
    try:
        yield
    finally:
        _actor.reset(token)


def create_folder(name: str, parent_folder_id: UUID | None) -> UUID:
    actor = _require_actor()
    if name.strip() == "":
        raise ValueError("folder name is required")
    folder_id = uuid4()
    with _bound_store().transaction() as connection:
        if parent_folder_id is not None and not _folder_exists(connection, actor, parent_folder_id):
            raise CatalogNotFound("folder was not found")
        connection.execute(
            """
            INSERT INTO folders (project_id, folder_id, parent_folder_id, name)
            VALUES (?, ?, ?, ?)
            """,
            (
                str(actor.project_scope),
                str(folder_id),
                None if parent_folder_id is None else str(parent_folder_id),
                name,
            ),
        )
    return folder_id


def update_folder(folder_id: UUID, parent_folder_id: UUID | None) -> None:
    actor = _require_actor()
    with _bound_store().transaction() as connection:
        if not _folder_exists(connection, actor, folder_id):
            raise CatalogNotFound("folder was not found")
        if parent_folder_id is not None:
            if parent_folder_id == folder_id or _reaches(connection, actor, parent_folder_id, folder_id):
                raise FolderCycle("folder parent cycles")
            if not _folder_exists(connection, actor, parent_folder_id):
                raise CatalogNotFound("folder was not found")
        connection.execute(
            "UPDATE folders SET parent_folder_id = ? WHERE project_id = ? AND folder_id = ?",
            (
                None if parent_folder_id is None else str(parent_folder_id),
                str(actor.project_scope),
                str(folder_id),
            ),
        )


def create_tag(name: str) -> UUID:
    actor = _require_actor()
    if name.strip() == "":
        raise ValueError("tag name is required")
    tag_id = uuid4()
    with _bound_store().transaction() as connection:
        connection.execute(
            "INSERT INTO tags (project_id, tag_id, name) VALUES (?, ?, ?)",
            (str(actor.project_scope), str(tag_id), name),
        )
    return tag_id


def update_case_metadata(
    case_id: UUID,
    expected_revision: int,
    folder_id: UUID | None,
    tags: tuple[str, ...],
    priority: str | None,
    assignee_id: UUID | None,
) -> CaseView:
    actor = _require_actor()
    if priority is not None and priority not in _PRIORITIES:
        raise ValueError("invalid priority")
    with _bound_store().transaction() as connection:
        if folder_id is not None and not _folder_exists(connection, actor, folder_id):
            raise CatalogNotFound("folder was not found")
        tag_ids: list[str] = []
        for name in tags:
            row = connection.execute(
                "SELECT tag_id FROM tags WHERE project_id = ? AND name = ?",
                (str(actor.project_scope), name),
            ).fetchone()
            if row is None:
                raise ValueError("unknown tag")
            tag_ids.append(str(row[0]))
        updated = connection.execute(
            """
            UPDATE automation_cases
            SET folder_id = ?, priority = ?, assignee_id = ?, lock_version = lock_version + 1
            WHERE project_id = ? AND case_id = ? AND lock_version = ?
            """,
            (
                None if folder_id is None else str(folder_id),
                priority,
                None if assignee_id is None else str(assignee_id),
                str(actor.project_scope),
                str(case_id),
                expected_revision,
            ),
        )
        if updated.rowcount != 1:
            if _case_row(connection, actor, case_id) is None:
                raise CatalogNotFound("case was not found")
            raise StaleRevision("case lock changed")
        connection.execute(
            "DELETE FROM case_tag_links WHERE project_id = ? AND case_id = ?",
            (str(actor.project_scope), str(case_id)),
        )
        for tag_id in tag_ids:
            connection.execute(
                "INSERT INTO case_tag_links (project_id, case_id, tag_id) VALUES (?, ?, ?)",
                (str(actor.project_scope), str(case_id), tag_id),
            )
        row = _case_row(connection, actor, case_id)
    if row is None:
        raise CatalogNotFound("case was not found")
    return _view(actor, case_id, row)


def list_cases(query: CaseListQuery) -> CursorPage:
    if query.sort not in _SORTS:
        raise ValueError("invalid sort")
    if query.limit < 1 or query.limit > 100:
        raise ValueError("invalid limit")
    actor = _require_actor()
    if actor.project_scope != query.project_id:
        raise CatalogNotFound("case was not found")
    order = _SORTS[query.sort]
    clauses = ["automation_cases.project_id = ?"]
    params: list[object] = [str(query.project_id)]
    if query.view not in {"", "all", "ready", "draft", "review", "incomplete", "archived"}:
        raise ValueError("invalid view")
    if query.archived or query.view == "archived":
        clauses.append("automation_cases.archived_at IS NOT NULL")
    else:
        clauses.append("automation_cases.archived_at IS NULL")
    if query.view == "ready":
        clauses.append("automation_cases.current_approval_id IS NOT NULL")
    elif query.view == "draft":
        clauses.append(
            "automation_cases.latest_draft_version_id IS NOT NULL AND automation_cases.current_approval_id IS NULL"
        )
    elif query.view == "review":
        clauses.append(
            """
            EXISTS (
                SELECT 1 FROM reviews
                WHERE reviews.project_id = automation_cases.project_id
                  AND reviews.case_id = automation_cases.case_id
                  AND NOT EXISTS (
                    SELECT 1 FROM approval_events
                    WHERE approval_events.project_id = reviews.project_id
                      AND approval_events.review_id = reviews.review_id
                  )
            )
            """
        )
    elif query.view == "incomplete":
        clauses.append(
            """
            EXISTS (
                SELECT 1 FROM recordings
                WHERE recordings.project_id = automation_cases.project_id
                  AND recordings.case_id = automation_cases.case_id
                  AND (recordings.completion_status = 'open' OR recordings.stop_status = 'running')
            )
            """
        )
    if query.text.strip() != "":
        escaped = query.text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        clauses.append("automation_cases.name LIKE ? ESCAPE '\\'")
        params.append(f"%{escaped}%")
    if query.folder_id is not None:
        clauses.append("automation_cases.folder_id = ?")
        params.append(str(query.folder_id))
    if query.priority is not None:
        clauses.append("automation_cases.priority = ?")
        params.append(query.priority)
    if query.assignee_id is not None:
        clauses.append("automation_cases.assignee_id = ?")
        params.append(str(query.assignee_id))
    if query.tag is not None:
        clauses.append(
            """
            EXISTS (
                SELECT 1 FROM case_tag_links
                JOIN tags ON tags.project_id = case_tag_links.project_id AND tags.tag_id = case_tag_links.tag_id
                WHERE case_tag_links.project_id = automation_cases.project_id
                  AND case_tag_links.case_id = automation_cases.case_id
                  AND tags.name = ?
            )
            """
        )
        params.append(query.tag)
    connection = _bound_store()._connection
    if query.cursor is not None:
        anchor = connection.execute(
            f"SELECT {order}, automation_cases.case_id FROM automation_cases WHERE project_id = ? AND case_id = ?",
            (str(query.project_id), query.cursor),
        ).fetchone()
        if anchor is None:
            raise ValueError("invalid cursor")
        clauses.append(f"({order} > ? OR ({order} = ? AND automation_cases.case_id > ?))")
        params.extend([anchor[0], anchor[0], anchor[1]])
    rows = connection.execute(
        f"""
        SELECT automation_cases.case_id, automation_cases.name, automation_cases.folder_id,
               automation_cases.priority, automation_cases.assignee_id, automation_cases.current_approval_id,
               automation_cases.archived_at, automation_cases.lock_version, automation_cases.tc_reference
        FROM automation_cases
        WHERE {' AND '.join(clauses)}
        ORDER BY {order}, automation_cases.case_id
        LIMIT ?
        """,
        (*params, query.limit + 1),
    ).fetchall()
    clock = connection.execute(
        "SELECT commit_seq FROM project_commit_clock WHERE project_id = ?",
        (str(query.project_id),),
    ).fetchone()
    visible = rows[: query.limit]
    next_cursor = None if len(rows) <= query.limit else str(visible[-1][0])
    return CursorPage(
        items=tuple(_row(item) for item in visible),
        next_cursor=next_cursor,
        snapshot_seq=0 if clock is None else int(clock[0]),
    )


def clone_case(clone: CloneCaseInput) -> CaseView:
    if clone.name.strip() == "":
        raise ValueError("case name is required")
    case_id = uuid4()
    version_id = uuid4()
    created_at = datetime.now(timezone.utc).isoformat()
    source_version: str | None = None
    ensure_projection_tables(_bound_store()._connection)
    with _bound_store().transaction() as connection:
        source = connection.execute(
            """
            SELECT latest_draft_version_id
            FROM automation_cases
            WHERE project_id = ? AND case_id = ?
            """,
            (str(clone.project_id), str(clone.source_case_id)),
        ).fetchone()
        if source is None:
            raise CatalogNotFound("case was not found")
        source_version = None if source[0] is None else str(source[0])
        connection.execute(
            """
            INSERT INTO automation_cases (
                project_id, case_id, name, folder_id, tc_reference, next_revision,
                latest_draft_version_id, current_approval_id, lock_version, archived_at,
                priority, assignee_id
            ) VALUES (?, ?, ?, NULL, NULL, 2, ?, NULL, 1, NULL, NULL, NULL)
            """,
            (str(clone.project_id), str(case_id), clone.name, None if source_version is None else str(version_id)),
        )
        if source_version is not None:
            snapshot = connection.execute(
                "SELECT definition_json, settings_json, recorded_steps_json FROM case_versions WHERE project_id=? AND version_id=?",
                (str(clone.project_id), source_version),
            ).fetchone()
            if snapshot is None:
                raise CatalogNotFound("source version was not found")
            content_hash = execution_snapshot_hash(*(json.loads(str(value)) for value in snapshot))
            connection.execute(
                """
                INSERT INTO case_versions (
                    project_id, case_id, version_id, revision, creation_kind, parent_version_id,
                    base_version_id, is_branch, definition_json, settings_json, recorded_steps_json,
                    content_hash, verification_digest, source_manifest_id, replay_package_id,
                    readiness_json, actor_id, reason, created_at
                )
                SELECT ?, ?, ?, 1, 'input', NULL, NULL, 0, definition_json, settings_json,
                       recorded_steps_json, ?, verification_digest, NULL, NULL,
                       readiness_json, ?, 'clone', ?
                FROM case_versions
                WHERE project_id = ? AND version_id = ?
                """,
                (
                    str(clone.project_id),
                    str(case_id),
                    str(version_id),
                    content_hash,
                    str(clone.actor_id),
                    created_at,
                    str(clone.project_id),
                    source_version,
                ),
            )
        if source_version is not None:
            row = connection.execute('SELECT definition_json FROM case_versions WHERE version_id=? AND project_id=?', (str(version_id), str(clone.project_id))).fetchone()
            persist_projection(connection, str(version_id), definition_from_document(json.loads(str(row[0]))))
        connection.execute(
            """
            INSERT INTO case_clone_provenance (
                project_id, case_id, source_case_id, source_version_id, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                str(clone.project_id),
                str(case_id),
                str(clone.source_case_id),
                source_version,
                created_at,
            ),
        )
        if source_version is None:
            connection.execute(
                """
                UPDATE automation_cases
                SET next_revision = 1, latest_draft_version_id = NULL, lock_version = 0
                WHERE project_id = ? AND case_id = ?
                """,
                (str(clone.project_id), str(case_id)),
            )
    return CaseView(
        project_id=clone.project_id,
        case_id=case_id,
        name=clone.name,
        current_approval_id=None,
        latest_draft_version_id=None if source_version is None else version_id,
        archived_at=None,
        lock_version=0 if source_version is None else 1,
    )


def archive_case(case_id: UUID, expected_revision: int) -> CaseView:
    actor = _require_actor()
    archived_at = datetime.now(timezone.utc).isoformat()
    with _bound_store().transaction() as connection:
        current = _case_row(connection, actor, case_id)
        if current is None:
            raise CatalogNotFound("case was not found")
        if int(current[6]) != expected_revision:
            raise StaleRevision("case lock changed")
        open_recording = connection.execute(
            """
            SELECT 1 FROM case_open_recordings
            WHERE project_id = ? AND case_id = ? AND status = 'active'
            """,
            (str(actor.project_scope), str(case_id)),
        ).fetchone()
        if open_recording is not None:
            raise ActiveRecording("an open recording belongs to this case")
        connection.execute(
            """
            UPDATE automation_cases
            SET archived_at = ?, lock_version = lock_version + 1
            WHERE project_id = ? AND case_id = ? AND lock_version = ?
            """,
            (archived_at, str(actor.project_scope), str(case_id), expected_revision),
        )
        row = _case_row(connection, actor, case_id)
    if row is None:
        raise CatalogNotFound("case was not found")
    return _view(actor, case_id, row)


def _folder_exists(connection, actor: Actor, folder_id: UUID) -> bool:
    row = connection.execute(
        "SELECT 1 FROM folders WHERE project_id = ? AND folder_id = ?",
        (str(actor.project_scope), str(folder_id)),
    ).fetchone()
    return row is not None


def _reaches(connection, actor: Actor, start: UUID, target: UUID) -> bool:
    seen: set[str] = set()
    current: str | None = str(start)
    while current is not None:
        if current == str(target) or current in seen:
            return current == str(target)
        seen.add(current)
        row = connection.execute(
            "SELECT parent_folder_id FROM folders WHERE project_id = ? AND folder_id = ?",
            (str(actor.project_scope), current),
        ).fetchone()
        if row is None:
            return False
        current = None if row[0] is None else str(row[0])
    return False


def _case_row(connection, actor: Actor, case_id: UUID):
    return connection.execute(
        """
        SELECT name, current_approval_id, latest_draft_version_id, archived_at, lock_version,
               folder_id, lock_version
        FROM automation_cases
        WHERE project_id = ? AND case_id = ?
        """,
        (str(actor.project_scope), str(case_id)),
    ).fetchone()


def _view(actor: Actor, case_id: UUID, row) -> CaseView:
    assert actor.project_scope is not None
    return CaseView(
        project_id=actor.project_scope,
        case_id=case_id,
        name=str(row[0]),
        current_approval_id=None if row[1] is None else UUID(str(row[1])),
        latest_draft_version_id=None if row[2] is None else UUID(str(row[2])),
        archived_at=None if row[3] is None else str(row[3]),
        lock_version=int(row[4]),
    )


def _row(item) -> CaseListRow:
    return CaseListRow(
        case_id=UUID(str(item[0])),
        name=str(item[1]),
        folder_id=None if item[2] is None else UUID(str(item[2])),
        priority=None if item[3] is None else str(item[3]),
        assignee_id=None if item[4] is None else UUID(str(item[4])),
        current_approval_id=None if item[5] is None else UUID(str(item[5])),
        archived_at=None if item[6] is None else str(item[6]),
        lock_version=int(item[7]),
        tc_reference=None if item[8] is None else UUID(str(item[8])),
    )


def project_overview(project_id: UUID) -> ProjectOverview | None:
    """Count unfinished work from the project tables. An empty project stays at zero."""

    with _bound_store().transaction() as connection:
        found = connection.execute(
            "SELECT 1 FROM projects WHERE project_id = ?",
            (str(project_id),),
        ).fetchone()
        if found is None:
            return None
        key = str(project_id)
        scope = connection.execute(
            """
            SELECT automation_cases.name
            FROM case_versions
            JOIN automation_cases
              ON automation_cases.project_id = case_versions.project_id
             AND automation_cases.case_id = case_versions.case_id
            WHERE case_versions.project_id = ?
            ORDER BY case_versions.created_at DESC, case_versions.version_id DESC
            LIMIT 1
            """,
            (key,),
        ).fetchone()
        result = connection.execute(
            """
            SELECT status FROM jobs
            WHERE project_id = ? AND status IN ('completed', 'error', 'cancelled', 'lost')
            ORDER BY rowid DESC
            LIMIT 1
            """,
            (key,),
        ).fetchone()
        base = f"/ui/projects/{project_id}"
        return ProjectOverview(
            project_id=project_id,
            incomplete_recordings=_count(
                connection,
                """
                SELECT COUNT(*) FROM recordings
                WHERE project_id = ? AND (completion_status = 'open' OR stop_status = 'running')
                """,
                key,
            ),
            reviews_waiting=_count(
                connection,
                """
                SELECT COUNT(*) FROM reviews
                WHERE project_id = ?
                  AND NOT EXISTS (
                    SELECT 1 FROM approval_events
                    WHERE approval_events.project_id = reviews.project_id
                      AND approval_events.review_id = reviews.review_id
                  )
                """,
                key,
            ),
            unclassified_failures=_count(
                connection,
                """
                SELECT COUNT(*) FROM recordings
                WHERE project_id = ? AND completion_status = 'error'
                """,
                key,
            ),
            running_runs=_count(
                connection,
                """
                SELECT COUNT(*) FROM jobs
                WHERE project_id = ?
                  AND status IN ('preparing', 'running', 'finalizing', 'cancel_requested')
                """,
                key,
            ),
            queued_runs=_count(
                connection,
                "SELECT COUNT(*) FROM jobs WHERE project_id = ? AND status = 'queued'",
                key,
            ),
            blocked_environments=_count(
                connection,
                """
                SELECT COUNT(*) FROM environments
                WHERE project_id = ? AND latest_revision_id IS NULL
                """,
                key,
            ),
            draft_cases=_count(
                connection,
                """
                SELECT COUNT(*) FROM automation_cases
                WHERE project_id = ? AND archived_at IS NULL
                  AND latest_draft_version_id IS NOT NULL
                  AND current_approval_id IS NULL
                """,
                key,
            ),
            approved_cases=_count(
                connection,
                """
                SELECT COUNT(*) FROM automation_cases
                WHERE project_id = ? AND archived_at IS NULL
                  AND current_approval_id IS NOT NULL
                """,
                key,
            ),
            recent_scope=None if scope is None else str(scope[0]),
            recent_result=None if result is None else str(result[0]),
            new_recording_href=f"{base}/recordings/new",
            saved_cases_href=f"{base}/cases",
            bundle_href=f"{base}/bundles",
        )


def _count(connection: sqlite3.Connection, sql: str, project_id: str) -> int:
    row = connection.execute(sql, (project_id,)).fetchone()
    return 0 if row is None else int(row[0])


def _require_actor() -> Actor:
    actor = _actor.get()
    if actor.project_scope is None:
        raise CatalogNotFound("case was not found")
    return actor


def _bound_store() -> Store:
    try:
        return _store.get()
    except LookupError as exc:
        raise RuntimeError("catalog store is not bound") from exc
