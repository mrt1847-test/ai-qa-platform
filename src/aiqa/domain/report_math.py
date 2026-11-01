"""Display results and execution rates. This module does not open a database or a screen."""

from __future__ import annotations

from aiqa.contracts.reports import CORE_RESULTS, CaseRunFacts, DisplayResult, ExecutionSummary

_UNVERIFIED = frozenset({"BLOCKED", "INCONCLUSIVE", "SKIPPED", "CANCELLED", "NOT_RUN"})


def derive_display_result(item: CaseRunFacts) -> DisplayResult | None:
    """Return one terminal code. A required violation stays a failure, and other states stay open."""

    if item.violations > 0:
        return DisplayResult("FAIL")
    if item.cancelled or item.disposition == "cancelled":
        return DisplayResult("CANCELLED")
    code = item.verdict if item.verdict in CORE_RESULTS else None
    if code is None and item.status in CORE_RESULTS:
        code = item.status
    if code is None:
        return None
    return DisplayResult(code)


def summarize_execution(items: list[CaseRunFacts]) -> ExecutionSummary:
    """Count terminal items, the three rates, and the five unfinished terminal kinds."""

    codes = [result.code for item in items if (result := derive_display_result(item)) is not None]
    total = len(items)
    terminal = len(codes)
    passed = sum(1 for code in codes if code == "PASS")
    failed = sum(1 for code in codes if code == "FAIL")
    verified = passed + failed
    return ExecutionSummary(
        n=total,
        terminal=terminal,
        completion_rate=None if total == 0 else terminal / total,
        verified_pass_rate=None if verified == 0 else passed / verified,
        total_pass_rate=None if total == 0 else passed / total,
        unverified=sum(1 for code in codes if code in _UNVERIFIED),
    )
