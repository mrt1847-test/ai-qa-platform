"""Frozen checks must not disappear behind worker fixture checks or PNG-only success."""
import copy,json,base64
from dataclasses import replace
import pytest
from aiqa.domain.hashing import canonical_hash
from aiqa.worker.case_context import resolve_claim_case_context
from test_rx98_model_requests import model_job,recording,ux_app


def pin_with_checks(job,*,method='deterministic'):
    job=copy.deepcopy(job);raw=job['snapshot']['case_context']
    raw['steps']=[{'id':'logical-one','instruction':'search and open','expected':[{'id':'step-required','kind':'text','expected':'Detail'}]}]
    raw['final_expected']=[{'id':'final-required','kind':'text','expected':'Done'}]
    raw['verification']=[{'method':method,'binding_id':'' if method=='deterministic' else 'saved-binding','allow_unknown_supplement':method=='deterministic_then_ai_unknown'}]
    raw['context_hash']=canonical_hash({k:v for k,v in raw.items() if k!='context_hash'},'canon-json-v1')
    return job,resolve_claim_case_context(job,required=True)


def test_required_checks_wait_for_final_action_and_preserve_missing_mapping(model_job):
    from aiqa.worker.replay_check_coverage import required_check_coverage
    _,pin=pin_with_checks(model_job['job'])
    assert required_check_coverage(pin,action_index=1,total_actions=2,observed_at='2026-11-15T00:00:00+09:00')==()
    rows=required_check_coverage(pin,action_index=2,total_actions=2,observed_at='2026-11-15T00:00:00+09:00')
    assert [(r.result.check_id,r.step_id,r.phase) for r in rows]==[('step-required','logical-one','step'),('final-required',None,'final')]
    assert all(r.result.status=='unknown' and r.context_hash==pin.context_hash for r in rows)
    assert rows[0].result.reason=='logical_step_mapping_missing'
    assert rows[1].result.reason=='deterministic_subject_missing'
    assert [r.result.expected_snapshot for r in rows]==['Detail','Done']


@pytest.mark.parametrize('method',['ai_visual','deterministic_then_ai_unknown'])
def test_source_verifier_configuration_is_not_a_model_grant(model_job,method):
    from aiqa.worker.replay_check_coverage import required_check_coverage
    _,pin=pin_with_checks(model_job['job'],method=method)
    rows=required_check_coverage(pin,action_index=1,total_actions=1,observed_at='2026-11-15T00:00:00+09:00')
    assert rows[-1].result.method==method and rows[-1].result.reason=='verifier_not_connected'
    assert all(r.result.status=='unknown' for r in rows)


@pytest.mark.parametrize('index,total',[(True,2),(0,2),(3,2),(1,False),(1,0),(1,51)])
def test_invalid_coverage_phase_cannot_claim_success(model_job,index,total):
    from aiqa.worker.replay_check_coverage import required_check_coverage
    _,pin=pin_with_checks(model_job['job'])
    with pytest.raises(ValueError):required_check_coverage(pin,action_index=index,total_actions=total,observed_at='2026-11-15T00:00:00+09:00')


def test_prepared_replay_cannot_drop_pinned_checks_behind_empty_fixture_tuple(model_job,tmp_path,monkeypatch):
    from test_rx87_case_context_consumer import _prepared_replay
    from aiqa.contracts.jobs import ControlDecision
    from aiqa.contracts.checks import CheckSpec
    handler,job,events=_prepared_replay(tmp_path,monkeypatch,model_job['job'])
    job,pin=pin_with_checks(job)
    # Worker-local fixture inputs must not override checks frozen in this claim.
    handler.context.checks=()
    handler.context.remote_checkpoint=lambda phase:ControlDecision(True,phase)
    result=handler.handle(job)
    assert result.actions==2 and result.outcome=='error'
    assert handler.stopped_reason=='check_failed'
    assert events.count('native')==2 and handler.authoring_calls_seen==handler.verifier_calls==handler.healer_calls==0
    assert [c.result.check_id for c in handler.check_coverage]==['step-required','final-required']
    logs=[base64.b64decode(a['body_b64']).decode() for a in result.evidence_artifacts if a['role']=='log']
    assert len(logs)==2 and 'verification=' not in logs[0]
    document=json.loads(logs[1].split('verification=',1)[1])
    assert [c['result']['check_id'] for c in document]==['step-required','final-required']
    assert all(c['context_hash']==pin.context_hash and c['result']['status']=='unknown' for c in document)


def test_next_invalid_claim_clears_previous_pinned_check_coverage(model_job,tmp_path,monkeypatch):
    from test_rx87_case_context_consumer import _prepared_replay
    from aiqa.contracts.jobs import ControlDecision
    handler,job,_=_prepared_replay(tmp_path,monkeypatch,model_job['job']);job,_=pin_with_checks(job)
    handler.context.remote_checkpoint=lambda phase:ControlDecision(True,phase)
    handler.handle(job)
    assert handler.check_coverage
    changed=copy.deepcopy(job);changed['attempt_id']='invalid'
    result=handler.handle(changed)
    assert result.actions==0 and handler.check_coverage==()


def test_unexecuted_last_action_does_not_evaluate_final_expected(model_job,tmp_path,monkeypatch):
    from test_rx87_case_context_consumer import _prepared_replay
    from aiqa.contracts.jobs import ControlDecision
    from test_rx_34 import _observation
    handler,job,events=_prepared_replay(tmp_path,monkeypatch,model_job['job']);job,_=pin_with_checks(job)
    handler.context.remote_checkpoint=lambda phase:ControlDecision(True,phase)
    captures=[]
    def capture():
        captures.append(1)
        if len(captures)==2:raise OSError('mock last frame lost')
        return _observation()
    handler.context.live_capture=capture
    result=handler.handle(job)
    assert result.ambiguous_dispatch and result.outcome=='error'
    assert events.count('native')==2 and handler.check_coverage==()
    logs=[base64.b64decode(a['body_b64']).decode() for a in result.evidence_artifacts if a['role']=='log']
    assert all('verification=' not in body for body in logs)


@pytest.mark.parametrize('stamp',['','2026-11-15T00:00:00',None,True])
def test_coverage_requires_known_aware_observation_time(model_job,stamp):
    from aiqa.worker.replay_check_coverage import required_check_coverage
    _,pin=pin_with_checks(model_job['job'])
    with pytest.raises(ValueError):required_check_coverage(pin,action_index=1,total_actions=1,observed_at=stamp)


def test_coverage_carries_stable_source_identity_for_accumulated_results(model_job):
    from aiqa.worker.replay_check_coverage import required_check_coverage
    _,pin=pin_with_checks(model_job['job'])
    rows=required_check_coverage(pin,action_index=1,total_actions=1,observed_at='2026-11-15T00:00:00+09:00')
    assert all(row.source_hash==pin.content_hash and row.case_version_id==pin.case_version_id and row.kind=='text' for row in rows)


@pytest.mark.parametrize('policies',[[],[{'method':'deterministic','binding_id':'','allow_unknown_supplement':False}]*2])
def test_missing_or_ambiguous_source_policy_cannot_become_default_verifier(model_job,policies):
    from aiqa.worker.replay_check_coverage import required_check_coverage
    job,_=pin_with_checks(model_job['job']);raw=job['snapshot']['case_context'];raw['verification']=policies
    raw['context_hash']=canonical_hash({k:v for k,v in raw.items() if k!='context_hash'},'canon-json-v1')
    pin=resolve_claim_case_context(job,required=True)
    rows=required_check_coverage(pin,action_index=1,total_actions=1,observed_at='2026-11-15T00:00:00+09:00')
    assert rows[-1].result.method=='unconfigured' and rows[-1].result.reason in {'verifier_policy_missing','verifier_policy_ambiguous'}


def test_durable_coverage_omits_expected_and_raw_observation_credentials(model_job,tmp_path,monkeypatch):
    from test_rx87_case_context_consumer import _prepared_replay
    from aiqa.contracts.jobs import ControlDecision
    from test_rx_34 import _observation
    handler,job,_=_prepared_replay(tmp_path,monkeypatch,model_job['job']);job,_=pin_with_checks(job)
    raw=job['snapshot']['case_context'];raw['final_expected'][0]['expected']='token=DEMO_SENTINEL'
    raw['context_hash']=canonical_hash({k:v for k,v in raw.items() if k!='context_hash'},'canon-json-v1')
    handler.context.live_capture=lambda:replace(_observation(),stdout='token=DEMO_SENTINEL')
    handler.context.remote_checkpoint=lambda phase:ControlDecision(True,phase)
    result=handler.handle(job)
    assert handler.check_coverage[-1].result.expected_snapshot=='token=DEMO_SENTINEL'
    log=base64.b64decode([p for p in result.evidence_artifacts if p['role']=='log'][-1]['body_b64']).decode()
    assert 'DEMO_SENTINEL' not in log


def test_coverage_log_fits_artifact_limit_for_large_source_expectation(model_job):
    from aiqa.worker.replay_check_coverage import required_check_coverage
    from aiqa.worker.android_jobs import android_evidence_artifacts
    from aiqa.store.artifacts import acceptable_size
    from test_rx_34 import _observation
    job,_=pin_with_checks(model_job['job']);raw=job['snapshot']['case_context'];raw['final_expected'][0]['expected']='x'*5_000_000
    raw['context_hash']=canonical_hash({k:v for k,v in raw.items() if k!='context_hash'},'canon-json-v1')
    pin=resolve_claim_case_context(job,required=True)
    rows=required_check_coverage(pin,action_index=1,total_actions=1,observed_at='2026-11-15T00:00:00+09:00')
    obs=_observation();parts=android_evidence_artifacts(attempt_id=job['attempt_id'],action_id='a1',before=obs,after=obs,owner_kind='ITEM',check_coverage=rows)
    body=base64.b64decode(parts[-1]['body_b64'])
    assert acceptable_size(len(body),body) and len(body)<65536


def test_invalid_final_timestamp_preserves_prior_evidence_without_escaping(model_job,tmp_path,monkeypatch):
    from test_rx87_case_context_consumer import _prepared_replay
    from aiqa.contracts.jobs import ControlDecision
    from test_rx_34 import _observation
    handler,job,events=_prepared_replay(tmp_path,monkeypatch,model_job['job']);job,_=pin_with_checks(job);captures=[]
    def capture():
        captures.append(1)
        return replace(_observation(),captured_at='' if len(captures)==2 else _observation().captured_at)
    handler.context.live_capture=capture;handler.context.remote_checkpoint=lambda phase:ControlDecision(True,phase)
    result=handler.handle(job)
    assert result.outcome=='error' and result.ambiguous_dispatch and result.actions==1
    assert result.final_seq==2 and len(result.evidence_artifacts)==3 and handler.check_coverage==()
    assert events.count('native')==2


@pytest.mark.parametrize('damage',['identifier','count'])
def test_unrepresentable_coverage_stops_before_app_or_gesture(model_job,tmp_path,monkeypatch,damage):
    from test_rx87_case_context_consumer import _prepared_replay
    from aiqa.contracts.jobs import ControlDecision
    handler,job,events=_prepared_replay(tmp_path,monkeypatch,model_job['job']);job,_=pin_with_checks(job)
    raw=job['snapshot']['case_context']
    if damage=='identifier':raw['final_expected'][0]['id']='x'*257
    else:raw['final_expected']=[{'id':'check-'+str(i),'kind':'text','expected':'x'} for i in range(257)]
    raw['context_hash']=canonical_hash({k:v for k,v in raw.items() if k!='context_hash'},'canon-json-v1')
    handler.context.remote_checkpoint=lambda phase:ControlDecision(True,phase)
    result=handler.handle(job)
    assert result.actions==0 and events==[] and handler.stopped_reason=='check_coverage_limits'
