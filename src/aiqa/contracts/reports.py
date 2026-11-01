"""Long-term item facts and the display-result kernel. Importing this module does not open a database."""

from __future__ import annotations

from dataclasses import dataclass

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


__all__ = [
    "CORE_RESULTS",
    "MEASUREMENT_STATUSES",
    "CaseRunFacts",
    "DisplayResult",
    "ExecutionSummary",
    "FingerprintObservation",
    "ItemFinalization",
    "ItemLifecycleEvent",
    "UsageAdjustment",
]
