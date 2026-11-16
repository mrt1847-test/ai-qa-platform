from copy import deepcopy
from pathlib import Path
import json,sqlite3,subprocess
from uuid import UUID
import pytest
from test_rx97_recording_pin import recording,ux_app
from test_ma03b_mobile_history import engine_job,client
from test_ma04_mobile_recording_session import prepare
from test_rx87_case_context import _save
from test_rx_65 import _observation
from aiqa.environments.android_app_launch import AppLaunchReceipt
from aiqa.worker.android_jobs import AndroidRecordingContext,bind_attempt_checkpoint
from aiqa.adapters.mobile_agent_android import MobileAgentAndroidAdapter,recording_broker
from aiqa.worker.control import RemoteLeaseGuard
from aiqa.worker.dispatch_journal import DispatchJournal
from aiqa.worker.spool import EvidenceSpool
from aiqa.worker.case_context import resolve_claim_case_context
from aiqa.worker.android_prepare import AndroidTargetPreparer
from aiqa.worker.runtime import WorkerRuntime,WorkerRuntimeConfig
from aiqa.contracts.jobs import ControlDecision


@pytest.fixture
def android_engine_job(recording,monkeypatch,request):
    f=recording
    with sqlite3.connect(f['database']) as db:
        db.execute("UPDATE resource_aliases SET target_kind='android' WHERE project_id=?",(f['project'],))
    saved=_save(f,objective='Open selected app search',target='android',package='com.example.saved')
    f['body'].update(input_case_version_id=saved['id'],input_version_hash=saved['content_hash'])
    return engine_job.__wrapped__(f,monkeypatch,request)


def setup(f,tmp_path,*,checkpoint=True):
    from aiqa.worker.mobile_agent_handler import OriginalAndroidRecordingHandler
    c,session,sent=prepare(f,tmp_path);launches=[];phases=[]
    job=deepcopy(f['job']);job['snapshot']['serial']='fixture-serial'
    context=AndroidRecordingContext(expected_serial='fixture-serial',fixture_response='',mono_seconds=None,
        live_capture=_observation,require_case_context=True)
    journal=DispatchJournal(tmp_path/'native.jsonl')
    def launch(package,*,before_native_send):
        before_native_send();launches.append(package);return AppLaunchReceipt(package,package+'/.Main')
    context.target_preparer=AndroidTargetPreparer(capture=_observation,launch=launch,client=c,journal=journal)
    handler=OriginalAndroidRecordingHandler(adapter=MobileAgentAndroidAdapter(),driver=session.driver,broker=recording_broker(),
        control=None,guard=RemoteLeaseGuard(),journal=journal,spool=EvidenceSpool(tmp_path/'spool'),context=context,
        client=c,runtime_root=tmp_path/'runtime')
    if checkpoint:
        from aiqa.worker.checkpoints import WorkerAttemptCheckpoint
        remote=WorkerAttemptCheckpoint(c,job)
        def fence(phase):phases.append(phase);return remote.checkpoint(phase)
        assert bind_attempt_checkpoint(handler,fence)
    return c,handler,job,sent,launches,phases


def test_handler_to_normal_finish_saves_unapproved_source_with_all_evidence(android_engine_job,tmp_path):
    f=android_engine_job;c,h,job,sent,launches,phases=setup(f,tmp_path)
    with c:
        r=h.handle(job)
        assert r.outcome=='completed' and r.review_pending and r.evidence_complete
        assert r.actions==2 and launches==['com.example.saved'] and len(sent)==1
        assert len(r.source_artifact_hashes)==10 and r.last_ack_seq==2
        runtime=WorkerRuntime(c,WorkerRuntimeConfig('fixture-boot',frozenset({'recording'})),h)
        finish=runtime._submit_finish(job,r)
        assert finish is not None,runtime.pending_finish
    assert phases.count('before_dispatch')==2 and phases.count('before_model')==2
    with sqlite3.connect(f['database']) as db:
        assert db.execute('SELECT COUNT(*) FROM recording_manifests').fetchone()[0]==1
        assert db.execute('SELECT COUNT(*) FROM approval_events').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM replay_packages').fetchone()[0]==1
        assert db.execute("SELECT COUNT(*) FROM case_versions WHERE source_manifest_id IS NOT NULL AND replay_package_id IS NOT NULL").fetchone()[0]==1
    assert h.session_result.process.receipt['main_invocations']==1


@pytest.mark.parametrize('mode',['fence','preparer','serial','case'])
def test_invalid_runtime_inputs_do_not_prepare_model_or_dispatch(android_engine_job,tmp_path,mode):
    c,h,job,sent,launches,_=setup(android_engine_job,tmp_path)
    if mode=='fence':h.context.remote_checkpoint=None
    elif mode=='preparer':h.context.target_preparer=None
    elif mode=='serial':job['snapshot']['serial']='wrong-device'
    else:job['snapshot'].pop('case_context')
    with c:r=h.handle(job)
    assert r.outcome=='error' and not r.review_pending
    assert sent==[] and launches==[] and android_engine_job['openai_sent']==[]


def test_same_attempt_cannot_prepare_again_even_with_new_handler(android_engine_job,tmp_path):
    f=android_engine_job;c,h,job,sent,launches,_=setup(f,tmp_path)
    with c:r=h.handle(job)
    c,again,job,sent2,launches2,_=setup(f,tmp_path)
    with c:second=again.handle(job)
    assert r.actions==2 and second.actions==0 and second.outcome=='error'
    assert launches2==[] and sent2==[] and len(f['openai_sent'])==2


def test_preparation_reservation_blocks_before_any_io_if_only_one_action(android_engine_job,tmp_path):
    f=android_engine_job;c,h,job,sent,launches,_=setup(f,tmp_path);h.context.max_actions=1
    with c:r=h.handle(job)
    assert r.actions==0 and r.outcome=='error'
    assert sent==[] and launches==[] and f['openai_sent']==[]


def test_final_native_gate_denial_preserves_preparation_without_click(android_engine_job,tmp_path):
    f=android_engine_job;c,h,job,sent,launches,phases=setup(f,tmp_path);remote=h.context.remote_checkpoint;native_gates=[]
    def fence(phase):
        if phase=='before_dispatch':
            native_gates.append(1)
            if len(native_gates)>1:return ControlDecision(False,'fixture cancelled')
        return remote(phase)
    h.context.remote_checkpoint=fence
    with c:r=h.handle(job)
    assert r.actions==1 and launches==['com.example.saved'] and sent==[]
    assert r.outcome=='error' and not r.review_pending and len(f['openai_sent'])==1


def test_time_spent_preparing_counts_toward_recording_timeout(android_engine_job,tmp_path,monkeypatch):
    f=android_engine_job;c,h,job,sent,launches,_=setup(f,tmp_path);clock=[0.0]
    monkeypatch.setattr('aiqa.worker.android_jobs.time.monotonic',lambda:clock[0])
    prepare_target=h.context.target_preparer.prepare
    def slow(*args,**kwargs):
        result=prepare_target(*args,**kwargs);clock[0]=32.0;return result
    monkeypatch.setattr(h.context.target_preparer,'prepare',slow)
    with c:r=h.handle(job)
    assert r.actions==1 and len(launches)==1 and sent==[] and f['openai_sent']==[]
    assert r.outcome=='error' and not r.review_pending


def test_cancel_after_preparation_ack_keeps_known_action_and_artifact_ids(android_engine_job,tmp_path,monkeypatch):
    f=android_engine_job;c,h,job,sent,launches,_=setup(f,tmp_path)
    publish=h.context.target_preparer._publish
    def commit_then_cancel():
        value=publish();h.context.cancelled=True;return value
    monkeypatch.setattr(h.context.target_preparer,'_publish',commit_then_cancel)
    with c:r=h.handle(job)
    assert launches==['com.example.saved'] and sent==[] and f['openai_sent']==[]
    assert r.actions==1 and len(r.source_artifact_hashes)==3
    assert r.outcome=='error' and not r.review_pending and not r.ambiguous_dispatch


def test_unreadable_preparation_journal_preserves_quarantine(android_engine_job,tmp_path,monkeypatch):
    f=android_engine_job;c,h,job,sent,launches,_=setup(f,tmp_path)
    def broken(*args,**kwargs):raise OSError('fixture journal unreadable')
    monkeypatch.setattr(h.context.target_preparer.journal,'states',broken)
    with c:r=h.handle(job)
    assert r.ambiguous_dispatch and r.outcome=='error' and r.actions==0
    assert launches==[] and sent==[] and f['openai_sent']==[]


def test_unknown_launch_finishes_but_cleanup_quarantines_resource(android_engine_job,tmp_path,monkeypatch):
    from aiqa.environments.android_app_launch import AppLaunchUnknown
    f=android_engine_job;c,h,job,sent,launches,_=setup(f,tmp_path)
    def unknown(package,*,before_native_send):before_native_send();raise AppLaunchUnknown('fixture lost launch ACK')
    monkeypatch.setattr(h.context.target_preparer,'launch',unknown)
    with c:
        result=h.handle(job)
        runtime=WorkerRuntime(c,WorkerRuntimeConfig('fixture-boot',frozenset({'recording'})),h)
        assert result.ambiguous_dispatch and runtime._submit_finish(job,result) is not None
        cleanup=runtime._submit_cleanup(job,result)
        assert cleanup['quarantined'] is True and cleanup['released'] is False
    with sqlite3.connect(f['database']) as db:
        assert db.execute('SELECT COUNT(*) FROM resource_quarantine').fetchone()[0]==1


def test_failure_does_not_export_previous_preparation_owner_ids(android_engine_job,tmp_path):
    from uuid import uuid4
    from aiqa.domain.hashing import canonical_hash
    from aiqa.worker.android_prepare import AppPreparationFailed
    f=android_engine_job;c,h,job,sent,launches,_=setup(f,tmp_path)
    with c:
        first=h.handle(job);assert len(first.source_artifact_hashes)==10
        other=deepcopy(job);other['attempt_id']=other['snapshot']['attempt_id']=str(uuid4())
        raw=other['snapshot']['case_context'];raw['attempt_id']=other['attempt_id']
        raw['target_secret_refs']={'account':{'project_id':f['project'],'ref_id':str(uuid4()),'revision':1}}
        raw['context_hash']=__import__('aiqa.domain.hashing',fromlist=['canonical_hash']).canonical_hash({k:v for k,v in raw.items() if k!='context_hash'},'canon-json-v1')
        with pytest.raises(AppPreparationFailed) as err:
            h.context.target_preparer.prepare(other,resolve_claim_case_context(other,required=True),checkpoint=lambda:None)
    assert err.value.artifact_ids==() and err.value.native_calls==0


def test_unknown_preparation_retains_committed_failure_evidence_ids(android_engine_job,tmp_path,monkeypatch):
    from aiqa.environments.android_app_launch import AppLaunchUnknown
    f=android_engine_job;c,h,job,sent,launches,_=setup(f,tmp_path)
    def unknown(package,*,before_native_send):before_native_send();raise AppLaunchUnknown('fixture lost launch ACK')
    monkeypatch.setattr(h.context.target_preparer,'launch',unknown)
    with c:r=h.handle(job)
    assert r.ambiguous_dispatch and r.actions==0 and len(r.source_artifact_hashes)==3
    assert r.action_mapping=='{}' and not r.review_pending and f['openai_sent']==[]


def test_denied_model_boundary_retains_already_acked_before_artifact(android_engine_job,tmp_path):
    f=android_engine_job;c,h,job,sent,launches,_=setup(f,tmp_path);remote=h.context.remote_checkpoint
    h.context.remote_checkpoint=lambda phase:ControlDecision(False,'fixture model denied') if phase=='before_model' else remote(phase)
    with c:r=h.handle(job)
    assert r.actions==1 and len(r.source_artifact_hashes)==5
    assert r.outcome=='error' and r.action_mapping=='{}' and f['openai_sent']==[] and sent==[]
    with sqlite3.connect(f['database']) as db:
        assert db.execute("SELECT dispatch_state,outcome_known FROM actions WHERE action_id LIKE 'ma-%'").fetchone()==('planned',0)
        facts=db.execute("SELECT artifact_id,role FROM artifact_objects WHERE action_id LIKE 'ma-%' ORDER BY rowid").fetchall()
    assert [role for _,role in facts]==['before','log']
    assert all(identity in r.source_artifact_hashes for identity,_ in facts)


def test_child_teardown_failure_keeps_prior_native_and_server_ack(android_engine_job,tmp_path,monkeypatch):
    import aiqa.worker.mobile_agent_process as process
    original=process.subprocess.Popen
    def start(*args,**kwargs):
        child=original(*args,**kwargs);wait=child.wait;calls=[]
        def fail_final(*args,**kwargs):
            calls.append(1)
            if len(calls)==2:raise OSError('fixture child cleanup failed')
            return wait(*args,**kwargs)
        child.wait=fail_final;return child
    monkeypatch.setattr(process.subprocess,'Popen',start)
    f=android_engine_job;c,h,job,sent,launches,_=setup(f,tmp_path)
    with c:
        r=h.handle(job)
        assert r.actions==2 and r.last_ack_seq==2 and len(r.source_artifact_hashes)==8
        assert r.outcome=='error' and r.cleanup_failed and r.action_mapping=='{}'
        runtime=WorkerRuntime(c,WorkerRuntimeConfig('fixture-boot',frozenset({'recording'})),h)
        assert runtime._submit_finish(job,r) is not None
        assert runtime._submit_cleanup(job,r)['quarantined'] is True


@pytest.mark.parametrize('location',['prepare','native'])
def test_interrupted_canonical_attempt_stays_ambiguous_without_redispatch(android_engine_job,tmp_path,location):
    f=android_engine_job;c,h,job,sent,launches,_=setup(f,tmp_path)
    folder=tmp_path/'runtime/mobile-agent'/job['project_id']/job['attempt_id'];folder.mkdir(parents=True)
    path=folder/'session/dispatch.jsonl' if location=='native' else folder/'prepare.jsonl'
    path.parent.mkdir(parents=True,exist_ok=True);journal=DispatchJournal(path)
    journal.append(job['attempt_id'],'interrupted','planned');journal.append(job['attempt_id'],'interrupted','dispatch_started')
    with c:r=h.handle(job)
    assert r.ambiguous_dispatch and r.actions==0 and not r.review_pending
    assert launches==[] and sent==[] and f['openai_sent']==[]


def test_initial_remote_latency_consumes_worker_timeout_before_preparation(android_engine_job,tmp_path,monkeypatch):
    f=android_engine_job;c,h,job,sent,launches,_=setup(f,tmp_path);remote=h.context.remote_checkpoint;clock=[0.0]
    monkeypatch.setattr('aiqa.worker.android_jobs.time.monotonic',lambda:clock[0]);h.context.max_seconds=1
    def slow(phase):
        result=remote(phase);clock[0]=2.0;return result
    h.context.remote_checkpoint=slow
    with c:r=h.handle(job)
    assert r.actions==0 and r.outcome=='error' and launches==[] and sent==[] and f['openai_sent']==[]


@pytest.mark.parametrize('objective',[None,' ','x'*16001])
def test_unusable_original_instruction_is_rejected_before_preparation(android_engine_job,tmp_path,objective):
    f=android_engine_job;c,h,job,sent,launches,_=setup(f,tmp_path)
    job['snapshot']['intent']['objective']=objective
    with c:r=h.handle(job)
    assert r.actions==0 and r.outcome=='error' and launches==[] and sent==[] and f['openai_sent']==[]
