"""A real ON claim stays closed without a recovery client and does not heal a normal replay."""
import copy

from test_rx87_healing_recovery import Client
from test_rx95_worker_healing_pin import admitted_healing, healing_claim, healing_execution, healing_metadata, ux_app
from test_rx_34 import _observation, _replay


def test_real_on_claim_blocks_without_a_client_then_replays_without_healing(healing_claim, tmp_path):
    handler, calls = _replay(tmp_path)
    claim = healing_claim
    claim["snapshot"]["serial"] = handler.context.expected_serial
    blocked = handler.handle(claim)
    assert blocked.actions == 0 and blocked.outcome == "error" and calls == []
    assert handler.stopped_reason == "healing_runtime_unavailable"
    assert handler.authoring_calls_seen == handler.healer_calls == handler.verifier_calls == 0

    handler.context.healing_client = Client(0)
    allowed = handler.handle(claim)
    assert allowed.outcome == "completed" and allowed.actions == len(calls) == 1
    assert handler.healer_calls == handler.authoring_calls_seen == handler.verifier_calls == 0
    assert handler.stopped_reason == ""

    capped, capped_calls = _replay(tmp_path)
    capped.context.healing_client = Client(0)
    capped.context.approved_plan = "click(250, 500)\nclick(250, 500)"
    capped.context.step_observations = tuple((_observation(), _observation()) for _ in range(2))
    snapshot = copy.deepcopy(claim["snapshot"])
    snapshot["limits"]["max_actions"] = 1
    budget = capped.handle({**claim, "snapshot": snapshot})
    assert budget.actions == len(capped_calls) == 1 and capped.stopped_reason == "action_budget"
    assert capped.healer_calls == capped.authoring_calls_seen == 0
