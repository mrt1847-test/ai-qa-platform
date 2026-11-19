from dataclasses import replace
from types import SimpleNamespace
import pytest
from aiqa.worker.case_context import CaseStep
from aiqa.worker.check_binding_pin import WorkerCheckBindingPin
from aiqa.environments.android_hierarchy import AndroidHierarchy,AndroidHierarchyTarget
from test_rx87_check_coverage import model_job,pin_with_checks,recording,ux_app
from test_rx_34 import _replay,_observation


def loading_handler(tmp_path,monkeypatch,*,never=False,after_changing=False,signature=True):
    from test_rx_34 import _claim
    from aiqa.replay.android_plan import TypedAndroidAction
    from aiqa.replay.android_native_trace import NativeStep
    from aiqa.replay.readiness import readiness_condition
    from io import BytesIO
    from PIL import Image
    frame=_observation();buffer=BytesIO();Image.new('RGB',(100,200),'white').save(buffer,format='PNG')
    placeholder=replace(frame,png=buffer.getvalue())
    action=TypedAndroidAction('tap',x=25,y=50)
    ready=readiness_condition(frame.png,action) if signature else None
    source=SimpleNamespace(steps=(NativeStep('source',1,100,200,0,action,ready,.25),))
    monkeypatch.setattr('aiqa.worker.android_jobs.resolve_claim_native_source',lambda *a,**kw:source)
    handler,calls=_replay(tmp_path);clock=[0.0];reads=[]
    def capture():
        reads.append(len(calls))
        if never or len(reads)==1:return placeholder
        if after_changing and calls:return placeholder if len(reads)%2 else frame
        return frame
    handler.context.live_capture=capture;handler.context.before=handler.context.after=None
    handler.context.readiness_enabled=True;handler.context.readiness_timeout=1
    handler.context.readiness_clock=lambda:clock[0]
    handler.context.readiness_pause=lambda n:clock.__setitem__(0,clock[0]+n)
    return handler,calls,reads,clock,_claim()


def test_replay_waits_for_target_then_settles_without_repeating_tap(tmp_path,monkeypatch):
    handler,calls,reads,clock,job=loading_handler(tmp_path,monkeypatch)
    result=handler.handle(job)
    assert result.outcome=='completed' and result.actions==len(calls)==1
    assert reads[:2]==[0,0] and len(reads)>=5 and clock[0]>=1


def test_never_ready_stops_before_native_input(tmp_path,monkeypatch):
    handler,calls,reads,clock,job=loading_handler(tmp_path,monkeypatch,never=True)
    result=handler.handle(job)
    assert result.outcome=='error' and result.actions==0 and calls==[]
    assert handler.stopped_reason=='loading_timeout'


def test_after_loading_timeout_retains_known_single_dispatch(tmp_path,monkeypatch):
    handler,calls,reads,clock,job=loading_handler(tmp_path,monkeypatch,after_changing=True)
    result=handler.handle(job)
    assert result.outcome=='error' and result.actions==len(calls)==1
    assert not result.ambiguous_dispatch and handler.stopped_reason=='loading_timeout'


def test_cancel_while_loading_never_dispatches(tmp_path,monkeypatch):
    handler,calls,reads,clock,job=loading_handler(tmp_path,monkeypatch,never=True)
    handler.context.cancelled=lambda:clock[0]>=.25
    result=handler.handle(job)
    assert result.outcome=='cancelled' and result.actions==0 and calls==[]


def test_tap_without_a_stored_signature_still_waits_inside_the_action(tmp_path,monkeypatch):
    handler,calls,reads,clock,job=loading_handler(tmp_path,monkeypatch,signature=False)
    result=handler.handle(job)
    assert result.outcome=='completed' and result.actions==len(calls)==1
    assert reads[0]==0 and len(reads)>=3 and clock[0]>=.5


def test_managed_replay_evaluates_source_check_even_at_last_native_budget(model_job,tmp_path):
    job,pin=pin_with_checks(model_job['job'])
    handler,calls=_replay(tmp_path)
    handler.context.require_case_context=True
    handler._case_context=replace(pin,steps=())
    handler._check_binding_pin=WorkerCheckBindingPin('m','h',(),(('final-required','com.example.app:id/result'),))
    handler._native_source=SimpleNamespace(steps=(SimpleNamespace(action_id='source'),))
    # Checking a completed action is read-only; native input budget is already exhausted.
    handler.dispatch_count=handler.context.max_actions=1
    handler.context.hierarchy_observer=lambda **kw:SimpleNamespace(snapshot=AndroidHierarchy(0,(
        AndroidHierarchyTarget('com.example.app:id/result','available','Done'),)),captured_at=_observation().captured_at)
    result=handler._verify_and_heal(_observation(),action_index=1,total_actions=1)
    assert result.success and result.check_results[0].status=='satisfied'
    assert calls==[]


def test_managed_source_check_mismatch_is_failed_without_healing(model_job,tmp_path):
    _,pin=pin_with_checks(model_job['job'])
    handler,calls=_replay(tmp_path);handler.context.require_case_context=True
    handler._case_context=replace(pin,steps=())
    handler._check_binding_pin=WorkerCheckBindingPin('m','h',(),(('final-required','com.example.app:id/result'),))
    handler._native_source=SimpleNamespace(steps=(SimpleNamespace(action_id='source'),))
    handler.context.hierarchy_observer=lambda **kw:SimpleNamespace(snapshot=AndroidHierarchy(0,(
        AndroidHierarchyTarget('com.example.app:id/result','available','Wrong'),)),captured_at=_observation().captured_at)
    result=handler._verify_and_heal(_observation(),action_index=1,total_actions=1)
    assert not result.success and result.check_results[0].status=='violated'
    assert handler.healer_calls==0 and calls==[]


def test_screen_sentence_uses_visual_verification_without_a_resource(model_job,tmp_path):
    job,pin=pin_with_checks(model_job['job'],method='ai_visual')
    handler,calls=_replay(tmp_path);handler.context.require_case_context=True
    handler._case_context=replace(pin,steps=())
    handler._check_binding_pin=None
    handler._native_source=SimpleNamespace(steps=(SimpleNamespace(action_id='source'),))
    seen=[]
    class Client:
        def evaluate_replay_check(self,*,payload,idempotency_key):
            seen.append(payload['check_id'])
            return {'provider_dispatched':True,'replayed':False,'result':{'status':'satisfied','reason':'screen_match','observed_at':payload['captured_at']}}
    observation=_observation()
    handler.context.verification_client=Client()
    handler._current_after_artifact='after-1'
    handler._current_action_id='source'
    handler._active_claim=job
    from aiqa.contracts.jobs import ControlDecision
    handler.context.remote_checkpoint=lambda phase:ControlDecision(True,phase)
    result=handler._verify_and_heal(observation,action_index=1,total_actions=1)
    row=result.check_results[0]
    assert seen==['final-required'] and row.status=='satisfied' and row.method=='ai_visual'
    assert row.reason=='screen_match' and handler.verifier_calls==1
    assert handler.authoring_calls_seen==handler.healer_calls==0 and calls==[]
