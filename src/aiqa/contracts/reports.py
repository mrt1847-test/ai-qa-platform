"""Long-term item facts. Importing this module does not open a database."""

from __future__ import annotations

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

__all__ = [
    "CORE_RESULTS",
    "MEASUREMENT_STATUSES",
    "FingerprintObservation",
    "ItemFinalization",
    "ItemLifecycleEvent",
    "UsageAdjustment",
]
