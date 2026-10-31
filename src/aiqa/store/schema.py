"""Schema integrity for the migrated store. Importing this module does not open a database."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from aiqa.store.database import Store

_REQUIRED_INDEXES: tuple[tuple[str, bool], ...] = (
    ("automation_cases_archive", False),
    ("jobs_queue", False),
    ("case_runs_requested", False),
    ("case_runs_case_requested", False),
    ("check_results_status", False),
    ("artifact_protections_artifact", False),
    ("item_finalizations_seq", False),
    ("item_lifecycle_seq", False),
    ("usage_adjustments_seq", False),
    ("approval_events_case", False),
    ("leases_resource", True),
    ("jobs_recording_owner", True),
    ("jobs_case_run_owner", True),
    ("approval_events_one_revoke", True),
)

_UNIQUE_KEYS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("case_versions", ("case_id", "revision")),
    ("recording_manifests", ("project_id", "recording_id", "revision")),
    ("materialization_receipts", ("project_id", "manifest_id")),
    ("attempt_events", ("project_id", "attempt_id", "local_seq")),
    ("actions", ("project_id", "attempt_id", "action_seq")),
    ("project_commit_clock", ("project_id",)),
    ("protection_releases", ("project_id", "protection_id")),
)


@dataclass(frozen=True, slots=True)
class SchemaIntegrityReport:
    integrity: str
    foreign_key_violations: int
    required_indexes_present: bool
    mutable_sealed_content: bool
    all_fk_target_tables_exist: bool
    nullable_fk_inserts_work: bool


def validate_schema(store: Store) -> SchemaIntegrityReport:
    connection = store._connection
    if connection.in_transaction:
        raise RuntimeError("schema validation starts its own probe transaction")
    integrity_row = connection.execute("PRAGMA integrity_check").fetchone()
    integrity = str(integrity_row[0]) if integrity_row is not None else "fail"
    foreign_key_violations = len(connection.execute("PRAGMA foreign_key_check").fetchall())
    foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()
    if foreign_keys is None or int(foreign_keys[0]) != 1:
        integrity = "foreign_keys_off"
    indexes_present = _indexes_present(connection)
    targets_exist = _fk_targets_exist(connection)
    mutable, partial_unique, nullable_ok = _probe(connection)
    return SchemaIntegrityReport(
        integrity=integrity,
        foreign_key_violations=foreign_key_violations,
        required_indexes_present=indexes_present and partial_unique,
        mutable_sealed_content=mutable,
        all_fk_target_tables_exist=targets_exist,
        nullable_fk_inserts_work=nullable_ok,
    )


def _indexes_present(connection: sqlite3.Connection) -> bool:
    for name, partial in _REQUIRED_INDEXES:
        row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?",
            (name,),
        ).fetchone()
        if row is None or row[0] is None:
            return False
        if partial and "where" not in str(row[0]).lower():
            return False
    return all(_unique_covers(connection, table, columns) for table, columns in _UNIQUE_KEYS)


def _unique_covers(connection: sqlite3.Connection, table: str, columns: tuple[str, ...]) -> bool:
    for index in connection.execute(f"PRAGMA index_list({table})"):
        if int(index[2]) != 1:
            continue
        names = tuple(
            str(info[2]) for info in connection.execute(f"PRAGMA index_info({index[1]})")
        )
        if names == columns:
            return True
    return False


def _fk_targets_exist(connection: sqlite3.Connection) -> bool:
    tables = {
        str(row[0])
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    for table in tables:
        for foreign_key in connection.execute(f"PRAGMA foreign_key_list({table})"):
            if str(foreign_key[2]) not in tables:
                return False
    return True


def _probe(connection: sqlite3.Connection) -> tuple[bool, bool, bool]:
    connection.execute("BEGIN")
    try:
        _insert_case(connection)
        mutable = not _denied(
            connection,
            "UPDATE case_versions SET content_hash = ? WHERE version_id = ?",
            ("changed", "v-probe"),
        )
        folder_denied = _denied(
            connection,
            """
            INSERT INTO automation_cases (
                project_id, case_id, name, folder_id, tc_reference, next_revision,
                latest_draft_version_id, current_approval_id, lock_version, archived_at
            ) VALUES ('p-probe', 'c-bad', 'Bad', 'missing-folder', NULL, 1, NULL, NULL, 0, NULL)
            """,
            (),
        )
        connection.execute(
            """
            INSERT INTO executions (
                project_id, execution_id, name, purpose, source, suite_version_id, scope_requested_at
            ) VALUES ('p-probe', 'e-probe', 'Run', 'trial', 'single', NULL, '2026-11-01T00:00:00+00:00')
            """
        )
        suite_denied = _denied(
            connection,
            """
            INSERT INTO executions (
                project_id, execution_id, name, purpose, source, suite_version_id, scope_requested_at
            ) VALUES ('p-probe', 'e-bad', 'Run', 'trial', 'suite', 'missing-suite', '2026-11-01T00:00:00+00:00')
            """,
            (),
        )
        connection.execute(
            """
            INSERT INTO recordings (
                project_id, case_id, recording_id, creation_kind, input_case_version_id,
                base_case_version_id, parent_recording_id, source_recording_id,
                storage_status, stop_status, completion_status, evidence_status
            ) VALUES (
                'p-probe', 'c-probe', 'r-probe', 'recorded', 'v-probe',
                NULL, NULL, NULL, 'local', 'stopped', 'open', 'incomplete'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO jobs (
                project_id, job_id, purpose, recording_id, case_run_id,
                payload_hash, source_refs, limits, status
            ) VALUES ('p-probe', 'j-rec', 'recording', 'r-probe', NULL, 'hash', '[]', '{}', 'queued')
            """
        )
        duplicate_owner = _denied(
            connection,
            """
            INSERT INTO jobs (
                project_id, job_id, purpose, recording_id, case_run_id,
                payload_hash, source_refs, limits, status
            ) VALUES ('p-probe', 'j-rec-2', 'recording', 'r-probe', NULL, 'hash', '[]', '{}', 'queued')
            """,
            (),
        )
        connection.execute(
            """
            INSERT INTO jobs (
                project_id, job_id, purpose, recording_id, case_run_id,
                payload_hash, source_refs, limits, status
            ) VALUES ('p-probe', 'j-mgmt', 'package_rebuild', NULL, NULL, 'hash', '["m"]', '{}', 'queued')
            """
        )
        missing_run = _denied(
            connection,
            """
            INSERT INTO jobs (
                project_id, job_id, purpose, recording_id, case_run_id,
                payload_hash, source_refs, limits, status
            ) VALUES ('p-probe', 'j-bad', 'trial', NULL, 'missing-run', 'hash', '[]', '{}', 'queued')
            """,
            (),
        )
        connection.execute(
            """
            INSERT INTO leases (
                project_id, job_id, generation, worker_id, physical_key_id, expires_at
            ) VALUES ('p-probe', 'j-rec', 1, 'worker-probe', NULL, '2026-11-01T01:00:00+00:00')
            """
        )
        missing_key = _denied(
            connection,
            """
            INSERT INTO leases (
                project_id, job_id, generation, worker_id, physical_key_id, expires_at
            ) VALUES ('p-probe', 'j-rec', 2, 'worker-probe', 'missing-key', '2026-11-01T01:00:00+00:00')
            """,
            (),
        )
        nullable_ok = folder_denied and suite_denied and missing_run and missing_key
        return mutable, duplicate_owner, nullable_ok
    finally:
        connection.execute("ROLLBACK")


def _insert_case(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        INSERT INTO projects (
            project_id, key, name, description, target, created_at,
            actor_id, actor_project_scope, actor_is_local_owner
        ) VALUES (
            'p-probe', 'probe-key', 'Probe', '', 'web', '2026-11-01T00:00:00+00:00',
            'actor-probe', NULL, 1
        )
        """
    )
    connection.execute(
        """
        INSERT INTO automation_cases (
            project_id, case_id, name, folder_id, tc_reference, next_revision,
            latest_draft_version_id, current_approval_id, lock_version, archived_at
        ) VALUES ('p-probe', 'c-probe', 'Case', NULL, NULL, 1, NULL, NULL, 0, NULL)
        """
    )
    connection.execute(
        """
        INSERT INTO case_versions (
            project_id, case_id, version_id, revision, creation_kind, parent_version_id,
            base_version_id, is_branch, definition_json, settings_json, recorded_steps_json,
            content_hash, verification_digest, source_manifest_id, replay_package_id,
            readiness_json, actor_id, reason, created_at
        ) VALUES (
            'p-probe', 'c-probe', 'v-probe', 1, 'input', NULL,
            NULL, 0, '{}', '{}', '[]',
            'hash-probe', 'digest-probe', NULL, NULL,
            '{}', 'actor-probe', 'probe', '2026-11-01T00:00:00+00:00'
        )
        """
    )


def _denied(connection: sqlite3.Connection, sql: str, params: tuple[object, ...]) -> bool:
    connection.execute("SAVEPOINT probe")
    try:
        connection.execute(sql, params)
    except sqlite3.IntegrityError:
        connection.execute("ROLLBACK TO probe")
        connection.execute("RELEASE probe")
        return True
    connection.execute("ROLLBACK TO probe")
    connection.execute("RELEASE probe")
    return False
