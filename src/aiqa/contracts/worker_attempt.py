"""Claim receipts and immutable job snapshots for remote workers."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class RecordingIntent:
    """Frozen case verification goal bound to one recording. Secret values stay out."""

    case_version_id: str
    content_hash: str
    objective: str
    preconditions: tuple[str, ...]
    steps: tuple[dict[str, object], ...]
    final_expected: tuple[dict[str, object], ...]
    variables: dict[str, object]
    secret_refs: dict[str, dict[str, object]]
    path_policy: dict[str, object]
    intent_hash: str


@dataclass(frozen=True, slots=True)
class JobSpecSnapshot:
    job_id: UUID
    attempt_id: UUID
    purpose: str
    target_ref: str | None
    revision_ref: str | None
    policy_ref: str | None
    digest: str
    intent_hash: str | None = None
    replay_package_id: str | None = None
    replay_package_hash: str | None = None
    self_healing_enabled: bool | None = None
    approved_plan: str | None = None


@dataclass(frozen=True, slots=True)
class ClaimReceipt:
    project_id: UUID
    job_id: UUID
    generation: int
    worker_id: str
    physical_key_id: UUID | None
    expires_at: str
    attempt_id: UUID
    session_id: str | None
    boot_id: str | None
    snapshot: JobSpecSnapshot
    replayed: bool


@dataclass(frozen=True, slots=True)
class WorkerAttemptFinishInput:
    """Trusted worker seal. Review and approve stay on the browser path."""

    project_id: UUID
    job_id: UUID
    attempt_id: UUID
    generation: int
    outcome: str
    final_seq: int
    last_ack_seq: int
    last_ack_hash: str
    manifest_digest: str
    evidence_complete: bool
    ambiguous_dispatch: bool
    physical_key_id: UUID | None = None
    source_artifact_hashes: tuple[str, ...] = ()
    action_mapping: str = "{}"
    cleanup_failed: bool = False
    required_violation: bool = False


@dataclass(frozen=True, slots=True)
class WorkerAttemptFinishReceipt:
    project_id: UUID
    job_id: UUID
    attempt_id: UUID
    status: str
    outcome: str
    replayed: bool
    approved: bool
    verdict: str | None
    purpose: str
