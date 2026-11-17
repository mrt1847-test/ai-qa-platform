"""Exact immutable annotation reaches replay workers without granting verification."""
import copy,json
from dataclasses import FrozenInstanceError
from uuid import uuid4
import pytest
from aiqa.domain.hashing import canonical_hash
from test_rx87_check_bindings import recorded,ux_app,save,PAYLOAD
from aiqa.replay.packages import resolve_claim_package_pin


def claim_for(r):
    from aiqa.recording.check_bindings import load_runtime_check_binding_pin
    with r['store'].transaction() as c:
        receipt=save(c,r)
        digest=c.execute('SELECT body_hash FROM replay_packages WHERE project_id=? AND package_id=?',(str(r['project']),receipt['replay_package_id'])).fetchone()[0]
        package=resolve_claim_package_pin(c,str(r['project']),package_id=receipt['replay_package_id'],package_hash=digest,purpose='trial')
        row=c.execute('SELECT content_hash,verification_digest,definition_json FROM case_versions WHERE project_id=? AND version_id=?',(str(r['project']),receipt['case_version_id'])).fetchone()
        annotation=load_runtime_check_binding_pin(c,r['project'],receipt['replay_package_id'])
    job,attempt,owner=(str(uuid4()) for _ in range(3));definition=json.loads(row[2])
    def checks(values):return [{k:v[k] for k in ('id','kind','expected')} for v in values]
    context={'schema':'case-context-v1','project_id':str(r['project']),'job_id':job,'attempt_id':attempt,'generation':1,'purpose':'trial',
        'owner_kind':'ITEM','owner_id':owner,'case_id':r['case'],'case_version_id':receipt['case_version_id'],
        'content_hash':row[0],'verification_digest':row[1],'replay_package_id':package.package_id,'replay_package_hash':package.package_hash,
        'replay_compiler_ref':'android-native-plan-v2','objective':definition['objective'],'preconditions':[],
        'steps':[{'id':s['id'],'instruction':s['instruction'],'expected':checks(s['expected'])} for s in definition['steps']],'final_expected':checks(definition['final_expected']),'path_policy':{'must_use':[],'forbidden':[]},
        'secret_refs':{},'target_secret_refs':{},'target':{'kind':'android','android_package':'com.example.app'},'verification':[],
        'check_bindings':annotation}
    context['context_hash']=canonical_hash(context,'canon-json-v1')
    return {'project_id':str(r['project']),'job_id':job,'attempt_id':attempt,'generation':1,'snapshot':{
        'purpose':'trial','job_id':job,'attempt_id':attempt,'revision_ref':'case_run:'+owner,'case_context':context,
        'approved_plan':package.approved_plan,'replay_package_id':package.package_id,'replay_package_hash':package.package_hash,
        'native_source':package.native_source,'self_healing_enabled':False}}


def resolve(job):
    from aiqa.worker.case_context import resolve_claim_case_context
    from aiqa.worker.native_source import resolve_claim_native_source
    from aiqa.worker.check_binding_pin import resolve_claim_check_binding_pin
    context=resolve_claim_case_context(job,required=True)
    return resolve_claim_check_binding_pin(job,case_context=context,native_source=resolve_claim_native_source(job,case_context=context))


def test_server_projects_only_the_exact_package_annotation_and_preserves_old_pin(recorded):
    from aiqa.recording.check_bindings import load_runtime_check_binding_pin
    r=recorded
    with r['store'].transaction() as c:
        original=c.execute('SELECT package_id FROM replay_packages WHERE source_manifest_id=?',(str(r['manifest']),)).fetchone()[0]
        one=save(c,r);frozen=load_runtime_check_binding_pin(c,r['project'],one['replay_package_id'])
        assert frozen['bindings']==PAYLOAD and frozen['manifest_id']==one['manifest_id']
        assert frozen['input_case_version_id']==r['input_version']
        assert load_runtime_check_binding_pin(c,r['project'],original) is None
        assert load_runtime_check_binding_pin(c,uuid4(),one['replay_package_id']) is None
        changed=copy.deepcopy(PAYLOAD);changed['step_boundaries'][0]['after_action_id']='a1'
        save(c,r,expected_manifest_id=one['manifest_id'],expected_manifest_hash=one['manifest_hash'],bindings=changed,request_key='next')
        assert load_runtime_check_binding_pin(c,r['project'],one['replay_package_id'])==frozen
        assert 'expected' not in json.dumps(frozen) and 'iphone' not in json.dumps(frozen)


def test_worker_pin_is_detached_and_is_not_a_model_or_pass_grant(recorded):
    job=claim_for(recorded);pin=resolve(job)
    assert pin.boundaries==(('s1','a2'),('s2','a3'))
    assert pin.targets==(('c1','com.example.app:id/query'),)
    job['snapshot']['case_context']['check_bindings']['bindings']['step_boundaries'][0]['after_action_id']='a1'
    assert pin.boundaries[0]==('s1','a2')
    with pytest.raises((FrozenInstanceError,AttributeError)):pin.binding_hash='changed'


@pytest.mark.parametrize('damage',['null','extra','manifest','manifest_hash','prior','input','binding_hash','boundary','target','missing_native'])
def test_invalid_binding_stops_replay_before_any_native_or_model(recorded,tmp_path,damage):
    from test_rx_34 import _replay
    job=claim_for(recorded);raw=job['snapshot']['case_context']['check_bindings']
    if damage=='null':job['snapshot']['case_context']['check_bindings']=None
    elif damage=='extra':raw['model_permission']=True
    elif damage=='manifest':raw['manifest_id']=str(uuid4())
    elif damage=='manifest_hash':raw['manifest_hash']='changed'
    elif damage=='prior':raw['source_manifest_id']=str(uuid4())
    elif damage=='input':raw['input_case_version_id']=str(uuid4())
    elif damage=='binding_hash':raw['binding_hash']='changed'
    elif damage=='boundary':raw['bindings']['step_boundaries'][0]['after_action_id']='foreign'
    elif damage=='target':raw['bindings']['check_targets'][0]['resource_id']='other.app:id/query'
    else:job['snapshot'].pop('native_source')
    context=job['snapshot']['case_context'];context['context_hash']=canonical_hash({k:v for k,v in context.items() if k!='context_hash'},'canon-json-v1')
    handler,calls=_replay(tmp_path,digest=job['snapshot']['replay_package_hash']);handler.context.require_case_context=True
    job['snapshot']['serial']=handler.context.expected_serial
    result=handler.handle(job)
    assert result.actions==0 and calls==[]
    assert handler.stopped_reason=={'null':'case_context_invalid','missing_native':'native_source_invalid'}.get(damage,'check_bindings_invalid')
    assert handler.healer_calls==handler.verifier_calls==handler.broker.authoring_calls==0


def test_valid_binding_reaches_replay_without_granting_a_pass_and_next_claim_clears_it(recorded,tmp_path):
    from test_rx_34 import _replay,_geometry,_observation
    from aiqa.contracts.jobs import ControlDecision
    job=claim_for(recorded);handler,calls=_replay(tmp_path,digest=job['snapshot']['replay_package_hash'])
    handler.context.require_case_context=True;job['snapshot']['serial']=handler.context.expected_serial
    handler.context.remote_checkpoint=lambda phase:ControlDecision(True,phase)
    obs=_observation(geometry=_geometry(physical=(1000,2000),model=(500,1000)))
    handler.context.step_observations=tuple((obs,obs) for _ in range(5))
    result=handler.handle(job)
    assert handler._check_binding_pin.boundaries==(('s1','a2'),('s2','a3'))
    assert result.actions==len(calls)==5
    assert result.outcome!='completed' and any(row.result.status=='unknown' for row in handler.check_coverage)
    assert handler.healer_calls==handler.verifier_calls==handler.broker.authoring_calls==0
    bad=copy.deepcopy(job);bad['snapshot']['case_context']['context_hash']='changed'
    assert handler.handle(bad).actions==0
    assert handler._check_binding_pin is None and handler.check_coverage==() and len(calls)==5


def test_detached_native_witness_cannot_be_swapped_for_later_annotation(recorded):
    from aiqa.recording.check_bindings import load_runtime_check_binding_pin
    from aiqa.worker.case_context import resolve_claim_case_context
    from aiqa.worker.native_source import resolve_claim_native_source
    from aiqa.worker.check_binding_pin import resolve_claim_check_binding_pin
    r=recorded;job=claim_for(r);context=resolve_claim_case_context(job,required=True)
    native=resolve_claim_native_source(job,case_context=context)
    first=job['snapshot']['case_context']['check_bindings']
    changed=copy.deepcopy(PAYLOAD);changed['step_boundaries'][0]['after_action_id']='a1'
    with r['store'].transaction() as c:
        two=save(c,r,expected_manifest_id=first['manifest_id'],expected_manifest_hash=first['manifest_hash'],bindings=changed,request_key='second')
        second=load_runtime_check_binding_pin(c,r['project'],two['replay_package_id'])
    raw=job['snapshot']['case_context'];raw['check_bindings']=second
    raw['context_hash']=canonical_hash({k:v for k,v in raw.items() if k!='context_hash'},'canon-json-v1')
    context=resolve_claim_case_context(job,required=True)
    job['snapshot']['native_source']['source_manifest_id']=second['manifest_id']
    job['snapshot']['native_source']['source_manifest_hash']=second['manifest_hash']
    with pytest.raises(ValueError):resolve_claim_check_binding_pin(job,case_context=context,native_source=native)


def test_web_context_never_accepts_android_annotation(recorded):
    from aiqa.worker.case_context import resolve_claim_case_context,CaseContextRejected
    job=claim_for(recorded);raw=job['snapshot']['case_context'];raw['target']={'kind':'web','android_package':''}
    raw['context_hash']=canonical_hash({k:v for k,v in raw.items() if k!='context_hash'},'canon-json-v1')
    with pytest.raises(CaseContextRejected):resolve_claim_case_context(job,required=True)


def large_inputs(unicode_ids):
    from aiqa.contracts.cases import CheckSpec
    from aiqa.worker.case_context import CaseStep
    steps=[];targets=[];boundaries=[];typed=[]
    for i in range(256):
        step='s'+str(i).zfill(3)+('한'*20 if unicode_ids else 's'*71)
        check='c'+str(i).zfill(3)+('한'*79 if unicode_ids else 'c'*242)
        expected={'id':check,'kind':'text','expected':'Ready'}
        steps.append({'id':step,'instruction':'inspect','expected':[expected]})
        typed.append(CaseStep(step,'inspect',(CheckSpec(check,'text','Ready'),)))
        boundaries.append({'step_id':step,'after_action_id':'a1'})
        targets.append({'check_id':check,'resource_id':'com.example.app:id/'+'r'*96})
    bindings={'step_boundaries':boundaries,'check_targets':targets}
    return steps,bindings,typed


@pytest.mark.parametrize('unicode_ids',[False,True])
def test_valid_near_limit_document_is_not_rejected_by_envelope_or_json_escaping(unicode_ids):
    from dataclasses import replace
    from aiqa.contracts.cases import CheckSpec
    from aiqa.worker.case_context import WorkerCaseContext,CaseStep,CaseTarget
    from aiqa.worker.native_source import resolve_claim_native_source
    from aiqa.worker.check_binding_pin import resolve_claim_check_binding_pin
    from aiqa.replay.android_native_trace import native_source_document,compile_native_source,physical_plan,parse_native_trace,COMPILER
    from test_rx87_native_trace import native_manifest
    source=native_manifest();steps,bindings,typed=large_inputs(unicode_ids)
    assert 120000<len(json.dumps(bindings,ensure_ascii=False,separators=(',',':')).encode('utf-8'))<131072
    annotation={'schema':'recording-check-binding-pin-v1','recording_id':str(source.recording_id),
        'manifest_id':str(uuid4()),'source_manifest_id':str(source.manifest_id),'source_manifest_hash':source.body_hash,
        'input_case_version_id':str(uuid4()),'source_content_hash':'source-hash','binding_hash':canonical_hash(bindings,'canon-json-v1'),'bindings':bindings}
    annotation['manifest_hash']=canonical_hash({'kind':'package_rebuild','origin':'check-bindings-v1',
        'prior_manifest_id':annotation['source_manifest_id'],'prior_hash':annotation['source_manifest_hash'],
        'recording_id':annotation['recording_id'],'input_version':annotation['input_case_version_id'],
        'content_hash':annotation['source_content_hash'],'binding_hash':annotation['binding_hash']},'canon-json-v1')
    from uuid import UUID
    source=replace(source,manifest_id=UUID(annotation['manifest_id']),body_hash=annotation['manifest_hash'])
    package=str(uuid4());digest=compile_native_source(source).body_hash
    context={'purpose':'trial','replay_package_id':package,'replay_package_hash':digest,'steps':steps,'final_expected':[], 'check_bindings':annotation}
    pin=WorkerCaseContext(str(uuid4()),'source-hash','inspect',CaseTarget('android','com.example.app'),tuple(typed),(), 'context',json.dumps(context),COMPILER)
    claim={'project_id':str(source.project_id),'snapshot':{'purpose':'trial','replay_package_id':package,'replay_package_hash':digest,
        'approved_plan':physical_plan(parse_native_trace(source.action_mapping)),'native_source':native_source_document(source.project_id,package,digest,source)}}
    native=resolve_claim_native_source(claim,case_context=pin)
    result=resolve_claim_check_binding_pin(claim,case_context=pin,native_source=native)
    assert len(result.boundaries)==len(result.targets)==256


def test_actual_trial_claim_carries_its_candidate_annotation(recorded):
    import asyncio,httpx
    from datetime import datetime,timezone
    from aiqa.api.auth import bound_auth_store,enroll_worker
    from worker_presence_support import seed_presence
    from ux_support import session
    from acceptance.test_w17 import _selection
    r=recorded;project=str(r['project']);worker='binding-pin-worker'
    resource,environment=(str(uuid4()) for _ in range(2))
    with bound_auth_store(r['store']):token=enroll_worker(r['actor'],worker,'trial')
    with r['store'].transaction() as c:
        saved=save(c,r)
        c.execute('INSERT INTO physical_resource_keys(physical_key_id,worker_id,native_id) VALUES(?,?,?)',(resource,worker,'emulator-5580'))
        c.execute("INSERT INTO resource_aliases(project_id,physical_key_id,display_name,target_kind) VALUES(?,?,'Android','android')",(project,resource))
        seed_presence(c,project,worker)
        c.execute("INSERT INTO resource_inventory(physical_key_id,state,os_build,geometry,permissions,ime,observed_at) VALUES(?,'ready','','','[]','','2026-11-17')",(resource,))
        c.execute("INSERT INTO environments(project_id,environment_id,name,next_revision,latest_revision_id) VALUES(?,'pin-env','Local',2,?)",(project,environment))
        c.execute("INSERT INTO environment_revisions(project_id,environment_id,revision_id,revision,body_json,content_hash,actor_id,created_at) VALUES(?,'pin-env',?,1,'{}','env-hash','actor','2026-11-17T00:00:00+00:00')",(project,environment))
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=r['app']),base_url='http://127.0.0.1') as client:
            headers=await session(client,project);body=_selection(saved['case_version_id'],environment,resource,False)
            preview=await client.post(f'/api/v1/projects/{project}/execution-previews',json=body,headers=headers)
            assert preview.status_code==200 and preview.json()['ready'],preview.text
            request={**body,'preview_hash':preview.json()['preview_hash'],'items':preview.json()['resolved_items']};request.pop('selection')
            admitted=await client.post(f'/api/v1/projects/{project}/executions',json=request,headers={**headers,'Idempotency-Key':'binding-trial'})
            assert admitted.status_code==201,admitted.text
            claim=await client.post('/api/v1/worker/claims',json={'project_id':project,'boot_id':'fixture-boot','now':datetime.now(timezone.utc).isoformat()},headers={'Authorization':'Bearer '+token,'Idempotency-Key':'binding-claim'})
            assert claim.status_code==200,claim.text
            job=claim.json();raw=job['snapshot']['case_context']['check_bindings']
            assert raw['manifest_id']==saved['manifest_id'] and raw['bindings']==PAYLOAD
            pin=resolve(job);assert pin.manifest_id==saved['manifest_id']
    asyncio.run(run())
    with r['store'].transaction() as c:assert c.execute('SELECT COUNT(*) FROM approval_events').fetchone()[0]==0


@pytest.mark.parametrize('unicode_ids',[False,True])
def test_saved_large_annotation_uses_the_same_projection_byte_budget(request,monkeypatch,unicode_ids):
    import test_rx87_check_bindings as fixtures
    from aiqa.recording.check_bindings import load_runtime_check_binding_pin
    steps,bindings,_=large_inputs(unicode_ids)
    monkeypatch.setattr(fixtures,'DEF',{'steps':steps,'final_expected':[]})
    r=request.getfixturevalue('recorded')
    with r['store'].transaction() as c:
        receipt=save(c,r,bindings=bindings)
        projected=load_runtime_check_binding_pin(c,r['project'],receipt['replay_package_id'])
        assert projected['bindings']==bindings


def test_oversized_canonical_binding_document_is_rejected_before_candidate_storage():
    from aiqa.recording.check_bindings import validate_bindings,BindingRejected
    steps,bindings,_=large_inputs(False)
    for item in bindings['check_targets']:item['resource_id']='com.example.app:id/'+'r'*127
    for step,boundary in zip(steps,bindings['step_boundaries']):
        step['id']=boundary['step_id']='s'+step['id']+'s'*100
    # Each identity/target is legal in isolation; the combined document is too big.
    with pytest.raises(BindingRejected):validate_bindings(bindings,definition={'steps':steps,'final_expected':[]},
        settings={'target_kind':'android','android_package':'com.example.app'},action_ids=('a1',))


def test_annotation_cannot_change_the_candidate_source_content_identity(recorded):
    job=claim_for(recorded);raw=job['snapshot']['case_context']
    assert raw['content_hash']==raw['check_bindings']['source_content_hash']
    raw['content_hash']='different source expectation hash'
    raw['context_hash']=canonical_hash({k:v for k,v in raw.items() if k!='context_hash'},'canon-json-v1')
    with pytest.raises(ValueError):resolve(job)
