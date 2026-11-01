"""Suite list, clone, and archive. This does not open a device or a model."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from uuid import UUID, uuid4

from aiqa.domain.hashing import canonical_json
from aiqa.store.models import Actor, Transaction


class SuiteRejected(Exception):
    """The suite command cannot be stored."""


class SuiteConflict(Exception):
    """The same key was sent with a different body."""


@dataclass(frozen=True, slots=True)
class SuiteHistory:
    """One immutable suite version."""

    suite_version_id: UUID
    content_hash: str
    entry_count: int


@dataclass(frozen=True, slots=True)
class SuiteEntry:
    """One exact item inside an immutable suite version."""

    entry_id: str
    case_id: UUID
    case_version_id: UUID
    approval_id: str
    data_name: str
    environment_revision_id: str
    reset_policy: str
    failure_policy: str
    resource_id: str
    target_kind: str
    position: int


@dataclass(frozen=True, slots=True)
class UpgradeProposal:
    """A newer approval that the suite has not adopted."""

    entry_id: str
    case_id: UUID
    from_version_id: UUID
    from_approval_id: str
    to_version_id: UUID
    to_approval_id: str
    definition_from: str
    definition_to: str
    procedure_from: str
    procedure_to: str
    policy_from: str
    policy_to: str


@dataclass(frozen=True, slots=True)
class SuiteVersionView:
    """One saved suite revision. Older revisions are not rewritten."""

    suite_id: UUID
    suite_version_id: UUID
    previous_version_id: UUID | None
    content_hash: str
    entries: tuple[SuiteEntry, ...]
    replayed: bool


@dataclass(frozen=True, slots=True)
class SuiteView:
    """One suite row for the list and the command receipt."""

    suite_id: UUID
    name: str
    description: str
    target_kind: str
    owner_name: str
    classification: str
    entry_count: int
    latest_run_id: UUID | None
    latest_run_at: str
    updated_at: str
    archived_at: str
    version_id: UUID | None
    history: tuple[SuiteHistory, ...]
    replayed: bool


def list_suites(tx: Transaction, actor: Actor, project_id: UUID, query: dict[str, str]) -> tuple[SuiteView, ...]:
    """Read suites in one project. Another project's rows stay out."""

    _scope(actor, project_id)
    rows = tx.connection.execute(
        """
        SELECT suite_id FROM suites
        WHERE project_id = ?
        ORDER BY updated_at, suite_id
        """,
        (str(project_id),),
    ).fetchall()
    found: list[SuiteView] = []
    needle = query.get("q", "").strip()
    classification = query.get("classification", "").strip()
    target = query.get("target", "").strip()
    for row in rows:
        view = _read(tx.connection, project_id, UUID(str(row[0])), False)
        if view is None:
            continue
        if classification != "" and view.classification != classification:
            continue
        if target != "" and view.target_kind != target:
            continue
        haystack = " ".join((str(view.suite_id), view.name, view.description, view.owner_name, view.classification))
        if needle != "" and needle not in haystack:
            continue
        found.append(view)
    return tuple(found)


def create_suite(
    tx: Transaction, actor: Actor, project_id: UUID, payload: dict[str, object], request_key: str
) -> SuiteView:
    """Store a suite. Zero entries are allowed."""

    _scope(actor, project_id)
    fields = _fields(payload)
    replay = _replay(tx.connection, project_id, actor, "create_suite", request_key, payload)
    if replay is not None:
        return replay
    suite_id = uuid4()
    version_id = uuid4()
    stamp = _now()
    digest = _empty_hash()
    tx.connection.execute(
        """
        INSERT INTO suites (
            project_id, suite_id, name, description, target_kind, owner_name, classification,
            head_version_id, archived_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
        """,
        (
            str(project_id),
            str(suite_id),
            fields[0],
            fields[1],
            fields[2],
            fields[3],
            fields[4],
            str(version_id),
            stamp,
            stamp,
        ),
    )
    tx.connection.execute(
        """
        INSERT INTO suite_versions (project_id, suite_id, suite_version_id, content_hash)
        VALUES (?, ?, ?, ?)
        """,
        (str(project_id), str(suite_id), str(version_id), digest),
    )
    _remember(tx.connection, project_id, actor, "create_suite", request_key, payload, suite_id, stamp)
    view = _read(tx.connection, project_id, suite_id, False)
    if view is None:
        raise SuiteRejected("suite was not stored")
    return view


def clone_suite(
    tx: Transaction, actor: Actor, project_id: UUID, suite_id: UUID, payload: dict[str, object], request_key: str
) -> SuiteView:
    """Copy metadata and the current version. The source run snapshot stays put."""

    _scope(actor, project_id)
    replay = _replay(tx.connection, project_id, actor, "clone_suite", request_key, payload)
    if replay is not None:
        return replay
    source = _read(tx.connection, project_id, suite_id, False)
    if source is None:
        raise SuiteRejected("suite was not found")
    name = payload.get("name")
    if type(name) is not str or name.strip() == "":
        name = source.name
    copy_id = uuid4()
    version_id = uuid4()
    stamp = _now()
    tx.connection.execute(
        """
        INSERT INTO suites (
            project_id, suite_id, name, description, target_kind, owner_name, classification,
            head_version_id, archived_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
        """,
        (
            str(project_id),
            str(copy_id),
            name.strip(),
            source.description,
            source.target_kind,
            source.owner_name,
            source.classification,
            str(version_id),
            stamp,
            stamp,
        ),
    )
    digest = _empty_hash() if source.version_id is None else _version_hash(tx.connection, project_id, source.version_id)
    tx.connection.execute(
        """
        INSERT INTO suite_versions (project_id, suite_id, suite_version_id, content_hash)
        VALUES (?, ?, ?, ?)
        """,
        (str(project_id), str(copy_id), str(version_id), digest),
    )
    if source.version_id is not None:
        entries = tx.connection.execute(
            """
            SELECT entry_id, position, case_id, case_version_id, approval_id, data_name,
                   environment_revision_id, reset_policy, failure_policy, resource_id, target_kind
            FROM suite_entries
            WHERE project_id = ? AND suite_version_id = ?
            ORDER BY position, entry_id
            """,
            (str(project_id), str(source.version_id)),
        ).fetchall()
        for entry in entries:
            tx.connection.execute(
                """
                INSERT INTO suite_entries (
                    project_id, suite_version_id, entry_id, position, case_id, case_version_id,
                    approval_id, data_name, environment_revision_id, reset_policy, failure_policy,
                    resource_id, target_kind
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (str(project_id), str(version_id), str(entry[0]), int(entry[1]), *[str(item) for item in entry[2:]]),
            )
    _remember(tx.connection, project_id, actor, "clone_suite", request_key, payload, copy_id, stamp)
    view = _read(tx.connection, project_id, copy_id, False)
    if view is None:
        raise SuiteRejected("suite was not stored")
    return view


def archive_suite(
    tx: Transaction, actor: Actor, project_id: UUID, suite_id: UUID, payload: dict[str, object], request_key: str
) -> SuiteView:
    """Mark a suite archived. Versions and execution snapshots stay unchanged."""

    _scope(actor, project_id)
    replay = _replay(tx.connection, project_id, actor, "archive_suite", request_key, payload)
    if replay is not None:
        return replay
    current = _read(tx.connection, project_id, suite_id, False)
    if current is None:
        raise SuiteRejected("suite was not found")
    stamp = current.archived_at if current.archived_at != "" else _now()
    tx.connection.execute(
        """
        UPDATE suites
        SET archived_at = ?, updated_at = ?
        WHERE project_id = ? AND suite_id = ?
        """,
        (stamp, _now(), str(project_id), str(suite_id)),
    )
    _remember(tx.connection, project_id, actor, "archive_suite", request_key, payload, suite_id, stamp)
    view = _read(tx.connection, project_id, suite_id, False)
    if view is None:
        raise SuiteRejected("suite was not stored")
    return view


def save_suite_revision(
    tx: Transaction, actor: Actor, project_id: UUID, suite_id: UUID, payload: dict[str, object], request_key: str
) -> SuiteVersionView:
    """Store a new immutable revision. The previous version rows stay as they were."""

    _scope(actor, project_id)
    replay = _replay_version(tx.connection, project_id, actor, request_key, payload)
    if replay is not None:
        return replay
    current = _read(tx.connection, project_id, suite_id, False)
    if current is None:
        raise SuiteRejected("suite was not found")
    entries = _revision_entries(tx.connection, project_id, payload)
    return _store_revision(
        tx.connection, actor, project_id, suite_id, current.version_id, entries, payload, request_key, _now(), "save_suite_revision"
    )


def approved_case_names(tx: Transaction, actor: Actor, project_id: UUID, needle: str) -> tuple[tuple[str, str], ...]:
    """List approved cases in this project. The search does not open another project."""

    _scope(actor, project_id)
    rows = tx.connection.execute(
        """
        SELECT case_id, name FROM automation_cases
        WHERE project_id = ? AND current_approval_id IS NOT NULL AND archived_at IS NULL
        ORDER BY name, case_id
        """,
        (str(project_id),),
    ).fetchall()
    found = [(str(row[0]), str(row[1])) for row in rows if needle.strip() == "" or needle.strip() in str(row[1])]
    return tuple(found)


def suite_editor(
    tx: Transaction, actor: Actor, project_id: UUID, suite_id: UUID, needle: str
) -> tuple[str, tuple[tuple[str, str], ...], tuple[SuiteEntry, ...], tuple[UpgradeProposal, ...]]:
    """Read the approved search, the current revision, and any newer approvals."""

    view = _read(tx.connection, project_id, suite_id, False)
    if view is None or view.version_id is None:
        raise SuiteRejected("suite was not found")
    version = _read_version(tx.connection, project_id, suite_id, view.version_id, False)
    entries = () if version is None else version.entries
    return view.name, approved_case_names(tx, actor, project_id, needle), entries, _proposals(tx.connection, project_id, entries)


def list_upgrade_proposals(tx: Transaction, actor: Actor, project_id: UUID, suite_id: UUID) -> tuple[UpgradeProposal, ...]:
    """List newer approvals for the current suite. This does not change a revision."""

    _scope(actor, project_id)
    view = _read(tx.connection, project_id, suite_id, False)
    if view is None or view.version_id is None:
        raise SuiteRejected("suite was not found")
    version = _read_version(tx.connection, project_id, suite_id, view.version_id, False)
    entries = () if version is None else version.entries
    return _proposals(tx.connection, project_id, entries)


def decide_suite_upgrade(
    tx: Transaction, actor: Actor, project_id: UUID, suite_id: UUID, payload: dict[str, object], request_key: str
) -> SuiteVersionView:
    """Reject a proposal or move only the selected entries. Other entries and runs stay."""

    _scope(actor, project_id)
    replay = _replay_version(tx.connection, project_id, actor, request_key, payload, "decide_suite_upgrade")
    if replay is not None:
        return replay
    current = _read(tx.connection, project_id, suite_id, False)
    if current is None or current.version_id is None:
        raise SuiteRejected("suite was not found")
    expected = payload.get("expected_version_id")
    if type(expected) is not str or expected != str(current.version_id):
        raise SuiteConflict("suite head does not match")
    decision = payload.get("decision")
    version = _read_version(tx.connection, project_id, suite_id, current.version_id, False)
    if version is None:
        raise SuiteRejected("suite was not found")
    stamp = _now()
    if decision == "reject":
        _remember(tx.connection, project_id, actor, "decide_suite_upgrade", request_key, payload, suite_id, stamp, str(current.version_id))
        return version
    if decision != "accept":
        raise SuiteRejected("decision is invalid")
    selected = _selected_ids(payload)
    proposals = {item.entry_id: item for item in _proposals(tx.connection, project_id, version.entries)}
    moved: list[SuiteEntry] = []
    for entry in version.entries:
        if entry.entry_id not in selected:
            moved.append(entry)
            continue
        proposal = proposals.get(entry.entry_id)
        if proposal is None:
            raise SuiteRejected("entry has no upgrade")
        moved.append(replace(entry, case_version_id=proposal.to_version_id, approval_id=proposal.to_approval_id))
    return _store_revision(tx.connection, actor, project_id, suite_id, current.version_id, tuple(moved), payload, request_key, stamp, "decide_suite_upgrade")


def refuse_empty_execution(tx: Transaction, actor: Actor, project_id: UUID, suite_id: UUID) -> None:
    """Reject a run when the current version has no entries. This writes nothing."""

    _scope(actor, project_id)
    view = _read(tx.connection, project_id, suite_id, False)
    if view is None:
        raise SuiteRejected("suite was not found")
    if view.entry_count == 0:
        raise SuiteRejected("empty suite cannot run")
    raise SuiteRejected("suite execution is not admitted")


def _read(connection: sqlite3.Connection, project_id: UUID, suite_id: UUID, replayed: bool) -> SuiteView | None:
    row = connection.execute(
        """
        SELECT name, description, target_kind, owner_name, classification, head_version_id,
               archived_at, updated_at
        FROM suites
        WHERE project_id = ? AND suite_id = ?
        """,
        (str(project_id), str(suite_id)),
    ).fetchone()
    if row is None:
        return None
    versions = connection.execute(
        """
        SELECT suite_version_id, content_hash FROM suite_versions
        WHERE project_id = ? AND suite_id = ?
        ORDER BY suite_version_id
        """,
        (str(project_id), str(suite_id)),
    ).fetchall()
    history: list[SuiteHistory] = []
    for version in versions:
        counted = connection.execute(
            """
            SELECT COUNT(*) FROM suite_entries
            WHERE project_id = ? AND suite_version_id = ?
            """,
            (str(project_id), str(version[0])),
        ).fetchone()
        history.append(
            SuiteHistory(
                suite_version_id=UUID(str(version[0])),
                content_hash=str(version[1]),
                entry_count=0 if counted is None else int(counted[0]),
            )
        )
    head = None if row[5] is None else UUID(str(row[5]))
    entry_count = 0
    for item in history:
        if head is not None and item.suite_version_id == head:
            entry_count = item.entry_count
    latest = connection.execute(
        """
        SELECT executions.execution_id, executions.scope_requested_at
        FROM executions
        JOIN suite_versions
          ON suite_versions.project_id = executions.project_id
         AND suite_versions.suite_version_id = executions.suite_version_id
        WHERE suite_versions.project_id = ? AND suite_versions.suite_id = ?
        ORDER BY executions.scope_requested_at DESC, executions.execution_id
        LIMIT 1
        """,
        (str(project_id), str(suite_id)),
    ).fetchone()
    return SuiteView(
        suite_id=suite_id,
        name=str(row[0]),
        description=str(row[1]),
        target_kind=str(row[2]),
        owner_name=str(row[3]),
        classification=str(row[4]),
        entry_count=entry_count,
        latest_run_id=None if latest is None else UUID(str(latest[0])),
        latest_run_at="" if latest is None else str(latest[1]),
        updated_at=str(row[7]),
        archived_at="" if row[6] is None else str(row[6]),
        version_id=head,
        history=tuple(history),
        replayed=replayed,
    )


def _fields(payload: dict[str, object]) -> tuple[str, str, str, str, str]:
    name = payload.get("name")
    if type(name) is not str or name.strip() == "":
        raise SuiteRejected("name is required")
    description = payload.get("description", "")
    owner = payload.get("owner_name", "")
    classification = payload.get("classification", "")
    target = payload.get("target_kind", "web")
    if type(description) is not str or type(owner) is not str or type(classification) is not str:
        raise SuiteRejected("suite body is invalid")
    if target not in {"web", "android"}:
        raise SuiteRejected("target is invalid")
    return name.strip(), description, str(target), owner, classification


def _replay(
    connection: sqlite3.Connection,
    project_id: UUID,
    actor: Actor,
    operation: str,
    request_key: str,
    payload: dict[str, object],
) -> SuiteView | None:
    if request_key.strip() == "":
        raise SuiteRejected("idempotency key is required")
    row = connection.execute(
        """
        SELECT body_hash, suite_id FROM suite_receipts
        WHERE project_id = ? AND actor_id = ? AND operation = ? AND request_key = ?
        """,
        (str(project_id), str(actor.actor_id), operation, request_key),
    ).fetchone()
    if row is None:
        return None
    if str(row[0]) != _body_hash(payload):
        raise SuiteConflict("idempotency body does not match")
    view = _read(connection, project_id, UUID(str(row[1])), True)
    if view is None:
        raise SuiteRejected("suite was not found")
    return view


def _remember(
    connection: sqlite3.Connection,
    project_id: UUID,
    actor: Actor,
    operation: str,
    request_key: str,
    payload: dict[str, object],
    suite_id: UUID,
    stamp: str,
    version_id: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO suite_receipts (
            project_id, actor_id, operation, request_key, body_hash, suite_id, created_at, suite_version_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(project_id),
            str(actor.actor_id),
            operation,
            request_key,
            _body_hash(payload),
            str(suite_id),
            stamp,
            version_id,
        ),
    )


def _store_revision(
    connection: sqlite3.Connection,
    actor: Actor,
    project_id: UUID,
    suite_id: UUID,
    previous_version_id: UUID | None,
    entries: tuple[SuiteEntry, ...],
    payload: dict[str, object],
    request_key: str,
    stamp: str,
    operation: str,
) -> SuiteVersionView:
    version_id = uuid4()
    digest = hashlib.sha256(canonical_json({"entries": [_entry_body(item) for item in entries]}).encode("utf-8")).hexdigest()
    connection.execute(
        """
        INSERT INTO suite_versions (project_id, suite_id, suite_version_id, content_hash)
        VALUES (?, ?, ?, ?)
        """,
        (str(project_id), str(suite_id), str(version_id), digest),
    )
    for item in entries:
        connection.execute(
            """
            INSERT INTO suite_entries (
                project_id, suite_version_id, entry_id, position, case_id, case_version_id,
                approval_id, data_name, environment_revision_id, reset_policy, failure_policy,
                resource_id, target_kind
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(project_id),
                str(version_id),
                item.entry_id,
                item.position,
                str(item.case_id),
                str(item.case_version_id),
                item.approval_id,
                item.data_name,
                item.environment_revision_id,
                item.reset_policy,
                item.failure_policy,
                item.resource_id,
                item.target_kind,
            ),
        )
    connection.execute(
        """
        UPDATE suites SET head_version_id = ?, updated_at = ?
        WHERE project_id = ? AND suite_id = ?
        """,
        (str(version_id), stamp, str(project_id), str(suite_id)),
    )
    _remember(connection, project_id, actor, operation, request_key, payload, suite_id, stamp, str(version_id))
    saved = _read_version(connection, project_id, suite_id, version_id, False)
    if saved is None:
        raise SuiteRejected("suite was not stored")
    return SuiteVersionView(
        saved.suite_id,
        saved.suite_version_id,
        previous_version_id,
        saved.content_hash,
        saved.entries,
        False,
    )


def _proposals(connection: sqlite3.Connection, project_id: UUID, entries: tuple[SuiteEntry, ...]) -> tuple[UpgradeProposal, ...]:
    found: list[UpgradeProposal] = []
    for entry in entries:
        current = _version_facts(connection, project_id, entry.case_version_id)
        newer = _latest_approval(connection, project_id, entry.case_id)
        if current is None or newer is None or newer[2] <= current[0] or newer[1] == entry.case_version_id:
            continue
        target = _version_facts(connection, project_id, newer[1])
        if target is None:
            continue
        found.append(
            UpgradeProposal(
                entry.entry_id,
                entry.case_id,
                entry.case_version_id,
                entry.approval_id,
                newer[1],
                newer[0],
                current[1],
                target[1],
                current[2],
                target[2],
                current[3],
                target[3],
            )
        )
    return tuple(found)


def _version_facts(connection: sqlite3.Connection, project_id: UUID, version_id: UUID) -> tuple[int, str, str, str] | None:
    row = connection.execute(
        """
        SELECT revision, definition_json, recorded_steps_json, settings_json
        FROM case_versions
        WHERE project_id = ? AND version_id = ?
        """,
        (str(project_id), str(version_id)),
    ).fetchone()
    if row is None:
        return None
    return int(row[0]), str(row[1]), str(row[2]), str(row[3])


def _latest_approval(connection: sqlite3.Connection, project_id: UUID, case_id: UUID) -> tuple[str, UUID, int] | None:
    row = connection.execute(
        """
        SELECT approval_events.approval_id, approval_events.case_version_id, case_versions.revision
        FROM approval_events
        JOIN case_versions
          ON case_versions.project_id = approval_events.project_id
         AND case_versions.case_id = approval_events.case_id
         AND case_versions.version_id = approval_events.case_version_id
        WHERE approval_events.project_id = ? AND approval_events.case_id = ? AND approval_events.event_kind = 'approved'
        ORDER BY case_versions.revision DESC, approval_events.approval_id
        LIMIT 1
        """,
        (str(project_id), str(case_id)),
    ).fetchone()
    if row is None:
        return None
    return str(row[0]), UUID(str(row[1])), int(row[2])


def _selected_ids(payload: dict[str, object]) -> set[str]:
    raw_ids = payload.get("entry_ids")
    if type(raw_ids) is not list or len(raw_ids) == 0 or any(type(item) is not str or item.strip() == "" for item in raw_ids):
        raise SuiteRejected("selection is required")
    if len(set(raw_ids)) != len(raw_ids):
        raise SuiteRejected("entry id is duplicated")
    return {str(item) for item in raw_ids}


def _replay_version(
    connection: sqlite3.Connection,
    project_id: UUID,
    actor: Actor,
    request_key: str,
    payload: dict[str, object],
    operation: str = "save_suite_revision",
) -> SuiteVersionView | None:
    if request_key.strip() == "":
        raise SuiteRejected("idempotency key is required")
    row = connection.execute(
        """
        SELECT body_hash, suite_id, suite_version_id FROM suite_receipts
        WHERE project_id = ? AND actor_id = ? AND operation = ? AND request_key = ?
        """,
        (str(project_id), str(actor.actor_id), operation, request_key),
    ).fetchone()
    if row is None:
        return None
    if str(row[0]) != _body_hash(payload):
        raise SuiteConflict("idempotency body does not match")
    if row[2] is None:
        raise SuiteRejected("suite was not found")
    view = _read_version(connection, project_id, UUID(str(row[1])), UUID(str(row[2])), True)
    if view is None:
        raise SuiteRejected("suite was not found")
    return view


def _read_version(
    connection: sqlite3.Connection,
    project_id: UUID,
    suite_id: UUID,
    version_id: UUID,
    replayed: bool,
) -> SuiteVersionView | None:
    version = connection.execute(
        """
        SELECT content_hash FROM suite_versions
        WHERE project_id = ? AND suite_id = ? AND suite_version_id = ?
        """,
        (str(project_id), str(suite_id), str(version_id)),
    ).fetchone()
    if version is None:
        return None
    head = connection.execute(
        "SELECT head_version_id FROM suites WHERE project_id = ? AND suite_id = ?",
        (str(project_id), str(suite_id)),
    ).fetchone()
    previous = None
    if head is not None and head[0] is not None and str(head[0]) != str(version_id):
        previous = UUID(str(head[0]))
    rows = connection.execute(
        """
        SELECT entry_id, case_id, case_version_id, approval_id, data_name, environment_revision_id,
               reset_policy, failure_policy, resource_id, target_kind, position
        FROM suite_entries
        WHERE project_id = ? AND suite_version_id = ?
        ORDER BY position, entry_id
        """,
        (str(project_id), str(version_id)),
    ).fetchall()
    entries = tuple(
        SuiteEntry(
            entry_id=str(row[0]),
            case_id=UUID(str(row[1])),
            case_version_id=UUID(str(row[2])),
            approval_id=str(row[3]),
            data_name=str(row[4]),
            environment_revision_id=str(row[5]),
            reset_policy=str(row[6]),
            failure_policy=str(row[7]),
            resource_id=str(row[8]),
            target_kind=str(row[9]),
            position=int(row[10]),
        )
        for row in rows
        if str(row[1]) != ""
    )
    return SuiteVersionView(suite_id, version_id, previous, str(version[0]), entries, replayed)


def _revision_entries(connection: sqlite3.Connection, project_id: UUID, payload: dict[str, object]) -> tuple[SuiteEntry, ...]:
    raw_entries = payload.get("entries")
    if type(raw_entries) is not list or len(raw_entries) == 0:
        raise SuiteRejected("entries are required")
    parsed: list[SuiteEntry] = []
    seen_ids: set[str] = set()
    seen_rows: set[tuple[str, str]] = set()
    for index, raw in enumerate(raw_entries, start=1):
        if type(raw) is not dict:
            raise SuiteRejected("entry is invalid")
        item = _one_entry(connection, project_id, raw, index)
        if item.entry_id in seen_ids:
            raise SuiteRejected("entry id is duplicated")
        row_key = (str(item.case_id), item.data_name)
        if row_key in seen_rows:
            raise SuiteRejected("data row is duplicated")
        seen_ids.add(item.entry_id)
        seen_rows.add(row_key)
        parsed.append(item)
    targets = {item.target_kind for item in parsed}
    if len(targets) > 1 and any(item.resource_id == "" for item in parsed):
        raise SuiteRejected("each target needs a resource")
    return tuple(parsed)


def _one_entry(connection: sqlite3.Connection, project_id: UUID, raw: dict[str, object], position: int) -> SuiteEntry:
    entry_id = raw.get("entry_id")
    data_name = raw.get("data_name")
    target = raw.get("target_kind")
    reset_policy = raw.get("reset_policy")
    failure_policy = raw.get("failure_policy")
    environment = raw.get("environment_revision_id", "")
    resource = raw.get("resource_id", "")
    if (
        type(entry_id) is not str
        or entry_id.strip() == ""
        or type(data_name) is not str
        or data_name.strip() == ""
        or target not in {"web", "android"}
        or reset_policy not in {"keep", "reset"}
        or failure_policy not in {"continue", "stop"}
        or type(environment) is not str
        or type(resource) is not str
    ):
        raise SuiteRejected("entry is invalid")
    case_id = _uuid(raw.get("case_id"), "case was not found")
    version_id = _uuid(raw.get("case_version_id"), "version was not found")
    approval = raw.get("approval_id")
    if type(approval) is not str or approval.strip() == "":
        raise SuiteRejected("approval is required")
    version = connection.execute(
        """
        SELECT 1 FROM case_versions
        WHERE project_id = ? AND case_id = ? AND version_id = ?
        """,
        (str(project_id), str(case_id), str(version_id)),
    ).fetchone()
    if version is None:
        raise SuiteRejected("version was not found")
    approved = connection.execute(
        """
        SELECT 1 FROM approval_events
        WHERE project_id = ? AND approval_id = ? AND case_id = ? AND case_version_id = ? AND event_kind = 'approved'
        """,
        (str(project_id), approval, str(case_id), str(version_id)),
    ).fetchone()
    if approved is None:
        raise SuiteRejected("approval does not match the version")
    if environment != "":
        stored_environment = connection.execute(
            "SELECT 1 FROM environment_revisions WHERE project_id = ? AND revision_id = ?",
            (str(project_id), environment),
        ).fetchone()
        if stored_environment is None:
            raise SuiteRejected("environment was not found")
    if resource != "":
        stored_resource = connection.execute(
            """
            SELECT target_kind FROM resource_aliases
            WHERE project_id = ? AND physical_key_id = ?
            """,
            (str(project_id), resource),
        ).fetchone()
        if stored_resource is None or str(stored_resource[0]) != target:
            raise SuiteRejected("resource was not found")
    return SuiteEntry(
        entry_id.strip(),
        case_id,
        version_id,
        approval,
        data_name.strip(),
        environment,
        str(reset_policy),
        str(failure_policy),
        resource,
        str(target),
        position,
    )


def _entry_body(item: SuiteEntry) -> dict[str, object]:
    return {
        "approval_id": item.approval_id,
        "case_id": str(item.case_id),
        "case_version_id": str(item.case_version_id),
        "data_name": item.data_name,
        "entry_id": item.entry_id,
        "environment_revision_id": item.environment_revision_id,
        "failure_policy": item.failure_policy,
        "position": item.position,
        "reset_policy": item.reset_policy,
        "resource_id": item.resource_id,
        "target_kind": item.target_kind,
    }


def _uuid(value: object, message: str) -> UUID:
    if type(value) is not str:
        raise SuiteRejected(message)
    try:
        return UUID(value)
    except ValueError as exc:
        raise SuiteRejected(message) from exc


def _version_hash(connection: sqlite3.Connection, project_id: UUID, version_id: UUID) -> str:
    row = connection.execute(
        """
        SELECT content_hash FROM suite_versions
        WHERE project_id = ? AND suite_version_id = ?
        """,
        (str(project_id), str(version_id)),
    ).fetchone()
    return _empty_hash() if row is None else str(row[0])


def _body_hash(payload: dict[str, object]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _empty_hash() -> str:
    return hashlib.sha256(canonical_json({"entries": []}).encode("utf-8")).hexdigest()


def _scope(actor: Actor, project_id: UUID) -> None:
    if actor.project_scope != project_id:
        raise SuiteRejected("project scope does not match")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
