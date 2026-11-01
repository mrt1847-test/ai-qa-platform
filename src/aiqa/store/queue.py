"""Durable job submission. One transaction owns the owner row, the job, and the receipt."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from aiqa.contracts.jobs import (
    MANAGEMENT_JOB_PURPOSES,
    AttemptReceipt,
    IdempotencyKey,
    JobLease,
    JobReceipt,
    JobSnapshot,
    JobSubmission,
    LeaseToken,
    ReconciliationReport,
    LeaseView,
    require_job_purpose,
)
from aiqa.domain.hashing import canonical_hash, canonical_json
from aiqa.store.models import Actor, Transaction, WorkerScope

_OPERATION = "enqueue_job"


class JobConflict(Exception):
    """The same idempotency key arrived with a different body."""


class JobNotFound(Exception):
    """The job is not in this project."""


class CancelRejected(Exception):
    """A new cancel cannot change this job."""


def enqueue_job(tx: Transaction, submission: JobSubmission, key: IdempotencyKey) -> JobReceipt:
    """Insert a purpose owner and its queued job, or return the stored receipt."""

    if key.project_id != submission.project_id or key.operation != _OPERATION or key.key.strip() == "":
        raise ValueError("idempotency key does not match this submission")
    purpose = require_job_purpose(submission.purpose)
    limits = _limits(submission.limits)
    refs = _refs(submission.source_refs)
    body_hash = _body_hash(submission, limits, refs)
    connection = tx.connection
    existing = connection.execute(
        """
        SELECT body_hash, job_id, purpose, recording_id, execution_id, case_run_id, status
        FROM job_receipts
        WHERE project_id = ? AND actor_id = ? AND operation = ? AND request_key = ?
        """,
        (str(key.project_id), str(key.actor_id), key.operation, key.key),
    ).fetchone()
    if existing is not None:
        if str(existing[0]) != body_hash:
            raise JobConflict("idempotency body does not match")
        return _stored(key.project_id, existing, body_hash, True)
    recording_id: UUID | None = None
    execution_id: UUID | None = None
    case_run_id: UUID | None = None
    if purpose == "recording":
        recording_id = _insert_recording(connection, submission)
    elif purpose in {"trial", "regression"}:
        execution_id, case_run_id = _insert_item(connection, submission, purpose)
    elif purpose in MANAGEMENT_JOB_PURPOSES:
        if submission.case_id is not None or submission.case_version_id is not None or refs == []:
            raise ValueError("management job needs source refs and no owner")
    job_id = uuid4()
    source_refs = json.dumps(refs, ensure_ascii=False, separators=(",", ":"))
    connection.execute(
        """
        INSERT INTO jobs (
            project_id, job_id, purpose, recording_id, case_run_id,
            payload_hash, source_refs, limits, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued')
        """,
        (
            str(submission.project_id),
            str(job_id),
            purpose,
            None if recording_id is None else str(recording_id),
            None if case_run_id is None else str(case_run_id),
            body_hash,
            source_refs,
            limits,
        ),
    )
    connection.execute(
        """
        INSERT INTO job_receipts (
            project_id, actor_id, operation, request_key, body_hash, job_id, purpose,
            recording_id, execution_id, case_run_id, status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?)
        """,
        (
            str(submission.project_id),
            str(key.actor_id),
            key.operation,
            key.key,
            body_hash,
            str(job_id),
            purpose,
            None if recording_id is None else str(recording_id),
            None if execution_id is None else str(execution_id),
            None if case_run_id is None else str(case_run_id),
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    return JobReceipt(
        job_id=job_id,
        purpose=purpose,
        status="queued",
        recording_id=recording_id,
        execution_id=execution_id,
        case_run_id=case_run_id,
        status_href=_href(submission.project_id, job_id),
        replayed=False,
        body_hash=body_hash,
    )


def enqueue_export(
    tx: Transaction,
    key: IdempotencyKey,
    execution_id: UUID,
    manifest: dict[str, object],
    request_hash: str,
) -> tuple[UUID, bool]:
    """Queue one export job. The same key and body return the original job."""

    if key.operation != "export_execution" or key.key.strip() == "" or key.project_id is None:
        raise ValueError("idempotency key does not match this export")
    connection = tx.connection
    existing = connection.execute(
        """
        SELECT body_hash, job_id FROM job_receipts
        WHERE project_id = ? AND actor_id = ? AND operation = ? AND request_key = ?
        """,
        (str(key.project_id), str(key.actor_id), key.operation, key.key),
    ).fetchone()
    if existing is not None:
        if str(existing[0]) != request_hash:
            raise JobConflict("idempotency body does not match")
        return UUID(str(existing[1])), True
    limits = canonical_json(manifest)
    job_id = uuid4()
    refs = [f"execution:{execution_id}"]
    connection.execute(
        """
        INSERT INTO jobs (
            project_id, job_id, purpose, recording_id, case_run_id,
            payload_hash, source_refs, limits, status
        ) VALUES (?, ?, 'export', NULL, NULL, ?, ?, ?, 'queued')
        """,
        (
            str(key.project_id),
            str(job_id),
            request_hash,
            json.dumps(refs, ensure_ascii=False, separators=(",", ":")),
            limits,
        ),
    )
    connection.execute(
        """
        INSERT INTO job_receipts (
            project_id, actor_id, operation, request_key, body_hash, job_id, purpose,
            recording_id, execution_id, case_run_id, status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'export', NULL, ?, NULL, 'queued', ?)
        """,
        (
            str(key.project_id),
            str(key.actor_id),
            key.operation,
            key.key,
            request_hash,
            str(job_id),
            str(execution_id),
            str(manifest["created_at"]),
        ),
    )
    return job_id, False


def load_job(tx: Transaction, project_id: UUID, job_id: UUID) -> JobReceipt:
    """Read one queued or later job. This does not claim it."""

    row = tx.connection.execute(
        """
        SELECT jobs.purpose, jobs.status, jobs.recording_id, jobs.case_run_id, jobs.payload_hash,
               case_runs.execution_id
        FROM jobs
        LEFT JOIN case_runs
          ON case_runs.project_id = jobs.project_id
         AND case_runs.case_run_id = jobs.case_run_id
        WHERE jobs.project_id = ? AND jobs.job_id = ?
        """,
        (str(project_id), str(job_id)),
    ).fetchone()
    if row is None:
        raise JobNotFound("job was not found")
    return JobReceipt(
        job_id=job_id,
        purpose=str(row[0]),
        status=str(row[1]),
        recording_id=None if row[2] is None else UUID(str(row[2])),
        execution_id=None if row[5] is None else UUID(str(row[5])),
        case_run_id=None if row[3] is None else UUID(str(row[3])),
        status_href=_href(project_id, job_id),
        replayed=False,
        body_hash=str(row[4]),
    )


def _stored(project_id: UUID, row: object, body_hash: str, replayed: bool) -> JobReceipt:
    values = tuple(row)  # type: ignore[arg-type]
    job_id = UUID(str(values[1]))
    return JobReceipt(
        job_id=job_id,
        purpose=str(values[2]),
        status=str(values[6]),
        recording_id=None if values[3] is None else UUID(str(values[3])),
        execution_id=None if values[4] is None else UUID(str(values[4])),
        case_run_id=None if values[5] is None else UUID(str(values[5])),
        status_href=_href(project_id, job_id),
        replayed=replayed,
        body_hash=body_hash,
    )


def _insert_recording(connection: object, submission: JobSubmission) -> UUID:
    _require_version(connection, submission)
    recording_id = uuid4()
    connection.execute(  # type: ignore[attr-defined]
        """
        INSERT INTO recordings (
            project_id, case_id, recording_id, creation_kind, input_case_version_id,
            base_case_version_id, parent_recording_id, source_recording_id,
            storage_status, stop_status, completion_status, evidence_status
        ) VALUES (?, ?, ?, 'recorded', ?, ?, NULL, NULL, 'local', 'running', 'open', 'incomplete')
        """,
        (
            str(submission.project_id),
            str(submission.case_id),
            str(recording_id),
            str(submission.case_version_id),
            None if submission.base_case_version_id is None else str(submission.base_case_version_id),
        ),
    )
    return recording_id


def _insert_item(connection: object, submission: JobSubmission, purpose: str) -> tuple[UUID, UUID]:
    _require_version(connection, submission)
    execution_id = uuid4()
    case_run_id = uuid4()
    requested_at = datetime.now(timezone.utc).isoformat()
    connection.execute(  # type: ignore[attr-defined]
        """
        INSERT INTO executions (
            project_id, execution_id, name, purpose, source, suite_version_id, scope_requested_at
        ) VALUES (?, ?, ?, ?, 'single', NULL, ?)
        """,
        (str(submission.project_id), str(execution_id), purpose, purpose, requested_at),
    )
    connection.execute(  # type: ignore[attr-defined]
        """
        INSERT INTO case_runs (
            project_id, execution_id, case_run_id, case_id, case_version_id, purpose, requested_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(submission.project_id),
            str(execution_id),
            str(case_run_id),
            str(submission.case_id),
            str(submission.case_version_id),
            purpose,
            requested_at,
        ),
    )
    return execution_id, case_run_id


def _require_version(connection: object, submission: JobSubmission) -> None:
    if submission.case_id is None or submission.case_version_id is None:
        raise ValueError("case version is required")
    row = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT 1 FROM case_versions
        WHERE project_id = ? AND case_id = ? AND version_id = ?
        """,
        (str(submission.project_id), str(submission.case_id), str(submission.case_version_id)),
    ).fetchone()
    if row is None:
        raise ValueError("case version is required")


def _limits(limits: str) -> str:
    try:
        parsed = json.loads(limits)
    except json.JSONDecodeError as exc:
        raise ValueError("limits must be an object") from exc
    if type(parsed) is not dict:
        raise ValueError("limits must be an object")
    return canonical_json(parsed)


def _refs(source_refs: tuple[str, ...]) -> list[str]:
    refs: list[str] = []
    for item in source_refs:
        if type(item) is not str or item.strip() == "":
            raise ValueError("source ref is invalid")
        refs.append(item)
    return refs


def _body_hash(submission: JobSubmission, limits: str, refs: list[str]) -> str:
    return canonical_hash(
        {
            "case_id": None if submission.case_id is None else str(submission.case_id),
            "case_version_id": None if submission.case_version_id is None else str(submission.case_version_id),
            "limits": limits,
            "purpose": submission.purpose,
            "source_refs": refs,
        },
        "canon-json-v1",
    )


def _href(project_id: UUID, job_id: UUID) -> str:
    return f"/api/v1/projects/{project_id}/jobs/{job_id}"


_ACTIVE = ("preparing", "running", "finalizing", "cancel_requested")
_TERMINAL = frozenset({"completed", "error", "cancelled", "lost"})
_PHYSICAL = frozenset({"recording", "trial", "regression", "resource_probe", "app_install"})
_LEASE_SECONDS = 45
_HEARTBEAT_SECONDS = 10
_POLL_SECONDS = 2
_WATCHDOG_SECONDS = 30


def claim_queued_job(connection: sqlite3.Connection, worker: WorkerScope, now: datetime) -> JobLease | None:
    """Claim one queued job. Slot, device, and the previous item are checked together."""

    projects = tuple(str(project_id) for project_id in worker.permitted_projects)
    purposes = tuple(purpose for purpose in worker.permitted_purposes if purpose.strip() != "")
    if projects == () or purposes == () or _active_slots(connection) >= 1:
        return None
    project_marks = ", ".join("?" for _ in projects)
    purpose_marks = ", ".join("?" for _ in purposes)
    rows = connection.execute(
        f"""
        SELECT project_id, job_id, purpose, case_run_id, source_refs
        FROM jobs
        WHERE status = 'queued' AND project_id IN ({project_marks}) AND purpose IN ({purpose_marks})
        ORDER BY rowid
        """,
        (*projects, *purposes),
    ).fetchall()
    for project_id, job_id, purpose, case_run_id, source_refs in rows:
        if _cleanup_pending(connection, str(project_id), None if case_run_id is None else str(case_run_id)):
            continue
        if _previous_item_blocks(connection, str(project_id), None if case_run_id is None else str(case_run_id)):
            continue
        if _approval_blocks_claim(connection, str(project_id), str(job_id)):
            continue
        if _snapshot_blocks_claim(connection, str(project_id), str(job_id), str(purpose), source_refs):
            continue
        usable, physical_key_id = _device(connection, str(project_id), str(purpose), str(source_refs))
        if not usable or _active_slots(connection) >= 1:
            continue
        updated = connection.execute(
            """
            UPDATE jobs SET status = 'preparing'
            WHERE project_id = ? AND job_id = ? AND status = 'queued'
            """,
            (str(project_id), str(job_id)),
        )
        if updated.rowcount != 1:
            continue
        attempt_id = uuid4()
        expires_at = (now.astimezone(timezone.utc) + timedelta(seconds=_LEASE_SECONDS)).isoformat()
        connection.execute(
            """
            INSERT INTO leases (
                project_id, job_id, generation, worker_id, physical_key_id, expires_at
            ) VALUES (?, ?, 1, ?, ?, ?)
            """,
            (str(project_id), str(job_id), worker.worker_id, physical_key_id, expires_at),
        )
        connection.execute(
            """
            INSERT INTO attempts (project_id, attempt_id, job_id, generation, physical_key_id)
            VALUES (?, ?, ?, 1, ?)
            """,
            (str(project_id), str(attempt_id), str(job_id), physical_key_id),
        )
        return JobLease(
            project_id=UUID(str(project_id)),
            job_id=UUID(str(job_id)),
            generation=1,
            worker_id=worker.worker_id,
            physical_key_id=None if physical_key_id is None else UUID(physical_key_id),
            expires_at=expires_at,
            attempt_id=attempt_id,
        )
    return None


def _active_slots(connection: sqlite3.Connection) -> int:
    marks = ", ".join("?" for _ in _ACTIVE)
    row = connection.execute(
        f"SELECT COUNT(*) FROM jobs WHERE status IN ({marks})",
        _ACTIVE,
    ).fetchone()
    return 0 if row is None else int(row[0])


def _snapshot_blocks_claim(
    connection: sqlite3.Connection, project_id: str, job_id: str, purpose: str, source_refs: object
) -> bool:
    from aiqa.domain.executions import validate_claim_snapshot
    from aiqa.store.models import JobSpec

    row = connection.execute(
        "SELECT payload_hash, limits, recording_id, case_run_id, status FROM jobs WHERE project_id = ? AND job_id = ?",
        (project_id, job_id),
    ).fetchone()
    if row is None:
        return True
    spec = JobSpec(
        UUID(project_id),
        UUID(job_id),
        purpose,
        None if row[2] is None else UUID(str(row[2])),
        None if row[3] is None else UUID(str(row[3])),
        str(row[0]),
        "" if source_refs is None else str(source_refs),
        str(row[1]),
        str(row[4]),
    )
    return validate_claim_snapshot(spec, connection).status == "BLOCKED"


def _approval_blocks_claim(connection: sqlite3.Connection, project_id: str, job_id: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM approval_queue_blocks WHERE project_id = ? AND job_id = ?",
        (project_id, job_id),
    ).fetchone()
    return row is not None


def _previous_item_blocks(connection: sqlite3.Connection, project_id: str, case_run_id: str | None) -> bool:
    """Hold the next item until the earlier item is terminal and its cleanup is clear."""

    if case_run_id is None:
        return False
    current = connection.execute(
        "SELECT execution_id, rowid FROM case_runs WHERE project_id = ? AND case_run_id = ?",
        (project_id, case_run_id),
    ).fetchone()
    if current is None:
        return False
    own = connection.execute(
        "SELECT 1 FROM item_finalizations WHERE project_id = ? AND case_run_id = ?",
        (project_id, case_run_id),
    ).fetchone()
    if own is not None:
        return True
    earlier = connection.execute(
        """
        SELECT case_run_id FROM case_runs
        WHERE project_id = ? AND execution_id = ? AND rowid < ?
        ORDER BY rowid
        """,
        (project_id, str(current[0]), int(current[1])),
    ).fetchall()
    for (earlier_id,) in earlier:
        final = connection.execute(
            "SELECT 1 FROM item_finalizations WHERE project_id = ? AND case_run_id = ?",
            (project_id, str(earlier_id)),
        ).fetchone()
        if final is None:
            return True
        quarantined = connection.execute(
            """
            SELECT 1
            FROM job_finish_facts
            JOIN jobs
              ON jobs.project_id = job_finish_facts.project_id
             AND jobs.job_id = job_finish_facts.job_id
            WHERE jobs.project_id = ? AND jobs.case_run_id = ? AND job_finish_facts.resource_state = 'quarantine'
            """,
            (project_id, str(earlier_id)),
        ).fetchone()
        if quarantined is not None:
            return True
    return False


def _cleanup_pending(connection: sqlite3.Connection, project_id: str, case_run_id: str | None) -> bool:
    if case_run_id is None:
        return False
    earlier = connection.execute(
        """
        SELECT jobs.job_id, jobs.status
        FROM case_runs AS current_run
        JOIN case_runs AS earlier_run
          ON earlier_run.project_id = current_run.project_id
         AND earlier_run.case_id = current_run.case_id
         AND earlier_run.requested_at < current_run.requested_at
        JOIN jobs
          ON jobs.project_id = earlier_run.project_id
         AND jobs.case_run_id = earlier_run.case_run_id
        WHERE current_run.project_id = ? AND current_run.case_run_id = ?
        """,
        (project_id, case_run_id),
    ).fetchall()
    for job_id, status in earlier:
        if str(status) not in _TERMINAL:
            return True
        lease = connection.execute(
            "SELECT 1 FROM leases WHERE project_id = ? AND job_id = ?",
            (project_id, str(job_id)),
        ).fetchone()
        if lease is not None:
            return True
    return False


def _device(
    connection: sqlite3.Connection, project_id: str, purpose: str, source_refs: str
) -> tuple[bool, str | None]:
    if purpose not in _PHYSICAL:
        return True, None
    try:
        refs = json.loads(source_refs)
    except json.JSONDecodeError:
        return False, None
    if type(refs) is not list:
        return False, None
    for ref in refs:
        if type(ref) is not str:
            continue
        alias = connection.execute(
            """
            SELECT 1 FROM resource_aliases
            WHERE project_id = ? AND physical_key_id = ?
            """,
            (project_id, ref),
        ).fetchone()
        if alias is None:
            continue
        busy = connection.execute(
            "SELECT COUNT(*) FROM leases WHERE physical_key_id = ?",
            (ref,),
        ).fetchone()
        if busy is not None and int(busy[0]) > 0:
            return False, None
        return True, ref
    return False, None


class StaleGeneration(Exception):
    """The lease generation is missing or expired."""


class RunnerConflict(Exception):
    """This attempt already has a different runner nonce."""


class LeaseDenied(Exception):
    """The worker cannot use this lease."""


def renew_lease_row(
    connection: sqlite3.Connection,
    worker: WorkerScope,
    lease: LeaseToken,
    now: datetime,
    model_wait: bool,
) -> LeaseView:
    """Extend one generation. Model wait keeps the same heartbeat."""

    if type(model_wait) is not bool:
        raise ValueError("model wait is invalid")
    _require_open_lease(connection, worker, lease, now)
    expires_at = (now.astimezone(timezone.utc) + timedelta(seconds=_LEASE_SECONDS)).isoformat()
    connection.execute(
        """
        UPDATE leases SET expires_at = ?
        WHERE project_id = ? AND job_id = ? AND generation = ? AND worker_id = ?
        """,
        (expires_at, str(lease.project_id), str(lease.job_id), lease.generation, worker.worker_id),
    )
    return LeaseView(
        project_id=lease.project_id,
        job_id=lease.job_id,
        generation=lease.generation,
        expires_at=expires_at,
        lease_seconds=_LEASE_SECONDS,
        heartbeat_seconds=_HEARTBEAT_SECONDS,
        poll_seconds=_POLL_SECONDS,
    )


def acknowledge_runner(
    connection: sqlite3.Connection,
    worker: WorkerScope,
    lease: LeaseToken,
    runner_nonce: UUID,
    now: datetime,
) -> AttemptReceipt:
    """Confirm the claim attempt. The same nonce does not create another attempt."""

    _require_open_lease(connection, worker, lease, now)
    attempt = connection.execute(
        """
        SELECT attempt_id FROM attempts
        WHERE project_id = ? AND job_id = ? AND generation = ?
        """,
        (str(lease.project_id), str(lease.job_id), lease.generation),
    ).fetchone()
    if attempt is None:
        raise StaleGeneration("lease generation is stale")
    attempt_id = str(attempt[0])
    existing = connection.execute(
        """
        SELECT runner_nonce FROM attempt_runners
        WHERE project_id = ? AND attempt_id = ?
        """,
        (str(lease.project_id), attempt_id),
    ).fetchone()
    if existing is None:
        connection.execute(
            """
            INSERT INTO attempt_runners (project_id, attempt_id, runner_nonce, acked_at)
            VALUES (?, ?, ?, ?)
            """,
            (str(lease.project_id), attempt_id, str(runner_nonce), now.astimezone(timezone.utc).isoformat()),
        )
        replayed = False
    elif str(existing[0]) != str(runner_nonce):
        raise RunnerConflict("runner nonce does not match")
    else:
        replayed = True
    return AttemptReceipt(attempt_id=UUID(attempt_id), runner_nonce=runner_nonce, replayed=replayed)


def _require_open_lease(
    connection: sqlite3.Connection, worker: WorkerScope, lease: LeaseToken, now: datetime
) -> None:
    if lease.project_id not in worker.permitted_projects:
        raise LeaseDenied("worker cannot use this lease")
    if type(lease.generation) is not int or lease.generation < 1:
        raise StaleGeneration("lease generation is stale")
    row = connection.execute(
        """
        SELECT expires_at, worker_id FROM leases
        WHERE project_id = ? AND job_id = ? AND generation = ?
        """,
        (str(lease.project_id), str(lease.job_id), lease.generation),
    ).fetchone()
    if row is None:
        raise StaleGeneration("lease generation is stale")
    if str(row[1]) != worker.worker_id:
        raise LeaseDenied("worker cannot use this lease")
    expires = datetime.fromisoformat(str(row[0]))
    if expires.tzinfo is None or now.astimezone(timezone.utc) >= expires.astimezone(timezone.utc):
        raise StaleGeneration("lease generation is stale")


def reconcile_stored(connection: sqlite3.Connection, now: datetime, boot_id: str) -> ReconciliationReport:
    """Keep queued jobs. Continue only a live generation. Do not resume the rest."""

    moment = now.astimezone(timezone.utc)
    queued = [str(row[0]) for row in connection.execute("SELECT job_id FROM jobs WHERE status = 'queued'")]
    marks = ", ".join("?" for _ in _ACTIVE)
    active = connection.execute(
        f"SELECT project_id, job_id FROM jobs WHERE status IN ({marks})",
        _ACTIVE,
    ).fetchall()
    for project_id, job_id in active:
        reason, physical, generation = _runner_state(connection, str(project_id), str(job_id), moment, boot_id)
        if reason == "live":
            _remember(connection, str(project_id), str(job_id), generation, "continued", "live", moment)
            continue
        connection.execute(
            """
            UPDATE jobs SET status = 'lost'
            WHERE project_id = ? AND job_id = ? AND status IN ({})
            """.format(marks),
            (str(project_id), str(job_id), *_ACTIVE),
        )
        if physical is not None:
            connection.execute(
                """
                INSERT OR IGNORE INTO resource_quarantine (physical_key_id, reason, quarantined_at)
                VALUES (?, ?, ?)
                """,
                (physical, _quarantine_reason(reason), moment.isoformat()),
            )
        if generation >= 1:
            _remember(connection, str(project_id), str(job_id), generation, "lost", reason, moment)
    preserved = True
    for job_id in queued:
        row = connection.execute("SELECT status FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row is None or str(row[0]) != "queued":
            preserved = False
    unhealthy = 0
    for project_id, job_id in connection.execute(
        f"SELECT project_id, job_id FROM jobs WHERE status IN ({marks})",
        _ACTIVE,
    ):
        reason, _physical, _generation = _runner_state(connection, str(project_id), str(job_id), moment, boot_id)
        if reason != "live":
            unhealthy += 1
    quarantine = connection.execute("SELECT COUNT(*) FROM resource_quarantine").fetchone()
    expired_resource = "quarantined" if quarantine is not None and int(quarantine[0]) > 0 else "open"
    return ReconciliationReport(
        queued_preserved=preserved,
        dead_runner_resumed=unhealthy > 0,
        expired_resource=expired_resource,
    )


def _runner_state(
    connection: sqlite3.Connection, project_id: str, job_id: str, now: datetime, boot_id: str
) -> tuple[str, str | None, int]:
    lease = connection.execute(
        """
        SELECT generation, physical_key_id, expires_at
        FROM leases
        WHERE project_id = ? AND job_id = ?
        ORDER BY generation DESC
        LIMIT 1
        """,
        (project_id, job_id),
    ).fetchone()
    if lease is None:
        return ("dead_runner", None, 0)
    generation = int(lease[0])
    physical = None if lease[1] is None else str(lease[1])
    expires = datetime.fromisoformat(str(lease[2]))
    expired = expires.tzinfo is None or now >= expires.astimezone(timezone.utc)
    attempt = connection.execute(
        """
        SELECT attempt_id FROM attempts
        WHERE project_id = ? AND job_id = ? AND generation = ?
        """,
        (project_id, job_id, generation),
    ).fetchone()
    acked_at = None
    host = None
    if attempt is not None:
        runner = connection.execute(
            "SELECT acked_at FROM attempt_runners WHERE project_id = ? AND attempt_id = ?",
            (project_id, str(attempt[0])),
        ).fetchone()
        host_row = connection.execute(
            "SELECT boot_id FROM runner_hosts WHERE project_id = ? AND attempt_id = ?",
            (project_id, str(attempt[0])),
        ).fetchone()
        acked_at = None if runner is None else str(runner[0])
        host = None if host_row is None else str(host_row[0])
    watchdog = True
    if acked_at is not None:
        acked = datetime.fromisoformat(acked_at)
        watchdog = acked.tzinfo is None or now >= acked.astimezone(timezone.utc) + timedelta(seconds=_WATCHDOG_SECONDS)
    if attempt is not None and acked_at is not None and host == boot_id and not expired and not watchdog:
        return ("live", physical, generation)
    if host is not None and host != boot_id:
        return ("restarted", physical, generation)
    if expired:
        return ("expired", physical, generation)
    if acked_at is not None and watchdog:
        return ("watchdog", physical, generation)
    return ("dead_runner", physical, generation)


def _quarantine_reason(reason: str) -> str:
    if reason == "restarted":
        return "restarted"
    if reason == "expired":
        return "expired"
    return "dead_runner"


def _remember(
    connection: sqlite3.Connection,
    project_id: str,
    job_id: str,
    generation: int,
    outcome: str,
    reason: str,
    now: datetime,
) -> None:
    connection.execute(
        """
        INSERT OR IGNORE INTO job_reconciliations (
            project_id, job_id, generation, outcome, reason, reconciled_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (project_id, job_id, generation, outcome, reason, now.isoformat()),
    )


_CANCEL_OPERATION = "cancel_job"
_JOB_STATES = frozenset(
    {
        "queued",
        "preparing",
        "running",
        "finalizing",
        "completed",
        "cancel_requested",
        "cancelled",
        "error",
        "lost",
    }
)
_CANCEL_FROM = {"queued": "cancelled", "preparing": "cancel_requested", "running": "cancel_requested"}


def cancel_job(
    tx: Transaction,
    actor: Actor,
    job_id: UUID,
    expected_state: str,
    key: IdempotencyKey,
) -> JobSnapshot:
    """Record a cancel before changing status. Replay returns the stored receipt."""

    if (
        actor.project_scope is None
        or key.project_id != actor.project_scope
        or key.actor_id != actor.actor_id
        or key.operation != _CANCEL_OPERATION
        or key.key.strip() == ""
        or type(expected_state) is not str
        or expected_state not in _JOB_STATES
    ):
        raise ValueError("cancel request is invalid")
    body_hash = canonical_hash(
        {"expected_state": expected_state, "job_id": str(job_id)},
        "canon-json-v1",
    )
    connection = tx.connection
    project_id = str(actor.project_scope)
    existing = connection.execute(
        """
        SELECT body_hash, job_id, status_after, runner_stopped, cleanup_completed
        FROM job_cancellations
        WHERE project_id = ? AND actor_id = ? AND request_key = ?
        """,
        (project_id, str(actor.actor_id), key.key),
    ).fetchone()
    if existing is not None:
        if str(existing[0]) != body_hash or str(existing[1]) != str(job_id):
            raise JobConflict("idempotency body does not match")
        return _cancel_snapshot(actor.project_scope, job_id, existing, True)
    job = connection.execute(
        "SELECT status FROM jobs WHERE project_id = ? AND job_id = ?",
        (project_id, str(job_id)),
    ).fetchone()
    if job is None:
        raise JobNotFound("job was not found")
    status = str(job[0])
    if status != expected_state or expected_state not in _CANCEL_FROM:
        raise CancelRejected("job can no longer be cancelled")
    taken = connection.execute(
        "SELECT 1 FROM job_cancellations WHERE project_id = ? AND job_id = ?",
        (project_id, str(job_id)),
    ).fetchone()
    if taken is not None:
        raise CancelRejected("job can no longer be cancelled")
    status_after = _CANCEL_FROM[expected_state]
    try:
        connection.execute(
            """
            INSERT INTO job_cancellations (
                project_id, actor_id, request_key, job_id, expected_state, body_hash,
                status_after, requested_at, runner_stopped, cleanup_completed
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0)
            """,
            (
                project_id,
                str(actor.actor_id),
                key.key,
                str(job_id),
                expected_state,
                body_hash,
                status_after,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise CancelRejected("job can no longer be cancelled") from exc
    updated = connection.execute(
        """
        UPDATE jobs SET status = ?
        WHERE project_id = ? AND job_id = ? AND status = ?
        """,
        (status_after, project_id, str(job_id), expected_state),
    )
    if updated.rowcount != 1:
        raise CancelRejected("job can no longer be cancelled")
    return JobSnapshot(
        project_id=actor.project_scope,
        job_id=job_id,
        status=status_after,
        cancel_requested=True,
        runner_stopped=False,
        cleanup_completed=False,
        replayed=False,
    )


_FINISH_STATUS = {"lost": "lost", "cancelled": "cancelled", "crash": "error"}


def finalize_job_control(connection: sqlite3.Connection, finish: object) -> JobSnapshot:
    """Store one terminal fact. Cleanup state does not change the QA verdict."""

    from aiqa.domain.verdicts import JobFinishInput
    from aiqa.worker.runner import control_finish

    if not isinstance(finish, JobFinishInput) or finish.finish_reason not in _FINISH_STATUS:
        raise ValueError("finish input is invalid")
    row = connection.execute(
        "SELECT purpose, status, recording_id, case_run_id FROM jobs WHERE project_id = ? AND job_id = ?",
        (str(finish.project_id), str(finish.job_id)),
    ).fetchone()
    if row is None:
        raise JobNotFound("job was not found")
    purpose = str(row[0])
    verdict, resource_state = control_finish(purpose, finish)
    status = _FINISH_STATUS[finish.finish_reason]
    if str(row[1]) in {"queued", "preparing", "running", "cancel_requested"}:
        connection.execute(
            """
            UPDATE jobs SET status = ?
            WHERE project_id = ? AND job_id = ? AND status = ?
            """,
            (status, str(finish.project_id), str(finish.job_id), str(row[1])),
        )
    existing = connection.execute(
        "SELECT verdict, resource_state FROM job_finish_facts WHERE project_id = ? AND job_id = ?",
        (str(finish.project_id), str(finish.job_id)),
    ).fetchone()
    if existing is None:
        connection.execute(
            """
            INSERT INTO job_finish_facts (
                project_id, job_id, verdict, finish_reason, cleanup_failed, resource_state, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(finish.project_id),
                str(finish.job_id),
                verdict,
                finish.finish_reason,
                1 if finish.cleanup_failed else 0,
                resource_state,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
    else:
        verdict = None if existing[0] is None else str(existing[0])
        resource_state = str(existing[1])
    stored = connection.execute(
        "SELECT status FROM jobs WHERE project_id = ? AND job_id = ?",
        (str(finish.project_id), str(finish.job_id)),
    ).fetchone()
    return JobSnapshot(
        project_id=finish.project_id,
        job_id=finish.job_id,
        status="" if stored is None else str(stored[0]),
        cancel_requested=finish.finish_reason == "cancelled",
        runner_stopped=True,
        cleanup_completed=not finish.cleanup_failed,
        replayed=existing is not None,
        verdict=verdict,
    )


def finish_job(connection: sqlite3.Connection, project_id: UUID, job_id: UUID) -> str:
    """Finish a live job. A stored cancel or an existing terminal status stays as it is."""

    connection.execute(
        """
        UPDATE jobs SET status = 'completed'
        WHERE project_id = ? AND job_id = ? AND status IN ('preparing', 'running')
          AND NOT EXISTS (
              SELECT 1 FROM job_cancellations
              WHERE job_cancellations.project_id = jobs.project_id
                AND job_cancellations.job_id = jobs.job_id
          )
        """,
        (str(project_id), str(job_id)),
    )
    row = connection.execute(
        "SELECT status FROM jobs WHERE project_id = ? AND job_id = ?",
        (str(project_id), str(job_id)),
    ).fetchone()
    if row is None:
        raise JobNotFound("job was not found")
    return str(row[0])


def _cancel_snapshot(project_id: UUID, job_id: UUID, row: object, replayed: bool) -> JobSnapshot:
    assert isinstance(row, tuple)
    return JobSnapshot(
        project_id=project_id,
        job_id=job_id,
        status=str(row[2]),
        cancel_requested=True,
        runner_stopped=int(row[3]) == 1,
        cleanup_completed=int(row[4]) == 1,
        replayed=replayed,
    )
