"""Attempt event cursor. The ack is the contiguous local seq, not the project commit seq."""

from __future__ import annotations

import hashlib
import sqlite3
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from aiqa.contracts.evidence import IngestReceipt
from aiqa.contracts.jobs import LeaseToken
from aiqa.store.artifacts import (
    ArtifactReceipt,
    ArtifactReconcileReport,
    ArtifactStream,
    ArtifactUpload,
    EvidenceUnavailable,
    acceptable_size,
    content_hash,
    expired_at,
    place_ready,
    resolve_stored,
    suffix_for,
)
from aiqa.store.database import Store
from aiqa.store.models import EventEnvelope, WorkerScope
from aiqa.store.queue import LeaseDenied, StaleGeneration

_TERMINAL = frozenset({"completed", "error", "cancelled", "lost"})


@dataclass(frozen=True, slots=True)
class ArtifactBinding:
    store: Store
    worker: WorkerScope
    now: datetime


_artifact_binding: ContextVar[ArtifactBinding] = ContextVar("aiqa_artifact_binding")


def bind_artifact_ingest(binding: ArtifactBinding):
    return _artifact_binding.set(binding)


def reset_artifact_ingest(token) -> None:
    _artifact_binding.reset(token)


class EventConflict(Exception):
    """The same local seq arrived with a different hash."""


def ingest_stored(
    connection: sqlite3.Connection,
    worker: WorkerScope,
    lease: LeaseToken,
    events: list[EventEnvelope],
    now: datetime,
) -> IngestReceipt:
    """Store new events and return the contiguous spool ack."""

    if lease.project_id not in worker.permitted_projects:
        raise LeaseDenied("worker cannot use this lease")
    row = connection.execute(
        """
        SELECT leases.expires_at, leases.worker_id, jobs.status, attempts.attempt_id
        FROM leases
        JOIN jobs
          ON jobs.project_id = leases.project_id
         AND jobs.job_id = leases.job_id
        JOIN attempts
          ON attempts.project_id = leases.project_id
         AND attempts.job_id = leases.job_id
         AND attempts.generation = leases.generation
        WHERE leases.project_id = ? AND leases.job_id = ? AND leases.generation = ?
        """,
        (str(lease.project_id), str(lease.job_id), lease.generation),
    ).fetchone()
    if row is None:
        raise StaleGeneration("lease generation is stale")
    if str(row[1]) != worker.worker_id:
        raise LeaseDenied("worker cannot use this lease")
    attempt_id = str(row[3])
    expires = datetime.fromisoformat(str(row[0]))
    terminal = str(row[2]) in _TERMINAL
    expired = expires.tzinfo is None or now.astimezone(timezone.utc) >= expires.astimezone(timezone.utc)
    if terminal or expired:
        reason = "terminal" if terminal else "expired"
        for event in events:
            _require_event(event, lease.project_id, attempt_id)
            connection.execute(
                """
                INSERT INTO stale_event_inbox (
                    project_id, inbox_id, attempt_id, job_id, generation, local_seq,
                    payload_hash, body_hash, reason, received_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(lease.project_id),
                    str(uuid4()),
                    attempt_id,
                    str(lease.job_id),
                    lease.generation,
                    event.local_seq,
                    event.payload_hash,
                    event.body_hash,
                    reason,
                    now.astimezone(timezone.utc).isoformat(),
                ),
            )
        committed_seq, committed_hash = _cursor(connection, lease.project_id, attempt_id)
        return IngestReceipt(UUID(attempt_id), committed_seq, committed_hash, len(events))
    for event in events:
        _require_event(event, lease.project_id, attempt_id)
        existing = connection.execute(
            """
            SELECT payload_hash, body_hash FROM attempt_events
            WHERE project_id = ? AND attempt_id = ? AND local_seq = ?
            """,
            (str(lease.project_id), attempt_id, event.local_seq),
        ).fetchone()
        if existing is None:
            connection.execute(
                """
                INSERT INTO attempt_events (
                    project_id, event_id, attempt_id, local_seq, captured_at, event_type,
                    minimum_facts, payload_hash, body_hash, detail_payload, sealed
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    str(lease.project_id),
                    str(event.event_id),
                    attempt_id,
                    event.local_seq,
                    event.captured_at,
                    event.event_type,
                    event.minimum_facts,
                    event.payload_hash,
                    event.body_hash,
                    event.detail_payload,
                ),
            )
        elif str(existing[0]) != event.payload_hash or str(existing[1]) != event.body_hash:
            raise EventConflict("event hash does not match")
    committed_seq, committed_hash = _cursor(connection, lease.project_id, attempt_id)
    return IngestReceipt(UUID(attempt_id), committed_seq, committed_hash, 0)


def _require_event(event: EventEnvelope, project_id: UUID, attempt_id: str) -> None:
    if event.project_id != project_id or str(event.attempt_id) != attempt_id:
        raise ValueError("event attempt does not match the lease")
    if type(event.local_seq) is not int or event.local_seq < 1:
        raise ValueError("local seq is invalid")
    if event.event_type.strip() == "" or event.payload_hash.strip() == "" or event.body_hash.strip() == "":
        raise ValueError("event hash is invalid")


def _cursor(connection: sqlite3.Connection, project_id: UUID, attempt_id: str) -> tuple[int, str]:
    rows = connection.execute(
        """
        SELECT local_seq, payload_hash, body_hash
        FROM attempt_events
        WHERE project_id = ? AND attempt_id = ?
        ORDER BY local_seq
        """,
        (str(project_id), attempt_id),
    ).fetchall()
    stored = {int(seq): (str(payload), str(body)) for seq, payload, body in rows}
    parts: list[str] = []
    seq = 1
    while seq in stored:
        payload, body = stored[seq]
        parts.append(f"{seq}:{payload}:{body}")
        seq += 1
    digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()
    return seq - 1, "sha256:" + digest


def ingest_artifact(lease: LeaseToken, upload: ArtifactUpload, *, fail_ready: bool = False) -> ArtifactReceipt:
    from aiqa.store.artifact_ingest import ingest_uploaded
    return ingest_uploaded(_artifact_binding.get(), lease, upload, fail_ready=fail_ready)


def _require_artifact_lease(
    connection: sqlite3.Connection, worker: WorkerScope, lease: LeaseToken, now: datetime
) -> None:
    row = connection.execute(
        """
        SELECT leases.expires_at, leases.worker_id, jobs.status
        FROM leases
        JOIN jobs
          ON jobs.project_id = leases.project_id
         AND jobs.job_id = leases.job_id
        WHERE leases.project_id = ? AND leases.job_id = ? AND leases.generation = ?
        """,
        (str(lease.project_id), str(lease.job_id), lease.generation),
    ).fetchone()
    if row is None:
        raise StaleGeneration("lease generation is stale")
    if str(row[1]) != worker.worker_id or str(row[2]) in _TERMINAL:
        raise LeaseDenied("worker cannot use this lease")
    expires = datetime.fromisoformat(str(row[0]))
    if expires.tzinfo is None or now.astimezone(timezone.utc) >= expires.astimezone(timezone.utc):
        raise LeaseDenied("worker cannot use this lease")


def reconcile_artifacts() -> ArtifactReconcileReport:
    """Mark missing, corrupt, and expired files. The stored hash is not replaced."""

    binding = _artifact_binding.get()
    root = binding.store.config.artifacts_dir
    with binding.store.transaction() as connection:
        rows = connection.execute(
            """
            SELECT project_id, artifact_id, object_key, content_hash, status, stored_at, owner_kind
            FROM artifact_objects
            """
        ).fetchall()
    ready_paths: set[Path] = set()
    updates: list[tuple[str, str, str]] = []
    missing = corruption = expired = stored = 0
    for project_id, artifact_id, object_key, digest, status, stored_at, owner_kind in rows:
        if str(status) != "ready":
            continue
        if owner_kind is None:
            updates.append(('unverified', str(project_id), str(artifact_id)))
            continue
        path = resolve_stored(root, str(object_key))
        if path is None or not path.is_file():
            custody = "missing"
            missing += 1
        else:
            ready_paths.add(path)
            if content_hash(path.read_bytes()) != str(digest):
                custody = "corruption"
                corruption += 1
            elif expired_at(str(stored_at), binding.now):
                custody = "expired"
                expired += 1
            else:
                custody = "stored"
                stored += 1
        updates.append((custody, str(project_id), str(artifact_id)))
    with binding.store.transaction() as connection:
        connection.executemany(
            """
            UPDATE artifact_objects SET custody = ?
            WHERE project_id = ? AND artifact_id = ?
            """,
            updates,
        )
    spooling = _spooling_files(root, ready_paths)
    return ArtifactReconcileReport(missing, corruption, expired, spooling, stored)


def artifact_project(artifact_id: UUID) -> UUID | None:
    binding = _artifact_binding.get()
    with binding.store.transaction() as connection:
        row = connection.execute(
            "SELECT project_id FROM artifact_objects WHERE artifact_id = ?",
            (str(artifact_id),),
        ).fetchone()
    if row is None:
        return None
    return UUID(str(row[0]))


def open_artifact(artifact_id: UUID) -> ArtifactStream | EvidenceUnavailable:
    """Return ready bytes, or the reason the file cannot be read."""

    binding = _artifact_binding.get()
    with binding.store.transaction() as connection:
        row = connection.execute(
            """
            SELECT project_id, object_key, content_hash, media_type, status, custody, stored_at, owner_kind
            FROM artifact_objects
            WHERE artifact_id = ?
            """,
            (str(artifact_id),),
        ).fetchone()
    if row is None or str(row[4]) != "ready":
        return EvidenceUnavailable("missing")
    if row[7] is None:
        return EvidenceUnavailable('unverified')
    path = resolve_stored(binding.store.config.artifacts_dir, str(row[1]))
    if path is None or not path.is_file():
        return EvidenceUnavailable("missing")
    if content_hash(path.read_bytes()) != str(row[2]):
        return EvidenceUnavailable("corruption")
    if str(row[5]) == "expired" or expired_at(str(row[6]), binding.now):
        return EvidenceUnavailable("expired")
    if str(row[3]) not in {"image/png", "text/plain"}:
        return EvidenceUnavailable("missing")
    return ArtifactStream(path.read_bytes(), str(row[3]))


def _spooling_files(root: Path, ready_paths: set[Path]) -> int:
    if not root.exists():
        return 0
    count = 0
    for path in root.rglob("*"):
        if not path.is_file() or path.resolve() in ready_paths:
            continue
        count += 1
    return count
