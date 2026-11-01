"""Whole-PC backup owned by the API storage service. The worker copy does not open SQLite."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from aiqa.store.models import Actor

WORKER_OPENS_SQLITE = False


class BackupRejected(ValueError):
    """This actor cannot take or read the whole-PC backup."""


class RestoreRejected(ValueError):
    """This restore cannot be checked or activated."""


@dataclass(frozen=True, slots=True)
class BackupSpec:
    project_id: UUID
    actor: Actor


@dataclass(frozen=True, slots=True)
class BackupReceipt:
    receipt_id: UUID
    job_id: UUID
    byte_length: int
    content_hash: str
    state: str
    missing_count: int
    qa: None


@dataclass(frozen=True, slots=True)
class RestoreSpec:
    project_id: UUID
    receipt_id: UUID
    actor: Actor


@dataclass(frozen=True, slots=True)
class RestoreValidation:
    validation_id: UUID
    receipt_id: UUID
    accepted: bool
    schema_ok: bool
    foreign_keys_ok: bool
    integrity_ok: bool
    manifest_ok: bool
    hash_ok: bool
    missing_count: int
    secret_reset_required: bool
    separate_path: str


@dataclass(frozen=True, slots=True)
class RestoreActivation:
    project_id: UUID
    validation_id: UUID
    actor: Actor
    confirmed: bool


@dataclass(frozen=True, slots=True)
class RestoreReceipt:
    activation_id: UUID
    validation_id: UUID
    auto_replayed_jobs: int
    old_leases_reused: bool
    secret_reset_required: bool


def copy_snapshot_bytes(payload: bytes, destination: Path) -> None:
    """Copy bytes a worker already received. This does not open a database."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)


def create_backup(store: object, spec: BackupSpec, now: datetime) -> BackupReceipt:
    """Snapshot the whole store after releasing the write lock. The project id is the request namespace."""

    if not spec.actor.is_local_owner or spec.actor.project_scope not in {None, spec.project_id}:
        raise BackupRejected("local owner required")
    database_path = store.config.database_path  # type: ignore[attr-defined]
    artifacts_dir = store.config.artifacts_dir  # type: ignore[attr-defined]
    backup_root = store.config.runtime_root / "backups"  # type: ignore[attr-defined]
    if not database_path.is_file():
        raise BackupRejected("store is missing")
    clock = now.astimezone(timezone.utc)
    receipt_id = uuid4()
    job_id = uuid4()
    pause_id = str(uuid4())
    pinned: list[str] = []
    with store.transaction() as connection:  # type: ignore[attr-defined]
        _start(connection, spec.project_id, job_id, receipt_id, pause_id, pinned, clock)
    folder = backup_root / str(receipt_id)
    folder.mkdir(parents=True, exist_ok=True)
    snapshot = folder / "snapshot.sqlite"
    digest = ""
    missing = 1
    state = "incomplete"
    try:
        _snapshot(database_path, snapshot)
        saved = snapshot.read_bytes()
        digest = "sha256:" + hashlib.sha256(saved).hexdigest()
        missing = _copy_ready(database_path, spec.project_id, artifacts_dir, folder / "files")
        manifest = {
            "cursors": _cursors(database_path),
            "missing_count": missing,
            "scope": "이 PC 전체 저장소",
            "namespace_project_id": str(spec.project_id),
        }
        (folder / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        state = "incomplete" if missing else "complete"
    finally:
        with store.transaction() as connection:  # type: ignore[attr-defined]
            _finish(
                connection,
                spec.project_id,
                job_id,
                receipt_id,
                pause_id,
                pinned,
                clock,
                snapshot,
                digest,
                state,
                missing,
            )
    if not snapshot.is_file():
        raise BackupRejected("snapshot is missing")
    saved = snapshot.read_bytes()
    return BackupReceipt(receipt_id, job_id, len(saved), digest, state, missing, None)


def validate_restore(store: object, spec: RestoreSpec, now: datetime) -> RestoreValidation:
    """Check a backup on a separate path. The live database file is left in place."""

    if not spec.actor.is_local_owner or spec.actor.project_scope not in {None, spec.project_id}:
        raise RestoreRejected("local owner required")
    database_path = store.config.database_path  # type: ignore[attr-defined]
    backup_root = store.config.runtime_root / "backups" / str(spec.receipt_id)  # type: ignore[attr-defined]
    snapshot = backup_root / "snapshot.sqlite"
    if not snapshot.is_file() or snapshot.resolve() == database_path.resolve():
        raise RestoreRejected("snapshot is missing")
    validation_id = uuid4()
    destination = store.config.runtime_root / "restores" / str(validation_id) / "snapshot.sqlite"  # type: ignore[attr-defined]
    if destination.resolve() == database_path.resolve():
        raise RestoreRejected("restore path overlaps the live store")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(snapshot, destination)
    shutil.copyfile(backup_root / "manifest.json", destination.parent / "manifest.json")
    checks = _inspect_copy(database_path, destination, destination.parent / "manifest.json")
    clock = now.astimezone(timezone.utc)
    with store.transaction() as connection:  # type: ignore[attr-defined]
        owned = connection.execute(
            "SELECT content_hash FROM backup_snapshots WHERE project_id = ? AND receipt_id = ?",
            (str(spec.project_id), str(spec.receipt_id)),
        ).fetchone()
        if owned is None:
            raise RestoreRejected("snapshot is missing")
        digest = "sha256:" + hashlib.sha256(destination.read_bytes()).hexdigest()
        hash_ok = digest == str(owned[0]) and checks["hash_readable"]
        accepted = bool(
            checks["schema_ok"]
            and checks["foreign_keys_ok"]
            and checks["integrity_ok"]
            and checks["manifest_ok"]
            and hash_ok
            and checks["missing_count"] == 0
        )
        connection.execute(
            """
            INSERT INTO restore_validations (
                project_id, validation_id, receipt_id, separate_path, schema_ok, foreign_keys_ok,
                integrity_ok, manifest_ok, hash_ok, missing_count, secret_reset_required, accepted, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                str(spec.project_id),
                str(validation_id),
                str(spec.receipt_id),
                str(destination),
                int(checks["schema_ok"]),
                int(checks["foreign_keys_ok"]),
                int(checks["integrity_ok"]),
                int(checks["manifest_ok"]),
                int(hash_ok),
                int(checks["missing_count"]),
                int(accepted),
                clock.isoformat(),
            ),
        )
    return RestoreValidation(
        validation_id,
        spec.receipt_id,
        accepted,
        bool(checks["schema_ok"]),
        bool(checks["foreign_keys_ok"]),
        bool(checks["integrity_ok"]),
        bool(checks["manifest_ok"]),
        hash_ok,
        int(checks["missing_count"]),
        True,
        str(destination),
    )


def activate_restore(store: object, spec: RestoreActivation, now: datetime) -> RestoreReceipt:
    """Enter maintenance and clear in-progress work. Queued rows are not replayed."""

    if not spec.confirmed:
        raise RestoreRejected("confirmation is required")
    if not spec.actor.is_local_owner or spec.actor.project_scope not in {None, spec.project_id}:
        raise RestoreRejected("local owner required")
    from aiqa.launcher import enter_maintenance

    clock = now.astimezone(timezone.utc)
    activation_id = uuid4()
    with store.transaction() as connection:  # type: ignore[attr-defined]
        row = connection.execute(
            """
            SELECT accepted FROM restore_validations
            WHERE project_id = ? AND validation_id = ?
            """,
            (str(spec.project_id), str(spec.validation_id)),
        ).fetchone()
        if row is None or int(row[0]) != 1:
            raise RestoreRejected("invalid restore stays inactive")
        _clear_progress(connection, clock)
        connection.execute(
            """
            INSERT INTO restore_activations (
                project_id, activation_id, validation_id, auto_replayed_jobs,
                old_leases_reused, secret_reset_required, created_at
            ) VALUES (?, ?, ?, 0, 0, 1, ?)
            """,
            (str(spec.project_id), str(activation_id), str(spec.validation_id), clock.isoformat()),
        )
    enter_maintenance(str(store.config.runtime_root))  # type: ignore[attr-defined]
    return RestoreReceipt(activation_id, spec.validation_id, 0, False, True)


def _inspect_copy(database_path: Path, copy_path: Path, manifest_path: Path) -> dict[str, object]:
    schema_ok = False
    foreign_keys_ok = False
    integrity_ok = False
    hash_readable = False
    missing_count = 1
    manifest_ok = False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if type(manifest) is dict and manifest.get("scope") == "이 PC 전체 저장소":
            missing_count = int(manifest.get("missing_count", 1))
            manifest_ok = True
    except (OSError, ValueError, TypeError):
        manifest_ok = False
    try:
        copied = sqlite3.connect(copy_path)
        live = sqlite3.connect(database_path)
        try:
            copied.execute("PRAGMA foreign_keys = ON")
            integrity_ok = copied.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            foreign_keys_ok = copied.execute("PRAGMA foreign_key_check").fetchone() is None
            hash_readable = True
            schema_ok = _schema_rows(copied) == _schema_rows(live)
        finally:
            copied.close()
            live.close()
    except sqlite3.DatabaseError:
        schema_ok = False
        foreign_keys_ok = False
        integrity_ok = False
        hash_readable = False
    return {
        "schema_ok": schema_ok,
        "foreign_keys_ok": foreign_keys_ok,
        "integrity_ok": integrity_ok,
        "manifest_ok": manifest_ok,
        "hash_readable": hash_readable,
        "missing_count": missing_count,
    }


def _schema_rows(connection: sqlite3.Connection) -> list[tuple[object, ...]]:
    return connection.execute(
        """
        SELECT type, name, sql FROM sqlite_master
        WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'
        ORDER BY type, name
        """
    ).fetchall()


def _clear_progress(connection: sqlite3.Connection, clock: datetime) -> None:
    rows = connection.execute(
        """
        SELECT project_id, job_id FROM jobs
        WHERE status IN ('queued', 'preparing', 'running', 'finalizing', 'cancel_requested')
        """
    ).fetchall()
    for project_id, job_id in rows:
        generation_row = connection.execute(
            """
            SELECT generation FROM leases
            WHERE project_id = ? AND job_id = ?
            ORDER BY generation DESC LIMIT 1
            """,
            (project_id, job_id),
        ).fetchone()
        generation = 1 if generation_row is None else int(generation_row[0])
        connection.execute(
            "UPDATE jobs SET status = 'cancelled' WHERE project_id = ? AND job_id = ?",
            (project_id, job_id),
        )
        connection.execute(
            """
            INSERT INTO job_reconciliations (
                project_id, job_id, generation, outcome, reason, reconciled_at
            ) VALUES (?, ?, ?, 'lost', 'dead_runner', ?)
            """,
            (project_id, job_id, generation, clock.isoformat()),
        )
    connection.execute("DELETE FROM leases")
    connection.execute("DELETE FROM worker_tokens")
    for row in connection.execute("SELECT physical_key_id FROM physical_resource_keys").fetchall():
        connection.execute(
            """
            INSERT OR IGNORE INTO resource_quarantine (physical_key_id, reason, quarantined_at)
            VALUES (?, 'dead_runner', ?)
            """,
            (str(row[0]), clock.isoformat()),
        )
    connection.execute(
        """
        UPDATE recordings
        SET stop_status = 'stopped', completion_status = 'interrupted'
        WHERE stop_status = 'running' OR completion_status = 'open'
        """
    )


def _start(
    connection: sqlite3.Connection,
    project_id: UUID,
    job_id: UUID,
    receipt_id: UUID,
    pause_id: str,
    pinned: list[str],
    clock: datetime,
) -> None:
    connection.execute(
        """
        INSERT INTO jobs (
            project_id, job_id, purpose, recording_id, case_run_id, payload_hash, source_refs, limits, status
        ) VALUES (?, ?, 'backup', NULL, NULL, 'pending', '["pc-store"]', '{}', 'queued')
        """,
        (str(project_id), str(job_id)),
    )
    connection.execute(
        "INSERT INTO backup_receipts (project_id, receipt_id, created_at) VALUES (?, ?, ?)",
        (str(project_id), str(receipt_id), clock.isoformat()),
    )
    connection.execute(
        "INSERT INTO gc_pause (pause_id, reason, created_at) VALUES (?, 'backup', ?)",
        (pause_id, clock.isoformat()),
    )
    for row in connection.execute(
        "SELECT artifact_id FROM artifact_objects WHERE project_id = ? AND status = 'ready'",
        (str(project_id),),
    ).fetchall():
        protection_id = str(uuid4())
        connection.execute(
            """
            INSERT INTO artifact_protections (
                project_id, protection_id, artifact_id, kind, backup_receipt_id, build_id, manual_request_id
            ) VALUES (?, ?, ?, 'backup', ?, NULL, NULL)
            """,
            (str(project_id), protection_id, str(row[0]), str(receipt_id)),
        )
        pinned.append(protection_id)


def _finish(
    connection: sqlite3.Connection,
    project_id: UUID,
    job_id: UUID,
    receipt_id: UUID,
    pause_id: str,
    pinned: list[str],
    clock: datetime,
    snapshot: Path,
    digest: str,
    state: str,
    missing: int,
) -> None:
    for protection_id in pinned:
        connection.execute(
            "DELETE FROM artifact_protections WHERE project_id = ? AND protection_id = ? AND kind = 'backup'",
            (str(project_id), protection_id),
        )
    connection.execute("DELETE FROM gc_pause WHERE pause_id = ?", (pause_id,))
    if not snapshot.is_file() or digest == "":
        return
    connection.execute(
        """
        INSERT INTO backup_snapshots (
            project_id, receipt_id, job_id, byte_length, content_hash, state, missing_count, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (str(project_id), str(receipt_id), str(job_id), snapshot.stat().st_size, digest, state, missing, clock.isoformat()),
    )
    connection.execute(
        "UPDATE jobs SET status = 'completed', payload_hash = ? WHERE project_id = ? AND job_id = ?",
        (digest, str(project_id), str(job_id)),
    )


def _snapshot(database_path: Path, destination: Path) -> None:
    source = sqlite3.connect(database_path)
    try:
        target = sqlite3.connect(destination)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()


def _copy_ready(database_path: Path, project_id: UUID, artifacts_dir: Path, folder: Path) -> int:
    missing = 0
    source = sqlite3.connect(database_path)
    try:
        rows = source.execute(
            "SELECT object_key FROM artifact_objects WHERE project_id = ? AND status = 'ready'",
            (str(project_id),),
        ).fetchall()
    finally:
        source.close()
    for row in rows:
        path = artifacts_dir / str(row[0])
        if not path.is_file():
            missing += 1
            continue
        copy_snapshot_bytes(path.read_bytes(), folder / str(row[0]))
    return missing


def _cursors(database_path: Path) -> dict[str, int]:
    source = sqlite3.connect(database_path)
    try:
        rows = source.execute("SELECT project_id, commit_seq FROM project_commit_clock").fetchall()
    finally:
        source.close()
    return {str(row[0]): int(row[1]) for row in rows}
