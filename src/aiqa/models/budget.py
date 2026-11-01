"""Reserve model budget before a call. A late response cannot start an action."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from threading import Lock
from uuid import UUID

from aiqa.contracts.jobs import ControlDecision
from aiqa.contracts.models import ModelResponse
from aiqa.worker.control import RunControl

_MAX_CALLS = 80
_HEALER_TRANSMISSIONS = 2
_budget: ContextVar[CallBudget] = ContextVar("aiqa_model_budget")
_control: ContextVar[RunControl] = ContextVar("aiqa_model_budget_control")


@dataclass(frozen=True, slots=True)
class ModelReservation:
    call_id: UUID
    role: str
    max_cost: str | None
    price_mode: str
    deadline: str
    transport_retries: int = 0


@dataclass(frozen=True, slots=True)
class Reservation:
    call_id: UUID
    reserved: bool
    incomplete: bool
    reason: str
    deadline: str


@dataclass(frozen=True, slots=True)
class Settlement:
    call_id: UUID
    settled: bool
    action_allowed: bool


class CallBudget:
    """One budget book. Reservations that would pass the cap are refused."""

    def __init__(self, budget: str = "2.00", max_calls: int = _MAX_CALLS) -> None:
        self.budget = Decimal(budget)
        self.max_calls = max_calls
        self.overbooked = 0
        self._lock = Lock()
        self._reserved_cost = Decimal("0")
        self._reserved_calls = 0
        self._healer = 0

    def room_for(self, role: str) -> bool:
        with self._lock:
            if role == "healing":
                return self._healer < _HEALER_TRANSMISSIONS
            return self._reserved_calls < self.max_calls

    def reserve(self, spec: ModelReservation, control: RunControl) -> Reservation:
        decision = control.checkpoint()
        if not isinstance(decision, ControlDecision) or not decision.allowed:
            return _closed(spec, "cancelled")
        if spec.price_mode == "strict" and spec.max_cost is None:
            return _closed(spec, "unknown_price")
        if spec.price_mode not in {"strict", "estimate"}:
            return _closed(spec, "price_mode")
        cost = Decimal("0") if spec.max_cost is None else Decimal(spec.max_cost)
        transmissions = 1 + spec.transport_retries
        if transmissions < 1:
            return _closed(spec, "calls")
        with self._lock:
            if spec.role == "healing" and self._healer + transmissions > _HEALER_TRANSMISSIONS:
                return _closed(spec, "healer")
            if self._reserved_calls + transmissions > self.max_calls:
                return _closed(spec, "calls")
            if self._reserved_cost + cost > self.budget:
                return _closed(spec, "budget")
            self._reserved_calls += transmissions
            self._reserved_cost += cost
            if spec.role == "healing":
                self._healer += transmissions
        incomplete = spec.price_mode == "estimate" and spec.max_cost is None
        return Reservation(spec.call_id, True, incomplete, "reserved", spec.deadline)


def bind_model_budget(budget: CallBudget, control: RunControl):
    budget_token = _budget.set(budget)
    control_token = _control.set(control)
    return budget_token, control_token


def reset_model_budget(tokens) -> None:
    budget_token, control_token = tokens
    _control.reset(control_token)
    _budget.reset(budget_token)


def reserve_model_call(spec: ModelReservation, control: RunControl) -> Reservation:
    """Hold cost, time, and call count before the provider is contacted."""

    return _budget.get().reserve(spec, control)


def settle_model_call(reservation: Reservation, response: ModelResponse) -> Settlement:
    """Settle a reserved call. A late or cancelled response does not dispatch."""

    if not reservation.reserved:
        return Settlement(reservation.call_id, False, False)
    control = _control.get()
    late = _late(reservation.deadline)
    decision = control.allow_model_action(late=late)
    allowed = isinstance(decision, ControlDecision) and decision.allowed and not late
    return Settlement(reservation.call_id, True, allowed and response.allowed)


def _closed(spec: ModelReservation, reason: str) -> Reservation:
    return Reservation(spec.call_id, False, False, reason, spec.deadline)


def _late(deadline: str) -> bool:
    parsed = datetime.fromisoformat(deadline)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return True
    return datetime.now(parsed.tzinfo) > parsed
