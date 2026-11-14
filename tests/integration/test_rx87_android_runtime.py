"""Normal API-frozen pins are consumed by the Android handler, with explicit fake ADB/model."""
from uuid import uuid4
import copy
from aiqa.domain.hashing import canonical_hash
import pytest
from test_rx97_recording_pin import recording,ux_app,request as start,claim as get_claim
from test_rx_48 import _handler


@pytest.fixture
def job(recording):
    result=start(recording);assert result.status_code==201,result.text
    return get_claim(recording)



def new_attempt(job):
    # Explicit local fake claim: each independently owned context follows its new
    # attempt. Reusing a foreign context is now correctly rejected by production.
    claim=copy.deepcopy(job);attempt=str(uuid4());claim['attempt_id']=attempt
    claim['snapshot']['attempt_id']=attempt
    context=claim['snapshot'].get('case_context')
    if context is not None:
        context['attempt_id']=attempt
        context['context_hash']=canonical_hash({k:v for k,v in context.items() if k!='context_hash'},'canon-json-v1')
    return claim


def handler_for(tmp_path,job,calls):
    handler=_handler(tmp_path,calls,responses=('click(100,200)',)*10,steps=10,mono_seconds=None)
    serial=job['snapshot'].get('serial') or job['snapshot']['native_id']
    handler.context.expected_serial=serial;handler.driver.serial=serial
    return handler


@pytest.mark.parametrize('recording',[('max_actions',1)],indirect=True)
def test_claim_action_cap_stops_model_and_gesture_at_one(job,tmp_path):
    calls=[];handler=handler_for(tmp_path,job,calls)
    result=handler.handle(job)
    assert result.actions==len(calls)==1
    assert handler.authoring_calls_seen==1 and handler.stopped_reason=='action_budget'
    assert handler.context.max_actions==50 and handler.context.max_seconds is None


@pytest.mark.parametrize('recording',[('max_model_calls',2)],indirect=True)
def test_claim_model_cap_blocks_next_local_actor_even_with_action_room(job,tmp_path):
    calls=[];handler=handler_for(tmp_path,job,calls)
    result=handler.handle(job)
    assert result.actions==len(calls)==2
    assert handler.authoring_calls_seen==2 and handler.stopped_reason=='model_budget'


@pytest.mark.parametrize('recording',[('max_actions',0)],indirect=True)
def test_zero_action_cap_does_no_model_or_gesture(job,tmp_path):
    calls=[];handler=handler_for(tmp_path,job,calls)
    result=handler.handle(job)
    assert result.actions==0 and not calls
    assert handler.broker.authoring_calls==0


@pytest.mark.parametrize('change',['time','cancel','invalid_plan'])
def test_post_model_gate_prevents_unstarted_gesture_and_unknown_journal(job,tmp_path,monkeypatch,change):
    clock={'now':1000.0};calls=[];handler=handler_for(tmp_path,job,calls)
    monkeypatch.setattr('aiqa.worker.android_jobs.time.monotonic',lambda:clock['now'])
    def model(claim):
        if change=='time':clock['now']+=32
        elif change=='cancel':handler.context.cancelled=True
        return 'invalid_plan' if change=='invalid_plan' else 'click(100,200)'
    handler.context.plan_provider=model
    result=handler.handle(job)
    assert result.actions==0 and not calls
    assert result.ambiguous_dispatch is False
    states=handler.journal.states(f"rec-{job['attempt_id']}-1",job['attempt_id'])
    assert 'dispatch_started' not in states and 'unknown' not in states
    assert handler.stopped_reason=={'time':'time_budget','cancel':'cancelled','invalid_plan':'recording_rejected'}[change]


def test_invalid_pin_rejected_before_model_and_gesture(job,tmp_path):
    calls=[];handler=handler_for(tmp_path,job,calls)
    job['snapshot']['limits']['max_actions']=50
    result=handler.handle(job)
    assert result.actions==0 and not calls and handler.broker.authoring_calls==0


@pytest.mark.parametrize('recording',[('max_actions',1)],indirect=True)
def test_reused_handler_starts_fresh_time_and_counters_for_next_claim(job,tmp_path,monkeypatch):
    clock={'now':1000.0};calls=[];handler=handler_for(tmp_path,job,calls)
    monkeypatch.setattr('aiqa.worker.android_jobs.time.monotonic',lambda:clock['now'])
    def model(claim):clock['now']+=1;return 'click(100,200)'
    handler.context.plan_provider=model
    for _ in range(2):
        claim=new_attempt(job);clock['now']+=1000
        result=handler.handle(claim)
        assert result.actions==1 and handler.authoring_calls_seen==1
    assert len(calls)==2 and handler.context.max_actions==50


def test_model_http_failure_is_sealed_without_device_ambiguity(job,tmp_path):
    from aiqa.worker.http_client import WorkerHttpError,RetryClass
    calls=[];handler=handler_for(tmp_path,job,calls)
    def failed_model(claim):
        raise WorkerHttpError('mock model response lost',retry_class=RetryClass.timeout,
            provider_dispatched=True,reason='provider_timeout')
    handler.context.plan_provider=failed_model
    result=handler.handle(job)
    assert result.actions==0 and not calls and result.ambiguous_dispatch is False
    assert handler.stopped_reason=='model_request_failed'
    assert handler.journal.states(f"rec-{job['attempt_id']}-1",job['attempt_id'])==('planned',)


def test_actual_device_timeout_stays_unknown_and_never_reclicks(job,tmp_path):
    calls=[];handler=handler_for(tmp_path,job,calls)
    def timeout(argv,seconds):calls.append(tuple(argv));raise TimeoutError('mock device response lost')
    handler.driver._runner=timeout
    first=handler.handle(job)
    assert first.ambiguous_dispatch is True and len(calls)==1
    assert handler.journal.states(f"rec-{job['attempt_id']}-1",job['attempt_id'])[-1]=='unknown'
    second=handler.handle(job)
    assert second.actions==0 and second.ambiguous_dispatch is True and len(calls)==1


@pytest.mark.parametrize('recording',[('max_model_calls',80)],indirect=True)
def test_guard_counts_each_gesture_once_and_resets_for_new_attempt(job,tmp_path):
    from aiqa.contracts.authoring import authoring_policy_ref
    job['snapshot']['limits']['max_actions']=50
    job['snapshot']['limits']['policy_ref']=authoring_policy_ref(job['snapshot']['limits'])
    job['snapshot']['policy_ref']=job['snapshot']['limits']['policy_ref']
    from test_rx_48 import _observation
    calls=[];handler=handler_for(tmp_path,job,calls)
    handler.context.fixture_responses=('click(100,200)',)*30+('finish()',)
    handler.context.step_observations=tuple((_observation(),_observation()) for _ in range(31))
    for _ in range(2):
        result=handler.handle(new_attempt(job))
        assert result.actions==30 and result.outcome=='completed'
        assert handler.guard._runner.actions==30
    assert len(calls)==60


@pytest.mark.parametrize('phase',['journal_cancel','journal_time','spool_cancel','spool_time','spool_failure'])
def test_final_native_boundary_blocks_changes_during_blocking_io(job,tmp_path,monkeypatch,phase):
    from aiqa.replay.android_runner import AndroidDispatchError
    calls=[];handler=handler_for(tmp_path,job,calls);clock={'now':1000.0}
    monkeypatch.setattr('aiqa.worker.android_jobs.time.monotonic',lambda:clock['now'])
    append=handler.journal.append;sanitize=handler.driver._sanitize_to_spool
    def change():
        if phase.endswith('cancel'):handler.context.cancelled=True
        elif phase.endswith('time'):clock['now']+=32
        else:raise AndroidDispatchError('sanitize_failed')
    def journal(*args):
        result=append(*args)
        if args[-1]=='dispatch_started' and phase.startswith('journal'):change()
        return result
    def spool(*args,**kwargs):
        if phase.startswith('spool'):change()
        return sanitize(*args,**kwargs)
    monkeypatch.setattr(handler.journal,'append',journal)
    monkeypatch.setattr(handler.driver,'_sanitize_to_spool',spool)
    result=handler.handle(job)
    assert not calls and result.actions==0 and result.ambiguous_dispatch is False
    assert not handler.journal.is_ambiguous(job['attempt_id'],f"rec-{job['attempt_id']}-1")


def test_injected_clock_uses_claim_relative_elapsed_time(job,tmp_path):
    calls=[];handler=handler_for(tmp_path,job,calls);handler.context.mono_seconds=1000.0
    def model(claim):handler.context.mono_seconds+=32;return 'click(100,200)'
    handler.context.plan_provider=model
    result=handler.handle(job)
    assert not calls and result.actions==0 and handler.stopped_reason=='time_budget'
