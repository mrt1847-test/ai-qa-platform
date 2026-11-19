"""Locator recovery repeats one unsent action and leaves the original QA untouched."""
import json
from dataclasses import replace
from aiqa.adapters.mobile_agent_android import MobileAgentRejected
from aiqa.healing.targets import HealingProposal, TargetCandidate
from test_rx_34 import _claim, _observation, _replay


def _screen(observation):
    element = {"role":"button","name":"Save","container":"bar","resource_id":"com.example:id/save","text":"Save","context":"main","locator":"#save","visible":True,"enabled":True,"bounds":[0,0,4,4]}
    return replace(observation, dom=json.dumps({"elements":[element]}))


def _proposal():
    candidate = TargetCandidate("button","Save","bar","com.example:id/save","Save","main","#save","tap","","ok",(1,1),"typed")
    return HealingProposal("button","Save","bar","com.example:id/save","Save","main","#save","tap","","ok",candidate,True)


class Client:
    def __init__(self, calls=1):
        self.calls = calls
    def reserve(self, **kwargs):
        return type("Receipt", (), {"eligible": self.calls > 0, "reserved_calls": self.calls})()
    def proposal(self, **kwargs):
        return _proposal()


def _enabled(monkeypatch):
    monkeypatch.setattr("aiqa.worker.android_jobs.resolve_claim_healing_pin", lambda snapshot: type("Pin", (), {"enabled": True, "policy": None, "binding": None})())


def test_locator_failure_dispatches_the_original_action_once(tmp_path, monkeypatch):
    handler, calls = _replay(tmp_path)
    _enabled(monkeypatch)
    handler.context.healing_client = Client()
    handler.context.before = _screen(handler.context.before)
    handler.context.after = _screen(handler.context.after)
    original = handler.adapter.replay_step
    seen = []
    def step(**kwargs):
        seen.append(kwargs["plan_response"])
        if len(seen) == 1:
            raise MobileAgentRejected("target_not_found")
        return original(**kwargs)
    monkeypatch.setattr(handler.adapter, "replay_step", step)
    result = handler.handle(_claim())
    assert result.outcome == "completed" and result.actions == 1 and len(calls) == 1
    assert seen[0] == seen[1] and handler.healer_calls == 1 and handler.authoring_calls_seen == 0
    assert handler.original_failure == "target_not_found"


def test_sent_action_and_assertion_failure_are_not_retried(tmp_path, monkeypatch):
    handler, calls = _replay(tmp_path)
    _enabled(monkeypatch)
    handler.context.healing_client = Client()
    original = handler.adapter.replay_step
    def step(**kwargs):
        kwargs["before_native_send"]()
        raise MobileAgentRejected("target_not_found")
    monkeypatch.setattr(handler.adapter, "replay_step", step)
    sent = handler.handle(_claim())
    assert sent.actions == 0 and calls == [] and handler.healer_calls == 0

    handler, calls = _replay(tmp_path)
    _enabled(monkeypatch)
    handler.context.healing_client = Client()
    monkeypatch.setattr(handler.adapter, "replay_step", lambda **kwargs: (_ for _ in ()).throw(MobileAgentRejected("text_mismatch")))
    denied = handler.handle(_claim())
    assert denied.actions == 0 and handler.healer_calls == 0 and handler.original_failure == "text_mismatch"


def test_on_without_a_client_does_not_run_and_success_does_not_heal(tmp_path, monkeypatch):
    handler, calls = _replay(tmp_path)
    _enabled(monkeypatch)
    blocked = handler.handle(_claim())
    assert blocked.actions == 0 and blocked.outcome == "error" and handler.stopped_reason == "healing_runtime_unavailable"
    handler, calls = _replay(tmp_path)
    _enabled(monkeypatch)
    handler.context.healing_client = Client(0)
    result = handler.handle(_claim())
    assert result.outcome == "completed" and result.actions == len(calls) == 1
    assert handler.healer_calls == 0
