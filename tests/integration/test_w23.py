"""Execution rates use the seven terminal results. An empty run has no rate."""

from __future__ import annotations

from aiqa.contracts.reports import CaseRunFacts
from aiqa.domain.report_math import derive_display_result, summarize_execution


def test_w23_01() -> None:
    items = (
        [_fact("PASS")] * 6
        + [_fact("FAIL")] * 2
        + [_fact("BLOCKED"), _fact("NOT_RUN")]
    )
    summary = summarize_execution(items)
    observed = {
        "terminal": summary.terminal,
        "completion_rate": summary.completion_rate,
        "verified_pass_rate": summary.verified_pass_rate,
        "total_pass_rate": summary.total_pass_rate,
        "unverified": summary.unverified,
    }
    running = summarize_execution(items + [_fact("running")])
    empty = summarize_execution([])
    latched = derive_display_result(CaseRunFacts("running", violations=1, cancelled=True))
    assert running.n == 11 and running.terminal == 10 and running.completion_rate == 10 / 11
    assert empty.completion_rate is None and empty.verified_pass_rate is None and empty.total_pass_rate is None
    assert latched is not None and latched.code == "FAIL"
    assert summarize_execution([CaseRunFacts("running", violations=1, cancelled=True)]).terminal == 1
    assert observed == {
        "terminal": 10,
        "completion_rate": 1,
        "verified_pass_rate": 0.75,
        "total_pass_rate": 0.6,
        "unverified": 2,
    }


def _fact(code: str) -> CaseRunFacts:
    if code in {"PASS", "FAIL", "BLOCKED", "INCONCLUSIVE", "SKIPPED", "CANCELLED", "NOT_RUN"}:
        return CaseRunFacts(code, code)
    return CaseRunFacts(code)
