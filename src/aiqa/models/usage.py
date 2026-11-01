"""Usage entry points. Importing this module does not call a model."""

from __future__ import annotations

from contextvars import ContextVar

from aiqa.store.usage import (
    ModelCallSettlement,
    UsageAdjustmentInput,
    UsageLedger,
    UsageLedgerView,
    UsageReceipt,
)

_ledger: ContextVar[UsageLedger] = ContextVar("aiqa_usage_ledger")


def bind_usage(ledger: UsageLedger):
    return _ledger.set(ledger)


def reset_usage(token) -> None:
    _ledger.reset(token)


def record_model_usage(settlement: ModelCallSettlement) -> UsageReceipt:
    """Count a real send. An unused role stays at zero calls and null tokens."""

    return _ledger.get().record(settlement)


def append_usage_adjustment(adjustment: UsageAdjustmentInput) -> UsageLedgerView:
    """Append a late bill. The original token fields stay as first recorded."""

    return _ledger.get().adjust(adjustment)
