"""Recording review actions refer to this stored source, not another case candidate."""
from datetime import datetime,timezone,timedelta
from html import unescape
from pathlib import Path
import asyncio,base64,json,re,sqlite3,subprocess
import httpx,pytest
from test_ma04_engine_authority import platform,ux_app,worker,choose
from test_ma05_failure_state import handler_for
from test_ma05_failure_evidence import run
from test_ma05_server_stop import cancel
from test_rx97_recording_pin import request as start
from unit.test_openai_provider_settings import response
from unit.test_mobile_agent_context import reply
from ux_support import session


def link(html,identity):
    for attrs in re.findall(r'<a\b([^>]*)>',html):
        values={key:unescape(value) for key,value in re.findall(r'([\w-]+)="([^"]*)"',attrs)}
        if values.get('id')==identity:return values.get('href')
    return None


def page(f,recording,action_id=None):
    async def get():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=f['app']),base_url='http://127.0.0.1') as c:
            headers=await session(c,f['project'])
            result=await c.get(f"/ui/projects/{f['project']}/recordings/{recording}",params={'action_id':action_id} if action_id else {},headers=headers)
            timeline=await c.get(f"/api/v1/projects/{f['project']}/recordings/{recording}/timeline",params={'action_id':action_id} if action_id else {},headers=headers)
            assert result.status_code==200,result.text
            return result.text,timeline.json()
    return asyncio.run(get())


def export(f,name,html,timeline):
    folder=Path('.review-work/mobile-agent-review-ui')
    folder.mkdir(parents=True,exist_ok=True)
    (folder/(name+'.html')).write_text(html,encoding='utf-8')
    (folder/(name+'-timeline.json')).write_text(json.dumps(timeline),encoding='utf-8')
    from aiqa.store.artifacts import resolve_stored
    store=f['app'].state.open_store()
    try:
        with sqlite3.connect(f['database']) as db:
            objects=db.execute("SELECT artifact_id,object_key,media_type FROM artifact_objects WHERE status='ready' AND acked=1").fetchall()
        assets={identity:{'media_type':media,'body_b64':base64.b64encode(resolve_stored(store.config.artifacts_dir,key).read_bytes()).decode()}
            for identity,key,media in objects}
        (folder/(name+'-assets.json')).write_text(json.dumps(assets),encoding='utf-8')
    finally:store.close()


def test_failed_recording_never_opens_another_candidate_and_rerecord_pins_own_input(platform,tmp_path,monkeypatch):
    f=platform;w=worker(f);choose(f,w);handler,_=handler_for(f,w,tmp_path,monkeypatch)
    handler.driver._runner=lambda argv,timeout:subprocess.CompletedProcess(argv,0,'','')
    complete,_=run(f,w,handler)
    with sqlite3.connect(f['database']) as db:
        produced=db.execute('SELECT produced_version_id FROM materialization_receipts').fetchone()[0]
    normal,timeline=page(f,complete['recording_id']);export(f,'completed',normal,timeline)
    assert link(normal,'recording-review-link')==f"/ui/projects/{f['project']}/cases/{f['body']['case_id']}/review?version={produced}"
    assert 'data-approved="false"' in normal
    # Another recording of the same case fails; the previous candidate remains a valid stored version.
    def click(req):
        f['model_sent'].append(req);body=response();body['output'][-1]['content'][0]['text']=reply({'action':'click','coordinate':[500,500]})
        return httpx.Response(200,json=body)
    f['app'].state.model_gateway.provider._transport=httpx.MockTransport(click)
    failed_handler,_=handler_for(f,w,tmp_path,monkeypatch)
    started=start(f,key='separate-failed-candidate');assert started.status_code==201,started.text
    from aiqa.worker.runtime import WorkerRuntime,WorkerRuntimeConfig
    assert WorkerRuntime(w.client,WorkerRuntimeConfig(w.boot,frozenset({'recording'})),failed_handler,inventory_provider=lambda:w.payload).run_once().finished
    with sqlite3.connect(f['database']) as db:
        db.execute('UPDATE worker_presence SET last_seen=? WHERE project_id=? AND worker_id=?',((datetime.now(timezone.utc)-timedelta(minutes=3)).isoformat(),f['project'],w.worker_id))
    failed,timeline=page(f,started.json()['recording_id'])
    failed,timeline=page(f,started.json()['recording_id'],next(a['action_id'] for a in timeline['actions'] if a['dispatch_state']=='unknown'));export(f,'failed',failed,timeline)
    assert link(failed,'recording-review-link') is None
    assert 'id="recording-offline-gate"' not in failed,'candidate readiness must not fall back to another source'
    assert link(failed,'recording-rerecord-link')==f"/ui/projects/{f['project']}/cases/{f['body']['case_id']}/rerecord?base={f['body']['input_case_version_id']}"
    assert link(failed,'recording-case-link')==f"/ui/projects/{f['project']}/cases/{f['body']['case_id']}/definition"
    assert timeline['completion_status']=='error' and any(a['log']=='stored' for a in timeline['actions'])
    with sqlite3.connect(f['database']) as db:
        assert db.execute('SELECT COUNT(*) FROM approval_events').fetchone()[0]==0
        assert db.execute('SELECT produced_version_id FROM materialization_receipts').fetchone()[0]==produced


@pytest.mark.parametrize('state,label',[('open','녹화 진행 중'),('interrupted','녹화 중단'),('error','녹화 실패')])
def test_recording_state_and_next_action_use_user_terms_without_changing_polling(platform,tmp_path,monkeypatch,state,label):
    f=platform;w=worker(f);choose(f,w)
    if state=='error':
        handler,_=handler_for(f,w,tmp_path,monkeypatch);started,_=run(f,w,handler)
    else:
        result=start(f);assert result.status_code==201;started=result.json()
        if state=='interrupted':assert cancel(f,started['job_id']).status_code==202
    html,timeline=page(f,started['recording_id']);export(f,state,html,timeline)
    assert label in html
    assert f'data-completion-status="{state}"' in html
    assert 'id="recording-candidate-state"' in html and link(html,'recording-review-link') is None
    assert 'compiler가' not in html and '<p>package ' not in html
    if state=='open':assert link(html,'recording-rerecord-link') is None
    else:assert '재녹화 준비' in html and '서버에 기록 보관됨' in html and '증거 확인 필요' in html


def test_legacy_stop_without_screenshots_never_claims_received_evidence(platform):
    f=platform;w=worker(f);choose(f,w);started=start(f);assert started.status_code==201
    async def stop():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=f['app']),base_url='http://127.0.0.1') as c:
            headers=await session(c,f['project'])
            return await c.post('/api/v1/recordings/'+started.json()['recording_id']+'/stop',json={'project_id':f['project']},headers={**headers,'Idempotency-Key':'legacy-stop-ui'})
    assert asyncio.run(stop()).status_code==201
    with sqlite3.connect(f['database']) as db:
        assert db.execute('SELECT evidence_status FROM recordings').fetchone()[0]=='complete'
    html,timeline=page(f,started.json()['recording_id'])
    assert timeline['actions']==[]
    assert 'id="recording-evidence-status" data-ready="false"' in html and '증거 확인 필요' in html
    assert '필수 증거 수신 완료' not in html


@pytest.mark.parametrize('damage',['missing','corrupt'])
def test_missing_or_corrupt_source_file_blocks_received_summary(platform,tmp_path,monkeypatch,damage):
    from aiqa.store.artifacts import resolve_stored
    f=platform;w=worker(f);choose(f,w);handler,_=handler_for(f,w,tmp_path,monkeypatch)
    handler.driver._runner=lambda argv,timeout:subprocess.CompletedProcess(argv,0,'','')
    complete,_=run(f,w,handler)
    normal,_=page(f,complete['recording_id'])
    assert 'id="recording-evidence-status" data-ready="true"' in normal
    store=f['app'].state.open_store()
    try:
        with sqlite3.connect(f['database']) as db:
            key=db.execute("SELECT object_key FROM artifact_objects WHERE role='after' AND action_id LIKE 'ma-%' LIMIT 1").fetchone()[0]
        target=resolve_stored(store.config.artifacts_dir,key);original=target.read_bytes()
        try:
            if damage=='missing':target.unlink()
            else:target.write_bytes(b'synthetic corrupt image')
            html,timeline=page(f,complete['recording_id'])
        finally:target.write_bytes(original)
    finally:store.close()
    assert any(item['after']==damage for item in timeline['actions'])
    assert 'id="recording-evidence-status" data-ready="false"' in html and '증거 확인 필요' in html
