"""Attempt event cursor. The ack is the contiguous local seq, not the project commit seq."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from aiqa.contracts.evidence import EvidenceCommitAck, IngestReceipt
from aiqa.contracts.jobs import LeaseToken
from aiqa.store.artifacts import (
    ArtifactReceipt,
    ArtifactReconcileReport,
    ArtifactRejected,
    ArtifactStream,
    ArtifactUpload,
    EvidenceUnavailable,
    acceptable_size,
    content_hash,
    expired_at,
    place_ready,
    publish_durable,
    resolve_stored,
    suffix_for,
)
from aiqa.store.database import Store
from aiqa.store.models import EventEnvelope, WorkerScope
from aiqa.store.queue import LeaseDenied, StaleGeneration

_TERMINAL = frozenset({"completed", "error", "cancelled", "lost"})


@dataclass(frozen=True, slots=True)
class EvidenceArtifactPart:
    filename: str
    media_type: str
    declared_hash: str
    declared_length: int
    body: bytes
    role: str = "source"
    owner_kind: str = "REC"
    owner_id: UUID | None = None
    attempt_id: UUID | None = None
    action_id: str | None = None


class UnsanitizedEvidence(ValueError):
    """Refuse to accept evidence that was not sanitized."""


class EvidenceHashRejected(ValueError):
    """Declared content hash does not match the body."""


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


def commit_sanitized_evidence(
    binding: ArtifactBinding,
    lease: LeaseToken,
    *,
    sanitized: bool,
    events: list[EventEnvelope],
    artifacts: list[EvidenceArtifactPart],
    request_key: str,
    body_fingerprint: str,
) -> EvidenceCommitAck:
    """Commit a contiguous sanitized event prefix and optional artifacts. Late work is recovery-only."""

    if sanitized is not True:
        raise UnsanitizedEvidence("unsanitized evidence cannot be committed")
    if type(request_key) is not str or request_key.strip() == "":
        raise ValueError("idempotency key is required")
    if lease.project_id not in binding.worker.permitted_projects:
        raise LeaseDenied("worker cannot use this lease")
    for part in artifacts:
        digest = content_hash(part.body)
        if part.declared_hash != digest or part.declared_length != len(part.body):
            raise EvidenceHashRejected("artifact hash does not match")
        if not acceptable_size(part.declared_length, part.body):
            raise EvidenceHashRejected("artifact size is invalid")

    worker_id = binding.worker.worker_id
    identity = (
        str(lease.project_id),
        str(lease.job_id),
        lease.generation,
        worker_id,
        request_key.strip(),
    )
    with binding.store.transaction() as connection:
        row = connection.execute(
            """
            SELECT body_hash, response_body FROM evidence_commit_requests
            WHERE project_id=? AND job_id=? AND generation=? AND worker_id=? AND request_key=?
            """,
            identity,
        ).fetchone()
        if row is not None:
            if str(row[0]) != body_fingerprint:
                raise EventConflict("commit key already has another body")
            if row[1]:
                saved = json.loads(str(row[1]))
                saved_ids = saved.get("artifact_ids") or []
                return EvidenceCommitAck(
                    UUID(str(saved["attempt_id"])),
                    int(saved["contiguous_seq"]),
                    str(saved["prefix_hash"]),
                    int(saved["stale_count"]),
                    bool(saved["late"]),
                    int(saved["artifact_count"]),
                    tuple(str(item) for item in saved_ids),
                )
        else:
            connection.execute(
                """
                INSERT INTO evidence_commit_requests (
                    project_id, job_id, generation, worker_id, request_key, body_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (*identity, body_fingerprint, binding.now.astimezone(timezone.utc).isoformat()),
            )

        lease_row = connection.execute(
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
        has_lease = lease_row is not None
        if lease_row is None:
            attempt_row = connection.execute(
                """
                SELECT jobs.status, attempts.attempt_id
                FROM jobs
                JOIN attempts
                  ON attempts.project_id = jobs.project_id
                 AND attempts.job_id = jobs.job_id
                 AND attempts.generation = ?
                WHERE jobs.project_id = ? AND jobs.job_id = ?
                """,
                (lease.generation, str(lease.project_id), str(lease.job_id)),
            ).fetchone()
            if attempt_row is None:
                raise StaleGeneration("lease generation is stale")
            status = str(attempt_row[0])
            attempt_id = str(attempt_row[1])
            late = True
        else:
            if str(lease_row[1]) != worker_id:
                raise LeaseDenied("worker cannot use this lease")
            status = str(lease_row[2])
            attempt_id = str(lease_row[3])
            expires = datetime.fromisoformat(str(lease_row[0]))
            expired = (
                expires.tzinfo is None
                or binding.now.astimezone(timezone.utc) >= expires.astimezone(timezone.utc)
            )
            late = status in _TERMINAL or expired

        finish_before = connection.execute(
            "SELECT verdict, finish_reason, resource_state FROM job_finish_facts WHERE project_id=? AND job_id=?",
            (str(lease.project_id), str(lease.job_id)),
        ).fetchone()
        job_status_before = connection.execute(
            "SELECT status FROM jobs WHERE project_id=? AND job_id=?",
            (str(lease.project_id), str(lease.job_id)),
        ).fetchone()

        if events and has_lease:
            receipt = ingest_stored(connection, binding.worker, lease, events, binding.now)
        elif events and not has_lease:
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
                        "terminal" if status in _TERMINAL else "expired",
                        binding.now.astimezone(timezone.utc).isoformat(),
                    ),
                )
            committed_seq, committed_hash = _cursor(connection, lease.project_id, attempt_id)
            receipt = IngestReceipt(UUID(attempt_id), committed_seq, committed_hash, len(events))
        else:
            committed_seq, committed_hash = _cursor(connection, lease.project_id, attempt_id)
            receipt = IngestReceipt(UUID(attempt_id), committed_seq, committed_hash, 0)

        artifact_ids: list[str] = []
        if artifacts:
            if late:
                for part in artifacts:
                    digest = content_hash(part.body)
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO late_evidence_inbox (
                            project_id, inbox_id, attempt_id, job_id, generation,
                            content_hash, media_type, role, filename, reason, received_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            str(lease.project_id),
                            str(uuid4()),
                            attempt_id,
                            str(lease.job_id),
                            lease.generation,
                            digest,
                            part.media_type,
                            part.role,
                            part.filename,
                            "terminal" if status in _TERMINAL else "expired",
                            binding.now.astimezone(timezone.utc).isoformat(),
                        ),
                    )
            else:
                artifact_ids = _place_active_artifacts(
                    connection,
                    binding,
                    lease,
                    attempt_id=attempt_id,
                    artifacts=artifacts,
                )

        finish_after = connection.execute(
            "SELECT verdict, finish_reason, resource_state FROM job_finish_facts WHERE project_id=? AND job_id=?",
            (str(lease.project_id), str(lease.job_id)),
        ).fetchone()
        job_status_after = connection.execute(
            "SELECT status FROM jobs WHERE project_id=? AND job_id=?",
            (str(lease.project_id), str(lease.job_id)),
        ).fetchone()
        if finish_before != finish_after or job_status_before != job_status_after:
            raise RuntimeError("evidence commit must not change finish or job status")

        artifact_count = len(artifacts) if late else len(artifact_ids)
        ack = EvidenceCommitAck(
            receipt.attempt_id,
            receipt.committed_seq,
            receipt.committed_hash,
            receipt.stale_count,
            late,
            artifact_count,
            tuple(artifact_ids),
        )
        body = {
            "attempt_id": str(ack.attempt_id),
            "contiguous_seq": ack.contiguous_seq,
            "prefix_hash": ack.prefix_hash,
            "stale_count": ack.stale_count,
            "late": ack.late,
            "artifact_count": ack.artifact_count,
            "artifact_ids": list(ack.artifact_ids),
        }
        connection.execute(
            """
            UPDATE evidence_commit_requests
            SET response_body=?
            WHERE project_id=? AND job_id=? AND generation=? AND worker_id=? AND request_key=?
            """,
            (json.dumps(body, sort_keys=True), *identity),
        )
        return ack


def _place_active_artifacts(
    connection: object,
    binding: ArtifactBinding,
    lease: LeaseToken,
    *,
    attempt_id: str,
    artifacts: list[EvidenceArtifactPart],
) -> list[str]:
    """Publish ready PNG/log bytes, link actions, and return durable artifact ids."""

    job = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT jobs.purpose, jobs.recording_id, recordings.case_id, recordings.input_case_version_id
        FROM jobs
        LEFT JOIN recordings
          ON recordings.project_id = jobs.project_id
         AND recordings.recording_id = jobs.recording_id
        WHERE jobs.project_id = ? AND jobs.job_id = ?
        """,
        (str(lease.project_id), str(lease.job_id)),
    ).fetchone()
    if job is None:
        raise ValueError("job is missing")
    purpose = str(job[0])
    recording_id = None if job[1] is None else str(job[1])
    case_id = None if job[2] is None else str(job[2])
    case_version_id = None if job[3] is None else str(job[3])
    stored_ids: list[str] = []
    stamped = binding.now.astimezone(timezone.utc).isoformat()
    for part in artifacts:
        digest = content_hash(part.body)
        if part.declared_hash != digest or part.declared_length != len(part.body):
            raise EvidenceHashRejected("artifact hash does not match")
        if not acceptable_size(part.declared_length, part.body):
            raise ValueError("artifact is too large")
        suffix = suffix_for(part.filename, part.media_type)
        if suffix is None:
            raise ValueError("artifact filename is invalid")
        action_id = part.action_id
        if action_id is not None and action_id.strip() != "":
            if purpose != "recording" or recording_id is None or case_id is None or case_version_id is None:
                raise ValueError("action evidence requires a recording job")
            _ensure_recording_action(
                connection,
                project_id=str(lease.project_id),
                attempt_id=attempt_id,
                action_id=action_id,
                case_id=case_id,
                case_version_id=case_version_id,
            )
        owner_id = part.owner_id
        if owner_id is None and recording_id is not None:
            owner_id = UUID(recording_id)
        if owner_id is None:
            raise ValueError("artifact owner is required")
        existing = connection.execute(  # type: ignore[attr-defined]
            """
            SELECT artifact_id FROM artifact_objects
            WHERE project_id = ? AND attempt_id = ? AND content_hash = ? AND role = ?
              AND status = 'ready' AND acked = 1
            LIMIT 1
            """,
            (str(lease.project_id), attempt_id, digest, part.role),
        ).fetchone()
        if existing is not None:
            stored_ids.append(str(existing[0]))
            continue
        artifact_id = uuid4()
        try:
            durable = publish_durable(
                binding.store.config.artifacts_dir,
                lease.project_id,
                artifact_id,
                suffix,
                part.body,
                declared_hash=digest,
            )
        except ArtifactRejected as exc:
            raise ValueError(str(exc)) from exc
        if action_id is not None and action_id.strip() != "":
            connection.execute(  # type: ignore[attr-defined]
                """
                INSERT INTO artifact_refs(project_id, artifact_id, attempt_id, action_id)
                VALUES (?, ?, ?, ?)
                """,
                (str(lease.project_id), str(artifact_id), attempt_id, action_id),
            )
        elif recording_id is not None:
            connection.execute(  # type: ignore[attr-defined]
                """
                INSERT INTO artifact_refs(project_id, artifact_id, recording_id)
                VALUES (?, ?, ?)
                """,
                (str(lease.project_id), str(artifact_id), recording_id),
            )
        else:
            raise ValueError("artifact must bind to an action or recording")
        connection.execute(  # type: ignore[attr-defined]
            """
            INSERT INTO artifact_objects(
                project_id, artifact_id, object_key, content_hash, byte_length,
                media_type, owner_id, status, acked, custody, stored_at,
                owner_kind, attempt_id, action_id, check_id, role, job_id, generation
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'ready', 1, 'stored', ?, ?, ?, ?, NULL, ?, ?, ?)
            """,
            (
                str(lease.project_id),
                str(artifact_id),
                durable.object_key,
                digest,
                len(part.body),
                part.media_type,
                str(owner_id),
                stamped,
                part.owner_kind,
                attempt_id,
                action_id,
                part.role,
                str(lease.job_id),
                lease.generation,
            ),
        )
        stored_ids.append(str(artifact_id))
    return stored_ids


def _ensure_recording_action(
    connection: object,
    *,
    project_id: str,
    attempt_id: str,
    action_id: str,
    case_id: str,
    case_version_id: str,
) -> None:
    row = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT 1 FROM actions
        WHERE project_id = ? AND attempt_id = ? AND action_id = ?
        """,
        (project_id, attempt_id, action_id),
    ).fetchone()
    if row is not None:
        return
    seq_row = connection.execute(  # type: ignore[attr-defined]
        "SELECT COALESCE(MAX(action_seq), 0) FROM actions WHERE project_id = ? AND attempt_id = ?",
        (project_id, attempt_id),
    ).fetchone()
    next_seq = 1 if seq_row is None else int(seq_row[0]) + 1
    connection.execute(  # type: ignore[attr-defined]
        """
        INSERT INTO actions (
            project_id, attempt_id, action_seq, step_id, action_id, proposal_hash,
            dispatch_state, case_id, case_version_id, outcome_known
        ) VALUES (?, ?, ?, ?, ?, ?, 'observed', ?, ?, 1)
        """,
        (
            project_id,
            attempt_id,
            next_seq,
            action_id,
            action_id,
            "sha256:" + hashlib.sha256(action_id.encode("utf-8")).hexdigest(),
            case_id,
            case_version_id,
        ),
    )


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
    from aiqa.store.artifacts import ArtifactRejected, open_durable

    try:
        body = open_durable(binding.store.config.artifacts_dir, str(row[1]), str(row[2]))
    except ArtifactRejected as exc:
        reason = str(exc)
        if "hash" in reason:
            return EvidenceUnavailable("corruption")
        return EvidenceUnavailable("missing")
    if str(row[5]) == "expired" or expired_at(str(row[6]), binding.now):
        return EvidenceUnavailable("expired")
    if str(row[3]) not in {"image/png", "text/plain"}:
        return EvidenceUnavailable("missing")
    return ArtifactStream(body, str(row[3]))


def _spooling_files(root: Path, ready_paths: set[Path]) -> int:
    if not root.exists():
        return 0
    count = 0
    for path in root.rglob("*"):
        if not path.is_file() or path.resolve() in ready_paths:
            continue
        count += 1
    return count
