"""Workload cost inputs. Importing this module does not price a live model."""

from __future__ import annotations

from dataclasses import dataclass

ROLES = ("authoring", "verification", "healing", "maintenance")
CALL_KINDS = frozenset({"request", "retry", "check", "episode"})
PRICED_STATUSES = frozenset({"measured", "estimated"})
NULL_USAGE_STATUSES = frozenset({"unreported", "unknown", "not_used"})


@dataclass(frozen=True, slots=True)
class TariffFixture:
    """A test price table. These numbers are not a provider invoice."""

    tariff_id: str
    currency: str
    input_price: str
    output_price: str


@dataclass(frozen=True, slots=True)
class WorkloadCall:
    call_id: str
    role: str
    kind: str
    measurement_status: str
    commit_seq: int
    currency: str | None = None
    amount: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    tariff_id: str | None = None
    partial: bool = False
    occupancy_seconds: int = 0


@dataclass(frozen=True, slots=True)
class LedgerRow:
    commit_seq: int
    role: str
    measurement_status: str
    amount: str | None
    currency: str | None


@dataclass(frozen=True, slots=True)
class WorkloadFacts:
    as_of: int
    calls: tuple[WorkloadCall, ...]
    ledger: tuple[LedgerRow, ...]
    tariffs: tuple[TariffFixture, ...]
    sample_size: int


@dataclass(frozen=True, slots=True)
class WorkloadCostSummary:
    role_costs: tuple[tuple[str, str], ...]
    currency_totals: tuple[tuple[str, str], ...]
    combined_amount: str | None
    unreported_usage: str | None
    unused_role_cost: str
    occupancy_seconds: int
    occupancy_amount: str | None
    partial_roles: tuple[str, ...]
    kind_counts: tuple[tuple[str, tuple[tuple[str, int], ...]], ...]
    tariff_quotes: tuple[tuple[str, str], ...]
    per_item_cost: str | None
    monthly_cost: str | None
    excluded_late_rows: int
    fixture_notice: str
