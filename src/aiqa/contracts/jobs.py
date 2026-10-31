"""RUN, ITEM, job, and attempt types. Importing this module does not open a database."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from aiqa.store.models import AttemptSnapshot, CaseRunSnapshot, ExecutionSnapshot, JobSpec

RUN_PURPOSES = frozenset({"trial", "regression", "reverification"})
JOB_PURPOSES = frozenset(
    {
        "recording",
        "trial",
        "regression",
        "structure",
        "app_inspect",
        "app_install",
        "resource_probe",
        "model_check",
        "export",
        "evidence_sync",
        "package_rebuild",
        "backup",
    }
)
MANAGEMENT_JOB_PURPOSES = frozenset(
    {
        "structure",
        "app_inspect",
        "app_install",
        "resource_probe",
        "model_check",
        "export",
        "evidence_sync",
        "package_rebuild",
        "backup",
    }
)

__all__ = [
    "JOB_PURPOSES",
    "MANAGEMENT_JOB_PURPOSES",
    "RUN_PURPOSES",
    "AttemptSnapshot",
    "CaseRunSnapshot",
    "ExecutionSnapshot",
    "AttemptReceipt",
    "IdempotencyKey",
    "JobLease",
    "JobReceipt",
    "JobSnapshot",
    "LeaseToken",
    "LeaseView",
    "JobSpec",
    "JobSubmission",
    "ControlDecision",
    "ReconciliationReport",
    "require_job_purpose",
]


@dataclass(frozen=True, slots=True)
class JobSubmission:
    project_id: UUID
    purpose: str
    case_id: UUID | None
    case_version_id: UUID | None
    source_refs: tuple[str, ...]
    limits: str


@dataclass(frozen=True, slots=True)
class IdempotencyKey:
    actor_id: UUID
    project_id: UUID
    operation: str
    key: str


@dataclass(frozen=True, slots=True)
class LeaseToken:
    project_id: UUID
    job_id: UUID
    generation: int


@dataclass(frozen=True, slots=True)
class LeaseView:
    project_id: UUID
    job_id: UUID
    generation: int
    expires_at: str
    lease_seconds: int
    heartbeat_seconds: int
    poll_seconds: int


@dataclass(frozen=True, slots=True)
class AttemptReceipt:
    attempt_id: UUID
    runner_nonce: UUID
    replayed: bool


@dataclass(frozen=True, slots=True)
class JobLease:
    project_id: UUID
    job_id: UUID
    generation: int
    worker_id: str
    physical_key_id: UUID | None
    expires_at: str
    attempt_id: UUID


@dataclass(frozen=True, slots=True)
class JobReceipt:
    job_id: UUID
    purpose: str
    status: str
    recording_id: UUID | None
    execution_id: UUID | None
    case_run_id: UUID | None
    status_href: str
    replayed: bool
    body_hash: str


@dataclass(frozen=True, slots=True)
class JobSnapshot:
    project_id: UUID
    job_id: UUID
    status: str
    cancel_requested: bool
    runner_stopped: bool
    cleanup_completed: bool
    replayed: bool


@dataclass(frozen=True, slots=True)
class ControlDecision:
    allowed: bool
    reason: str


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    queued_preserved: bool
    dead_runner_resumed: bool
    expired_resource: str


def require_job_purpose(purpose: str) -> str:
    """reverification is a RUN purpose. Its worker job purpose is regression."""

    if purpose not in JOB_PURPOSES:
        raise ValueError("job purpose is invalid")
    return purpose
