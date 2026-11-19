import json
from dataclasses import replace
from aiqa.healing.recovery import plan_bounded_recovery
from aiqa.healing.targets import HealingProposal, TargetCandidate
from test_rx_34 import _observation


def proposal(action="tap", path="ok", candidate_action=None):
    candidate = TargetCandidate("button","Save","bar","com.example:id/save","Save","main","#save",action if candidate_action is None else candidate_action,"",path,(1,1),"typed")
    return HealingProposal("button","Save","bar","com.example:id/save","Save","main","#save",action,"",path,candidate,True)


def observation():
    element = {"role":"button","name":"Save","container":"bar","resource_id":"com.example:id/save","text":"Save","context":"main","locator":"#save","visible":True,"enabled":True,"bounds":[0,0,2,2]}
    return replace(_observation(), dom=json.dumps({"elements":[element]}))


def decide(**changes):
    values = dict(reason="target_not_found", product_violation=False, dispatch_sent=False, proposal=proposal(), observation=observation(), checkpoint=lambda: True, reserved_calls=1, already_used=False)
    values.update(changes)
    return plan_bounded_recovery(**values)


def test_unique_same_target_allows_one_dispatch_without_changing_qa():
    decision = decide()
    assert decision.dispatch_once is True and decision.healer_calls == 1
    assert decision.changes_original_result is False and decision.reason == "same_target"


def test_assertion_unknown_and_changed_target_do_not_dispatch():
    assert decide(reason="text_mismatch").reason == "not_a_locator_failure"
    assert decide(product_violation=True).dispatch_once is False
    assert decide(dispatch_sent=True).reason == "already_sent"
    assert decide(already_used=True).dispatch_once is False
    assert decide(reserved_calls=0).reason == "episode_exhausted"
    assert decide(checkpoint=lambda: False).reason == "control_blocked"
    assert decide(proposal=proposal(candidate_action="type")).reason == "target_not_proven"
    assert decide(reason="ambiguous").dispatch_once is False
