"""Role cost totals for one as-of sample. Fixture prices stay out of a monthly claim."""

from __future__ import annotations

from decimal import Decimal

from aiqa.contracts.benchmarks import (
    CALL_KINDS,
    NULL_USAGE_STATUSES,
    PRICED_STATUSES,
    ROLES,
    LedgerRow,
    TariffFixture,
    WorkloadCall,
    WorkloadCostSummary,
    WorkloadFacts,
)

_NOTICE = "이 금액은 fixture 가격입니다. 실제 단가나 월 비용이 아닙니다."


def summarize_workload_cost(facts: WorkloadFacts) -> WorkloadCostSummary:
    """Sum one currency at a time. A later ledger row stays outside this as-of."""

    if type(facts.as_of) is not int or facts.sample_size < 0:
        raise ValueError("workload as_of is invalid")
    tariffs = {row.tariff_id: row for row in facts.tariffs}
    included = tuple(call for call in facts.calls if call.commit_seq <= facts.as_of)
    late_rows = sum(1 for row in facts.ledger if row.commit_seq > facts.as_of)
    for call in included:
        if call.role not in ROLES or call.kind not in CALL_KINDS:
            raise ValueError("workload call is invalid")
        if call.measurement_status in NULL_USAGE_STATUSES and call.amount is not None:
            raise ValueError("missing usage has no amount")
    role_costs = tuple((role, _role_amount(role, facts.ledger, facts.as_of)) for role in ROLES)
    return WorkloadCostSummary(
        role_costs=role_costs,
        currency_totals=_currency_totals(facts.ledger, facts.as_of),
        combined_amount=None,
        unreported_usage=_unreported(included),
        unused_role_cost=_unused_cost(role_costs, included),
        occupancy_seconds=sum(call.occupancy_seconds for call in included),
        occupancy_amount=None,
        partial_roles=tuple(dict.fromkeys(call.role for call in included if call.partial)),
        kind_counts=tuple(
            (
                role,
                tuple(
                    (kind, sum(1 for call in included if call.role == role and call.kind == kind))
                    for kind in ("request", "retry", "check", "episode")
                ),
            )
            for role in ROLES
        ),
        tariff_quotes=tuple(
            (call.call_id, _quote(tariffs[call.tariff_id], call))
            for call in included
            if call.tariff_id in tariffs and call.input_tokens is not None and call.output_tokens is not None
        ),
        per_item_cost=None,
        monthly_cost=None,
        excluded_late_rows=late_rows,
        fixture_notice=_NOTICE,
    )


def _role_amount(role: str, ledger: tuple[LedgerRow, ...], as_of: int) -> str:
    priced = [
        str(row.amount)
        for row in ledger
        if row.role == role
        and row.commit_seq <= as_of
        and row.measurement_status in PRICED_STATUSES
        and row.amount is not None
    ]
    if priced == []:
        return "0"
    return _sum(priced)


def _unused_cost(role_costs: tuple[tuple[str, str], ...], calls: tuple[WorkloadCall, ...]) -> str:
    amounts = dict(role_costs)
    for role in ROLES:
        role_calls = [call for call in calls if call.role == role]
        if role_calls and all(call.measurement_status == "not_used" for call in role_calls):
            return amounts[role]
    return "0"


def _currency_totals(ledger: tuple[LedgerRow, ...], as_of: int) -> tuple[tuple[str, str], ...]:
    grouped: dict[str, list[str]] = {}
    for row in ledger:
        if row.commit_seq > as_of or row.measurement_status not in PRICED_STATUSES:
            continue
        if row.currency is None or row.amount is None:
            continue
        grouped.setdefault(row.currency, []).append(row.amount)
    return tuple((currency, _sum(amounts)) for currency, amounts in sorted(grouped.items()))


def _unreported(calls: tuple[WorkloadCall, ...]) -> None:
    for call in calls:
        if call.measurement_status in {"unreported", "unknown"}:
            return None
    return None


def _quote(tariff: TariffFixture, call: WorkloadCall) -> str:
    if call.input_tokens is None or call.output_tokens is None:
        raise ValueError("tariff quote needs tokens")
    total = Decimal(tariff.input_price) * call.input_tokens + Decimal(tariff.output_price) * call.output_tokens
    return _format(total)


def _sum(amounts: list[str]) -> str:
    total = sum((Decimal(amount) for amount in amounts), Decimal("0"))
    return _format(total)


def _format(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'))}"
