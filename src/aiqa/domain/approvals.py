"""Atomic case approval. A failed pointer or pin leaves no approval row."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from aiqa.contracts.jobs import IdempotencyKey
from aiqa.domain.projects import next_commit_seq
from aiqa.store.artifacts import ArtifactRejected, pin_approval
from aiqa.store.database import Store
from aiqa.store.models import Actor, Transaction
from aiqa.store.queue import CancelRejected, JobConflict, JobNotFound, cancel_job

_store: ContextVar[Store] = ContextVar("aiqa_approval_store")


class ApprovalRejected(Exception):
    """The snapshot cannot become the default approval."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ApprovalConflict(Exception):
    """The default pointer moved before this approval committed."""

    def __init__(self, reason: str, current_approval_id: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.current_approval_id = current_approval_id


@dataclass(frozen=True, slots=True)
class ApprovalInput:
    review_id: UUID
    case_version_id: UUID
    version_hash: str
    evidence_set_hash: str
    expected_current_approval_id: UUID | None
    reason: str


@dataclass(frozen=True, slots=True)
class RejectionInput:
    review_id: UUID
    case_version_id: UUID
    version_hash: str
    reason: str


@dataclass(frozen=True, slots=True)
class DecisionReceipt:
    decision_id: UUID
    review_id: UUID
    case_id: UUID
    case_version_id: UUID
    state: str
    reason: str
    actor_id: UUID
    created_at: str
    version_hash: str
    current_approval_id: UUID | None


@dataclass(frozen=True, slots=True)
class ApprovalReceipt:
    approval_id: UUID
    review_id: UUID
    case_id: UUID
    case_version_id: UUID
    previous_default_id: UUID | None
    audit_id: UUID
    protection_ids: tuple[UUID, ...]


@contextmanager
def bind_approval_store(store: Store) -> Iterator[None]:
    token = _store.set(store)
    try:
        yield
    finally:
        _store.reset(token)


def reject_case(actor: Actor, rejection: RejectionInput) -> DecisionReceipt:
    """Store one rejection. The current default and the existing decision stay."""

    if actor.project_scope is None:
        raise ApprovalRejected("project is missing")
    if rejection.reason.strip() == "":
        raise ApprovalRejected("rejection reason is missing")
    store = _store.get()
    with store.transaction() as connection:
        return _reject(connection, actor, rejection)


def case_decision(connection: object, project_id: UUID, case_id: UUID) -> dict[str, object] | None:
    """Describe the latest candidate and the default that a rejection must keep."""

    version = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT version_id, content_hash, source_manifest_id
        FROM case_versions
        WHERE project_id = ? AND case_id = ?
        ORDER BY revision DESC
        LIMIT 1
        """,
        (str(project_id), str(case_id)),
    ).fetchone()
    if version is None:
        return None
    pointer = connection.execute(  # type: ignore[attr-defined]
        "SELECT current_approval_id FROM automation_cases WHERE project_id = ? AND case_id = ?",
        (str(project_id), str(case_id)),
    ).fetchone()
    review = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT review_id, version_hash, evidence_set_hash
        FROM reviews
        WHERE project_id = ? AND case_version_id = ?
        ORDER BY created_commit_seq DESC
        LIMIT 1
        """,
        (str(project_id), str(version[0])),
    ).fetchone()
    decision = None
    if review is not None:
        decision = connection.execute(  # type: ignore[attr-defined]
            """
            SELECT state, reason, actor_id, created_at, version_hash
            FROM review_decisions
            WHERE project_id = ? AND review_id = ?
            """,
            (str(project_id), str(review[0])),
        ).fetchone()
    recording = None
    if version[2] is not None:
        recording = connection.execute(  # type: ignore[attr-defined]
            """
            SELECT recordings.storage_status, recordings.completion_status, recordings.stop_status
            FROM recording_manifests
            JOIN recordings
              ON recordings.project_id = recording_manifests.project_id
             AND recordings.recording_id = recording_manifests.recording_id
            WHERE recording_manifests.project_id = ? AND recording_manifests.manifest_id = ?
            """,
            (str(project_id), str(version[2])),
        ).fetchone()
    blocked = recording is None or tuple(str(item) for item in recording) != ("stored", "completed", "stopped")
    return {
        "version_id": str(version[0]),
        "version_hash": "" if review is None else str(review[1]),
        "evidence_set_hash": "" if review is None else str(review[2]),
        "review_id": "" if review is None else str(review[0]),
        "current_approval_id": "" if pointer is None or pointer[0] is None else str(pointer[0]),
        "blocked": blocked or review is None,
        "rejected_retained": decision is not None and str(decision[0]) == "rejected",
        "rejected_reason": "" if decision is None else str(decision[1]),
        "rejected_actor_id": "" if decision is None else str(decision[2]),
        "rejected_at": "" if decision is None else str(decision[3]),
        "rejected_hash": "" if decision is None else str(decision[4]),
    }


@dataclass(frozen=True, slots=True)
class RevokeInput:
    approval_id: UUID
    expected_current_approval_id: UUID | None
    reason: str


@dataclass(frozen=True, slots=True)
class RevokeReceipt:
    revoke_id: UUID
    approval_id: UUID
    case_id: UUID
    current_approval_id: UUID | None
    queued_blocked: int
    running_cancelled: int
    grace_until: str
    fallback: bool


def revoke_preview(connection: object, project_id: UUID, case_id: UUID) -> dict[str, object] | None:
    """Count the queued, running, and suite rows a current approval would affect."""

    pointer = connection.execute(  # type: ignore[attr-defined]
        "SELECT current_approval_id FROM automation_cases WHERE project_id = ? AND case_id = ?",
        (str(project_id), str(case_id)),
    ).fetchone()
    if pointer is None or pointer[0] is None:
        return None
    approval = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT case_version_id FROM approval_events
        WHERE project_id = ? AND approval_id = ? AND event_kind = 'approved'
        """,
        (str(project_id), str(pointer[0])),
    ).fetchone()
    if approval is None:
        return None
    version_id = str(approval[0])
    queued = _job_count(connection, project_id, version_id, ("queued",))
    running = _job_count(connection, project_id, version_id, ("preparing", "running"))
    suites = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT COUNT(DISTINCT executions.suite_version_id)
        FROM case_runs
        JOIN executions
          ON executions.project_id = case_runs.project_id
         AND executions.execution_id = case_runs.execution_id
        WHERE case_runs.project_id = ? AND case_runs.case_version_id = ?
          AND executions.suite_version_id IS NOT NULL
        """,
        (str(project_id), version_id),
    ).fetchone()
    return {
        "approval_id": str(pointer[0]),
        "queued": queued,
        "running": running,
        "suites": 0 if suites is None else int(suites[0]),
    }


def revoke_case(actor: Actor, revocation: RevokeInput) -> RevokeReceipt:
    """Append one revoke. The current default becomes empty and does not fall back."""

    if actor.project_scope is None:
        raise ApprovalRejected("project is missing")
    if revocation.reason.strip() == "":
        raise ApprovalRejected("revoke reason is missing")
    store = _store.get()
    with store.transaction() as connection:
        return _revoke(connection, actor, revocation)


def approve_case(actor: Actor, approval: ApprovalInput) -> ApprovalReceipt:
    """Commit the approved event, required pins, default pointer, and audit together."""

    if actor.project_scope is None:
        raise ApprovalRejected("project is missing")
    if approval.reason.strip() == "":
        raise ApprovalRejected("approval reason is missing")
    store = _store.get()
    with store.transaction() as connection:
        return _approve(connection, actor, approval)


def _approve(connection: object, actor: Actor, approval: ApprovalInput) -> ApprovalReceipt:
    project_id = actor.project_scope
    assert project_id is not None
    review = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT case_id, case_version_id, version_hash, source_manifest_id, trial_case_run_id, evidence_set_hash
        FROM reviews
        WHERE project_id = ? AND review_id = ?
        """,
        (str(project_id), str(approval.review_id)),
    ).fetchone()
    if review is None:
        raise ApprovalRejected("review is missing")
    case_id = UUID(str(review[0]))
    version_id = UUID(str(review[1]))
    if version_id != approval.case_version_id:
        raise ApprovalRejected("review version mismatch")
    if str(review[2]) != approval.version_hash or str(review[5]) != approval.evidence_set_hash:
        raise ApprovalRejected("review hash mismatch")
    version = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT content_hash, source_manifest_id, replay_package_id, definition_json, settings_json
        FROM case_versions
        WHERE project_id = ? AND case_id = ? AND version_id = ?
        """,
        (str(project_id), str(case_id), str(version_id)),
    ).fetchone()
    if version is None or str(version[0]) != approval.version_hash:
        raise ApprovalRejected("review hash mismatch")
    if str(version[1] or "") != str(review[3] or ""):
        raise ApprovalRejected("source manifest mismatch")
    pointer = connection.execute(  # type: ignore[attr-defined]
        "SELECT current_approval_id FROM automation_cases WHERE project_id = ? AND case_id = ?",
        (str(project_id), str(case_id)),
    ).fetchone()
    if pointer is None:
        raise ApprovalRejected("case is missing")
    current = None if pointer[0] is None else UUID(str(pointer[0]))
    if current != approval.expected_current_approval_id:
        raise ApprovalConflict("approval pointer moved", None if current is None else str(current))
    _require_recording(connection, project_id, review[3])
    package_id = version[2]
    if package_id is None:
        raise ApprovalRejected("package evidence is missing")
    _require_package(connection, project_id, package_id)
    _require_trial(connection, project_id, review[4], version_id, approval.version_hash, str(version[4]))
    source_ids, trial_ids = _require_reviewed_evidence(connection, project_id, approval.review_id)
    package_ids = _package_artifacts(connection, project_id, review[3])
    if package_ids == ():
        raise ApprovalRejected("package evidence is missing")
    _require_checks(connection, project_id, str(review[4]), str(version[3]))
    approval_id = uuid4()
    audit_id = uuid4()
    created_at = datetime.now(timezone.utc).isoformat()
    connection.execute(  # type: ignore[attr-defined]
        """
        INSERT INTO approval_events (
            project_id, approval_id, case_id, case_version_id, review_id, event_kind,
            prior_approval_id, version_hash, evidence_set_hash, reason
        ) VALUES (?, ?, ?, ?, ?, 'approved', NULL, ?, ?, ?)
        """,
        (
            str(project_id),
            str(approval_id),
            str(case_id),
            str(version_id),
            str(approval.review_id),
            approval.version_hash,
            approval.evidence_set_hash,
            approval.reason,
        ),
    )
    protection_ids: list[UUID] = []
    for artifact_id in source_ids + trial_ids + package_ids:
        protection_id = uuid4()
        try:
            pin_approval(connection, project_id, UUID(artifact_id), protection_id)
        except ArtifactRejected as exc:
            raise ApprovalRejected(exc.args[0] if exc.args else "artifact is not ready") from exc
        protection_ids.append(protection_id)
    if approval.expected_current_approval_id is None:
        updated = connection.execute(  # type: ignore[attr-defined]
            """
            UPDATE automation_cases
            SET current_approval_id = ?, lock_version = lock_version + 1
            WHERE project_id = ? AND case_id = ? AND current_approval_id IS NULL
            """,
            (str(approval_id), str(project_id), str(case_id)),
        )
    else:
        updated = connection.execute(  # type: ignore[attr-defined]
            """
            UPDATE automation_cases
            SET current_approval_id = ?, lock_version = lock_version + 1
            WHERE project_id = ? AND case_id = ? AND current_approval_id = ?
            """,
            (str(approval_id), str(project_id), str(case_id), str(approval.expected_current_approval_id)),
        )
    if updated.rowcount != 1:
        moved = connection.execute(  # type: ignore[attr-defined]
            "SELECT current_approval_id FROM automation_cases WHERE project_id = ? AND case_id = ?",
            (str(project_id), str(case_id)),
        ).fetchone()
        current_text = None if moved is None or moved[0] is None else str(moved[0])
        raise ApprovalConflict("approval pointer moved", current_text)
    commit_seq = next_commit_seq(Transaction(connection), project_id)  # type: ignore[arg-type]
    connection.execute(  # type: ignore[attr-defined]
        """
        INSERT INTO project_audits (
            project_id, audit_id, commit_seq, actor_id, action, created_at
        ) VALUES (?, ?, ?, ?, 'approve', ?)
        """,
        (str(project_id), str(audit_id), commit_seq, str(actor.actor_id), created_at),
    )
    connection.execute(  # type: ignore[attr-defined]
        """
        INSERT INTO project_audit_links (project_id, audit_id, note, commit_seq)
        VALUES (?, ?, ?, ?)
        """,
        (str(project_id), str(audit_id), str(approval_id), commit_seq),
    )
    return ApprovalReceipt(
        approval_id,
        approval.review_id,
        case_id,
        version_id,
        current,
        audit_id,
        tuple(protection_ids),
    )


def _job_count(connection: object, project_id: UUID, version_id: str, statuses: tuple[str, ...]) -> int:
    marks = ", ".join("?" for _ in statuses)
    row = connection.execute(  # type: ignore[attr-defined]
        f"""
        SELECT COUNT(*)
        FROM jobs
        JOIN case_runs
          ON case_runs.project_id = jobs.project_id
         AND case_runs.case_run_id = jobs.case_run_id
        WHERE jobs.project_id = ? AND case_runs.case_version_id = ? AND jobs.status IN ({marks})
        """,
        (str(project_id), version_id, *statuses),
    ).fetchone()
    return 0 if row is None else int(row[0])


def _revoke(connection: object, actor: Actor, revocation: RevokeInput) -> RevokeReceipt:
    project_id = actor.project_scope
    assert project_id is not None
    approved = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT case_id, case_version_id, review_id, version_hash, evidence_set_hash
        FROM approval_events
        WHERE project_id = ? AND approval_id = ? AND event_kind = 'approved'
        """,
        (str(project_id), str(revocation.approval_id)),
    ).fetchone()
    if approved is None:
        raise ApprovalRejected("approval is missing")
    case_id = UUID(str(approved[0]))
    version_id = str(approved[1])
    pointer = connection.execute(  # type: ignore[attr-defined]
        "SELECT current_approval_id FROM automation_cases WHERE project_id = ? AND case_id = ?",
        (str(project_id), str(case_id)),
    ).fetchone()
    if pointer is None:
        raise ApprovalRejected("case is missing")
    current = None if pointer[0] is None else UUID(str(pointer[0]))
    if current != revocation.expected_current_approval_id:
        raise ApprovalConflict("approval pointer moved", None if current is None else str(current))
    existing = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT 1 FROM approval_events
        WHERE project_id = ? AND prior_approval_id = ? AND event_kind = 'revoked'
        """,
        (str(project_id), str(revocation.approval_id)),
    ).fetchone()
    if existing is not None:
        raise ApprovalConflict("approval is already revoked", None if current is None else str(current))
    revoke_id = uuid4()
    now = datetime.now(timezone.utc)
    connection.execute(  # type: ignore[attr-defined]
        """
        INSERT INTO approval_events (
            project_id, approval_id, case_id, case_version_id, review_id, event_kind,
            prior_approval_id, version_hash, evidence_set_hash, reason
        ) VALUES (?, ?, ?, ?, ?, 'revoked', ?, ?, ?, ?)
        """,
        (
            str(project_id),
            str(revoke_id),
            str(case_id),
            version_id,
            str(approved[2]),
            str(revocation.approval_id),
            str(approved[3]),
            str(approved[4]),
            revocation.reason,
        ),
    )
    queued = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT jobs.job_id
        FROM jobs
        JOIN case_runs
          ON case_runs.project_id = jobs.project_id
         AND case_runs.case_run_id = jobs.case_run_id
        WHERE jobs.project_id = ? AND case_runs.case_version_id = ? AND jobs.status = 'queued'
        """,
        (str(project_id), version_id),
    ).fetchall()
    for row in queued:
        connection.execute(  # type: ignore[attr-defined]
            """
            INSERT INTO approval_queue_blocks (project_id, job_id, approval_id, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (str(project_id), str(row[0]), str(revocation.approval_id), now.isoformat()),
        )
    active = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT jobs.job_id, jobs.status
        FROM jobs
        JOIN case_runs
          ON case_runs.project_id = jobs.project_id
         AND case_runs.case_run_id = jobs.case_run_id
        WHERE jobs.project_id = ? AND case_runs.case_version_id = ? AND jobs.status IN ('preparing', 'running')
        """,
        (str(project_id), version_id),
    ).fetchall()
    for job_id, status in active:
        try:
            cancel_job(
                Transaction(connection),  # type: ignore[arg-type]
                actor,
                UUID(str(job_id)),
                str(status),
                IdempotencyKey(actor.actor_id, project_id, "cancel_job", f"revoke-{revocation.approval_id}-{job_id}"),
            )
        except (CancelRejected, JobConflict, JobNotFound) as exc:
            raise ApprovalRejected("running job cannot be cancelled") from exc
    grace_until = (now + timedelta(days=90)).isoformat()
    protections = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT artifact_protections.protection_id
        FROM artifact_protections
        JOIN review_evidence_entries
          ON review_evidence_entries.project_id = artifact_protections.project_id
         AND review_evidence_entries.artifact_ref_id = artifact_protections.artifact_id
        WHERE artifact_protections.project_id = ? AND artifact_protections.kind = 'approval'
          AND review_evidence_entries.review_id = ?
        """,
        (str(project_id), str(approved[2])),
    ).fetchall()
    for row in protections:
        connection.execute(  # type: ignore[attr-defined]
            """
            INSERT INTO approval_pin_releases (
                project_id, release_id, protection_id, approval_id, released_at, grace_until
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (str(project_id), str(uuid4()), str(row[0]), str(revocation.approval_id), now.isoformat(), grace_until),
        )
    if current == revocation.approval_id:
        updated = connection.execute(  # type: ignore[attr-defined]
            """
            UPDATE automation_cases
            SET current_approval_id = NULL, lock_version = lock_version + 1
            WHERE project_id = ? AND case_id = ? AND current_approval_id = ?
            """,
            (str(project_id), str(case_id), str(revocation.approval_id)),
        )
        if updated.rowcount != 1:
            raise ApprovalConflict("approval pointer moved", None if current is None else str(current))
        current = None
    commit_seq = next_commit_seq(Transaction(connection), project_id)  # type: ignore[arg-type]
    audit_id = uuid4()
    connection.execute(  # type: ignore[attr-defined]
        """
        INSERT INTO project_audits (
            project_id, audit_id, commit_seq, actor_id, action, created_at
        ) VALUES (?, ?, ?, ?, 'revoke', ?)
        """,
        (str(project_id), str(audit_id), commit_seq, str(actor.actor_id), now.isoformat()),
    )
    connection.execute(  # type: ignore[attr-defined]
        """
        INSERT INTO project_audit_links (project_id, audit_id, note, commit_seq)
        VALUES (?, ?, ?, ?)
        """,
        (str(project_id), str(audit_id), str(revocation.approval_id), commit_seq),
    )
    return RevokeReceipt(revoke_id, revocation.approval_id, case_id, current, len(queued), len(active), grace_until, False)


def _reject(connection: object, actor: Actor, rejection: RejectionInput) -> DecisionReceipt:
    project_id = actor.project_scope
    assert project_id is not None
    review = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT case_id, case_version_id, version_hash
        FROM reviews
        WHERE project_id = ? AND review_id = ?
        """,
        (str(project_id), str(rejection.review_id)),
    ).fetchone()
    if review is None:
        raise ApprovalRejected("review is missing")
    case_id = UUID(str(review[0]))
    version_id = UUID(str(review[1]))
    if version_id != rejection.case_version_id or str(review[2]) != rejection.version_hash:
        raise ApprovalRejected("review hash mismatch")
    pointer = connection.execute(  # type: ignore[attr-defined]
        "SELECT current_approval_id FROM automation_cases WHERE project_id = ? AND case_id = ?",
        (str(project_id), str(case_id)),
    ).fetchone()
    if pointer is None:
        raise ApprovalRejected("case is missing")
    current = None if pointer[0] is None else UUID(str(pointer[0]))
    decision_id = uuid4()
    created_at = datetime.now(timezone.utc).isoformat()
    try:
        connection.execute(  # type: ignore[attr-defined]
            """
            INSERT INTO review_decisions (
                project_id, review_id, decision_id, state, actor_id, created_at, reason, version_hash
            ) VALUES (?, ?, ?, 'rejected', ?, ?, ?, ?)
            """,
            (
                str(project_id),
                str(rejection.review_id),
                str(decision_id),
                str(actor.actor_id),
                created_at,
                rejection.reason,
                rejection.version_hash,
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise ApprovalConflict("rejection record is already stored", None if current is None else str(current)) from exc
    kept = connection.execute(  # type: ignore[attr-defined]
        "SELECT current_approval_id FROM automation_cases WHERE project_id = ? AND case_id = ?",
        (str(project_id), str(case_id)),
    ).fetchone()
    if kept is None or kept[0] != pointer[0]:
        raise ApprovalRejected("default changed during rejection")
    return DecisionReceipt(
        decision_id,
        rejection.review_id,
        case_id,
        version_id,
        "rejected",
        rejection.reason,
        actor.actor_id,
        created_at,
        rejection.version_hash,
        current,
    )


def _require_recording(connection: object, project_id: UUID, manifest_id: object) -> None:
    if manifest_id is None:
        raise ApprovalRejected("recording is in progress")
    row = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT recordings.storage_status, recordings.evidence_status, recordings.stop_status, recordings.completion_status
        FROM recording_manifests
        JOIN recordings
          ON recordings.project_id = recording_manifests.project_id
         AND recordings.recording_id = recording_manifests.recording_id
        WHERE recording_manifests.project_id = ? AND recording_manifests.manifest_id = ?
        """,
        (str(project_id), str(manifest_id)),
    ).fetchone()
    if row is None or tuple(str(item) for item in row) != ("stored", "complete", "stopped", "completed"):
        raise ApprovalRejected("recording is in progress")


def _require_package(connection: object, project_id: UUID, package_id: object) -> None:
    row = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT ready, lock_hash, step_mapping_hash
        FROM replay_packages
        WHERE project_id = ? AND package_id = ?
        """,
        (str(project_id), str(package_id)),
    ).fetchone()
    if row is None or int(row[0]) != 1 or str(row[1]) == "" or str(row[2]) == "":
        raise ApprovalRejected("package is not ready")


def _require_trial(
    connection: object,
    project_id: UUID,
    case_run_id: object,
    version_id: UUID,
    version_hash: str,
    settings_json: str,
) -> None:
    if _policy_enabled(settings_json):
        raise ApprovalRejected("policy is not off")
    if case_run_id is None:
        raise ApprovalRejected("trial is not off")
    row = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT case_runs.case_version_id, case_versions.content_hash, jobs.limits,
               case_versions.replay_package_id, packages.body_hash
        FROM case_runs
        JOIN case_versions
          ON case_versions.project_id = case_runs.project_id
         AND case_versions.version_id = case_runs.case_version_id
        JOIN jobs
          ON jobs.project_id = case_runs.project_id
         AND jobs.case_run_id = case_runs.case_run_id
         AND jobs.purpose = 'trial'
        LEFT JOIN replay_packages AS packages
          ON packages.project_id = case_versions.project_id
         AND packages.package_id = case_versions.replay_package_id
         AND packages.ready = 1
        WHERE case_runs.project_id = ? AND case_runs.case_run_id = ? AND case_runs.purpose = 'trial'
        """,
        (str(project_id), str(case_run_id)),
    ).fetchone()
    if row is None or str(row[0]) != str(version_id) or str(row[1]) != version_hash or not _limits_off(row[2]):
        raise ApprovalRejected("trial is not off")
    try:
        limits = json.loads(str(row[2]))
    except json.JSONDecodeError as exc:
        raise ApprovalRejected("trial is not off") from exc
    if type(limits) is not dict:
        raise ApprovalRejected("trial is not off")
    pinned_id = limits.get("replay_package_id")
    pinned_hash = limits.get("replay_package_hash")
    if pinned_id not in {None, ""} or pinned_hash not in {None, ""}:
        if row[3] in {None, ""} or row[4] in {None, ""}:
            raise ApprovalRejected("package is not ready")
        if str(pinned_id or "") != str(row[3]):
            raise ApprovalRejected("trial package mismatch")
        if str(pinned_hash or "") != str(row[4]):
            raise ApprovalRejected("trial package mismatch")


def _require_reviewed_evidence(connection: object, project_id: UUID, review_id: UUID) -> tuple[tuple[str, ...], tuple[str, ...]]:
    rows = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT entry_id, owner_kind, artifact_ref_id
        FROM review_evidence_entries
        WHERE project_id = ? AND review_id = ?
        """,
        (str(project_id), str(review_id)),
    ).fetchall()
    source: list[str] = []
    trial: list[str] = []
    if not rows:
        raise ApprovalRejected("action review is missing")
    for entry_id, owner_kind, artifact_id in rows:
        latest = connection.execute(  # type: ignore[attr-defined]
            """
            SELECT state FROM action_reviews
            WHERE project_id = ? AND entry_id = ?
            ORDER BY created_at DESC, rowid DESC
            LIMIT 1
            """,
            (str(project_id), str(entry_id)),
        ).fetchone()
        if latest is None or str(latest[0]) != "reviewed":
            raise ApprovalRejected("action review is missing")
        if str(owner_kind) == "REC":
            source.append(str(artifact_id))
        elif str(owner_kind) == "ITEM":
            trial.append(str(artifact_id))
    if source == [] or trial == []:
        raise ApprovalRejected("required evidence is missing")
    return tuple(source), tuple(trial)


def _package_artifacts(connection: object, project_id: UUID, manifest_id: object) -> tuple[str, ...]:
    if manifest_id is None:
        return ()
    rows = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT artifact_objects.artifact_id
        FROM recording_manifests
        JOIN artifact_objects
          ON artifact_objects.project_id = recording_manifests.project_id
         AND artifact_objects.owner_kind = 'REC'
         AND artifact_objects.owner_id = recording_manifests.recording_id
         AND artifact_objects.role = 'source'
         AND artifact_objects.status = 'ready'
        WHERE recording_manifests.project_id = ? AND recording_manifests.manifest_id = ?
        """,
        (str(project_id), str(manifest_id)),
    ).fetchall()
    return tuple(str(row[0]) for row in rows)


def _require_checks(connection: object, project_id: UUID, case_run_id: str, definition_json: str) -> None:
    try:
        body = json.loads(definition_json)
    except json.JSONDecodeError as exc:
        raise ApprovalRejected("checks are invalid") from exc
    checks = [] if type(body) is not dict else body.get("checks", [])
    if type(checks) is not list:
        raise ApprovalRejected("checks are invalid")
    attempt = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT attempts.attempt_id
        FROM jobs
        JOIN attempts ON attempts.project_id = jobs.project_id AND attempts.job_id = jobs.job_id
        WHERE jobs.project_id = ? AND jobs.case_run_id = ? AND jobs.purpose = 'trial'
        """,
        (str(project_id), case_run_id),
    ).fetchone()
    if checks and attempt is None:
        raise ApprovalRejected("check is missing")
    for item in checks:
        if type(item) is not dict or type(item.get("id")) is not str or str(item.get("id")) == "":
            raise ApprovalRejected("checks are invalid")
        found = connection.execute(  # type: ignore[attr-defined]
            """
            SELECT status FROM check_results
            WHERE project_id = ? AND attempt_id = ? AND check_id = ?
            """,
            (str(project_id), str(attempt[0]), str(item["id"])),
        ).fetchone()
        if found is None or str(found[0]) != "satisfied":
            raise ApprovalRejected("check is missing")


def _policy_enabled(settings_json: str) -> bool:
    try:
        body = json.loads(settings_json)
    except json.JSONDecodeError:
        return True
    return type(body) is dict and body.get("self_healing_enabled") is True


def _limits_off(raw: object) -> bool:
    try:
        limits = json.loads(str(raw))
    except json.JSONDecodeError:
        return False
    if type(limits) is not dict:
        return False
    return limits.get("self_healing_enabled") is False and limits.get("actor") == 0
