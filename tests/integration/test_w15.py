"""W15 model broker tests. These do not call a provider."""

from __future__ import annotations

from uuid import uuid4

from aiqa.contracts.jobs import ControlDecision
from aiqa.contracts.models import ModelRequest, OwnedCheck, OwnedEpisode, RoleBinding
from aiqa.models.broker import ModelBroker
from aiqa.models.client import ModelClient


def test_w15_01() -> None:
    secret = "secret-handle"
    broker = ModelBroker(
        "item-1",
        (
            RoleBinding("authoring", 1, "fixture-author", secret),
            RoleBinding("verification", 1, "fixture-check", secret),
            RoleBinding("healing", 1, "fixture-heal", secret),
        ),
        (OwnedCheck("check-1", "item-1"),),
        (OwnedEpisode("episode-1", "item-1"), OwnedEpisode("episode-other", "item-2")),
    )
    client = ModelClient(broker)
    control = _Allow()
    unowned = client.invoke(_request("verification", "check", "check-missing", check_id="check-missing"), control)
    client.invoke(_request("billing", "authoring", "item-1"), control)
    cross = client.invoke(
        _request("healing", "episode", "episode-other", episode_id="episode-other"),
        control,
    )
    authoring = client.invoke(_request("authoring", "authoring", "item-1"), control)
    script = client.replay_script()
    observed = {
        "unowned_call_allowed": unowned.allowed,
        "cross_item_call_allowed": cross.allowed,
        "script_has_key": secret in script or "key" in script or "http" in script,
        "authoring_metered": authoring.measurement_status == "metered" and broker.authoring_calls == 1,
    }
    assert authoring.allowed is True and authoring.actual_model == "fixture-author"
    assert authoring.call_id is not None and script == "actor=0"
    assert unowned.actual_model is None and cross.measurement_status == "not_used"
    assert observed == {
        "unowned_call_allowed": False,
        "cross_item_call_allowed": False,
        "script_has_key": False,
        "authoring_metered": True,
    }


def _request(
    role: str,
    owner_kind: str,
    owner_id: str,
    check_id: str | None = None,
    episode_id: str | None = None,
) -> ModelRequest:
    return ModelRequest(
        uuid4(),
        role,
        owner_kind,
        owner_id,
        1,
        (),
        16,
        "2026-11-01T00:00:00+00:00",
        check_id,
        episode_id,
    )


class _Allow:
    def __init__(self) -> None:
        self.allowed = True

    def checkpoint(self) -> ControlDecision:
        return ControlDecision(self.allowed, "before_model")

    def allow_model_action(self, *, late: bool) -> ControlDecision:
        if late or not self.allowed:
            return ControlDecision(False, "late" if late else "cancelled")
        return ControlDecision(True, "before_model")


def test_w15_02() -> None:
    from aiqa.models.usage import append_usage_adjustment, bind_usage, record_model_usage, reset_usage
    from aiqa.store.usage import ModelCallSettlement, UsageAdjustmentInput, UsageLedger

    ledger = UsageLedger()
    missing = uuid4()
    partial = uuid4()
    unused = uuid4()
    marker = bind_usage(ledger)
    try:
        record_model_usage(_settlement(unused, "maintenance", False, None, None, "not_used", None))
        unreported = record_model_usage(_settlement(missing, "authoring", True, "provider-1", None, "unreported", None))
        record_model_usage(_settlement(partial, "verification", True, "provider-2", 200, "measured", 4))
        retried = record_model_usage(_settlement(missing, "authoring", True, "provider-3", 429, "unreported", None))
        duplicate = record_model_usage(_settlement(missing, "authoring", True, "provider-3", 429, "unreported", None))
        before = ledger.tokens(missing)[0]
        late = append_usage_adjustment(
            UsageAdjustmentInput(missing, "authoring", "1.00", "USD", 9, None, None, None, "estimated")
        )
    finally:
        reset_usage(marker)
    observed = {
        "unreported_tokens": before,
        "unused_role_calls": ledger.unused_role_calls(),
        "partial_total": ledger.partial_total(),
        "late_rewrites_original": ledger.tokens(missing)[0] != before,
    }
    assert unreported.calls == 1 and retried.calls == 2 and duplicate.duplicate is True
    assert late.append_seq == 1 and late.original_input_tokens is None and late.latest_input_tokens == 9
    assert observed == {
        "unreported_tokens": None,
        "unused_role_calls": 0,
        "partial_total": "partial",
        "late_rewrites_original": False,
    }


def test_w15_03() -> None:
    from threading import Thread
    from uuid import uuid4

    from aiqa.contracts.models import ModelRequest, ModelResponse, OwnedEpisode, RoleBinding
    from aiqa.models.broker import ModelBroker
    from aiqa.models.budget import (
        CallBudget,
        ModelReservation,
        bind_model_budget,
        reserve_model_call,
        reset_model_budget,
        settle_model_call,
    )

    control = _Allow()
    race_budget = CallBudget()
    raced: list[object] = []

    def hold() -> None:
        tokens = bind_model_budget(race_budget, control)
        try:
            raced.append(
                reserve_model_call(
                    ModelReservation(uuid4(), "authoring", "2.00", "strict", "2099-01-01T00:00:00+00:00"),
                    control,
                )
            )
        finally:
            reset_model_budget(tokens)

    first = Thread(target=hold)
    second = Thread(target=hold)
    first.start()
    second.start()
    first.join()
    second.join()
    book = CallBudget()
    tokens = bind_model_budget(book, control)
    try:
        unknown = reserve_model_call(
            ModelReservation(uuid4(), "authoring", None, "strict", "2099-01-01T00:00:00+00:00"),
            control,
        )
        estimate = reserve_model_call(
            ModelReservation(uuid4(), "authoring", None, "estimate", "2099-01-01T00:00:00+00:00"),
            control,
        )
    finally:
        reset_model_budget(tokens)
    cap = CallBudget()
    cap_tokens = bind_model_budget(cap, control)
    try:
        opened = [
            reserve_model_call(
                ModelReservation(uuid4(), "authoring", "0.00", "strict", "2099-01-01T00:00:00+00:00"),
                control,
            )
            for _ in range(80)
        ]
        extra = reserve_model_call(
            ModelReservation(uuid4(), "authoring", "0.00", "strict", "2099-01-01T00:00:00+00:00"),
            control,
        )
    finally:
        reset_model_budget(cap_tokens)
    healer = CallBudget()
    healer_tokens = bind_model_budget(healer, control)
    try:
        heal_one = reserve_model_call(
            ModelReservation(uuid4(), "healing", "0.00", "strict", "2099-01-01T00:00:00+00:00", 1),
            control,
        )
        heal_two = reserve_model_call(
            ModelReservation(uuid4(), "healing", "0.00", "strict", "2099-01-01T00:00:00+00:00"),
            control,
        )
        broker = ModelBroker("item-1", (RoleBinding("healing", 1, "fixture-heal", "secret-handle"),), (), (OwnedEpisode("episode-1", "item-1"),))
        broker.attach_budget(healer)
        admitted = broker.admit(
            ModelRequest(uuid4(), "healing", "episode", "episode-1", 1, (), 16, "2099-01-01T00:00:00+00:00", None, "episode-1")
        )
        late_hold = reserve_model_call(
            ModelReservation(uuid4(), "authoring", "0.00", "strict", "2020-01-01T00:00:00+00:00"),
            control,
        )
        late = settle_model_call(late_hold, ModelResponse(late_hold.call_id, "fixture-author", "", "metered", True, None))
        control.allowed = False
        cancelled_hold = reserve_model_call(
            ModelReservation(uuid4(), "authoring", "0.00", "strict", "2099-01-01T00:00:00+00:00"),
            control,
        )
    finally:
        reset_model_budget(healer_tokens)
    observed = {
        "overbooked_reservations": race_budget.overbooked,
        "strict_unknown_price_allowed": unknown.reserved,
        "healer_third_call": heal_two.reserved or admitted.allowed,
        "late_action_dispatched": late.action_allowed,
    }
    assert sum(item.reserved for item in raced) == 1
    assert estimate.reserved is True and estimate.incomplete is True
    assert all(item.reserved for item in opened) and extra.reserved is False
    assert heal_one.reserved is True and heal_two.reserved is False
    assert cancelled_hold.reserved is False
    assert observed == {
        "overbooked_reservations": 0,
        "strict_unknown_price_allowed": False,
        "healer_third_call": False,
        "late_action_dispatched": False,
    }


def _settlement(
    call_id: object,
    role: str,
    sent: bool,
    provider: str | None,
    http_status: int | None,
    status: str,
    input_tokens: int | None,
) -> object:
    from aiqa.store.usage import ModelCallSettlement

    return ModelCallSettlement(
        call_id,
        role,
        sent,
        provider,
        http_status,
        "fixture-author" if sent else None,
        "tariff-1" if status == "measured" else None,
        "USD" if status == "measured" else None,
        input_tokens,
        None,
        None,
        None,
        status,
    )
