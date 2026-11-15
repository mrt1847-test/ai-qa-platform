"""Frozen server metadata is validated before any model/capture/native side effect."""
import copy
from dataclasses import FrozenInstanceError
from uuid import uuid4
import pytest
from aiqa.domain.hashing import canonical_hash
from test_rx98_model_requests import model_job,recording,ux_app
from test_rx87_android_runtime import handler_for


def _rehash(job):
    raw=job['snapshot']['case_context']
    raw['context_hash']=canonical_hash({k:v for k,v in raw.items() if k!='context_hash'},'canon-json-v1')


def test_normal_api_context_is_detached_and_read_only(model_job):
    from aiqa.worker.case_context import resolve_claim_case_context
    job=model_job['job'];pin=resolve_claim_case_context(job,required=True)
    assert pin.case_version_id==job['snapshot']['case_context']['case_version_id']
    assert pin.objective=='Check saved target' and pin.target.kind=='web'
    job['snapshot']['case_context']['objective']='mutated'
    assert pin.objective=='Check saved target'
    with pytest.raises((FrozenInstanceError,AttributeError)):pin.objective='changed'


@pytest.mark.parametrize('change',['hash','project','job','attempt','generation','generation_bool','generation_nan','purpose','owner_kind','version','target','secret_value','secret_revision_bool','duplicate_check','bad_verifier'])
def test_worker_rejects_corrupt_or_foreign_context(model_job,change):
    from aiqa.worker.case_context import resolve_claim_case_context,CaseContextRejected
    job=copy.deepcopy(model_job['job']);raw=job['snapshot']['case_context']
    if change=='hash':raw['objective']='unhashed mutation'
    elif change in {'project','job','attempt'}:raw[change+'_id']=str(uuid4());_rehash(job)
    elif change=='generation':raw['generation']+=1;_rehash(job)
    elif change=='generation_bool':raw['generation']=True;_rehash(job)
    elif change=='generation_nan':raw['generation']=float('nan')
    elif change=='purpose':raw['purpose']='regression';_rehash(job)
    elif change=='owner_kind':raw['owner_kind']='ITEM';_rehash(job)
    elif change=='version':raw['case_version_id']=str(uuid4());_rehash(job)
    elif change=='target':raw['target']={'kind':'android','android_package':'pkg;rm'};_rehash(job)
    elif change=='secret_revision_bool':raw['secret_refs']={'account':{'project_id':job['project_id'],'ref_id':str(uuid4()),'revision':True}};_rehash(job)
    elif change=='duplicate_check':
        raw['steps']=[{'id':'s1','instruction':'tap','expected':[{'id':'dup','kind':'text','expected':'A'}]}]
        raw['final_expected']=[{'id':'dup','kind':'text','expected':'B'}];_rehash(job)
    elif change=='bad_verifier':raw['verification'][0]['method']='raw_shell';_rehash(job)
    else:raw['secret_refs']={'account':{'project_id':job['project_id'],'ref_id':str(uuid4()),'revision':1,'value':'never-forward'}};_rehash(job)
    with pytest.raises(CaseContextRejected):resolve_claim_case_context(job,required=True)
    assert model_job['provider'].sent==0


def test_missing_required_context_blocks_handler_before_side_effects(model_job,tmp_path):
    job=copy.deepcopy(model_job['job']);job['snapshot'].pop('case_context')
    calls=[];handler=handler_for(tmp_path,job,calls);handler.context.require_case_context=True
    result=handler.handle(job)
    assert result.actions==0 and calls==[] and handler.broker.authoring_calls==0
    assert handler.stopped_reason=='case_context_invalid'


def test_changed_context_is_not_silently_ignored_by_a_development_handler(model_job,tmp_path):
    job=copy.deepcopy(model_job['job']);job['snapshot']['case_context']['objective']='changed without hash'
    calls=[];handler=handler_for(tmp_path,job,calls)
    result=handler.handle(job)
    assert result.actions==0 and calls==[] and handler.broker.authoring_calls==0
    assert handler.stopped_reason=='case_context_invalid'


def test_replay_builder_has_no_device_side_effect_before_a_valid_claim(tmp_path,monkeypatch):
    from pathlib import Path
    import aiqa.worker.android_jobs as jobs
    prepared=[]
    monkeypatch.setattr(jobs,'_live_android_capture_pair',lambda **kwargs:(lambda:None,lambda:prepared.append('start')))
    handler=jobs.build_approved_android_replay_handler(adb_path=Path('C:/platform-tools/adb.exe'),serial='emulator-5580',
        expected_avd='fixture-avd',runtime_root=tmp_path,approved_digest='',approved_plan='')
    assert prepared==[],'builder started an app before claim validation or ACK'
    assert handler.context.require_case_context is True


def test_supplied_null_context_is_not_the_legacy_missing_field_seam():
    from aiqa.worker.case_context import resolve_claim_case_context,CaseContextRejected
    assert resolve_claim_case_context({'snapshot':{}},required=False) is None
    with pytest.raises(CaseContextRejected):resolve_claim_case_context({'snapshot':{'case_context':None}},required=False)


@pytest.mark.parametrize('mode',['fixture','operational'])
def test_live_recording_builders_require_metadata_before_capture_or_prepare(tmp_path,monkeypatch,mode):
    from pathlib import Path
    import aiqa.worker.android_jobs as jobs
    calls=[]
    monkeypatch.setattr(jobs,'_live_android_capture_pair',lambda **kwargs:(lambda:calls.append('capture'),lambda:calls.append('prepare')))
    factory=jobs.build_fixture_android_recording_handler if mode=='fixture' else jobs.build_operational_android_recording_handler
    kwargs={'fixture_response':'finish()'} if mode=='fixture' else {'client':object()}
    handler=factory(adb_path=Path('C:/platform-tools/adb.exe'),serial='emulator-5580',expected_avd='fixture',runtime_root=tmp_path,**kwargs)
    assert handler.context.require_case_context is True and calls==[]
    result=handler.handle({'snapshot':{'purpose':'recording'}})
    assert result.actions==0 and handler.stopped_reason=='case_context_invalid' and calls==[]


from test_rx95_worker_healing_pin import healing_claim,admitted_healing,healing_execution,healing_metadata


def test_actual_replay_context_resolves_without_becoming_a_model_grant(healing_claim):
    from aiqa.worker.case_context import resolve_claim_case_context
    pin=resolve_claim_case_context(healing_claim,required=True)
    assert pin.case_version_id==healing_claim['snapshot']['case_context']['case_version_id']
    document=pin.to_document();document['target']['kind']='changed'
    assert pin.to_document()['target']['kind']==pin.target.kind


@pytest.mark.parametrize('damage',['version','package','missing'])
def test_replay_context_mismatch_stops_before_native_or_healing(healing_claim,tmp_path,damage):
    from test_rx_34 import _replay
    job=copy.deepcopy(healing_claim);handler,calls=_replay(tmp_path);handler.context.require_case_context=True
    job['snapshot']['serial']=handler.context.expected_serial
    if damage=='missing':job['snapshot'].pop('case_context')
    else:
        key='case_version_id' if damage=='version' else 'replay_package_id'
        job['snapshot']['case_context'][key]=str(uuid4());_rehash(job)
    result=handler.handle(job)
    assert result.actions==0 and handler.stopped_reason=='case_context_invalid' and calls==[]
    assert handler.healer_calls==handler.verifier_calls==handler.broker.authoring_calls==0


def test_prepared_android_entry_rejects_a_valid_web_target_before_dispatch(model_job,tmp_path):
    job=model_job['job'];assert job['snapshot']['case_context']['target']['kind']=='web'
    calls=[];handler=handler_for(tmp_path,job,calls);handler.context.require_case_context=True
    result=handler.handle(job)
    assert result.actions==0 and calls==[] and handler.broker.authoring_calls==0
    assert handler.stopped_reason=='case_context_invalid'


def test_actual_android_api_context_reaches_the_prepared_handler(recording,tmp_path):
    import sqlite3
    from test_rx87_case_context import _save,start,claim
    job=_android_api_claim(recording);calls=[];handler=handler_for(tmp_path,job,calls)
    handler.context.require_case_context=True;handler.context.fixture_responses=('click(100,200)','finish()')
    from aiqa.contracts.jobs import ControlDecision
    handler.context.remote_checkpoint=lambda phase:ControlDecision(True,phase)  # Explicit test fence.
    result=handler.handle(job)
    assert result.actions==len(calls)==1 and handler._case_context.target.android_package=='com.example.saved'
    assert handler._case_context.steps[0].expected[0].expected=='Saved'
    # Explicit fake actor/device verifies the metadata gate; required checks/launch
    # themselves are B2.2b/B2.3 and this is not real-device QA acceptance.


def test_invalid_next_recording_context_clears_previous_claim_statistics(model_job,tmp_path):
    job=model_job['job'];calls=[];handler=handler_for(tmp_path,job,calls)
    handler.context.fixture_responses=('click(100,200)','finish()')
    assert handler.handle(job).actions==1
    invalid=copy.deepcopy(job);invalid['attempt_id']=str(uuid4())
    result=handler.handle(invalid)
    assert result.actions==0 and len(calls)==1
    assert handler.tap_count==handler.authoring_calls_seen==0 and handler.finished_by_model is False
    assert handler._case_context is None and handler.evidence_commits==[]


@pytest.mark.parametrize('damage',['snapshot_job','snapshot_attempt','snapshot_job_missing','snapshot_attempt_missing','owner','owner_missing'])
def test_context_matches_repeated_snapshot_ids_and_authoritative_owner_pin(model_job,damage):
    from aiqa.worker.case_context import resolve_claim_case_context,CaseContextRejected
    job=copy.deepcopy(model_job['job'])
    if damage=='snapshot_job':job['snapshot']['job_id']=str(uuid4())
    elif damage=='snapshot_attempt':job['snapshot']['attempt_id']=str(uuid4())
    elif damage=='snapshot_job_missing':job['snapshot'].pop('job_id')
    elif damage=='snapshot_attempt_missing':job['snapshot'].pop('attempt_id')
    elif damage=='owner_missing':job['snapshot'].pop('revision_ref')
    else:job['snapshot']['case_context']['owner_id']=str(uuid4());_rehash(job)
    with pytest.raises(CaseContextRejected):resolve_claim_case_context(job,required=True)


@pytest.mark.parametrize('damage',['manifest','package_id','package_hash','execution_list','execution_null'])
def test_replay_context_matches_all_available_frozen_source_pins(healing_claim,damage):
    from aiqa.worker.case_context import resolve_claim_case_context,CaseContextRejected
    job=copy.deepcopy(healing_claim);job['snapshot']['self_healing_enabled']=False
    limits=job['snapshot']['limits']
    if damage=='manifest':limits['execution_snapshot']['manifest_hash']='different-source'
    elif damage=='package_id':limits['replay_package_id']=str(uuid4())
    elif damage=='package_hash':limits['replay_package_hash']='different-package-hash'
    else:limits['execution_snapshot']=[] if damage=='execution_list' else None
    with pytest.raises(CaseContextRejected):resolve_claim_case_context(job,required=True)


def _prepared_replay(tmp_path,monkeypatch,source_job):
    import subprocess
    from pathlib import Path
    import aiqa.worker.android_jobs as jobs
    from test_rx_34 import _observation,_Script
    job=copy.deepcopy(source_job);snapshot=job['snapshot'];raw=snapshot['case_context']
    owner=str(uuid4());package=str(uuid4());digest='sha256:'+'a'*64
    snapshot.update(purpose='trial',self_healing_enabled=False,revision_ref='case_run:'+owner,
        replay_package_id=package,replay_package_hash=digest,approved_digest=digest,
        approved_plan='click(100,200)\nclick(100,200)',limits={'max_actions':2,'max_model_calls':0,'timeout_seconds':30,
        'replay_package_id':package,'replay_package_hash':digest})
    snapshot.pop('intent',None)
    raw.update(purpose='trial',owner_kind='ITEM',owner_id=owner,replay_package_id=package,replay_package_hash=digest,replay_compiler_ref='android-plan-v1',
        target={'kind':'android','android_package':'com.example.saved'})
    _rehash(job);events=[]
    def capture():events.append('capture');return _observation()
    def prepare(package,*,before_native_send):
        from aiqa.environments.android_app_launch import AppLaunchReceipt
        before_native_send();events.append('prepare');return AppLaunchReceipt(package,package+'/.Main')
    def native(argv,seconds):events.append('native');return subprocess.CompletedProcess(argv,0,b'',b'')
    monkeypatch.setattr(jobs,'_live_android_capture_pair',lambda **kwargs:(capture,prepare))
    from test_rx87_target_prepare import Client
    handler=jobs.build_approved_android_replay_handler(client=Client(),adb_path=Path('C:/platform-tools/adb.exe'),
        serial=snapshot['serial'],expected_avd='fixture',runtime_root=tmp_path,
        approved_digest=digest,approved_plan=snapshot['approved_plan'])
    monkeypatch.setattr(handler.driver,'_runner',native)
    handler.context.verify_transport=_Script()  # Explicit fixture, no paid check calls.
    return handler,job,events


@pytest.mark.parametrize('fence',['absent','denied','allowed'])
def test_official_replay_preparation_requires_a_fence_and_runs_once(model_job,tmp_path,monkeypatch,fence):
    from aiqa.contracts.jobs import ControlDecision
    handler,job,events=_prepared_replay(tmp_path,monkeypatch,model_job['job'])
    if fence!='absent':handler.context.remote_checkpoint=lambda phase:ControlDecision(fence=='allowed',phase)
    result=handler.handle(job)
    if fence=='allowed':
        assert result.actions==2 and events.count('prepare')==1 and events.count('capture')==4 and events.count('native')==2
    else:assert result.actions==0 and events==[]


def _android_api_claim(f):
    import sqlite3
    from test_rx87_case_context import _save,start,claim
    with sqlite3.connect(f['database']) as c:
        c.execute("UPDATE resource_aliases SET target_kind='android' WHERE project_id=? AND physical_key_id=?",(f['project'],f['body']['resource_id']))
    saved=_save(f,objective='Selected Android app',target='android',package='com.example.saved')
    f['body'].update(input_case_version_id=saved['id'],input_version_hash=saved['content_hash'])
    result=start(f);assert result.status_code==201,result.text
    return claim(f)


@pytest.mark.parametrize('fence',['absent','denied'])
def test_prepared_recording_requires_fence_before_prepare_or_capture(recording,tmp_path,fence):
    from aiqa.contracts.jobs import ControlDecision
    from test_rx_34 import _observation
    job=_android_api_claim(recording);calls=[];handler=handler_for(tmp_path,job,calls)
    handler.context.require_case_context=True
    handler.context.prepare_device=lambda:calls.append('prepare')
    handler.context.live_capture=lambda:(calls.append('capture') or _observation())
    if fence=='denied':handler.context.remote_checkpoint=lambda phase:ControlDecision(False,phase)
    result=handler.handle(job)
    assert result.actions==0 and calls==[] and handler.broker.authoring_calls==0
    assert handler.stopped_reason in {'remote_checkpoint_missing','remote_checkpoint_blocked'}


def test_official_replay_reserves_setup_slot_before_any_io(model_job,tmp_path,monkeypatch):
    from aiqa.contracts.jobs import ControlDecision
    handler,job,events=_prepared_replay(tmp_path,monkeypatch,model_job['job'])
    job['snapshot']['approved_plan']='\n'.join(['click(100,200)']*50)
    handler.context.remote_checkpoint=lambda phase:ControlDecision(True,phase)
    result=handler.handle(job)
    assert result.actions==0 and handler.stopped_reason=='action_budget' and events==[]


@pytest.mark.parametrize('plan',['click(100,200)',''])
def test_official_native_compiler_context_cannot_lose_witness_or_use_fallback(model_job,tmp_path,monkeypatch,plan):
    handler,job,events=_prepared_replay(tmp_path,monkeypatch,model_job['job'])
    raw=job['snapshot']['case_context'];raw['replay_compiler_ref']='android-native-plan-v2';_rehash(job)
    job['snapshot']['approved_plan']=plan
    result=handler.handle(job)
    assert result.actions==0 and events==[] and handler.stopped_reason=='native_source_invalid'


def test_normal_recording_context_identifies_that_no_replay_compiler_is_selected(model_job):
    raw=model_job['job']['snapshot']['case_context']
    assert 'replay_compiler_ref' in raw and raw['replay_compiler_ref'] is None
