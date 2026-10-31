"""Case definition types. Importing this module does not hash or open a database."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from aiqa.store.models import SecretRef

JsonObject = dict[str, object]


@dataclass(frozen=True, slots=True)
class CheckSpec:
    id: str
    kind: str
    expected: str


@dataclass(frozen=True, slots=True)
class StepSpec:
    id: str
    instruction: str
    expected: tuple[CheckSpec, ...]
    point: tuple[int, int] | None = None


@dataclass(frozen=True, slots=True)
class PathPolicy:
    must_use: tuple[str, ...] = ()
    forbidden: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CaseSettings:
    target_kind: str
    execution_mode: str = "recorded_replay"
    document: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CaseRevisionInput:
    definition: CaseDefinition
    settings: CaseSettings
    recorded_steps: tuple[dict[str, object], ...] = ()
    parent_version_id: UUID | None = None
    base_version_id: UUID | None = None
    reason: str = ""
    branch: bool = False


@dataclass(frozen=True, slots=True)
class ReadinessReason:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class CaseReadiness:
    saved: bool
    recordable: bool
    replayable: bool
    reviewable: bool
    formal_runnable: bool
    reasons: tuple[ReadinessReason, ...]


@dataclass(frozen=True, slots=True)
class CaseVersion:
    id: UUID
    project_id: UUID
    case_id: UUID
    definition: CaseDefinition
    replay_package_id: UUID | None
    approval_id: UUID | None
    creation_kind: str
    content_hash: str
    verification_digest: str
    parent_version_id: UUID | None = None
    rebuild: bool = False


@dataclass(frozen=True, slots=True)
class ReadinessFacts:
    variables_resolved: bool = True
    resources_available: bool = True
    capability_supported: bool = True
    model_binding_available: bool = True
    budget_available: bool = True
    package_ready: bool = False
    package_valid: bool = False
    evidence_complete: bool = False
    source_complete: bool = True
    trial_present: bool = False
    trial_clean: bool = False
    trial_passed: bool = False
    review_complete: bool = False
    approval_valid: bool = False
    approval_revoked: bool = False
    scope_match: bool = True


@dataclass(frozen=True, slots=True)
class CaseVersionView:
    project_id: UUID
    case_id: UUID
    id: UUID
    revision: int
    creation_kind: str
    parent_version_id: UUID | None
    base_version_id: UUID | None
    content_hash: str
    verification_digest: str
    replay_package_id: UUID | None
    readiness: CaseReadiness


@dataclass(frozen=True, slots=True)
class CaseDefinition:
    raw_text: str
    objective: str
    preconditions: tuple[str, ...]
    variables: dict[str, object]
    secret_refs: dict[str, SecretRef]
    steps: tuple[StepSpec, ...]
    final_expected: tuple[CheckSpec, ...]
    path_policy: PathPolicy


def secret_ref_document(ref: SecretRef) -> dict[str, object]:
    return {"project_id": str(ref.project_id), "ref_id": str(ref.ref_id), "revision": ref.revision}


def check_document(check: CheckSpec) -> dict[str, object]:
    return {"id": check.id, "kind": check.kind, "expected": check.expected}
