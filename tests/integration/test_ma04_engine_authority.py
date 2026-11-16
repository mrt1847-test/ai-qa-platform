"""Authenticated inventory -> browser start -> true selected-PC claim, no forced marker."""
from dataclasses import replace
from datetime import datetime,timezone,timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID,uuid4
import asyncio,json,sqlite3,subprocess
import httpx,pytest
from test_rx97_recording_pin import recording,ux_app,request as start,_new_revision
from test_rx87_case_context import _save
from test_rx_65 import _observation
from unit.test_openai_provider_settings import response
from unit.test_mobile_agent_context import reply
from aiqa.api.auth import bound_auth_store,enroll_worker
from aiqa.store.models import Actor,SecretInput
from aiqa.security.secrets import MemorySecretBackend,bind_secret_store,build_server_secret_resolver
from aiqa.models.broker import ServerModelGateway
from aiqa.models.openai_server import OpenAIServerProvider
from aiqa.config import WorkerClientSettings
from aiqa.worker.http_client import WorkerHttpClient,SyncASGITransport
from aiqa.contracts.mobile_agent_engine import mobile_agent_engine_ref
from ux_support import session


@pytest.fixture
def platform(ux_app):
    app,project,database=ux_app
    async def create():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1') as c:
            headers=await session(c,project)
            case=await c.post(f'/api/v1/projects/{project}/cases',json={'name':'Selected PC original','tc_reference':None},headers=headers)
            assert case.status_code==201,case.text
            case_id=case.json()['case_id']
            version=await c.post(f'/api/v1/projects/{project}/cases/{case_id}/versions',json={
                'definition':{'objective':'Selected execution PC','steps':[{'id':'saved-step','instruction':'tap','expected':[{'id':'saved-check','kind':'text','expected':'Saved'}]}],
                    'final_expected':[{'id':'saved-final','kind':'text','expected':'Done'}]},
                'settings':{'target_kind':'android','android_package':'com.example.saved','limits':{'timeout_seconds':31,'max_actions':4,'max_model_calls':3,'budget':'0.70','currency':'USD'}}},
                headers={**headers,'Idempotency-Key':'version-authority'})
            assert version.status_code==201,version.text
            return {'case_id':case_id,'input_case_version_id':version.json()['id'],'input_version_hash':version.json()['content_hash'],'resource_id':''}
    f={'app':app,'project':project,'database':database,'body':asyncio.run(create())}
    app.state.settings=replace(app.state.settings,model_price_mode='estimate')
    backend=MemorySecretBackend();resolver=build_server_secret_resolver(app.state.settings,backend=backend)
    store=app.state.open_store()
    try:
        with store.transaction() as db:
            actor=Actor(UUID(db.execute('SELECT actor_id FROM case_versions WHERE version_id=?',(f['body']['input_case_version_id'],)).fetchone()[0]),UUID(project),True)
        with bind_secret_store(store):secret=resolver.put(actor,SecretInput(value='synthetic-authority-key',name='author'))
        from aiqa.domain.model_bindings import bind_model_store,save_model_binding_revision
        from aiqa.store.models import ModelBindingInput,SecretRef
        with bind_model_store(store):
            save_model_binding_revision(ModelBindingInput(project_id=UUID(project),actor_id=actor.actor_id,name='authoring',role='authoring',
                provider='openai',endpoint_kind='https',endpoint='https://api.openai.com',model='gpt-6-luna',
                key_ref=SecretRef(UUID(project),secret.ref_id,secret.revision),prompt_hash='sha256:'+'ab'*32,tariff_id='t1',compatibility_status='unchecked'))
    finally:store.close()
    sent=[]
    def http(request):
        args={'action':'click','coordinate':[500,500]} if not sent else {'action':'terminate','status':'success'}
        sent.append(request);raw=response();raw['output'][-1]['content'][0]['text']=reply(args)
        return httpx.Response(200,json=raw)
    provider=OpenAIServerProvider(transport=httpx.MockTransport(http))
    app.state.secret_resolver=resolver;app.state.model_gateway=ServerModelGateway(provider=provider,resolver=resolver)
    f.update(actor=actor,model_sent=sent,clients=[],secret=secret)
    yield f
    for client in f['clients']:client.close()


def worker(f,*,purpose='recording',mode='original',worker_id=None,boot='shared-boot',serial='emulator-5554'):
    worker_id=worker_id or str(uuid4());store=f['app'].state.open_store()
    try:
        with bound_auth_store(store):token=enroll_worker(f['actor'],worker_id,purpose)
    finally:store.close()
    client=WorkerHttpClient(WorkerClientSettings('https://127.0.0.1',token),transport=SyncASGITransport(f['app']));f['clients'].append(client)
    heartbeat=client.heartbeat(boot)
    with sqlite3.connect(f['database']) as db:session_id=db.execute('SELECT session_id FROM worker_presence WHERE project_id=? AND worker_id=?',(f['project'],worker_id)).fetchone()[0]
    permissions={'authoring_mode':mode,'authoring_engine_boot_id':boot,'authoring_engine_session_id':session_id}
    if mode=='original':permissions['authoring_engine']=mobile_agent_engine_ref()
    payload={'project_id':f['project'],'native_id':serial,'target_kind':'android','state':'ready','os_build':'test','geometry':'100x200@0',
        'permissions':json.dumps(permissions),'ime':'test','observed_at':datetime.now(timezone.utc).isoformat(),'display_name':'Selected PC emulator'}
    inventory=client.report_inventory(payload,idempotency_key='inventory-'+str(uuid4()))
    return SimpleNamespace(client=client,worker_id=worker_id,resource_id=inventory['physical_key_id'],boot=boot,session_id=session_id,payload=payload,heartbeat=heartbeat,serial=serial)


def choose(f,w):f['body']['resource_id']=w.resource_id

def claim(f,w):return w.client.claim(project_id=f['project'],boot_id=w.boot,now=datetime.now(timezone.utc).isoformat(),idempotency_key='claim-'+str(uuid4()))


def test_marked_job_cannot_be_claimed_by_other_pc_with_identical_emulator_serial(platform):
    f=platform;selected=worker(f);other=worker(f);choose(f,selected)
    result=start(f);assert result.status_code==201,result.text
    assert claim(f,other) is None,'another registered PC acquired the selected PC recording'
    owned=claim(f,selected)
    assert owned is not None and owned['worker_id']==selected.worker_id and owned['physical_key_id']==selected.resource_id


@pytest.mark.parametrize('change',['session','mode','engine'])
def test_claim_rechecks_current_original_capability_before_lease(platform,change):
    f=platform;w=worker(f);choose(f,w);assert start(f).status_code==201
    with sqlite3.connect(f['database']) as db:
        permissions=json.loads(db.execute('SELECT permissions FROM resource_inventory WHERE physical_key_id=?',(w.resource_id,)).fetchone()[0])
        if change=='session':permissions['authoring_engine_session_id']=str(uuid4())
        elif change=='mode':permissions['authoring_mode']='fixture';permissions.pop('authoring_engine',None)
        else:permissions['authoring_engine']={'unsupported':True}
        db.execute('UPDATE resource_inventory SET permissions=? WHERE physical_key_id=?',(json.dumps(permissions),w.resource_id))
    assert claim(f,w) is None
    with sqlite3.connect(f['database']) as db:assert db.execute('SELECT COUNT(*) FROM leases').fetchone()[0]==0


def test_probe_only_inventory_cannot_confer_recording_authority(platform):
    f=platform;w=worker(f,purpose='resource_probe');choose(f,w)
    preview=start(f,path=f"/api/v1/projects/{f['project']}/recording-previews")
    assert preview.json()['ready'] is False
    assert start(f).status_code==422


def test_same_boot_after_offline_requires_new_authenticated_capability_report(platform):
    f=platform;w=worker(f);choose(f,w)
    with sqlite3.connect(f['database']) as db:db.execute('UPDATE worker_presence SET last_seen=? WHERE project_id=? AND worker_id=?',((datetime.now(timezone.utc)-timedelta(minutes=2)).isoformat(),f['project'],w.worker_id))
    refreshed=w.client.heartbeat(w.boot)
    assert start(f).status_code==422,'old inventory survived a new presence incarnation'


def test_heartbeat_exposes_authoritative_boot_and_session_for_capability_reports(platform):
    f=platform;w=worker(f)
    assert w.heartbeat['boot_id']==w.boot and w.heartbeat['session_id']==w.session_id


@pytest.mark.parametrize('bad',['gateway','price'])
def test_actual_server_model_configuration_blocks_before_any_recording(platform,bad):
    f=platform;w=worker(f);choose(f,w)
    if bad=='gateway':
        from aiqa.models.provider_http import FixtureProviderHttp
        f['app'].state.model_gateway.provider=FixtureProviderHttp()
    else:f['app'].state.settings=replace(f['app'].state.settings,model_price_mode='strict')
    preview=start(f,path=f"/api/v1/projects/{f['project']}/recording-previews")
    assert preview.json()['ready'] is False
    assert start(f).status_code==422
    assert f['model_sent']==[]


def test_unavailable_source_does_not_prevent_building_other_worker_routes(platform,tmp_path,monkeypatch):
    import aiqa.worker.android_jobs as jobs
    import aiqa.adapters.mobile_agent_upstream as source
    from aiqa.worker.mobile_agent_handler import OriginalAndroidRecordingHandler
    def fail():raise ValueError('fixture vendor source unavailable')
    monkeypatch.setattr(source,'load_protocol',fail)
    monkeypatch.setattr(jobs,'_live_android_capture_pair',lambda **kwargs:(_observation,lambda *a,**k:None))
    h=jobs.build_operational_android_recording_handler(adb_path=Path('adb.exe'),serial='emulator-5554',expected_avd=None,runtime_root=tmp_path,client=object())
    assert isinstance(h,OriginalAndroidRecordingHandler)
    router=jobs.register_android_recording_handler(h,other={'resource_probe':object()})
    assert 'resource_probe' in router.routes


def test_real_inventory_browser_start_and_runtime_claim_preserve_selected_pc(platform,tmp_path,monkeypatch):
    from aiqa.worker.android_jobs import build_operational_android_recording_handler
    from aiqa.worker.runtime import WorkerRuntime,WorkerRuntimeConfig
    from aiqa.environments.android_app_launch import AppLaunchReceipt
    f=platform;w=worker(f);choose(f,w);sent=[];launches=[]
    def launch(package,*,before_native_send):before_native_send();launches.append(package);return AppLaunchReceipt(package,package+'/.Main')
    monkeypatch.setattr('aiqa.worker.android_jobs._live_android_capture_pair',lambda **kwargs:(_observation,launch))
    handler=build_operational_android_recording_handler(adb_path=Path('adb.exe'),serial=w.serial,expected_avd=None,runtime_root=tmp_path,client=w.client)
    def adb(argv,timeout):sent.append(tuple(argv));return subprocess.CompletedProcess(argv,0,'','')
    handler.driver._runner=adb
    started=start(f);assert started.status_code==201,started.text
    runtime=WorkerRuntime(w.client,WorkerRuntimeConfig(w.boot,frozenset({'recording'})),handler,inventory_provider=lambda:w.payload)
    report=runtime.run_once()
    assert report.finished and report.actions==2,report
    assert launches==['com.example.saved'] and len(sent)==1 and len(f['model_sent'])==2
    assert handler.session_result.process.receipt['main_invocations']==1
    with sqlite3.connect(f['database']) as db:
        assert db.execute('SELECT COUNT(*) FROM recording_manifests').fetchone()[0]==1
        assert db.execute('SELECT COUNT(*) FROM replay_packages').fetchone()[0]==1
        assert db.execute('SELECT COUNT(*) FROM approval_events').fetchone()[0]==0


def save_input(f,definition_changes=None,settings_changes=None):
    with sqlite3.connect(f['database']) as db:
        row=db.execute('SELECT definition_json,settings_json FROM case_versions WHERE version_id=?',(f['body']['input_case_version_id'],)).fetchone()
    definition=json.loads(row[0]);settings=json.loads(row[1]);definition.update(definition_changes or {});settings.update(settings_changes or {})
    async def save():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=f['app']),base_url='http://127.0.0.1') as c:
            headers=await session(c,f['project'])
            result=await c.post(f"/api/v1/projects/{f['project']}/cases/{f['body']['case_id']}/versions",json={
                'definition':definition,'settings':settings,'expected_head':f['body']['input_case_version_id'],'parent_version_id':f['body']['input_case_version_id']},headers={**headers,'Idempotency-Key':str(uuid4())})
            assert result.status_code==201,result.text
            return result.json()
    saved=asyncio.run(save());f['body'].update(input_case_version_id=saved['id'],input_version_hash=saved['content_hash'])


@pytest.mark.parametrize('bad',['zero_actions','one_action','definition_secret','target_secret','goal_limit'])
def test_original_saved_input_restrictions_match_preview_and_enqueue(platform,bad):
    f=platform;w=worker(f);choose(f,w)
    if bad in {'zero_actions','one_action'}:
        save_input(f,settings_changes={'limits':{'timeout_seconds':31,'max_actions':0 if bad=='zero_actions' else 1,'max_model_calls':3,'budget':'0.70','currency':'USD'}})
    elif bad=='definition_secret':save_input(f,definition_changes={'secret_refs':{'account':{'project_id':f['project'],'ref_id':str(f['secret'].ref_id),'revision':f['secret'].revision}}})
    elif bad=='target_secret':save_input(f,settings_changes={'secret_refs':{'account':{'project_id':f['project'],'ref_id':str(f['secret'].ref_id),'revision':f['secret'].revision}}})
    else:save_input(f,definition_changes={'variables':{'query'+str(i):'x'*700 for i in range(20)}})
    preview=start(f,path=f"/api/v1/projects/{f['project']}/recording-previews")
    assert preview.json()['ready'] is False,preview.json()
    assert start(f).status_code==422
    assert f['model_sent']==[]


def test_normal_settings_ui_saves_openai_binding_then_preview_and_start(platform):
    f=platform;w=worker(f);choose(f,w)
    async def save():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=f['app']),base_url='http://127.0.0.1') as c:
            headers=await session(c,f['project'])
            return await c.post(f"/ui/projects/{f['project']}/settings",json={'expected_lock':0,'timeout_seconds':600,
                'roles':[{'role':'authoring','mode':'replace','endpoint':'https://api.openai.com/','model':'gpt-6-luna','key':'synthetic-settings-key'}]},
                headers={**headers,'Idempotency-Key':'settings-openai'})
    saved=asyncio.run(save());assert saved.status_code==201,saved.text
    with sqlite3.connect(f['database']) as db:
        current=db.execute("SELECT provider FROM binding_revisions WHERE project_id=? AND revision_id=(SELECT latest_revision_id FROM model_bindings WHERE project_id=? AND role='authoring')",(f['project'],f['project'])).fetchone()
    assert current[0]=='openai'
    preview=start(f,path=f"/api/v1/projects/{f['project']}/recording-previews")
    assert preview.json()['ready'] is True,preview.json()
    assert start(f).status_code==201


@pytest.mark.parametrize('mode',['fixture','missing','malformed'])
def test_fixture_binding_requires_affirmative_authenticated_fixture_route(platform,mode):
    f=platform;w=worker(f,mode='fixture' if mode=='fixture' else None);choose(f,w)
    if mode=='malformed':
        payload=dict(w.payload);payload['permissions']='[]';w.client.report_inventory(payload,idempotency_key='malformed-'+str(uuid4()))
    with sqlite3.connect(f['database']) as db:_new_revision(db,f['project'],provider='fixture',model='fixture-author',endpoint_kind='loopback',endpoint='http://127.0.0.1')
    result=start(f)
    assert result.status_code==(201 if mode=='fixture' else 422),result.text
    if mode=='fixture':
        with sqlite3.connect(f['database']) as db:
            limits=json.loads(db.execute('SELECT limits FROM jobs WHERE job_id=?',(result.json()['job_id'],)).fetchone()[0])
        assert 'authoring_engine' not in limits


def test_expired_reporting_credential_does_not_leave_authoring_capability_active(platform):
    f=platform;w=worker(f);choose(f,w)
    with sqlite3.connect(f['database']) as db:
        permissions=json.loads(db.execute('SELECT permissions FROM resource_inventory WHERE physical_key_id=?',(w.resource_id,)).fetchone()[0])
        token_id=permissions['authoring_report']['token_id']
        db.execute('UPDATE worker_tokens SET expires_at=? WHERE token_id=?',((datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat(),token_id))
    assert start(f).status_code==422


def test_capability_report_is_scoped_to_authenticated_project_alias(platform):
    from aiqa.domain.projects import bind_store,create_project
    from aiqa.store.models import ProjectCreate
    from worker_presence_support import seed_resource_alias
    from aiqa.recording.mobile_agent_admission import require_recording_report,MobileAgentAdmissionRejected
    f=platform;w=worker(f);store=f['app'].state.open_store()
    try:
        with bind_store(store):other=create_project(Actor(uuid4(),None,True),ProjectCreate('Other alias','other-alias','scope','web'))
        with bound_auth_store(store):token=enroll_worker(Actor(uuid4(),other.project_id,True),w.worker_id,'recording')
        with store.transaction() as db:seed_resource_alias(db,str(other.project_id),w.resource_id,target_kind='android')
    finally:store.close()
    with WorkerHttpClient(WorkerClientSettings('https://127.0.0.1',token),transport=SyncASGITransport(f['app'])) as other_client:
        other_client.heartbeat(w.boot)
    with sqlite3.connect(f['database']) as db:
        assert require_recording_report(db,UUID(f['project']),w.resource_id)=='original'
        with pytest.raises(MobileAgentAdmissionRejected):require_recording_report(db,other.project_id,w.resource_id)


def test_binding_and_server_blockers_link_to_settings(platform):
    f=platform;w=worker(f);choose(f,w);f['app'].state.settings=replace(f['app'].state.settings,model_price_mode='strict')
    preview=start(f,path=f"/api/v1/projects/{f['project']}/recording-previews")
    engine=next(reason for reason in preview.json()['reasons'] if reason['code']=='engine')
    assert engine['href']==f"/ui/projects/{f['project']}/settings"
