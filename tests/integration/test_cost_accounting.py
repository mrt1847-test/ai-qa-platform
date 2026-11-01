"""Cost accounting around retries, empty samples, and fixture tariffs."""

from __future__ import annotations

from aiqa.contracts.benchmarks import WorkloadFacts
from aiqa.domain.costs import summarize_workload_cost


def test_empty_sample_has_no_invented_rate() -> None:
    summary = summarize_workload_cost(WorkloadFacts(20, (), (), (), 0))
    assert summary.currency_totals == ()
    assert summary.per_item_cost is None
    assert summary.monthly_cost is None
    assert summary.unused_role_cost == "0"
    assert summary.unreported_usage is None
    assert summary.combined_amount is None
