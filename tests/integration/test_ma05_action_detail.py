"""Selected evidence explains commands honestly and tolerates unreadable stored logs."""
import asyncio,base64,hashlib,json,sqlite3,subprocess
from pathlib import Path
from datetime import datetime,timezone
from uuid import uuid4
import httpx,pytest
from test_ma04_engine_authority import platform,ux_app,worker,choose,claim
from test_ma05_failure_state import handler_for
from test_ma05_failure_evidence import run
from test_ma05_recording_review_ui import page,export
from test_rx97_recording_pin import request as start
from test_rx_65 import _observation
from unit.test_openai_provider_settings import response
from unit.test_mobile_agent_context import reply


@pytest.mark.parametrize('mode',['unknown','swipe','text','key'])
def test_selected_original_action_explains_saved_command_and_coordinates(platform,tmp_path,monkeypatch,mode):
    f=platform
    if mode=='text':
        from test_ma04_engine_authority import save_input
        save_input(f,definition_changes={'variables':{'query':'Saved'}})
    w=worker(f);choose(f,w);handler,sent=handler_for(f,w,tmp_path,monkeypatch)
    actions={'unknown':{'action':'click','coordinate':[500,500]},'swipe':{'action':'swipe','coordinate':[100,200],'coordinate2':[800,900]},
             'text':{'action':'type','text':'Saved'},'key':{'action':'system_button','button':'Back'}}
    requests=[]
    def provider(req):
        requests.append(req);result=response();result['output'][-1]['content'][0]['text']=reply(actions[mode] if len(requests)==1 else {'action':'terminate','status':'success'})
        return httpx.Response(200,json=result)
    f['app'].state.model_gateway.provider._transport=httpx.MockTransport(provider)
    if mode!='unknown':handler.driver._runner=lambda argv,timeout:subprocess.CompletedProcess(argv,0,'','')
    started,_=run(f,w,handler)
    _,timeline=page(f,started['recording_id']);action=next(a for a in timeline['actions'] if a['action_id'].startswith('ma-'))
    html,timeline=page(f,started['recording_id'],action['action_id']);export(f,'detail-'+mode,html,timeline)
    assert 'data-command-summary' in html and '기록된 geometry만' not in html
    assert '원본 참조·시각' in html and '<h3>단계 '+action['step_id'] not in html
    assert '<details class="evidence-log" open>' not in html
    if mode=='unknown':
        assert '요청 명령' in html and '(50, 100)' in html and '전달 결과 확인 불가' in html
        assert '100 × 200' in html and len(requests)==1 and len(sent)==1
    elif mode=='swipe':
        assert '(9, 40)' in html and '(79, 179)' in html and '800ms' in html
        assert '이 행동의 swipe 좌표는 없습니다.' not in html
    elif mode=='text':assert '텍스트 입력' in html and '5자' in html
    else:assert '뒤로가기' in html and '키 코드 4' in html
    with sqlite3.connect(f['database']) as db:assert db.execute('SELECT COUNT(*) FROM approval_events').fetchone()[0]==0


@pytest.mark.parametrize('fault',['nonutf8','read_race','hash_race','state_error','resolve_state','resolve_log'])
def test_unreadable_log_keeps_recording_and_timeline_readable(platform,monkeypatch,fault):
    f=platform;w=worker(f);choose(f,w);started=start(f);assert started.status_code==201
    job=claim(f,w);assert job is not None
    w.client.acknowledge(project_id=f['project'],job_id=job['job_id'],generation=job['generation'],runner_nonce=str(uuid4()),
        now=datetime.now(timezone.utc).isoformat(),idempotency_key='invalid-log-ack')
    parts=[]
    for role,body,media in [('before',_observation().png,'image/png'),('log',b'\xff\xfe\x80','text/plain')]:
        parts.append({'filename':'legacy.'+('png' if role=='before' else 'log'),'media_type':media,'declared_length':len(body),
            'declared_hash':'sha256:'+hashlib.sha256(body).hexdigest(),'body_b64':base64.b64encode(body).decode(),
            'owner_kind':'REC','attempt_id':job['attempt_id'],'action_id':'legacy-unreadable','role':role})
    w.client.commit_evidence(sanitized=True,project_id=f['project'],job_id=job['job_id'],generation=job['generation'],
        now=datetime.now(timezone.utc).isoformat(),events=[],artifacts=parts,idempotency_key='invalid-log-body')
    original_read=Path.read_bytes
    if fault!='nonutf8':
        from aiqa.store.artifacts import resolve_stored
        store=f['app'].state.open_store()
        try:
            with sqlite3.connect(f['database']) as db:key=db.execute("SELECT object_key FROM artifact_objects WHERE role='log'").fetchone()[0]
            log_path=resolve_stored(store.config.artifacts_dir,key)
        finally:store.close()
        calls=[]
        def read(path):
            if path==log_path:
                calls.append(1)
                if fault=='state_error' or len(calls)%2==0:
                    if fault=='hash_race':return b'changed during read'
                    raise OSError('synthetic read race')
            return original_read(path)
        if fault.startswith('resolve_'):
            import aiqa.api.artifacts as api
            resolver=api.resolve_stored
            def resolve(root,object_key):
                if object_key==key:
                    calls.append(1)
                    if fault=='resolve_state' or len(calls)%2==0:raise PermissionError('synthetic resolve failure')
                return resolver(root,object_key)
            monkeypatch.setattr(api,'resolve_stored',resolve)
        else:monkeypatch.setattr(Path,'read_bytes',read)
    html,timeline=page(f,started.json()['recording_id'])
    reason={'hash_race':'파일 내용이 보관 hash와 다릅니다.','state_error':'파일이 없습니다.','resolve_state':'파일이 없습니다.'}.get(fault,'로그를 읽을 수 없습니다.')
    assert reason in html
    if fault=='nonutf8':export(f,'detail-unreadable',html,timeline)
    assert timeline['actions'][0]['log']=='missing'
    assert 'id="recording-evidence-status" data-ready="false"' in html
    with sqlite3.connect(f['database']) as db:
        assert db.execute("SELECT COUNT(*) FROM artifact_objects WHERE role='log' AND status='ready'").fetchone()[0]==1
    assert f['model_sent']==[]


@pytest.mark.parametrize('fault',['native_mismatch','receipt_missing','protocol_unavailable','protocol_import','invalid_plan','frame_missing','owner_item','roles_missing'])
def test_command_detail_requires_matching_saved_model_receipt(platform,tmp_path,monkeypatch,fault):
    from aiqa.api.artifacts import _viewer
    from aiqa.api.artifacts import EvidenceViewerSelection
    from aiqa.recording.action_evidence_display import describe_action_evidence
    import aiqa.recording.action_evidence_display as display
    from uuid import UUID
    f=platform;w=worker(f);choose(f,w);handler,_=handler_for(f,w,tmp_path,monkeypatch)
    started,_=run(f,w,handler)
    _,body=page(f,started['recording_id']);action=next(a for a in body['actions'] if a['action_id'].startswith('ma-'))
    selection=EvidenceViewerSelection('REC',started['recording_id'],body['attempt_id'],action['action_id'])
    store=f['app'].state.open_store()
    try:
        with sqlite3.connect(f['database']) as db:
            view=_viewer(db,store.config.artifacts_dir,UUID(f['project']),selection,datetime.now(timezone.utc))
            saved=next(a for a in view.actions if a.action_id==action['action_id'])
            rows=db.execute('SELECT action_id,role,artifact_id,object_key,content_hash,status,custody,stored_at,media_type FROM artifact_objects WHERE attempt_id=? AND action_id=?',(body['attempt_id'],action['action_id'])).fetchall()
            roles={row[1]:row for row in rows};raw=saved.log_text
            if fault=='native_mismatch':
                doc=json.loads(raw);doc['native']['x']=1;raw=json.dumps(doc)
            if fault in {'protocol_unavailable','protocol_import'}:
                def unavailable():
                    if fault=='protocol_import':raise ModuleNotFoundError('synthetic optional module unavailable')
                    raise ValueError('synthetic pinned protocol unavailable')
                monkeypatch.setattr(display,'load_protocol',unavailable,raising=False)
            if fault=='invalid_plan':
                from aiqa.replay.android_plan import PlanRejected
                def invalid(*args):raise PlanRejected('synthetic legacy invalid action')
                monkeypatch.setattr(display,'upstream_action',invalid)
            if fault=='owner_item':selection=EvidenceViewerSelection('ITEM',selection.owner_id,selection.attempt_id,selection.action_id)
            if fault=='roles_missing':roles={}
            class MissingReceipt:
                def execute(self,query,args):
                    if (fault=='receipt_missing' and 'model_request_receipts' in query) or (fault=='frame_missing' and 'FROM model_observations' in query):return db.execute('SELECT 1 WHERE 0')
                    return db.execute(query,args)
            result=describe_action_evidence(MissingReceipt() if fault in {'receipt_missing','frame_missing'} else db,UUID(f['project']),selection,
                action_id=action['action_id'],action_seq=2,dispatch_state=action['dispatch_state'],roles=roles,
                before=saved.before,after=saved.after,log_text=raw)
            assert result.coordinates=='' and result.swipe_path==''
            assert result.label=='동작 2'
            if fault!='owner_item':assert result.state_label=='명령 근거 확인 필요'
            assert db.execute('SELECT COUNT(*) FROM approval_events').fetchone()[0]==0
    finally:store.close()
