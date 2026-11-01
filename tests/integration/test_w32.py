"""Workload cost formula. Fixture prices are not a monthly invoice."""

from __future__ import annotations

from aiqa.contracts.benchmarks import LedgerRow, TariffFixture, WorkloadCall, WorkloadFacts
from aiqa.domain.costs import summarize_workload_cost


def test_w32_01() -> None:
    facts = WorkloadFacts(
        as_of=20,
        sample_size=6,
        tariffs=(TariffFixture("fixture-tariff", "USD", "0.01", "0.02"),),
        calls=(
            WorkloadCall("author-1", "authoring", "request", "measured", 10, "USD", "1.00", occupancy_seconds=30),
            WorkloadCall("author-retry", "authoring", "retry", "measured", 12, "USD", "0.50"),
            WorkloadCall(
                "verify-check",
                "verification",
                "check",
                "estimated",
                15,
                "USD",
                "0.04",
                input_tokens=2,
                output_tokens=1,
                tariff_id="fixture-tariff",
                partial=True,
            ),
            WorkloadCall("heal-episode", "healing", "episode", "measured", 18, "KRW", "1000"),
            WorkloadCall("maintain-idle", "maintenance", "request", "not_used", 16),
            WorkloadCall("author-missing", "authoring", "request", "unreported", 17),
        ),
        ledger=(
            LedgerRow(10, "authoring", "measured", "1.00", "USD"),
            LedgerRow(12, "authoring", "measured", "0.50", "USD"),
            LedgerRow(15, "verification", "estimated", "0.04", "USD"),
            LedgerRow(18, "healing", "measured", "1000", "KRW"),
            LedgerRow(16, "maintenance", "not_used", None, None),
            LedgerRow(17, "authoring", "unreported", None, None),
            LedgerRow(30, "authoring", "measured", "9.00", "USD"),
        ),
    )
    summary = summarize_workload_cost(facts)
    roles = dict(summary.role_costs)
    totals = dict(summary.currency_totals)
    counts = {role: dict(kinds) for role, kinds in summary.kind_counts}
    observed = {
        "unreported_usage": summary.unreported_usage,
        "unused_role_cost": summary.unused_role_cost,
        "mixed_currencies_combined": summary.combined_amount is not None,
        "late_asof_respected": totals.get("USD") == "1.54" and summary.excluded_late_rows == 1,
    }
    assert roles["maintenance"] == "0"
    assert roles["authoring"] == "1.50" and roles["verification"] == "0.04" and roles["healing"] == "1000.00"
    assert totals["KRW"] == "1000.00"
    assert dict(summary.tariff_quotes)["verify-check"] == "0.04"
    assert counts["authoring"]["retry"] == 1
    assert counts["verification"]["check"] == 1
    assert counts["healing"]["episode"] == 1
    assert summary.partial_roles == ("verification",)
    assert summary.occupancy_seconds == 30 and summary.occupancy_amount is None
    assert summary.monthly_cost is None and "월 비용" in summary.fixture_notice
    assert "90.00" not in totals.values()
    assert observed == {
        "unreported_usage": None,
        "unused_role_cost": "0",
        "mixed_currencies_combined": False,
        "late_asof_respected": True,
    }
