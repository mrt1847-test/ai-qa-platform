"""Long-term item facts and the display-result kernel. Importing this module does not open a database."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from aiqa.store.models import (
    FingerprintObservation,
    ItemFinalization,
    ItemLifecycleEvent,
    UsageAdjustment,
)

CORE_RESULTS = frozenset(
    {"PASS", "FAIL", "BLOCKED", "INCONCLUSIVE", "SKIPPED", "CANCELLED", "NOT_RUN"}
)
MEASUREMENT_STATUSES = frozenset({"measured", "estimated", "unreported", "not_used", "unknown"})

@dataclass(frozen=True, slots=True)
class CaseRunFacts:
    status: str
    verdict: str | None = None
    disposition: str | None = None
    violations: int = 0
    cancelled: bool = False
    healing_used: bool = False
    healing_outcome: str = ""
    action_error: bool = False
    action_retry: bool = False
    recovery_used: bool = False
    verifier_used: bool = False
    project_id: str = ""
    case_id: str = ""
    verification_digest: str = ""
    target_kind: str = ""
    env_profile_revision: str = ""
    data_fingerprint: str = ""
    oracle_policy: str = ""
    actual_build: str = ""
    actual_build_seq: int | None = None
    device_os: str = ""
    browser: str = ""
    viewport_dpr: str = ""
    engine_patch: str = ""
    model_prompt: str = ""
    model_status: str = "unknown"
    package_hash: str = ""
    runtime_ref: str = ""
    lock_hash: str = ""
    healing_requested: str = "off"
    healing_policy_hash: str = ""
    verifier_method: str = ""
    verifier_binding: str = ""
    requested_at: str = ""
    execution_id: str = ""
    item_id: str = ""
    secret_ref: str = ""


@dataclass(frozen=True, slots=True)
class DisplayResult:
    code: str


@dataclass(frozen=True, slots=True)
class ExecutionSummary:
    n: int
    terminal: int
    completion_rate: float | None
    verified_pass_rate: float | None
    total_pass_rate: float | None
    unverified: int


@dataclass(frozen=True, slots=True)
class AnalyticsQuery:
    project_id: UUID
    period_from: str
    period_to: str
    as_of: int
    purpose: str = ""
    include_trial: bool = False
    criteria: str = "all_observations"
    case_filter: str = ""
    version_filter: str = ""
    verification_filter: str = ""
    data_filter: str = ""
    env_filter: str = ""
    build_filter: str = ""
    model_filter: str = ""
    release_label: str = ""


@dataclass(frozen=True, slots=True)
class Observation:
    case_run_id: UUID
    execution_id: UUID
    source: str
    purpose: str
    in_denominator: bool
    terminal: bool
    result: str | None
    attempt_count: int


@dataclass(frozen=True, slots=True)
class ObservationPage:
    items: tuple[Observation, ...]


@dataclass(frozen=True, slots=True)
class AnalyticsReport:
    sample_count: int
    denominator: int
    unverified: int
    as_of: int
    criteria: str
    rates: tuple[float | None, float | None, float | None] | None
    p50: float | None
    p95: float | None
    not_run_duration: int | None
    cost: str | None
    storage_count: int
    trend_dates: tuple[str, ...]
    repeated_checks: int
    analysis_count: int
    first_satisfied: int
    recovery_count: int
    condition_count: int
    period_from: str
    period_to: str
    purpose: str
    case_id: str


__all__ = [
    "CORE_RESULTS",
    "MEASUREMENT_STATUSES",
    "AnalyticsQuery",
    "AnalyticsReport",
    "CaseRunFacts",
    "Observation",
    "ObservationPage",
    "DisplayResult",
    "ExecutionSummary",
    "FingerprintObservation",
    "ItemFinalization",
    "ItemLifecycleEvent",
    "UsageAdjustment",
]
