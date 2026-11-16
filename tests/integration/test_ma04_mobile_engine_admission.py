import json,sqlite3
from pathlib import Path
from copy import deepcopy
import pytest
from test_rx97_recording_pin import recording,ux_app,request as start,_new_revision,limits_for
from test_rx87_case_context import _save
from aiqa.contracts.mobile_agent_engine import mobile_agent_engine_ref


def prepare_admission(f,mode='ok'):
    saved=_save(f,objective='Original recorded search',target='android',package='com.example.saved')
    f['body'].update(input_case_version_id=saved['id'],input_version_hash=saved['content_hash'])
    from dataclasses import replace
    import httpx
    from aiqa.models.broker import ServerModelGateway
    from aiqa.models.openai_server import OpenAIServerProvider
    f['app'].state.settings=replace(f['app'].state.settings,model_price_mode='estimate')
    f['app'].state.model_gateway=ServerModelGateway(provider=OpenAIServerProvider(transport=httpx.MockTransport(lambda req:httpx.Response(500))),resolver=f['app'].state.secret_resolver)
    model='other-model' if mode=='model' else 'gpt-6-luna'
    endpoint='https://other.invalid' if mode=='endpoint' else 'https://api.openai.com'
    with sqlite3.connect(f['database']) as db:
        db.execute("UPDATE resource_aliases SET target_kind='android' WHERE project_id=?",(f['project'],))
        from authoring_metadata_support import seed_recording_capability
        seed_recording_capability(db,f['project'],f['body']['resource_id'],mode='original')
        permissions=json.loads(db.execute('SELECT permissions FROM resource_inventory WHERE physical_key_id=?',(f['body']['resource_id'],)).fetchone()[0])
        if mode=='missing':permissions={}
        elif mode=='stale':permissions['authoring_engine_boot_id']='old-boot'
        elif mode=='wrong_ref':permissions['authoring_engine']['commit']='wrong'
        elif mode=='malformed':permissions=[]
        db.execute('UPDATE resource_inventory SET permissions=? WHERE physical_key_id=?',(json.dumps(permissions),f['body']['resource_id']))
        _new_revision(db,f['project'],provider='openai',model=model,endpoint=endpoint,endpoint_kind='https')
    return f


def test_normal_admission_freezes_exact_original_engine_without_worker_or_browser_marker(recording):
    f=prepare_admission(recording);r=start(f)
    assert r.status_code==201,r.text
    limits=limits_for(f,r.json()['job_id'])
    assert limits['authoring_engine']==mobile_agent_engine_ref()
    from aiqa.contracts.authoring import authoring_policy_ref
    assert limits['policy_ref']==authoring_policy_ref(limits)


@pytest.mark.parametrize('mode',['missing','stale','wrong_ref','malformed','model','endpoint'])
def test_unsupported_original_admission_creates_no_recording_or_job(recording,mode):
    f=prepare_admission(recording,mode);r=start(f)
    assert r.status_code==422,r.text
    with sqlite3.connect(f['database']) as db:
        assert db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM recordings').fetchone()[0]==0


def test_admission_retry_preserves_engine_after_worker_report_changes(recording):
    f=prepare_admission(recording);first=start(f);assert first.status_code==201
    with sqlite3.connect(f['database']) as db:db.execute("UPDATE resource_inventory SET permissions='{}'")
    second=start(f)
    assert second.status_code==200 and second.json()['job_id']==first.json()['job_id']
    assert limits_for(f,first.json()['job_id'])['authoring_engine']==mobile_agent_engine_ref()


def test_web_fixture_admission_stays_unmarked(recording):
    r=start(recording);assert r.status_code==201
    assert 'authoring_engine' not in limits_for(recording,r.json()['job_id'])


def test_operational_factory_selects_actual_original_handler_without_legacy_model_loop(tmp_path,monkeypatch):
    import aiqa.worker.android_jobs as jobs
    from aiqa.worker.mobile_agent_handler import OriginalAndroidRecordingHandler
    from test_rx_65 import _observation
    monkeypatch.setattr(jobs,'_live_android_capture_pair',lambda **kwargs:(_observation,lambda *a,**k:None))
    h=jobs.build_operational_android_recording_handler(adb_path=Path('adb.exe'),serial='fixture-serial',expected_avd=None,runtime_root=tmp_path,client=object())
    assert isinstance(h,OriginalAndroidRecordingHandler) and h.context.plan_provider is None


def test_inventory_publishes_only_actual_supported_recording_route(android_engine_job,tmp_path):
    from test_ma04_mobile_runtime_handler import setup
    from aiqa.worker.android_jobs import register_android_recording_handler
    from aiqa.worker.mobile_agent_registration import inventory_with_recording_engine
    c,h,*_=setup(android_engine_job,tmp_path)
    payload={'target_kind':'android','state':'ready','permissions':json.dumps({'rotation':0,'authoring_engine':{'fake':True},'authoring_engine_boot_id':'old'})}
    with c:
        report=inventory_with_recording_engine(payload,register_android_recording_handler(h),'new-boot',prepared=True,session_id='11111111-1111-4111-8111-111111111111')
        permission=json.loads(report['permissions'])
        assert permission=={'rotation':0,'authoring_engine':mobile_agent_engine_ref(),'authoring_engine_boot_id':'new-boot','authoring_engine_session_id':'11111111-1111-4111-8111-111111111111','authoring_mode':'original'}
        inert=inventory_with_recording_engine(payload,object(),'new-boot',prepared=True,session_id='11111111-1111-4111-8111-111111111111')
        assert json.loads(inert['permissions'])=={'rotation':0}
        not_prepared=inventory_with_recording_engine(payload,h,'new-boot',prepared=False,session_id='11111111-1111-4111-8111-111111111111')
        assert json.loads(not_prepared['permissions'])=={'rotation':0}
    assert json.loads(payload['permissions'])['authoring_engine']=={'fake':True}


def test_source_verification_failure_does_not_advertise_original_engine(android_engine_job,tmp_path,monkeypatch):
    from test_ma04_mobile_runtime_handler import setup
    import aiqa.worker.mobile_agent_registration as registration
    c,h,*_=setup(android_engine_job,tmp_path)
    def fail():raise ValueError('fixture original source changed')
    monkeypatch.setattr(registration,'load_protocol',fail)
    with c:report=registration.inventory_with_recording_engine({'target_kind':'android','state':'ready','permissions':'{}'},h,'new-boot',prepared=True,session_id='11111111-1111-4111-8111-111111111111')
    assert 'authoring_engine' not in json.loads(report['permissions'])


from test_ma04_mobile_runtime_handler import android_engine_job


def test_actual_worker_runtime_cycle_uses_original_main_and_stores_unapproved_version(unacked_android_engine_job,tmp_path,monkeypatch):
    from test_ma04_mobile_runtime_handler import setup
    from aiqa.worker.runtime import WorkerRuntime,WorkerRuntimeConfig
    f=unacked_android_engine_job;c,h,job,sent,launches,_=setup(f,tmp_path,checkpoint=False)
    with c:
        monkeypatch.setattr(c,'claim',lambda **kwargs:job)
        runtime=WorkerRuntime(c,WorkerRuntimeConfig('fixture-boot',frozenset({'recording'})),h)
        report=runtime.run_once()
        assert report.finished and report.actions==2,report
    with sqlite3.connect(f['database']) as db:
        assert db.execute('SELECT COUNT(*) FROM recording_manifests').fetchone()[0]==1
        assert db.execute('SELECT COUNT(*) FROM replay_packages').fetchone()[0]==1
        assert db.execute('SELECT COUNT(*) FROM approval_events').fetchone()[0]==0
    assert launches==['com.example.saved'] and len(sent)==1 and len(f['openai_sent'])==2
    assert h.session_result.process.receipt['main_invocations']==1


@pytest.fixture
def unacked_android_engine_job(recording,monkeypatch,request):
    import test_rx98_model_requests as seed
    with monkeypatch.context() as temporary:
        temporary.setattr(seed,'ack',lambda f:None)
        return android_engine_job.__wrapped__(recording,monkeypatch,request)


def test_explicit_android_fixture_adapter_stays_unmarked(recording):
    f=recording;saved=_save(f,objective='Fixture only',target='android',package='com.example.saved')
    f['body'].update(input_case_version_id=saved['id'],input_version_hash=saved['content_hash'])
    with sqlite3.connect(f['database']) as db:db.execute("UPDATE resource_aliases SET target_kind='android' WHERE project_id=?",(f['project'],))
    r=start(f);assert r.status_code==201,r.text
    assert 'authoring_engine' not in limits_for(f,r.json()['job_id'])


def test_rerecord_admission_uses_selected_resource_engine(recording):
    from uuid import UUID
    from aiqa.store.models import Actor
    from aiqa.recording.service import start_rerecording,RerecordInput
    f=prepare_admission(recording)
    with sqlite3.connect(f['database']) as db:
        actor=Actor(UUID(db.execute('SELECT actor_id FROM case_versions WHERE version_id=?',(f['body']['input_case_version_id'],)).fetchone()[0]),UUID(f['project']),True)
        spec=RerecordInput(UUID(f['body']['case_id']),UUID(f['body']['input_case_version_id']),UUID(f['body']['input_case_version_id']),
            'new candidate',f['body']['resource_id'],'','','none',True,True,True,True,None)
        from aiqa.recording.mobile_agent_admission import runtime_for_app
        receipt=start_rerecording(db,actor,UUID(f['project']),spec,'rerecord-engine',model_runtime=runtime_for_app(f['app']))
        limits=json.loads(db.execute('SELECT limits FROM jobs WHERE job_id=?',(str(receipt.job_id),)).fetchone()[0])
    assert limits['authoring_engine']==mobile_agent_engine_ref()


def test_runtime_inventory_http_report_contains_actual_engine_and_current_boot(android_engine_job,tmp_path):
    import httpx
    from uuid import uuid4
    from aiqa.worker.http_client import WorkerHttpClient,WorkerClientSettings
    from aiqa.worker.runtime import WorkerRuntime,WorkerRuntimeConfig
    from test_ma04_mobile_runtime_handler import setup
    c,h,*_=setup(android_engine_job,tmp_path);reports=[]
    def http(request):
        if request.url.path.endswith('/heartbeats'):return httpx.Response(200,json={'state':'online','boot_id':'current-boot','session_id':'11111111-1111-4111-8111-111111111111'})
        if request.url.path.endswith('/inventory'):
            reports.append(json.loads(request.content));return httpx.Response(200,json={'physical_key_id':str(uuid4())})
        return httpx.Response(204)
    payload={'project_id':android_engine_job['project'],'native_id':'fixture-serial','target_kind':'android','state':'ready','permissions':'{"rotation":0}'}
    with c,WorkerHttpClient(WorkerClientSettings('https://127.0.0.1','synthetic-token'),transport=httpx.MockTransport(http)) as client:
        runtime=WorkerRuntime(client,WorkerRuntimeConfig('current-boot',frozenset({'recording'})),h,inventory_provider=lambda:payload)
        runtime.run_once()
    assert len(reports)==1
    assert json.loads(reports[0]['permissions'])=={'rotation':0,'authoring_engine':mobile_agent_engine_ref(),'authoring_engine_boot_id':'current-boot','authoring_engine_session_id':'11111111-1111-4111-8111-111111111111','authoring_mode':'original'}


def test_original_engine_readiness_preview_agrees_with_start_block(recording):
    f=prepare_admission(recording,'missing')
    preview=start(f,path=f"/api/v1/projects/{f['project']}/recording-previews")
    assert preview.status_code==200 and preview.json()['ready'] is False
    assert any(r['code']=='engine' for r in preview.json()['reasons'])
    assert start(f).status_code==422


def test_changed_worker_source_is_rejected_before_selected_app_launch(android_engine_job,tmp_path,monkeypatch):
    import aiqa.worker.mobile_agent_handler as handler_module
    from test_ma04_mobile_runtime_handler import setup
    f=android_engine_job;c,h,job,sent,launches,_=setup(f,tmp_path)
    def fail():raise ValueError('fixture changed source')
    monkeypatch.setattr(handler_module,'load_protocol',fail,raising=False)
    with c:r=h.handle(job)
    assert r.actions==0 and r.outcome=='error' and launches==[] and sent==[] and f['openai_sent']==[]


@pytest.mark.parametrize('endpoint',['https://api.openai.com/','https://api.openai.com/v1/responses/'])
def test_admission_accepts_official_endpoint_forms_supported_by_model_port(recording,endpoint):
    f=prepare_admission(recording)
    with sqlite3.connect(f['database']) as db:_new_revision(db,f['project'],provider='openai',model='gpt-6-luna',endpoint=endpoint,endpoint_kind='https')
    r=start(f)
    assert r.status_code==201,r.text
    assert limits_for(f,r.json()['job_id'])['authoring_engine']==mobile_agent_engine_ref()
