"""Durable job submission. One transaction owns the owner row, the job, and the receipt."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
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
from aiqa.contracts.worker_attempt import (
    ClaimReceipt,
    JobSpecSnapshot,
    WorkerAttemptFinishInput,
    WorkerAttemptFinishReceipt,
)
from aiqa.domain.hashing import canonical_hash, canonical_json
from aiqa.domain.resource_readiness import resource_readiness
from aiqa.store.models import Actor, Transaction, WorkerIncarnation, WorkerScope
from aiqa.worker.presence import get_presence, incarnation_of

_OPERATION = "enqueue_job"


class JobConflict(Exception):
    """The same idempotency key arrived with a different body."""


class ClaimConflict(Exception):
    """The same claim idempotency key arrived with a different body or scope."""


class JobNotFound(Exception):
    """The job is not in this project."""


class ResourceOffline(ValueError):
    """A new physical job cannot be accepted for this execution PC."""


class CancelRejected(Exception):
    """A new cancel cannot change this job."""


class FinishRejected(Exception):
    """The worker finish cannot succeed under the current evidence or fence."""


class FinishConflict(Exception):
    """The same finish key arrived with a different body."""


def enqueue_job(
    tx: Transaction, submission: JobSubmission, key: IdempotencyKey, *, now: datetime | None = None,
) -> JobReceipt:
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
    if purpose in _PHYSICAL:
        now = now or datetime.now(timezone.utc)
        pinned_resource = _snapshot_resource(purpose, json.loads(limits))
        for ref in refs if pinned_resource is None else [pinned_resource]:
            owner = connection.execute(
                """SELECT resource.worker_id FROM resource_aliases AS alias
                   JOIN physical_resource_keys AS resource USING (physical_key_id)
                   WHERE alias.project_id = ? AND alias.physical_key_id = ?""",
                (str(submission.project_id), ref),
            ).fetchone()
            if (owner is None and pinned_resource is not None) or (
                owner and get_presence(connection, owner[0], now, project_id=submission.project_id).state != "online"
            ):
                raise ResourceOffline("execution PC is offline or unavailable")
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
    from aiqa.recording.intent import freeze_intent_for_version, persist_recording_intent

    _require_version(connection, submission)
    if submission.case_id is None or submission.case_version_id is None:
        raise ValueError("recording requires a case version")
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
    intent = freeze_intent_for_version(
        connection,  # type: ignore[arg-type]
        project_id=submission.project_id,
        case_id=submission.case_id,
        case_version_id=submission.case_version_id,
    )
    persist_recording_intent(
        connection,  # type: ignore[arg-type]
        project_id=submission.project_id,
        recording_id=recording_id,
        intent=intent,
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
_MAX_ACTIVE_SLOTS = 1


def configure_active_slots(limit: int) -> None:
    """Set the server-wide concurrent active job slot budget. Default remains 1."""

    global _MAX_ACTIVE_SLOTS
    if type(limit) is not int or limit < 1:
        raise ValueError("active slot limit must be an integer >= 1")
    _MAX_ACTIVE_SLOTS = limit


def active_slot_limit() -> int:
    """Current concurrent active-job slot budget used by claim."""

    return _MAX_ACTIVE_SLOTS


def claim_queued_job(
    connection: sqlite3.Connection, worker: WorkerScope, now: datetime, *, boot_id: object = None
) -> JobLease | None:
    """Claim one queued job. Slot, device, and the previous item are checked together."""

    projects = tuple(str(project_id) for project_id in worker.permitted_projects)
    purposes = tuple(purpose for purpose in worker.permitted_purposes if purpose.strip() != "")
    if projects == () or purposes == () or _active_slots(connection) >= _MAX_ACTIVE_SLOTS:
        return None
    if worker.token_id is not None and connection.execute(
        "SELECT 1 FROM worker_tokens WHERE token_id = ?", (worker.token_id,)
    ).fetchone() is None:
        return None
    project_marks = ", ".join("?" for _ in projects)
    purpose_marks = ", ".join("?" for _ in purposes)
    rows = connection.execute(
        f"""
        SELECT project_id, job_id, purpose, case_run_id, source_refs, limits
        FROM jobs
        WHERE status = 'queued' AND project_id IN ({project_marks}) AND purpose IN ({purpose_marks})
        ORDER BY rowid
        """,
        (*projects, *purposes),
    ).fetchall()
    for project_id, job_id, purpose, case_run_id, source_refs, limits in rows:
        if _cleanup_pending(connection, str(project_id), None if case_run_id is None else str(case_run_id)):
            continue
        if _previous_item_blocks(connection, str(project_id), None if case_run_id is None else str(case_run_id)):
            continue
        if _approval_blocks_claim(connection, str(project_id), str(job_id)):
            continue
        if _snapshot_blocks_claim(connection, str(project_id), str(job_id), str(purpose), source_refs):
            continue
        if str(purpose) in _PHYSICAL:
            _ensure_claimant_session(
                connection, worker.worker_id, str(project_id), str(job_id), now
            )
        usable, physical_key_id = _device(
            connection, worker.worker_id, str(project_id), str(job_id), str(purpose),
            str(source_refs), str(limits), now, boot_id,
        )
        if not usable or _active_slots(connection) >= _MAX_ACTIVE_SLOTS:
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
        _pin_attempt_incarnation(
            connection, str(project_id), str(attempt_id), worker.worker_id, now
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


def _pin_attempt_incarnation(
    connection: sqlite3.Connection,
    project_id: str,
    attempt_id: str,
    worker_id: str,
    now: datetime,
) -> None:
    presence = get_presence(connection, worker_id, now, project_id=project_id)
    incarnation = incarnation_of(worker_id, presence)
    if incarnation is None:
        return
    connection.execute(
        """
        INSERT INTO attempt_incarnations (
            project_id, attempt_id, worker_id, session_id, boot_id
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (project_id, attempt_id, incarnation.worker_id, incarnation.session_id, incarnation.boot_id),
    )


def load_attempt_incarnation(
    connection: sqlite3.Connection, project_id: UUID | str, attempt_id: UUID | str
) -> WorkerIncarnation | None:
    row = connection.execute(
        """
        SELECT worker_id, session_id, boot_id
        FROM attempt_incarnations
        WHERE project_id = ? AND attempt_id = ?
        """,
        (str(project_id), str(attempt_id)),
    ).fetchone()
    if row is None:
        return None
    return WorkerIncarnation(str(row[0]), str(row[1]), str(row[2]))


def claim_with_receipt(
    connection: sqlite3.Connection,
    worker: WorkerScope,
    now: datetime,
    *,
    request_key: str,
    boot_id: object = None,
    project_id: object = None,
) -> ClaimReceipt | None:
    """Claim one job or replay the receipt for the same worker key."""

    if type(request_key) is not str or request_key.strip() == "":
        raise ValueError("claim idempotency key is required")
    if len(worker.permitted_projects) != 1:
        raise ClaimConflict("worker scope cannot claim")
    scoped = worker.permitted_projects[0]
    if project_id is not None and str(project_id) != str(scoped):
        raise ClaimConflict("worker scope cannot claim")
    body_hash = canonical_hash({"boot_id": "" if boot_id is None else str(boot_id)}, "canon-json-v1")
    existing = connection.execute(
        """
        SELECT body_hash, job_id, attempt_id, generation, physical_key_id, expires_at,
               session_id, boot_id, purpose, target_ref, revision_ref, policy_ref, digest
        FROM claim_receipts
        WHERE project_id = ? AND worker_id = ? AND request_key = ?
        """,
        (str(scoped), worker.worker_id, request_key),
    ).fetchone()
    if existing is not None:
        if str(existing[0]) != body_hash:
            raise ClaimConflict("idempotency body does not match")
        physical = None if existing[4] is None else UUID(str(existing[4]))
        purpose = str(existing[8])
        intent_hash = _intent_hash_for_job(connection, scoped, UUID(str(existing[1])), purpose)
        pin = _package_pin_for_job(connection, scoped, UUID(str(existing[1])), purpose)
        snapshot = JobSpecSnapshot(
            job_id=UUID(str(existing[1])),
            attempt_id=UUID(str(existing[2])),
            purpose=purpose,
            target_ref=None if existing[9] is None else str(existing[9]),
            revision_ref=None if existing[10] is None else str(existing[10]),
            policy_ref=None if existing[11] is None else str(existing[11]),
            digest=str(existing[12]),
            intent_hash=intent_hash,
            replay_package_id=None if pin is None else pin.package_id,
            replay_package_hash=None if pin is None else pin.package_hash,
            self_healing_enabled=None if pin is None else pin.self_healing_enabled,
            approved_plan=None if pin is None else pin.approved_plan,
        )
        return ClaimReceipt(
            project_id=scoped,
            job_id=UUID(str(existing[1])),
            generation=int(existing[3]),
            worker_id=worker.worker_id,
            physical_key_id=physical,
            expires_at=str(existing[5]),
            attempt_id=UUID(str(existing[2])),
            session_id=None if existing[6] is None else str(existing[6]),
            boot_id=None if existing[7] is None else str(existing[7]),
            snapshot=snapshot,
            replayed=True,
        )
    lease = claim_queued_job(connection, worker, now, boot_id=boot_id)
    if lease is None:
        return None
    job = connection.execute(
        """
        SELECT purpose, source_refs, limits, case_run_id, recording_id
        FROM jobs WHERE project_id = ? AND job_id = ?
        """,
        (str(lease.project_id), str(lease.job_id)),
    ).fetchone()
    if job is None:
        raise ClaimConflict("claimed job is missing")
    purpose = str(job[0])
    target_ref = _canonical_target_ref(connection, lease.project_id, lease.physical_key_id, str(job[1]))
    revision_ref = _revision_ref(str(job[1]), None if job[3] is None else str(job[3]), None if job[4] is None else str(job[4]))
    policy_ref = _policy_ref(str(job[2]))
    intent_hash = None
    if purpose == "recording" and job[4] is not None:
        intent_hash = _recording_intent_hash(connection, lease.project_id, str(job[4]))
    pin = _package_pin_for_job(connection, lease.project_id, lease.job_id, purpose, limits=str(job[2]))
    digest_body: dict[str, object] = {
        "job_id": str(lease.job_id),
        "attempt_id": str(lease.attempt_id),
        "purpose": purpose,
        "target_ref": target_ref,
        "revision_ref": revision_ref,
        "policy_ref": policy_ref,
    }
    if intent_hash is not None:
        digest_body["intent_hash"] = intent_hash
    if pin is not None:
        digest_body["replay_package_id"] = pin.package_id
        digest_body["replay_package_hash"] = pin.package_hash
        digest_body["self_healing_enabled"] = pin.self_healing_enabled
    snapshot = JobSpecSnapshot(
        job_id=lease.job_id,
        attempt_id=lease.attempt_id,
        purpose=purpose,
        target_ref=target_ref,
        revision_ref=revision_ref,
        policy_ref=policy_ref,
        digest=canonical_hash(digest_body, "canon-json-v1"),
        intent_hash=intent_hash,
        replay_package_id=None if pin is None else pin.package_id,
        replay_package_hash=None if pin is None else pin.package_hash,
        self_healing_enabled=None if pin is None else pin.self_healing_enabled,
        approved_plan=None if pin is None else pin.approved_plan,
    )
    incarnation = load_attempt_incarnation(connection, lease.project_id, lease.attempt_id)
    connection.execute(
        """
        INSERT INTO claim_receipts (
            project_id, worker_id, request_key, body_hash, job_id, attempt_id, generation,
            physical_key_id, expires_at, session_id, boot_id, purpose, target_ref,
            revision_ref, policy_ref, digest, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(lease.project_id),
            worker.worker_id,
            request_key,
            body_hash,
            str(lease.job_id),
            str(lease.attempt_id),
            lease.generation,
            None if lease.physical_key_id is None else str(lease.physical_key_id),
            lease.expires_at,
            None if incarnation is None else incarnation.session_id,
            None if incarnation is None else incarnation.boot_id,
            snapshot.purpose,
            snapshot.target_ref,
            snapshot.revision_ref,
            snapshot.policy_ref,
            snapshot.digest,
            now.astimezone(timezone.utc).isoformat(),
        ),
    )
    return ClaimReceipt(
        project_id=lease.project_id,
        job_id=lease.job_id,
        generation=lease.generation,
        worker_id=lease.worker_id,
        physical_key_id=lease.physical_key_id,
        expires_at=lease.expires_at,
        attempt_id=lease.attempt_id,
        session_id=None if incarnation is None else incarnation.session_id,
        boot_id=None if incarnation is None else incarnation.boot_id,
        snapshot=snapshot,
        replayed=False,
    )


def load_claim_receipt_for_attempt(
    connection: sqlite3.Connection, project_id: UUID | str, attempt_id: UUID | str
) -> ClaimReceipt | None:
    row = connection.execute(
        """
        SELECT project_id, job_id, generation, worker_id, physical_key_id, expires_at, attempt_id,
               session_id, boot_id, purpose, target_ref, revision_ref, policy_ref, digest
        FROM claim_receipts
        WHERE project_id = ? AND attempt_id = ?
        """,
        (str(project_id), str(attempt_id)),
    ).fetchone()
    if row is None:
        return None
    purpose = str(row[9])
    intent_hash = _intent_hash_for_job(connection, UUID(str(row[0])), UUID(str(row[1])), purpose)
    pin = _package_pin_for_job(connection, UUID(str(row[0])), UUID(str(row[1])), purpose)
    snapshot = JobSpecSnapshot(
        job_id=UUID(str(row[1])),
        attempt_id=UUID(str(row[6])),
        purpose=purpose,
        target_ref=None if row[10] is None else str(row[10]),
        revision_ref=None if row[11] is None else str(row[11]),
        policy_ref=None if row[12] is None else str(row[12]),
        digest=str(row[13]),
        intent_hash=intent_hash,
        replay_package_id=None if pin is None else pin.package_id,
        replay_package_hash=None if pin is None else pin.package_hash,
        self_healing_enabled=None if pin is None else pin.self_healing_enabled,
        approved_plan=None if pin is None else pin.approved_plan,
    )
    return ClaimReceipt(
        project_id=UUID(str(row[0])),
        job_id=UUID(str(row[1])),
        generation=int(row[2]),
        worker_id=str(row[3]),
        physical_key_id=None if row[4] is None else UUID(str(row[4])),
        expires_at=str(row[5]),
        attempt_id=UUID(str(row[6])),
        session_id=None if row[7] is None else str(row[7]),
        boot_id=None if row[8] is None else str(row[8]),
        snapshot=snapshot,
        replayed=False,
    )


def _package_pin_for_job(
    connection: sqlite3.Connection,
    project_id: UUID,
    job_id: UUID,
    purpose: str,
    *,
    limits: str | None = None,
):
    """Load the server-fixed package pin for trial/regression claims."""

    if purpose not in {"trial", "regression"}:
        return None
    raw = limits
    if raw is None:
        row = connection.execute(
            "SELECT limits FROM jobs WHERE project_id = ? AND job_id = ?",
            (str(project_id), str(job_id)),
        ).fetchone()
        if row is None:
            return None
        raw = str(row[0])
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if type(parsed) is not dict:
        return None
    from aiqa.replay.packages import resolve_claim_package_pin

    return resolve_claim_package_pin(
        connection,
        project_id,
        package_id=parsed.get("replay_package_id"),
        package_hash=parsed.get("replay_package_hash"),
        purpose=purpose,
        self_healing_enabled=parsed.get("self_healing_enabled"),
    )


def _recording_intent_hash(
    connection: sqlite3.Connection, project_id: UUID | str, recording_id: str
) -> str | None:
    row = connection.execute(
        """
        SELECT intent_hash FROM recording_intents
        WHERE project_id = ? AND recording_id = ?
        """,
        (str(project_id), recording_id),
    ).fetchone()
    return None if row is None else str(row[0])


def _intent_hash_for_job(
    connection: sqlite3.Connection, project_id: UUID, job_id: UUID, purpose: str
) -> str | None:
    if purpose != "recording":
        return None
    row = connection.execute(
        "SELECT recording_id FROM jobs WHERE project_id = ? AND job_id = ?",
        (str(project_id), str(job_id)),
    ).fetchone()
    if row is None or row[0] is None:
        return None
    return _recording_intent_hash(connection, project_id, str(row[0]))


def _canonical_target_ref(
    connection: sqlite3.Connection,
    project_id: UUID,
    physical_key_id: UUID | None,
    source_refs: str,
) -> str | None:
    if physical_key_id is not None:
        return str(physical_key_id)
    try:
        refs = json.loads(source_refs)
    except json.JSONDecodeError:
        return None
    if type(refs) is not list or refs == []:
        return None
    first = refs[0]
    if type(first) is not str:
        return None
    alias = connection.execute(
        """
        SELECT physical_key_id FROM resource_aliases
        WHERE project_id = ? AND physical_key_id = ?
        """,
        (str(project_id), first),
    ).fetchone()
    return str(alias[0]) if alias is not None else first


def _revision_ref(source_refs: str, case_run_id: str | None, recording_id: str | None) -> str | None:
    if case_run_id is not None:
        return f"case_run:{case_run_id}"
    if recording_id is not None:
        return f"recording:{recording_id}"
    try:
        refs = json.loads(source_refs)
    except json.JSONDecodeError:
        return None
    if type(refs) is list and refs and type(refs[0]) is str:
        return str(refs[0])
    return None


def _policy_ref(limits: str) -> str | None:
    try:
        parsed = json.loads(limits)
    except json.JSONDecodeError:
        return None
    if type(parsed) is not dict:
        return None
    policy = parsed.get("policy_ref")
    return str(policy) if type(policy) is str else None


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


def _snapshot_resource(purpose: str, limits: object) -> str | None:
    if purpose in {"trial", "regression"} and isinstance(limits, dict):
        resource = limits.get("resource_id")
        if isinstance(resource, str):
            return resource
    return None


def _ensure_claimant_session(
    connection: sqlite3.Connection,
    worker_id: str,
    project_id: str,
    job_id: str,
    now: datetime,
) -> None:
    """Attach the claiming worker's live presence to the job so multi-worker claim can race."""

    presence = get_presence(connection, worker_id, now, project_id=project_id)
    if presence.state != "online" or presence.session_id is None:
        return
    connection.execute(
        """
        INSERT INTO job_worker_sessions (project_id, job_id, worker_id, session_id)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(project_id, job_id, worker_id) DO UPDATE SET
            session_id = excluded.session_id
        """,
        (project_id, job_id, worker_id, presence.session_id),
    )


def physical_scope_is_leased(connection: sqlite3.Connection, physical_key_id: str) -> bool:
    """True when this physical key or another key with the same native_id already has a lease.

    Lease rows remain until cleanup confirmation, so expired generations still block reassignment.
    """

    direct = connection.execute(
        "SELECT COUNT(*) FROM leases WHERE physical_key_id = ?",
        (physical_key_id,),
    ).fetchone()
    if direct is not None and int(direct[0]) > 0:
        return True
    native = connection.execute(
        "SELECT native_id FROM physical_resource_keys WHERE physical_key_id = ?",
        (physical_key_id,),
    ).fetchone()
    if native is None:
        return False
    shared = connection.execute(
        """
        SELECT COUNT(*) FROM leases AS lease
        JOIN physical_resource_keys AS keys ON keys.physical_key_id = lease.physical_key_id
        WHERE keys.native_id = ?
        """,
        (str(native[0]),),
    ).fetchone()
    return shared is not None and int(shared[0]) > 0


def _device(
    connection: sqlite3.Connection, worker_id: str, project_id: str, job_id: str,
    purpose: str, source_refs: str, limits: str, now: datetime, boot_id: object,
) -> tuple[bool, str | None]:
    if purpose not in _PHYSICAL:
        return True, None
    presence = get_presence(connection, worker_id, now, project_id=project_id)
    if presence.state != "online" or (boot_id is not None and boot_id != presence.boot_id):
        return False, None
    if connection.execute(
        """SELECT 1 FROM job_worker_sessions
           WHERE project_id = ? AND job_id = ? AND worker_id = ? AND session_id = ?""",
        (project_id, job_id, worker_id, presence.session_id),
    ).fetchone() is None:
        return False, None
    try:
        pinned_resource = _snapshot_resource(purpose, json.loads(limits))
        refs = json.loads(source_refs) if pinned_resource is None else [pinned_resource]
    except json.JSONDecodeError:
        return False, None
    if type(refs) is not list:
        return False, None
    for ref in refs:
        if type(ref) is not str:
            continue
        # Project alias binds the common physical key. Claiming worker need not own the key row;
        # presence/session still fence the claiming worker.
        alias = connection.execute(
            """
            SELECT alias.target_kind, alias.alias_id FROM resource_aliases AS alias
            JOIN physical_resource_keys AS resource USING (physical_key_id)
            WHERE alias.project_id = ? AND alias.physical_key_id = ?
            """,
            (project_id, ref),
        ).fetchone()
        if alias is None:
            continue
        if purpose != "resource_probe" and not resource_readiness(
            connection, UUID(project_id), ref, alias[0], now=now,
        ).ready:
            continue
        if physical_scope_is_leased(connection, ref):
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
    *,
    server_now: datetime | None = None,
) -> LeaseView:
    """Extend one generation. Model wait keeps the same heartbeat."""

    if type(model_wait) is not bool:
        raise ValueError("model wait is invalid")
    now = _require_open_lease(connection, worker, lease, now, server_now)
    expires_at = (now.astimezone(timezone.utc) + timedelta(seconds=_LEASE_SECONDS)).isoformat()
    connection.execute(
        """
        UPDATE leases SET expires_at = ?
        WHERE project_id = ? AND job_id = ? AND generation = ? AND worker_id = ?
        """,
        (expires_at, str(lease.project_id), str(lease.job_id), lease.generation, worker.worker_id),
    )
    connection.execute(
        """
        UPDATE claim_receipts SET expires_at = ?
        WHERE project_id = ? AND job_id = ? AND worker_id = ?
          AND attempt_id = (
              SELECT attempt_id FROM attempts
              WHERE project_id = ? AND job_id = ? AND generation = ?
          )
        """,
        (
            expires_at,
            str(lease.project_id),
            str(lease.job_id),
            worker.worker_id,
            str(lease.project_id),
            str(lease.job_id),
            lease.generation,
        ),
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
    *,
    server_now: datetime | None = None,
) -> AttemptReceipt:
    """Confirm the claim attempt. The same nonce does not create another attempt."""

    now = _require_open_lease(connection, worker, lease, now, server_now)
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
    incarnation = load_attempt_incarnation(connection, lease.project_id, attempt_id)
    receipt = load_claim_receipt_for_attempt(connection, lease.project_id, attempt_id)
    if incarnation is not None and receipt is None:
        raise StaleGeneration("claim receipt is missing")
    if receipt is not None:
        expires = datetime.fromisoformat(receipt.expires_at)
        if expires.tzinfo is None or now.astimezone(timezone.utc) >= expires.astimezone(timezone.utc):
            raise StaleGeneration("claim receipt is expired")
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
    connection: sqlite3.Connection, worker: WorkerScope, lease: LeaseToken,
    now: datetime, server_now: datetime | None,
) -> datetime:
    if lease.project_id not in worker.permitted_projects:
        raise LeaseDenied("worker cannot use this lease")
    if type(lease.generation) is not int or lease.generation < 1:
        raise StaleGeneration("lease generation is stale")
    row = connection.execute(
        """
        SELECT lease.expires_at, lease.worker_id, session.session_id FROM leases AS lease
        LEFT JOIN job_worker_sessions AS session
          ON session.project_id = lease.project_id AND session.job_id = lease.job_id
         AND session.worker_id = lease.worker_id
        WHERE lease.project_id = ? AND lease.job_id = ? AND lease.generation = ?
        """,
        (str(lease.project_id), str(lease.job_id), lease.generation),
    ).fetchone()
    if row is None:
        raise StaleGeneration("lease generation is stale")
    if str(row[1]) != worker.worker_id:
        raise LeaseDenied("worker cannot use this lease")
    if row[2] is not None:
        now = server_now or now
        presence = get_presence(connection, worker.worker_id, now, project_id=lease.project_id)
        if presence.state != "online" or presence.session_id != row[2]:
            raise StaleGeneration("worker session is stale")
    now = server_now or now
    _require_matching_incarnation(connection, worker, lease, now)
    expires = datetime.fromisoformat(str(row[0]))
    if expires.tzinfo is None or now.astimezone(timezone.utc) >= expires.astimezone(timezone.utc):
        raise StaleGeneration("lease generation is stale")
    return now


def _require_matching_incarnation(
    connection: sqlite3.Connection, worker: WorkerScope, lease: LeaseToken, now: datetime
) -> None:
    attempt = connection.execute(
        """
        SELECT attempt_id FROM attempts
        WHERE project_id = ? AND job_id = ? AND generation = ?
        """,
        (str(lease.project_id), str(lease.job_id), lease.generation),
    ).fetchone()
    if attempt is None:
        return
    stored = load_attempt_incarnation(connection, lease.project_id, attempt[0])
    if stored is None:
        return
    current = incarnation_of(
        worker.worker_id,
        get_presence(connection, worker.worker_id, now, project_id=lease.project_id),
    )
    if current != stored:
        raise StaleGeneration("worker incarnation is stale")


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
        SELECT generation, physical_key_id, expires_at, worker_id
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
    incarnation = None
    if attempt is not None:
        runner = connection.execute(
            "SELECT acked_at FROM attempt_runners WHERE project_id = ? AND attempt_id = ?",
            (project_id, str(attempt[0])),
        ).fetchone()
        host_row = connection.execute(
            "SELECT boot_id FROM runner_hosts WHERE project_id = ? AND attempt_id = ?",
            (project_id, str(attempt[0])),
        ).fetchone()
        incarnation = load_attempt_incarnation(connection, project_id, attempt[0])
        acked_at = None if runner is None else str(runner[0])
        host = None if host_row is None else str(host_row[0])
    watchdog = True
    if acked_at is not None:
        acked = datetime.fromisoformat(acked_at)
        watchdog = acked.tzinfo is None or now >= acked.astimezone(timezone.utc) + timedelta(seconds=_WATCHDOG_SECONDS)
    if incarnation is not None:
        current = incarnation_of(
            incarnation.worker_id,
            get_presence(connection, incarnation.worker_id, now, project_id=project_id),
        )
        matched = current == incarnation
        if attempt is not None and acked_at is not None and matched and not expired and not watchdog:
            return ("live", physical, generation)
        if current is not None and not matched:
            return ("restarted", physical, generation)
        if expired:
            return ("expired", physical, generation)
        if acked_at is not None and watchdog:
            return ("watchdog", physical, generation)
        return ("dead_runner", physical, generation)
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


_SUCCESS_OUTCOMES = frozenset({"completed"})
_FINISH_OUTCOMES = frozenset({"completed", "error", "interrupted", "lost", "cancelled", "crash"})
_OUTCOME_TO_REASON = {
    "completed": None,
    "error": "crash",
    "interrupted": "cancelled",
    "lost": "lost",
    "cancelled": "cancelled",
    "crash": "crash",
}


def finish_worker_attempt(
    connection: sqlite3.Connection,
    worker: WorkerScope,
    finish: WorkerAttemptFinishInput,
    *,
    request_key: str,
    body_hash: str,
    now: datetime,
) -> WorkerAttemptFinishReceipt:
    """Seal one attempt. Worker finish never creates an approval."""

    if type(request_key) is not str or request_key.strip() == "":
        raise ValueError("idempotency key is required")
    if finish.outcome not in _FINISH_OUTCOMES:
        raise ValueError("finish outcome is invalid")
    if finish.project_id not in worker.permitted_projects:
        raise LeaseDenied("worker cannot use this lease")
    if type(finish.final_seq) is not int or finish.final_seq < 0:
        raise ValueError("final seq is invalid")
    if type(finish.last_ack_seq) is not int or finish.last_ack_seq < 0:
        raise ValueError("last ack seq is invalid")
    if type(finish.last_ack_hash) is not str or finish.last_ack_hash.strip() == "":
        raise ValueError("last ack hash is invalid")
    if type(finish.manifest_digest) is not str or finish.manifest_digest.strip() == "":
        raise ValueError("manifest digest is invalid")

    key = request_key.strip()
    identity = (str(finish.project_id), str(finish.attempt_id), key)
    existing = connection.execute(
        """
        SELECT body_hash, response_body, worker_id FROM attempt_finish_requests
        WHERE project_id = ? AND attempt_id = ? AND request_key = ?
        """,
        identity,
    ).fetchone()
    if existing is not None:
        if str(existing[2]) != worker.worker_id:
            raise LeaseDenied("worker cannot use this lease")
        if str(existing[0]) != body_hash:
            raise FinishConflict("finish body does not match")
        saved = json.loads(str(existing[1]))
        return WorkerAttemptFinishReceipt(
            UUID(str(saved["project_id"])),
            UUID(str(saved["job_id"])),
            UUID(str(saved["attempt_id"])),
            str(saved["status"]),
            str(saved["outcome"]),
            True,
            False,
            None if saved.get("verdict") is None else str(saved["verdict"]),
            str(saved["purpose"]),
        )

    job = connection.execute(
        """
        SELECT purpose, status, recording_id, case_run_id
        FROM jobs
        WHERE project_id = ? AND job_id = ?
        """,
        (str(finish.project_id), str(finish.job_id)),
    ).fetchone()
    if job is None:
        raise JobNotFound("job was not found")
    purpose = str(job[0])
    recording_id = None if job[2] is None else UUID(str(job[2]))

    attempt = connection.execute(
        """
        SELECT generation, physical_key_id FROM attempts
        WHERE project_id = ? AND attempt_id = ? AND job_id = ?
        """,
        (str(finish.project_id), str(finish.attempt_id), str(finish.job_id)),
    ).fetchone()
    if attempt is None:
        raise StaleGeneration("lease generation is stale")
    if int(attempt[0]) != finish.generation:
        raise StaleGeneration("lease generation is stale")
    attempt_physical = None if attempt[1] is None else UUID(str(attempt[1]))
    if finish.physical_key_id is not None and attempt_physical is not None:
        if finish.physical_key_id != attempt_physical:
            raise FinishRejected("physical fence does not match")

    lease = connection.execute(
        """
        SELECT worker_id, physical_key_id, generation, expires_at
        FROM leases
        WHERE project_id = ? AND job_id = ? AND generation = ?
        """,
        (str(finish.project_id), str(finish.job_id), finish.generation),
    ).fetchone()
    if lease is None:
        raise LeaseDenied("worker cannot use this lease")
    if str(lease[0]) != worker.worker_id:
        raise LeaseDenied("worker cannot use this lease")
    leased_physical = None if lease[1] is None else UUID(str(lease[1]))
    if finish.physical_key_id is not None and leased_physical != finish.physical_key_id:
        raise FinishRejected("physical fence does not match")

    claim = connection.execute(
        """
        SELECT digest FROM claim_receipts
        WHERE project_id = ? AND attempt_id = ? AND worker_id = ?
        """,
        (str(finish.project_id), str(finish.attempt_id), worker.worker_id),
    ).fetchone()
    if claim is not None and str(claim[0]) != finish.manifest_digest:
        raise FinishRejected("manifest digest does not match")

    from aiqa.store.evidence import _cursor

    committed_seq, committed_hash = _cursor(connection, finish.project_id, str(finish.attempt_id))
    if finish.last_ack_seq != committed_seq or finish.last_ack_hash != committed_hash:
        raise FinishRejected("last ACK does not match committed prefix")
    if finish.final_seq > finish.last_ack_seq:
        raise FinishRejected("final seq exceeds last ACK")

    if finish.outcome in _SUCCESS_OUTCOMES:
        # Success requires current generation, valid lease vs server now, and start ACK.
        expires_at = datetime.fromisoformat(str(lease[3]))
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= now.astimezone(timezone.utc):
            raise FinishRejected("lease expired")
        runner = connection.execute(
            """
            SELECT acked_at FROM attempt_runners
            WHERE project_id = ? AND attempt_id = ?
            """,
            (str(finish.project_id), str(finish.attempt_id)),
        ).fetchone()
        if runner is None or runner[0] is None:
            raise FinishRejected("start ACK is missing")
        if str(job[1]) in {"cancel_requested", "cancelled"}:
            raise FinishRejected("job was cancelled")
        incarnation = load_attempt_incarnation(connection, finish.project_id, finish.attempt_id)
        presence = get_presence(connection, worker.worker_id, now, project_id=finish.project_id)
        if (
            incarnation is not None
            and incarnation.boot_id is not None
            and presence.boot_id is not None
            and str(incarnation.boot_id) != str(presence.boot_id)
        ):
            raise FinishRejected("boot id does not match")
        if finish.ambiguous_dispatch:
            raise FinishRejected("ambiguous dispatch cannot succeed")
        if not finish.evidence_complete:
            raise FinishRejected("evidence is incomplete")
        if finish.final_seq > 0 and finish.last_ack_seq < 1:
            raise FinishRejected("evidence is missing")

    other = connection.execute(
        """
        SELECT worker_id FROM attempt_finish_requests
        WHERE project_id = ? AND attempt_id = ? AND worker_id != ?
        LIMIT 1
        """,
        (str(finish.project_id), str(finish.attempt_id), worker.worker_id),
    ).fetchone()
    if other is not None:
        raise LeaseDenied("worker cannot use this lease")

    verdict: str | None = None
    if finish.outcome in _SUCCESS_OUTCOMES:
        status = finish_job(connection, finish.project_id, finish.job_id)
        if purpose == "recording" and recording_id is not None:
            from aiqa.recording.manifests import RecordingFinishInput
            from aiqa.recording.service import finish_recording

            artifact_refs = finish.source_artifact_hashes
            if artifact_refs == ():
                raise FinishRejected("required artifact is missing")
            actor = Actor(uuid4(), finish.project_id, True)
            finish_recording(
                connection,
                actor,
                finish.project_id,
                RecordingFinishInput(
                    recording_id,
                    "completed",
                    finish.final_seq,
                    artifact_refs,
                    key,
                    finish.action_mapping,
                ),
            )
        elif purpose in {"trial", "regression"} and finish.required_violation:
            from aiqa.domain.verdicts import JobFinishInput

            snapshot = finalize_job_control(
                connection,
                JobFinishInput(
                    finish.project_id,
                    finish.job_id,
                    "crash",
                    True,
                    True,
                    finish.cleanup_failed,
                ),
            )
            verdict = snapshot.verdict
            status = snapshot.status
    else:
        reason = _OUTCOME_TO_REASON[finish.outcome]
        assert reason is not None
        from aiqa.domain.verdicts import JobFinishInput

        snapshot = finalize_job_control(
            connection,
            JobFinishInput(
                finish.project_id,
                finish.job_id,
                reason,
                finish.required_violation,
                True,
                finish.cleanup_failed,
            ),
        )
        status = snapshot.status
        verdict = snapshot.verdict

    receipt = WorkerAttemptFinishReceipt(
        finish.project_id,
        finish.job_id,
        finish.attempt_id,
        status,
        finish.outcome,
        False,
        False,
        verdict,
        purpose,
    )
    body = {
        "project_id": str(receipt.project_id),
        "job_id": str(receipt.job_id),
        "attempt_id": str(receipt.attempt_id),
        "status": receipt.status,
        "outcome": receipt.outcome,
        "replayed": False,
        "approved": False,
        "verdict": receipt.verdict,
        "purpose": receipt.purpose,
    }
    connection.execute(
        """
        INSERT INTO attempt_finish_requests (
            project_id, attempt_id, worker_id, request_key, body_hash, response_body, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(finish.project_id),
            str(finish.attempt_id),
            worker.worker_id,
            key,
            body_hash,
            json.dumps(body, sort_keys=True),
            now.astimezone(timezone.utc).isoformat(),
        ),
    )
    return receipt


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


@dataclass(frozen=True, slots=True)
class CleanupConfirmationInput:
    project_id: UUID
    job_id: UUID
    attempt_id: UUID
    generation: int
    physical_key_id: UUID | None
    proof_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CleanupConfirmationReceipt:
    project_id: UUID
    attempt_id: UUID
    released: bool
    quarantined: bool
    replayed: bool


def confirm_cleanup(
    connection: sqlite3.Connection,
    worker: WorkerScope,
    confirmation: CleanupConfirmationInput,
    now: datetime,
) -> CleanupConfirmationReceipt:
    """Release the lease only when attempt, generation, worker, and resource fence match."""

    moment = now.astimezone(timezone.utc)
    if confirmation.project_id not in worker.permitted_projects:
        raise LeaseDenied("worker cannot use this lease")
    if type(confirmation.generation) is not int or confirmation.generation < 1:
        raise StaleGeneration("lease generation is stale")
    existing = connection.execute(
        """
        SELECT released, quarantined FROM cleanup_confirmations
        WHERE project_id = ? AND attempt_id = ?
        """,
        (str(confirmation.project_id), str(confirmation.attempt_id)),
    ).fetchone()
    if existing is not None:
        return CleanupConfirmationReceipt(
            confirmation.project_id,
            confirmation.attempt_id,
            bool(int(existing[0])),
            bool(int(existing[1])),
            True,
        )
    lease = connection.execute(
        """
        SELECT worker_id, physical_key_id, generation FROM leases
        WHERE project_id = ? AND job_id = ?
        ORDER BY generation DESC
        LIMIT 1
        """,
        (str(confirmation.project_id), str(confirmation.job_id)),
    ).fetchone()
    if lease is None:
        raise StaleGeneration("lease generation is stale")
    if str(lease[0]) != worker.worker_id:
        raise LeaseDenied("worker cannot use this lease")
    if int(lease[2]) != confirmation.generation:
        raise StaleGeneration("lease generation is stale")
    attempt = connection.execute(
        """
        SELECT attempt_id, physical_key_id FROM attempts
        WHERE project_id = ? AND job_id = ? AND generation = ?
        """,
        (str(confirmation.project_id), str(confirmation.job_id), confirmation.generation),
    ).fetchone()
    if attempt is None or str(attempt[0]) != str(confirmation.attempt_id):
        raise StaleGeneration("lease generation is stale")
    lease_physical = None if lease[1] is None else str(lease[1])
    attempt_physical = None if attempt[1] is None else str(attempt[1])
    confirmed_physical = None if confirmation.physical_key_id is None else str(confirmation.physical_key_id)
    if lease_physical != attempt_physical or lease_physical != confirmed_physical:
        raise StaleGeneration("resource fence does not match")
    incarnation = load_attempt_incarnation(connection, confirmation.project_id, confirmation.attempt_id)
    if incarnation is not None:
        current = incarnation_of(
            worker.worker_id,
            get_presence(connection, worker.worker_id, moment, project_id=confirmation.project_id),
        )
        if current != incarnation:
            raise StaleGeneration("worker incarnation is stale")
    proofs = tuple(ref for ref in confirmation.proof_refs if type(ref) is str and ref.strip() != "")
    quarantined = lease_physical is not None and proofs == ()
    released = not quarantined
    if quarantined and lease_physical is not None:
        connection.execute(
            """
            INSERT OR IGNORE INTO resource_quarantine (physical_key_id, reason, quarantined_at)
            VALUES (?, 'dead_runner', ?)
            """,
            (lease_physical, moment.isoformat()),
        )
    connection.execute(
        """
        DELETE FROM leases
        WHERE project_id = ? AND job_id = ? AND generation = ? AND worker_id = ?
        """,
        (
            str(confirmation.project_id),
            str(confirmation.job_id),
            confirmation.generation,
            worker.worker_id,
        ),
    )
    connection.execute(
        """
        INSERT INTO cleanup_confirmations (
            project_id, attempt_id, job_id, generation, worker_id, physical_key_id,
            released, quarantined, proof_refs, confirmed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(confirmation.project_id),
            str(confirmation.attempt_id),
            str(confirmation.job_id),
            confirmation.generation,
            worker.worker_id,
            lease_physical,
            1 if released else 0,
            1 if quarantined else 0,
            json.dumps(list(proofs)),
            moment.isoformat(),
        ),
    )
    return CleanupConfirmationReceipt(
        confirmation.project_id,
        confirmation.attempt_id,
        released,
        quarantined,
        False,
    )
