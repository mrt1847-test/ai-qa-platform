"""Project storage types. Importing this module does not open a database."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Actor:
    actor_id: UUID
    project_scope: UUID | None
    is_local_owner: bool


@dataclass(frozen=True, slots=True)
class ProjectCreate:
    name: str
    key: str
    description: str
    target: str


@dataclass(frozen=True, slots=True)
class ProjectView:
    project_id: UUID
    name: str
    key: str
    description: str
    target: str
    commit_seq: int
    audit_id: UUID
    archived_at: str | None = None
    case_count: int = 0
    review_count: int = 0
    run_count: int = 0


@dataclass(frozen=True, slots=True)
class Transaction:
    connection: sqlite3.Connection


@dataclass(frozen=True, slots=True)
class BrowserSession:
    session_id: UUID
    origin: str
    csrf_token: str
    actor: Actor
    expires_at: str


@dataclass(frozen=True, slots=True)
class WorkerScope:
    worker_id: str
    permitted_projects: tuple[UUID, ...]
    permitted_purposes: tuple[str, ...]
    token_id: str | None = None


@dataclass(frozen=True, slots=True)
class WorkerIncarnation:
    worker_id: str
    session_id: str
    boot_id: str


@dataclass(frozen=True, slots=True)
class JobRef:
    project_id: UUID
    purpose: str
    job_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class SecretInput:
    value: str
    name: str = ""
    ref_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class SecretRef:
    project_id: UUID
    ref_id: UUID
    revision: int


@dataclass(frozen=True, slots=True)
class SecretRefView:
    project_id: UUID
    ref_id: UUID
    revision: int
    name: str
    availability: str


@dataclass(frozen=True, slots=True)
class RuntimeScope:
    project_id: UUID
    actor_id: UUID


@dataclass(frozen=True, slots=True)
class SecretValue:
    value: str


@dataclass(frozen=True, slots=True)
class CaseMetadata:
    project_id: UUID
    case_id: UUID
    name: str
    tc_reference: str | None
    folder_id: UUID | None
    lock_version: int


@dataclass(frozen=True, slots=True)
class TcRevisionInput:
    project_id: UUID
    actor_id: UUID
    name: str
    body: dict[str, object]
    tc_id: UUID | None = None
    reason: str = ""


@dataclass(frozen=True, slots=True)
class TcVersionView:
    project_id: UUID
    tc_id: UUID
    id: UUID
    revision: int
    name: str
    content_hash: str
    archived_at: str | None


@dataclass(frozen=True, slots=True)
class DatasetRevisionInput:
    project_id: UUID
    actor_id: UUID
    name: str
    row_schema: dict[str, object]
    rows: tuple[dict[str, object], ...]
    dataset_id: UUID | None = None
    secret_ref: SecretRef | None = None
    case_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class DatasetVersionView:
    project_id: UUID
    dataset_id: UUID
    id: UUID
    revision: int
    content_hash: str
    secret_ref: SecretRef | None


@dataclass(frozen=True, slots=True)
class EnvironmentRevisionInput:
    project_id: UUID
    actor_id: UUID
    name: str
    target_kind: str
    allowlist: tuple[str, ...]
    viewport: dict[str, int]
    locale: str
    reset_policy: str
    limits: dict[str, object]
    environment_id: UUID | None = None
    profile: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class EnvironmentRevisionView:
    project_id: UUID
    environment_id: UUID
    id: UUID
    revision: int
    target_kind: str
    locale: str
    content_hash: str


@dataclass(frozen=True, slots=True)
class ModelBindingInput:
    project_id: UUID
    actor_id: UUID
    name: str
    role: str
    provider: str
    endpoint_kind: str
    endpoint: str
    model: str
    key_ref: SecretRef
    prompt_hash: str
    tariff_id: str
    compatibility_status: str
    binding_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class ModelBindingView:
    project_id: UUID
    binding_id: UUID
    id: UUID
    revision: int
    role: str
    model: str
    content_hash: str
    compatibility_status: str


@dataclass(frozen=True, slots=True)
class CaseMetadataView:
    project_id: UUID
    case_id: UUID
    name: str
    tc_reference: UUID | None
    current_approval_id: UUID | None
    latest_draft_version_id: UUID | None
    lock_version: int


@dataclass(frozen=True, slots=True)
class CaseListQuery:
    project_id: UUID
    text: str = ""
    folder_id: UUID | None = None
    tag: str | None = None
    priority: str | None = None
    assignee_id: UUID | None = None
    archived: bool = False
    view: str = ""
    sort: str = "name"
    limit: int = 25
    cursor: str | None = None


@dataclass(frozen=True, slots=True)
class CaseListRow:
    case_id: UUID
    name: str
    folder_id: UUID | None
    priority: str | None
    assignee_id: UUID | None
    current_approval_id: UUID | None
    archived_at: str | None
    lock_version: int
    tc_reference: UUID | None = None
    target_kind: str | None = None
    draft_revision: int | None = None
    approved_revision: int | None = None
    latest_result: str | None = None
    latest_run_at: str | None = None


@dataclass(frozen=True, slots=True)
class CursorPage:
    items: tuple[CaseListRow, ...]
    next_cursor: str | None
    snapshot_seq: int
    total: int = 0
    start: int = 0
    end: int = 0
    previous_cursor: str | None = None


@dataclass(frozen=True, slots=True)
class CloneCaseInput:
    project_id: UUID
    actor_id: UUID
    source_case_id: UUID
    name: str


@dataclass(frozen=True, slots=True)
class CaseView:
    project_id: UUID
    case_id: UUID
    name: str
    current_approval_id: UUID | None
    latest_draft_version_id: UUID | None
    archived_at: str | None
    lock_version: int


@dataclass(frozen=True, slots=True)
class RecordingSession:
    project_id: UUID
    case_id: UUID
    recording_id: UUID
    creation_kind: str
    input_case_version_id: UUID
    base_case_version_id: UUID | None
    parent_recording_id: UUID | None
    source_recording_id: UUID | None
    storage_status: str
    stop_status: str
    completion_status: str
    evidence_status: str


@dataclass(frozen=True, slots=True)
class RecordingManifest:
    project_id: UUID
    case_id: UUID
    recording_id: UUID
    manifest_id: UUID
    revision: int
    kind: str
    prior_manifest_id: UUID | None
    input_version_hash: str
    source_artifact_hashes: str
    action_mapping: str
    evidence_completeness: str
    request_key: str
    body_hash: str


@dataclass(frozen=True, slots=True)
class MaterializationReceipt:
    project_id: UUID
    receipt_id: UUID
    manifest_id: UUID
    produced_version_id: UUID
    body_hash: str


@dataclass(frozen=True, slots=True)
class PhysicalResourceKey:
    worker_id: UUID
    native_id: str


@dataclass(frozen=True, slots=True)
class ResourceAlias:
    project_id: UUID
    physical_key_id: UUID
    display_name: str
    target_kind: str


@dataclass(frozen=True, slots=True)
class ResourceObservation:
    project_id: UUID
    resource_id: UUID
    probe_job_id: UUID
    attempt_id: UUID
    captured_at: str
    geometry: str
    artifact_id: UUID
    scope_hash: str


@dataclass(frozen=True, slots=True)
class CaseProposalInput:
    case_id: UUID
    base_version_id: UUID
    base_hash: str
    kind: str
    body: dict[str, object]
    source_job_id: UUID | None
    tc_version_id: UUID | None


@dataclass(frozen=True, slots=True)
class CaseProposalView:
    proposal_id: UUID
    project_id: UUID
    case_id: UUID
    base_version_id: UUID
    base_hash: str
    kind: str
    body: str
    body_hash: str
    source_job_id: UUID | None
    tc_version_id: UUID | None


@dataclass(frozen=True, slots=True)
class ExecutionSnapshot:
    project_id: UUID
    execution_id: UUID
    name: str
    purpose: str
    source: str
    suite_version_id: UUID | None
    scope_requested_at: str


@dataclass(frozen=True, slots=True)
class CaseRunSnapshot:
    project_id: UUID
    execution_id: UUID
    case_run_id: UUID
    case_id: UUID
    case_version_id: UUID
    purpose: str
    requested_at: str


@dataclass(frozen=True, slots=True)
class JobSpec:
    project_id: UUID
    job_id: UUID
    purpose: str
    recording_id: UUID | None
    case_run_id: UUID | None
    payload_hash: str
    source_refs: str
    limits: str
    status: str


@dataclass(frozen=True, slots=True)
class AttemptSnapshot:
    project_id: UUID
    attempt_id: UUID
    job_id: UUID
    physical_key_id: UUID | None
    generation: int


@dataclass(frozen=True, slots=True)
class ActionEnvelope:
    project_id: UUID
    attempt_id: UUID
    action_seq: int
    step_id: str
    action_id: UUID
    package_step_id: UUID | None
    proposal_hash: str
    dispatch_state: str
    case_id: UUID
    case_version_id: UUID
    outcome_known: bool


@dataclass(frozen=True, slots=True)
class CheckResult:
    project_id: UUID
    attempt_id: UUID
    action_id: UUID
    check_id: str
    status: str
    method: str
    expected_snapshot: str
    sanitized_observed: str
    reason: str
    artifact_refs: str
    observed_at: str


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    project_id: UUID
    event_id: UUID
    attempt_id: UUID
    local_seq: int
    captured_at: str
    event_type: str
    minimum_facts: str
    payload_hash: str
    body_hash: str
    detail_payload: str | None


@dataclass(frozen=True, slots=True)
class ModelCallFact:
    project_id: UUID
    call_id: UUID
    attempt_id: UUID
    role: str
    action_id: UUID | None
    check_id: str | None
    measurement_status: str
    input_tokens: int | None
    output_tokens: int | None
    cache_tokens: int | None
    image_tokens: int | None


@dataclass(frozen=True, slots=True)
class ReviewSnapshot:
    project_id: UUID
    review_id: UUID
    case_id: UUID
    case_version_id: UUID
    version_hash: str
    source_manifest_id: UUID | None
    trial_case_run_id: UUID | None
    evidence_set_hash: str
    expected_current_approval_id: UUID | None
    created_commit_seq: int


@dataclass(frozen=True, slots=True)
class ReviewEvidenceEntry:
    project_id: UUID
    review_id: UUID
    entry_id: UUID
    owner_kind: str
    owner_id: UUID
    attempt_id: UUID
    action_id: UUID
    artifact_ref_id: UUID
    role: str
    expected_hash: str
    evidence_digest: str


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    project_id: UUID
    artifact_id: UUID
    attempt_id: UUID | None
    action_id: UUID | None
    check_id: str | None
    recording_id: UUID | None
    review_id: UUID | None
    build_id: UUID | None
    export_id: UUID | None
    package_id: UUID | None
    healing_id: UUID | None
    proposal_id: UUID | None
    resource_observation_id: UUID | None


@dataclass(frozen=True, slots=True)
class ArtifactProtection:
    project_id: UUID
    protection_id: UUID
    artifact_id: UUID
    kind: str
    backup_receipt_id: UUID | None
    build_id: UUID | None
    manual_request_id: UUID | None


@dataclass(frozen=True, slots=True)
class ApprovalEvent:
    project_id: UUID
    approval_id: UUID
    case_id: UUID
    case_version_id: UUID
    review_id: UUID
    event_kind: str
    prior_approval_id: UUID | None
    version_hash: str
    evidence_set_hash: str
    reason: str


@dataclass(frozen=True, slots=True)
class ReplayPackage:
    project_id: UUID
    package_id: UUID
    case_id: UUID
    case_version_id: UUID
    ready: bool
    schema_version: str
    source_manifest_id: UUID
    source_manifest_hash: str
    raw_source_hash: str
    approved_code_hash: str
    runtime_ref: str
    compiler_ref: str
    lock_hash: str
    step_mapping_hash: str
    body_hash: str


@dataclass(frozen=True, slots=True)
class PackageStep:
    project_id: UUID
    package_id: UUID
    step_id: str
    position: int
    step_hash: str


@dataclass(frozen=True, slots=True)
class HealingEpisode:
    project_id: UUID
    episode_id: UUID
    case_run_id: UUID
    attempt_id: UUID
    package_id: UUID
    request_key: str


@dataclass(frozen=True, slots=True)
class RuntimeOverride:
    project_id: UUID
    override_id: UUID
    episode_id: UUID
    case_run_id: UUID
    attempt_id: UUID
    package_id: UUID
    request_key: str
    body_hash: str


@dataclass(frozen=True, slots=True)
class RepairProposal:
    project_id: UUID
    proposal_id: UUID
    episode_id: UUID
    case_run_id: UUID
    attempt_id: UUID
    package_id: UUID
    request_key: str
    diff_hash: str


@dataclass(frozen=True, slots=True)
class ItemFinalization:
    project_id: UUID
    case_run_id: UUID
    created_seq: int
    finalized_seq: int
    release_label: str
    content_hash: str
    core_result: str
    denominator: bool


@dataclass(frozen=True, slots=True)
class ItemLifecycleEvent:
    project_id: UUID
    event_id: UUID
    case_run_id: UUID
    commit_seq: int
    kind: str


@dataclass(frozen=True, slots=True)
class UsageAdjustment:
    project_id: UUID
    adjustment_id: UUID
    case_run_id: UUID
    commit_seq: int
    role: str
    measurement_status: str
    amount: str | None
    currency: str | None


@dataclass(frozen=True, slots=True)
class FingerprintObservation:
    project_id: UUID
    observation_id: UUID
    case_run_id: UUID
    commit_seq: int
    case_id: UUID
    verification_digest: str
    target_kind: str
    env_profile_revision: str
    data_fingerprint: str
    oracle_policy: str
    schema_version: str
