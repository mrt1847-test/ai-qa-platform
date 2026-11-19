"""Saved check boundaries are evaluated on the claimed package, without an ordinal guess."""
import base64,hashlib,json
from uuid import UUID
import pytest
from aiqa.contracts.checks import CheckSpec
from aiqa.contracts.jobs import ControlDecision
from aiqa.domain.hashing import canonical_hash
from aiqa.environments.android_hierarchy import AndroidHierarchy,AndroidHierarchyTarget
from test_rx87_check_binding_pin import claim_for
from test_rx87_check_bindings import recorded,ux_app
from test_rx_34 import _geometry,_observation,_replay


def prepared(recorded,tmp_path,*,verification=None,extra_steps=(),final=None,bindings=None,limits=None):
    job=claim_for(recorded);raw=job['snapshot']['case_context']
    if verification is not None:raw['verification']=verification
    if extra_steps:raw['steps'].extend(extra_steps)
    if final is not None:raw['final_expected']=final
    if bindings is not None:
        from aiqa.recording.check_bindings import validate_bindings
        from aiqa.replay.android_native_trace import compile_native_source,parse_native_trace
        from aiqa.store.models import RecordingManifest
        witness=job['snapshot']['native_source']
        actions=tuple(step.action_id for step in parse_native_trace(witness['mapping']))
        document=validate_bindings(bindings,definition={'steps':raw['steps'],'final_expected':raw['final_expected']},
            settings={'target_kind':'android','android_package':raw['target']['android_package']},action_ids=actions)
        annotation=raw['check_bindings'];annotation['bindings']=document.to_document()
        annotation['binding_hash']=canonical_hash(document.to_document(),'canon-json-v1')
        annotation['manifest_hash']=canonical_hash({'kind':'package_rebuild','origin':'check-bindings-v1',
            'prior_manifest_id':annotation['source_manifest_id'],'prior_hash':annotation['source_manifest_hash'],
            'recording_id':annotation['recording_id'],'input_version':annotation['input_case_version_id'],
            'content_hash':annotation['source_content_hash'],'binding_hash':annotation['binding_hash']},'canon-json-v1')
        witness['source_manifest_hash']=annotation['manifest_hash']
        model=RecordingManifest(UUID(witness['project_id']),UUID(int=0),UUID(int=0),UUID(annotation['manifest_id']),
            1,'original',None,'',json.dumps([hashlib.sha256(witness['mapping'].encode()).hexdigest()]),
            witness['mapping'],'complete','native-claim',annotation['manifest_hash'])
        digest=compile_native_source(model).body_hash
        witness['package_hash']=job['snapshot']['replay_package_hash']=job['snapshot']['approved_digest']=digest
        raw['replay_package_hash']=digest
    raw['context_hash']=canonical_hash({k:v for k,v in raw.items() if k!='context_hash'},'canon-json-v1')
    handler,calls=_replay(tmp_path,digest=job['snapshot']['replay_package_hash'])
    handler.context.require_case_context=True
    handler.context.remote_checkpoint=lambda phase:ControlDecision(True,phase)
    handler.context.checks=(CheckSpec('c1','text','FIXTURE_SHOULD_NOT_APPLY'),)
    job['snapshot']['serial']=handler.context.expected_serial
    frame=_observation(geometry=_geometry(physical=(1000,2000),model=(500,1000)))
    pngs=[]
    def capture():
        pngs.append(1);return frame
    handler.context.live_capture=capture;handler.context.before=handler.context.after=None
    if limits is not None:
        job['snapshot']['limits']=limits;handler.context.max_actions=limits['max_actions']
    return handler,job,calls,pngs


def deterministic():
    return [{'method':'deterministic','binding_id':'','allow_unknown_supplement':False}]


def observe(handler,targets):
    reads=[]
    def read(**kwargs):
        kwargs['checkpoint']();reads.append((handler.dispatch_count,tuple(kwargs['resource_ids']),kwargs['timeout']))
        rows=tuple(targets.get(resource,AndroidHierarchyTarget(resource,'missing')) for resource in kwargs['resource_ids'])
        return type('Obs',(),{'snapshot':AndroidHierarchy(0,rows),'captured_at':_observation().captured_at})()
    handler.context.hierarchy_observer=read
    return reads


def test_unapproved_policy_keeps_required_unknown_and_does_not_read(recorded,tmp_path):
    handler,job,calls,pngs=prepared(recorded,tmp_path)
    reads=observe(handler,{});result=handler.handle(job)
    assert reads==[] and result.outcome=='error' and result.actions==len(calls)==5
    assert handler.stopped_reason=='check_failed'
    assert [row.result.reason for row in handler.check_coverage]==['verifier_policy_missing','verifier_policy_missing']
    assert handler.authoring_calls_seen==handler.verifier_calls==handler.healer_calls==0


def test_claim_evaluates_only_the_saved_boundary_and_preserves_unmapped_required(recorded,tmp_path):
    handler,job,calls,pngs=prepared(recorded,tmp_path,verification=deterministic(),extra_steps=(
        {'id':'s3','instruction':'leftover','expected':[{'id':'loose','kind':'text','expected':'kept'}]},))
    reads=observe(handler,{'com.example.app:id/query':AndroidHierarchyTarget('com.example.app:id/query','available','mouse')})
    result=handler.handle(job)
    assert result.outcome=='error' and result.actions==len(calls)==5 and len(pngs)==6
    assert handler.stopped_reason=='check_failed'
    assert [len(reads[i][1]) for i in range(len(reads))]==[1]
    assert reads[0][0]==2 and reads[0][1]==('com.example.app:id/query',) and reads[0][2]<=30
    rows=[(item['action_id'][-1],item['result']['check_id'],item['result']['status'],item['result']['reason'])
        for item in result.check_results]
    assert rows==[('2','c1','satisfied','exact_text_match'),
        ('5','loose','unknown','logical_step_mapping_missing'),
        ('5','final','unknown','deterministic_subject_missing')]
    assert handler.check_coverage[0].result.expected_snapshot=='mouse'
    assert handler.check_coverage[0].source_hash==job['snapshot']['case_context']['content_hash']
    logs=[base64.b64decode(item['body_b64']).decode() for item in result.evidence_artifacts if item['role']=='log']
    assert 'mouse' not in ''.join(logs) and 'kept' not in ''.join(logs) and 'FIXTURE_SHOULD_NOT_APPLY' not in ''.join(logs)
    assert '[source expectation omitted]' in logs[1] and 'verification=' not in logs[0]
    assert handler.authoring_calls_seen==handler.verifier_calls==handler.healer_calls==handler.broker.authoring_calls==0


def test_text_contradiction_stops_without_healing_or_a_later_pass(recorded,tmp_path):
    handler,job,calls,pngs=prepared(recorded,tmp_path,verification=deterministic())
    observe(handler,{'com.example.app:id/query':AndroidHierarchyTarget('com.example.app:id/query','available','other')})
    result=handler.handle(job)
    assert result.outcome=='error' and result.actions==len(calls)==2 and len(pngs)==3
    assert handler.stopped_reason=='check_failed'
    assert [(item['result']['check_id'],item['result']['status'],item['result']['latch']) for item in result.check_results]==[
        ('c1','violated','FAIL')]
    assert 'other' not in result.check_results[0]['result']['reason']
    assert handler.healer_calls==handler.verifier_calls==0


@pytest.mark.parametrize('status',['ambiguous','redacted','unavailable'])
def test_unreadable_target_stays_unknown_without_a_pass(recorded,tmp_path,status):
    handler,job,calls,_=prepared(recorded,tmp_path,verification=deterministic())
    observe(handler,{'com.example.app:id/query':AndroidHierarchyTarget('com.example.app:id/query',status,text='secret')})
    result=handler.handle(job)
    assert result.outcome=='error' and result.actions==len(calls)==5
    assert result.check_results[0]['result']['status']=='unknown'
    assert result.check_results[0]['result']['reason']=='target_'+status
    assert 'secret' not in json.dumps(result.check_results)
    assert handler.healer_calls==0


def test_cancel_before_the_bound_action_does_not_invent_success(recorded,tmp_path):
    handler,job,calls,pngs=prepared(recorded,tmp_path,verification=deterministic())
    reads=observe(handler,{'com.example.app:id/query':AndroidHierarchyTarget('com.example.app:id/query','available','mouse')})
    def capture():
        pngs.append(1)
        if len(pngs)>=2:handler.context.cancelled=True
        return _observation(geometry=_geometry(physical=(1000,2000),model=(500,1000)))
    handler.context.live_capture=capture
    result=handler.handle(job)
    assert result.outcome=='cancelled' and result.actions==1 and calls and reads==[]
    assert all(item['result']['status']!='satisfied' for item in result.check_results)


def test_exhausted_native_budget_still_allows_the_final_read(recorded,tmp_path):
    bindings={'step_boundaries':[{'step_id':'s1','after_action_id':'a2'},{'step_id':'s2','after_action_id':'a3'}],
        'check_targets':[{'check_id':'c1','resource_id':'com.example.app:id/query'},
            {'check_id':'final','resource_id':'com.example.app:id/button'}]}
    handler,job,calls,pngs=prepared(recorded,tmp_path,verification=deterministic(),
        final=[{'id':'final','kind':'state','expected':'enabled=true'}],bindings=bindings,
        limits={'max_actions':5,'max_model_calls':0,'timeout_seconds':9})
    reads=observe(handler,{
        'com.example.app:id/query':AndroidHierarchyTarget('com.example.app:id/query','available','mouse'),
        'com.example.app:id/button':AndroidHierarchyTarget('com.example.app:id/button','available',enabled=True)})
    result=handler.handle(job)
    assert result.outcome=='completed' and result.actions==len(calls)==5 and len(pngs)==6
    assert handler.stopped_reason=='' and handler.dispatch_count==5
    assert [item[0] for item in reads]==[2,5]
    assert reads[-1][1]==('com.example.app:id/button',) and reads[-1][2]<=9
    assert [item['result']['status'] for item in result.check_results]==['satisfied','satisfied']
    assert handler.verifier_calls==handler.healer_calls==handler.broker.authoring_calls==0


def test_earlier_unknown_is_not_cleared_by_a_later_satisfied_check(recorded,tmp_path):
    bindings={'step_boundaries':[{'step_id':'s1','after_action_id':'a2'},{'step_id':'s2','after_action_id':'a3'}],
        'check_targets':[{'check_id':'c1','resource_id':'com.example.app:id/query'},
            {'check_id':'final','resource_id':'com.example.app:id/button'}]}
    handler,job,calls,_=prepared(recorded,tmp_path,verification=deterministic(),
        final=[{'id':'final','kind':'state','expected':'enabled=true'}],bindings=bindings,
        limits={'max_actions':5,'max_model_calls':0,'timeout_seconds':9})
    observe(handler,{
        'com.example.app:id/query':AndroidHierarchyTarget('com.example.app:id/query','ambiguous',text='mouse'),
        'com.example.app:id/button':AndroidHierarchyTarget('com.example.app:id/button','available',enabled=True)})
    result=handler.handle(job)
    assert result.outcome=='error' and result.actions==len(calls)==5
    assert [item['result']['status'] for item in result.check_results]==['unknown','satisfied']
    assert handler.stopped_reason=='check_failed'


def test_final_state_mismatch_at_the_action_ceiling_is_not_healed(recorded,tmp_path):
    bindings={'step_boundaries':[{'step_id':'s1','after_action_id':'a2'},{'step_id':'s2','after_action_id':'a3'}],
        'check_targets':[{'check_id':'c1','resource_id':'com.example.app:id/query'},
            {'check_id':'final','resource_id':'com.example.app:id/button'}]}
    handler,job,calls,_=prepared(recorded,tmp_path,verification=deterministic(),
        final=[{'id':'final','kind':'state','expected':'enabled=true'}],bindings=bindings,
        limits={'max_actions':5,'max_model_calls':0,'timeout_seconds':9})
    observe(handler,{
        'com.example.app:id/query':AndroidHierarchyTarget('com.example.app:id/query','available','mouse'),
        'com.example.app:id/button':AndroidHierarchyTarget('com.example.app:id/button','available',enabled=False)})
    result=handler.handle(job)
    assert result.outcome=='error' and result.actions==len(calls)==5
    assert result.check_results[-1]['result']['status']=='violated'
    assert result.check_results[-1]['result']['latch']=='FAIL'
    assert handler.healer_calls==handler.verifier_calls==0
