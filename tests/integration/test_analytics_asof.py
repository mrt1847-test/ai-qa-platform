"""A later ledger row stays outside an earlier as-of total."""

from __future__ import annotations

from aiqa.store.usage import ledger_total_as_of


def test_late_usage_stays_outside_earlier_asof() -> None:
    entries = ((10, "2.00"), (30, "1.00"))
    assert ledger_total_as_of(entries, 25) == "2.00"
    assert ledger_total_as_of(entries, 30) == "3.00"
    assert ledger_total_as_of((), 30) is None
