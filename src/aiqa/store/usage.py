"""Append-only model usage. A late bill does not rewrite the original call."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID, uuid4


@dataclass(frozen=True, slots=True)
class ModelCallSettlement:
    call_id: UUID
    role: str
    sent: bool
    provider_request_id: str | None
    http_status: int | None
    actual_model: str | None
    tariff_id: str | None
    currency: str | None
    input_tokens: int | None
    output_tokens: int | None
    cache_tokens: int | None
    image_tokens: int | None
    measurement_status: str


@dataclass(frozen=True, slots=True)
class UsageReceipt:
    call_id: UUID
    calls: int
    measurement_status: str
    duplicate: bool


@dataclass(frozen=True, slots=True)
class UsageAdjustmentInput:
    call_id: UUID
    role: str
    amount: str | None
    currency: str | None
    input_tokens: int | None
    output_tokens: int | None
    cache_tokens: int | None
    image_tokens: int | None
    measurement_status: str


@dataclass(frozen=True, slots=True)
class UsageLedgerView:
    call_id: UUID
    append_seq: int
    original_input_tokens: int | None
    latest_input_tokens: int | None


@dataclass
class _Call:
    call_id: UUID
    role: str
    calls: int
    measurement_status: str
    actual_model: str | None
    tariff_id: str | None
    currency: str | None
    input_tokens: int | None
    output_tokens: int | None
    cache_tokens: int | None
    image_tokens: int | None
    provider_ids: set[str] = field(default_factory=set)
    adjustments: list[UsageAdjustmentInput] = field(default_factory=list)


class UsageLedger:
    """Call-level usage. Unused stays at no calls, and missing numbers stay null."""

    def __init__(self) -> None:
        self._calls: dict[UUID, _Call] = {}

    def record(self, settlement: ModelCallSettlement) -> UsageReceipt:
        existing = self._calls.get(settlement.call_id)
        if settlement.provider_request_id and existing is not None:
            if settlement.provider_request_id in existing.provider_ids:
                return UsageReceipt(existing.call_id, existing.calls, existing.measurement_status, True)
        if not settlement.sent or settlement.measurement_status == "not_used":
            row = _Call(
                settlement.call_id,
                settlement.role,
                0,
                "not_used",
                None,
                None,
                None,
                None,
                None,
                None,
                None,
            )
            self._calls[settlement.call_id] = row
            return UsageReceipt(settlement.call_id, 0, "not_used", False)
        if settlement.measurement_status == "unreported":
            tokens = (None, None, None, None)
            status = "unreported"
        elif settlement.measurement_status == "unknown":
            tokens = (None, None, None, None)
            status = "unknown"
        else:
            tokens = (
                settlement.input_tokens,
                settlement.output_tokens,
                settlement.cache_tokens,
                settlement.image_tokens,
            )
            status = settlement.measurement_status
        if existing is None:
            row = _Call(
                settlement.call_id,
                settlement.role,
                1,
                status,
                settlement.actual_model,
                settlement.tariff_id,
                settlement.currency,
                tokens[0],
                tokens[1],
                tokens[2],
                tokens[3],
            )
        else:
            row = existing
            row.calls += 1
        if settlement.provider_request_id:
            row.provider_ids.add(settlement.provider_request_id)
        self._calls[settlement.call_id] = row
        return UsageReceipt(row.call_id, row.calls, row.measurement_status, False)

    def adjust(self, adjustment: UsageAdjustmentInput) -> UsageLedgerView:
        row = self._calls.get(adjustment.call_id)
        if row is None:
            raise KeyError("usage call was not found")
        original = row.input_tokens
        row.adjustments.append(adjustment)
        latest = adjustment.input_tokens
        return UsageLedgerView(row.call_id, len(row.adjustments), original, latest)

    def tokens(self, call_id: UUID) -> tuple[int | None, int | None, int | None, int | None]:
        row = self._calls[call_id]
        return (row.input_tokens, row.output_tokens, row.cache_tokens, row.image_tokens)

    def unused_role_calls(self) -> int:
        return sum(row.calls for row in self._calls.values() if row.measurement_status == "not_used")

    def partial_total(self) -> str:
        for row in self._calls.values():
            if row.measurement_status not in {"measured", "estimated"}:
                continue
            present = [row.input_tokens, row.output_tokens, row.cache_tokens, row.image_tokens]
            if any(token is None for token in present) and any(token is not None for token in present):
                return "partial"
        return "complete"


def new_adjustment_id() -> UUID:
    return uuid4()
