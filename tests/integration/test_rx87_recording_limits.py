"""Frozen recording policy caps narrow worker defaults and never grow them."""
import pytest
from aiqa.worker.recording_limits import resolve_recording_limits
from aiqa.contracts.authoring import authoring_policy_ref


def snapshot(**caps):
    limits={'authoring_schema':'authoring-admission-v1','authoring_binding':{
        'binding_id':'binding','revision_id':'revision','revision':1,'role':'authoring',
        'content_hash':'hash','key_ref_id':'key','key_revision':1},
        'input_case_version_id':'version','input_version_hash':'saved-hash',
        'timeout_seconds':31,'max_actions':4,'max_model_calls':3,'budget':'0.7','currency':'USD'}
    limits.update(caps);limits['policy_ref']=authoring_policy_ref(limits)
    return {'purpose':'recording','limits':limits,'policy_ref':limits['policy_ref'],
        'intent':{'case_version_id':'version','content_hash':'saved-hash'}}


def test_claim_caps_narrow_worker_defaults_without_aliasing():
    saved=snapshot();budget=resolve_recording_limits(saved,worker_actions=50,worker_seconds=None)
    assert (budget.max_actions,budget.max_model_calls,budget.timeout_seconds)==(4,3,31)
    saved['limits']['max_actions']=50
    assert budget.max_actions==4
    local=resolve_recording_limits(snapshot(),worker_actions=2,worker_seconds=5)
    assert (local.max_actions,local.timeout_seconds)==(2,5)


@pytest.mark.parametrize('actions',[True,-1,51,1.5])
def test_invalid_worker_action_limit_cannot_bypass_caps(actions):
    with pytest.raises(ValueError):resolve_recording_limits(snapshot(),worker_actions=actions,worker_seconds=None)


@pytest.mark.parametrize('seconds',[True,0,-1,float('nan'),float('inf'),'5'])
def test_invalid_worker_time_limit_cannot_disable_pin(seconds):
    with pytest.raises(ValueError):resolve_recording_limits(snapshot(),worker_actions=50,worker_seconds=seconds)


def test_invalid_pin_is_not_legacy_and_zero_actions_stay_zero():
    bad=snapshot();bad['limits']['max_actions']=50
    with pytest.raises(ValueError):resolve_recording_limits(bad,worker_actions=50,worker_seconds=None)
    assert resolve_recording_limits(snapshot(max_actions=0),worker_actions=50,worker_seconds=None).max_actions==0
    assert resolve_recording_limits({'purpose':'recording'},worker_actions=50,worker_seconds=None) is None
