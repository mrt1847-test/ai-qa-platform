"""Per-claim replay budgets and final native control, with explicit fake device."""
from uuid import uuid4
import pytest
from aiqa.contracts.jobs import ControlDecision
from test_rx_34 import _replay,_claim,_observation


def replay(tmp_path,steps=2):
    handler,calls=_replay(tmp_path)
    handler.context.approved_plan='\n'.join(['click(250, 500)']*steps)
    handler.context.step_observations=tuple((_observation(),_observation()) for _ in range(steps))
    claim=_claim(purpose='regression')
    claim['snapshot'].update(self_healing_enabled=False,
        limits={'max_actions':50,'max_model_calls':4,'timeout_seconds':30})
    return handler,calls,claim


def test_replay_uses_claim_action_cap_and_keeps_actor_zero(tmp_path):
    handler,calls,claim=replay(tmp_path)
    claim['snapshot']['limits']['max_actions']=1
    result=handler.handle(claim)
    assert result.actions==len(calls)==1 and handler.stopped_reason=='action_budget'
    assert handler.authoring_calls_seen==0 and handler.broker.authoring_calls==0


@pytest.mark.parametrize('boundary',['capture_time','spool_cancel','journal_time','remote'])
def test_replay_final_native_gate_blocks_changes_during_io(tmp_path,monkeypatch,boundary):
    handler,calls,claim=replay(tmp_path,1)
    handler.context.mono_seconds=100.0
    if boundary=='capture_time':
        handler.context.step_observations=()
        def capture():handler.context.mono_seconds+=32;return _observation()
        handler.context.live_capture=capture
    elif boundary=='spool_cancel':
        original=handler.driver._sanitize_to_spool
        def sanitize(*args,**kwargs):
            result=original(*args,**kwargs);handler.context.cancelled=True;return result
        monkeypatch.setattr(handler.driver,'_sanitize_to_spool',sanitize)
    elif boundary=='journal_time':
        original=handler.journal.append
        def append(*args):
            result=original(*args)
            if args[-1]=='dispatch_started':handler.context.mono_seconds+=32
            return result
        monkeypatch.setattr(handler.journal,'append',append)
    else:handler.context.remote_checkpoint=lambda phase:ControlDecision(False,'mock cancelled')
    result=handler.handle(claim)
    assert result.actions==0 and calls==[] and result.ambiguous_dispatch is False
    assert not handler.journal.is_ambiguous(claim['attempt_id'],'r1')


def test_replay_guard_and_time_restart_for_new_claim(tmp_path):
    handler,calls,claim=replay(tmp_path,30)
    for _ in range(2):
        claim={**claim,'attempt_id':str(uuid4())};handler.context.mono_seconds+=1
        result=handler.handle(claim)
        assert result.actions==30 and result.outcome=='completed'
    assert len(calls)==60 and handler.guard._runner.actions==30


def test_bad_healing_pin_never_reaches_replay_device(tmp_path):
    handler,calls,claim=replay(tmp_path,1)
    claim['snapshot']['self_healing_enabled']=True
    result=handler.handle(claim)
    assert result.actions==0 and calls==[] and handler.broker.authoring_calls==0


def test_replay_injected_clock_is_relative_to_each_claim(tmp_path):
    handler,calls,claim=replay(tmp_path,1);handler.context.mono_seconds=1000.0
    result=handler.handle(claim)
    assert result.actions==len(calls)==1 and result.outcome=='completed'


@pytest.mark.parametrize('field,value',[('max_actions',True),('max_actions',51),('max_model_calls',81),('max_model_calls',-1),('timeout_seconds',0),('timeout_seconds',float('nan')),('timeout_seconds',True)])
def test_bad_replay_cap_types_are_not_coerced(field,value):
    from aiqa.worker.replay_limits import resolve_replay_limits
    snapshot={'limits':{'max_actions':10,'max_model_calls':4,'timeout_seconds':30}}
    snapshot['limits'][field]=value
    with pytest.raises(ValueError):resolve_replay_limits(snapshot,worker_actions=50,worker_seconds=None)


def test_replay_caps_are_detached_and_worker_settings_only_narrow():
    from aiqa.worker.replay_limits import resolve_replay_limits
    snapshot={'limits':{'max_actions':10,'max_model_calls':4,'timeout_seconds':30}}
    caps=resolve_replay_limits(snapshot,worker_actions=2,worker_seconds=15)
    snapshot['limits']['max_actions']=1
    assert (caps.max_actions,caps.max_model_calls,caps.timeout_seconds)==(2,4,15)
    with pytest.raises((AttributeError,TypeError)):caps.max_actions=20
    assert resolve_replay_limits({'limits':{}},worker_actions=50,worker_seconds=None) is None


def test_replay_invalid_next_claim_does_not_keep_previous_claim_statistics(tmp_path):
    handler,calls,claim=replay(tmp_path,1)
    assert handler.handle(claim).actions==1
    invalid={**claim,'attempt_id':str(uuid4()),'snapshot':{**claim['snapshot'],'self_healing_enabled':True}}
    result=handler.handle(invalid)
    assert result.actions==0 and handler.dispatch_count==0 and handler.authoring_calls_seen==0
    assert handler.healer_calls==handler.verifier_calls==0 and len(calls)==1


def test_replay_after_capture_failure_is_unknown_and_never_reclicked(tmp_path):
    handler,calls,claim=replay(tmp_path,1);handler.context.step_observations=();seen=[]
    def capture():
        seen.append(1)
        if len(seen)>1:raise OSError('mock after capture lost')
        return _observation()
    handler.context.live_capture=capture
    first=handler.handle(claim)
    assert len(calls)==1 and first.ambiguous_dispatch is True and first.evidence_complete is False
    again=handler.handle(claim)
    assert again.actions==0 and again.ambiguous_dispatch is True and len(calls)==1


def test_runtime_binds_only_the_selected_android_route(tmp_path):
    from aiqa.worker.android_jobs import PurposeRoutedHandler
    from aiqa.worker.runtime import InertHandler,WorkerRuntime,WorkerRuntimeConfig
    from aiqa.worker.keepalive import WorkerAttemptKeepalive
    handler,calls,claim=replay(tmp_path,1)
    class Client:pass
    router=PurposeRoutedHandler({'trial':InertHandler(),'regression':handler})
    runtime=WorkerRuntime(Client(),WorkerRuntimeConfig('fixture-boot',frozenset({'trial','regression'})),router)
    other={**claim,'snapshot':{**claim['snapshot'],'purpose':'trial'}}
    assert runtime._bind_attempt_checkpoint(other) is None
    assert handler.context.remote_checkpoint is None
    control=runtime._bind_attempt_checkpoint(claim)
    assert isinstance(control,WorkerAttemptKeepalive)
    assert handler.context.remote_checkpoint.__self__ is control
    assert control.close() is True and calls==[]


@pytest.mark.parametrize('failure',['invalid_plan','spool','native_timeout'])
def test_replay_separates_unstarted_failures_from_real_native_unknown(tmp_path,monkeypatch,failure):
    import subprocess
    from aiqa.replay.android_runner import AndroidDispatchError
    handler,calls,claim=replay(tmp_path,1)
    if failure=='invalid_plan':handler.context.approved_plan='unrecognized()'
    elif failure=='spool':
        def refuse(*args,**kwargs):raise AndroidDispatchError('sanitize_failed')
        monkeypatch.setattr(handler.driver,'_sanitize_to_spool',refuse)
    else:
        def lost(argv,seconds):calls.append(tuple(argv));raise subprocess.TimeoutExpired(argv,seconds)
        monkeypatch.setattr(handler.driver,'_runner',lost)
    result=handler.handle(claim)
    assert result.ambiguous_dispatch is (failure=='native_timeout')
    assert len(calls)==(1 if failure=='native_timeout' else 0)
    if failure=='native_timeout':
        again=handler.handle(claim)
        assert again.ambiguous_dispatch is True and len(calls)==1


@pytest.mark.parametrize('purpose',['trial','regression'])
def test_explicit_off_claim_does_not_inherit_worker_healing_default(tmp_path,purpose):
    handler,calls,claim=replay(tmp_path,1);handler.context.healing_enabled=True
    claim['snapshot']['purpose']=purpose
    result=handler.handle(claim)
    assert result.outcome=='completed' and result.actions==1 and len(calls)==1
    assert handler.authoring_calls_seen==handler.healer_calls==handler.verifier_calls==0


from test_rx95_worker_healing_pin import healing_claim,admitted_healing,healing_execution,healing_metadata,ux_app


def test_valid_server_on_pin_is_explicitly_unavailable_until_episode_ports_exist(healing_claim,tmp_path):
    handler,calls=_replay(tmp_path)
    # This test never dispatches. Bind fixture serial only to reach policy validation;
    # it is not Android target/native acceptance of this server fixture.
    healing_claim['snapshot']['serial']=handler.context.expected_serial
    result=handler.handle(healing_claim)
    assert result.actions==0 and result.outcome=='error' and calls==[]
    assert handler.stopped_reason=='healing_runtime_unavailable'
    assert handler._healing_pin.enabled is True and handler._healing_pin.policy.effective_limits['max_model_calls_per_item']==1
