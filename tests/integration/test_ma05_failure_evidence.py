"""Original failure facts are evidence, never successful history/replay source."""
from dataclasses import replace
from pathlib import Path
import asyncio, base64, hashlib, json, sqlite3, subprocess
import httpx,pytest
from test_ma04_engine_authority import platform,ux_app,worker,choose
from test_ma05_failure_state import handler_for,recording_state
from test_rx97_recording_pin import request as start
from test_rx_65 import _observation
from ux_support import session
from aiqa.worker.runtime import WorkerRuntime,WorkerRuntimeConfig
from aiqa.store.artifacts import resolve_stored


def facts(f):
    with sqlite3.connect(f['database']) as db:
        action=db.execute("SELECT action_id,dispatch_state,outcome_known FROM actions WHERE action_id LIKE 'ma-%' ORDER BY action_seq LIMIT 1").fetchone()
        objects=db.execute("SELECT role,object_key,content_hash FROM artifact_objects WHERE action_id=? ORDER BY rowid",(action[0],)).fetchall()
        events=db.execute('SELECT COUNT(*) FROM attempt_events').fetchone()[0]
    return action,objects,events


def read_log(f,objects):
    key=next(key for role,key,digest in objects if role=='log')
    store=f['app'].state.open_store()
    try:return json.loads(resolve_stored(store.config.artifacts_dir,key).read_bytes())
    finally:store.close()


def run(f,w,handler):
    started=start(f);assert started.status_code==201,started.text
    report=WorkerRuntime(w.client,WorkerRuntimeConfig(w.boot,frozenset({'recording'})),handler,inventory_provider=lambda:w.payload).run_once()
    assert report.finished,report
    return started.json(),report


def test_native_timeout_saves_unknown_log_without_retry_or_source(platform,tmp_path,monkeypatch):
    f=platform;w=worker(f);choose(f,w);handler,sent=handler_for(f,w,tmp_path,monkeypatch)
    started,report=run(f,w,handler)
    action,objects,events=facts(f)
    assert action[1:]==('unknown',0)
    assert [role for role,_,_ in objects]==['before','log']
    log=read_log(f,objects)
    assert log['schema']=='mobile-agent-failure-v1' and log['state']=='unknown'
    assert log['native_calls']==0 and log['reason']=='dispatch_unknown'
    assert log['native']['kind']=='tap' and log['native']['x']==50 and log['native']['y']==100
    assert log['action_id']==action[0] and log['call_id']==action[0][3:]
    assert log['before_image_hash']==objects[0][2]
    assert events==0 and report.actions==1 and len(sent)==1 and len(f['model_sent'])==1
    assert handler.session_result.action_mapping=='{}' and not handler.session_result.review_pending
    assert recording_state(f,started['recording_id'])==('error','stopped','stored','incomplete')


def test_native_ack_then_after_capture_failure_saves_known_fact_with_no_after(platform,tmp_path,monkeypatch):
    f=platform;w=worker(f);choose(f,w);handler,sent=handler_for(f,w,tmp_path,monkeypatch)
    captures=[]
    def capture():
        captures.append(1)
        # App preparation uses its separately bound capture. Session reads before/fresh/after.
        if len(captures)==3:raise OSError('synthetic-private-raw-exception')
        return _observation()
    handler.context.live_capture=capture
    def ack(argv,timeout):sent.append(tuple(argv));return subprocess.CompletedProcess(argv,0,'','')
    handler.driver._runner=ack
    _,report=run(f,w,handler)
    action,objects,events=facts(f)
    assert action[1:]==('acknowledged',1)
    assert [role for role,_,_ in objects]==['before','log']
    log=read_log(f,objects)
    assert log['state']=='acknowledged' and log['native_calls']==1 and log['reason']=='after_capture_failed'
    assert 'synthetic-private-raw-exception' not in json.dumps(log)
    assert events==0 and report.actions==2 and len(sent)==1 and len(f['model_sent'])==1
    assert len(captures)==3 and handler.session_result.action_mapping=='{}'


def test_frame_drift_is_known_not_sent_and_never_unknown(platform,tmp_path,monkeypatch):
    f=platform;w=worker(f);choose(f,w);handler,sent=handler_for(f,w,tmp_path,monkeypatch)
    captures=[]
    def capture():
        captures.append(1)
        return _observation(fill=b'\x00\xff\x00' if len(captures)>1 else b'\xff\x00\x00')
    handler.context.live_capture=capture
    _,report=run(f,w,handler)
    action,objects,events=facts(f)
    assert action[1:]==('lookup_failed',1)
    log=read_log(f,objects)
    assert log['state']=='not_sent' and log['native_calls']==0
    assert not handler.session_result.ambiguous_dispatch and report.actions==1
    assert sent==[] and len(f['model_sent'])==1 and events==0


def test_model_before_is_only_planned_until_verified_turn_evidence(platform,tmp_path,monkeypatch):
    f=platform;w=worker(f);choose(f,w);handler,_=handler_for(f,w,tmp_path,monkeypatch)
    seen=[];request=w.client.request_model
    def inspect(**kwargs):
        with sqlite3.connect(f['database']) as db:
            seen.append(db.execute("SELECT dispatch_state,outcome_known FROM actions WHERE action_id LIKE 'ma-%'").fetchone())
        return request(**kwargs)
    monkeypatch.setattr(w.client,'request_model',inspect)
    run(f,w,handler)
    assert seen==[('planned',0)]


@pytest.mark.parametrize('tamper',['reason_type','native_number_type','call','before_hash','native','count','extra','duplicate','events','owner'])
def test_server_rejects_unbound_or_malformed_failure_fact(platform,tmp_path,monkeypatch,tamper):
    from copy import deepcopy
    from aiqa.worker.http_client import WorkerHttpError
    f=platform;w=worker(f);choose(f,w);handler,sent=handler_for(f,w,tmp_path,monkeypatch)
    commit=w.client.commit_evidence;rejected=[]
    def inspect(**payload):
        if any(p.get('filename','').endswith('-failure.log') for p in payload['artifacts']):
            bad=deepcopy(payload);bad['idempotency_key']+='-bad-'+tamper
            part=bad['artifacts'][0];doc=json.loads(base64.b64decode(part['body_b64']))
            if tamper=='reason_type':doc['reason']=[]
            elif tamper=='native_number_type':doc['native']['duration_ms']=300.0
            elif tamper=='call':doc['call_id']='00000000-0000-4000-8000-000000000000'
            elif tamper=='before_hash':doc['before_image_hash']='sha256:'+'00'*32
            elif tamper=='native':doc['native']['x']=1
            elif tamper=='count':doc['native_calls']=True
            elif tamper=='extra':doc['raw_exception']='never accepted'
            elif tamper=='events':bad['events']=[{'invalid':'synthetic'}]
            elif tamper=='owner':part['owner_kind']='ITEM'
            raw=json.dumps(doc,separators=(',',':')).encode()
            if tamper=='duplicate':raw=raw[:-1]+b',"state":"unknown"}'
            part.update(body_b64=base64.b64encode(raw).decode(),declared_hash='sha256:'+hashlib.sha256(raw).hexdigest(),declared_length=len(raw))
            try:
                result=commit(**bad);rejected.append(('accepted',result))
            except WorkerHttpError as exc:rejected.append(('rejected',exc.status_code))
        return commit(**payload)
    monkeypatch.setattr(w.client,'commit_evidence',inspect)
    run(f,w,handler)
    assert rejected==[('rejected',422)],rejected
    action,objects,_=facts(f)
    assert action[1:]==('unknown',0) and len([p for p in objects if p[0]=='log'])==1
    assert len(sent)==1 and len(f['model_sent'])==1


def test_failure_log_lost_ack_recovers_only_same_packet_after_finish(platform,tmp_path,monkeypatch):
    from copy import deepcopy
    from aiqa.worker.http_client import WorkerHttpError,RetryClass
    f=platform;w=worker(f);choose(f,w);handler,sent=handler_for(f,w,tmp_path,monkeypatch)
    commit=w.client.commit_evidence;packets=[]
    def lose(**payload):
        ack=commit(**payload)
        if any(p.get('filename','').endswith('-failure.log') for p in payload['artifacts']):
            packets.append(deepcopy(payload))
            if len(packets)<=2:raise WorkerHttpError('synthetic lost ACK',retry_class=RetryClass.timeout)
        return ack
    monkeypatch.setattr(w.client,'commit_evidence',lose)
    started,report=run(f,w,handler)
    before_calls=(len(sent),len(f['model_sent']))
    # Recovery uses the owning durable journal; never the runtime handler again.
    from aiqa.worker.step_evidence import StepEvidenceCommitter
    with sqlite3.connect(f['database']) as db:
        attempt=db.execute('SELECT attempt_id,generation FROM attempts WHERE job_id=?',(started['job_id'],)).fetchone()
    claim={'project_id':f['project'],'job_id':started['job_id'],'attempt_id':attempt[0],'generation':attempt[1],'worker_id':w.worker_id}
    path=tmp_path/'mobile-agent'/f['project']/attempt[0]/'session/evidence-delivery.json'
    recovery=StepEvidenceCommitter(w.client,claim,namespace='mobile',pending_path=path)
    recovered=recovery.resume_pending()
    assert report.finished and handler.session_result.evidence_pending
    assert recovered is None  # Runtime already confirmed this exact frozen packet before finishing.
    assert len(packets)==3 and all(p==packets[0] for p in packets)
    assert recovery.resume_pending() is None
    assert before_calls==(len(sent),len(f['model_sent']))==(1,1)
    assert recording_state(f,started['recording_id'])==('error','stopped','stored','incomplete')
    action,objects,_=facts(f);assert action[1:]==('unknown',0)
    assert len([p for p in objects if p[0]=='log'])==1


def test_unknown_timeline_and_sanitized_log_readable_without_execution_pc(platform,tmp_path,monkeypatch):
    from datetime import datetime,timezone,timedelta
    f=platform;w=worker(f);choose(f,w);handler,sent=handler_for(f,w,tmp_path,monkeypatch)
    started,_=run(f,w,handler);action,objects,_=facts(f)
    with sqlite3.connect(f['database']) as db:
        log_id=db.execute("SELECT artifact_id FROM artifact_objects WHERE action_id=? AND role='log'",(action[0],)).fetchone()
        assert log_id is not None,'failed action log was never stored'
        db.execute('UPDATE worker_presence SET last_seen=? WHERE project_id=? AND worker_id=?',((datetime.now(timezone.utc)-timedelta(minutes=3)).isoformat(),f['project'],w.worker_id))
    async def read():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=f['app']),base_url='http://127.0.0.1') as c:
            headers=await session(c,f['project'])
            timeline=await c.get(f"/api/v1/projects/{f['project']}/recordings/{started['recording_id']}/timeline",headers=headers)
            log=await c.get('/api/v1/artifacts/'+log_id[0],headers=headers)
            return timeline,log
    timeline,log=asyncio.run(read())
    assert timeline.status_code==200 and log.status_code==200
    saved=next(item for item in timeline.json()['actions'] if item['action_id']==action[0])
    assert saved['dispatch_state']=='unknown' and saved['before']=='stored' and saved['after']=='missing' and saved['log']=='stored'
    assert log.json()==read_log(f,objects)
    assert len(sent)==1 and len(f['model_sent'])==1


def _part_bytes(part,raw):
    part.update(body_b64=base64.b64encode(raw).decode(),declared_hash='sha256:'+hashlib.sha256(raw).hexdigest(),declared_length=len(raw))


def _event_detail(event,**changes):
    doc=json.loads(event['detail_payload']);doc.update(changes)
    detail=json.dumps(doc,sort_keys=True,separators=(',',':'))
    event.update(detail_payload=detail,body_hash='sha256:'+hashlib.sha256(detail.encode()).hexdigest(),
        payload_hash='sha256:'+hashlib.sha256((str(event['local_seq'])+'\n'+detail).encode()).hexdigest())


@pytest.mark.parametrize('tamper',['duplicate_events','wrong_action','wrong_image','wrong_phase','event_hash','after_geometry'])
def test_observed_packet_requires_exact_pair_and_same_geometry(platform,tmp_path,monkeypatch,tamper):
    from copy import deepcopy
    from aiqa.worker.http_client import WorkerHttpError
    from test_rx_65 import _png
    f=platform;w=worker(f);choose(f,w);handler,sent=handler_for(f,w,tmp_path,monkeypatch)
    handler.driver._runner=lambda argv,timeout:subprocess.CompletedProcess(argv,0,'','')
    commit=w.client.commit_evidence;rejected=[]
    def inspect(**payload):
        if payload['events'] and not rejected:
            bad=deepcopy(payload);bad['idempotency_key']+='-bad-'+tamper
            if tamper=='duplicate_events':bad['events'][1]=deepcopy(bad['events'][0])
            elif tamper=='wrong_action':_event_detail(bad['events'][1],action_id='ma-00000000-0000-4000-8000-000000000000')
            elif tamper=='wrong_image':_event_detail(bad['events'][1],png_sha256='sha256:'+'00'*32)
            elif tamper=='wrong_phase':_event_detail(bad['events'][1],phase='before')
            elif tamper=='event_hash':bad['events'][1]['body_hash']='sha256:'+'00'*32
            else:
                after=next(p for p in bad['artifacts'] if p['role']=='after');_part_bytes(after,_png(50,100))
                log=next(p for p in bad['artifacts'] if p['role']=='log');doc=json.loads(base64.b64decode(log['body_b64']));doc['after_image_hash']=after['declared_hash'];_part_bytes(log,json.dumps(doc).encode())
                _event_detail(bad['events'][1],png_sha256=after['declared_hash'])
            try:rejected.append(('accepted',commit(**bad)))
            except WorkerHttpError as exc:rejected.append(('rejected',exc.status_code))
        return commit(**payload)
    monkeypatch.setattr(w.client,'commit_evidence',inspect)
    started=start(f);assert started.status_code==201
    report=WorkerRuntime(w.client,WorkerRuntimeConfig(w.boot,frozenset({'recording'})),handler,inventory_provider=lambda:w.payload).run_once()
    assert rejected==[('rejected',422)],rejected
    assert report.finished and handler.session_result.review_pending


@pytest.mark.parametrize('role',['before','log'])
def test_same_call_role_cannot_change_under_new_key(platform,tmp_path,monkeypatch,role):
    from copy import deepcopy
    from aiqa.worker.http_client import WorkerHttpError
    from test_rx_65 import _png
    f=platform;w=worker(f);choose(f,w);handler,_=handler_for(f,w,tmp_path,monkeypatch)
    captures=[]
    def capture():
        captures.append(1)
        if len(captures)==3:raise OSError('synthetic capture failure')
        return _observation()
    handler.context.live_capture=capture
    handler.driver._runner=lambda argv,timeout:subprocess.CompletedProcess(argv,0,'','')
    commit=w.client.commit_evidence;responses=[]
    def inspect(**payload):
        ack=commit(**payload)
        if any(p.get('filename','').endswith('-failure.log') for p in payload['artifacts']):
            bad=deepcopy(payload);bad['idempotency_key']+='-alternate-role'
            if role=='log':
                part=bad['artifacts'][0];doc=json.loads(base64.b64decode(part['body_b64']));doc['reason']='execution_stopped';_part_bytes(part,json.dumps(doc).encode())
            else:
                part=bad['artifacts'][0];part.update(role='before',filename='alternate-before.png',media_type='image/png');_part_bytes(part,_png(fill=b'\x00\xff\x00'))
            try:responses.append(('accepted',commit(**bad)))
            except WorkerHttpError as exc:responses.append(('rejected',exc.status_code))
        return ack
    monkeypatch.setattr(w.client,'commit_evidence',inspect)
    run(f,w,handler)
    assert responses==[('rejected',409)],responses
    action,objects,_=facts(f)
    assert action[1:]==('acknowledged',1) and len(objects)==2


@pytest.mark.parametrize('recovery_mode',['manual','loop','external_receipt'])
def test_unconfirmed_observed_packet_defers_finish_and_recovers_without_execution(platform,tmp_path,monkeypatch,recovery_mode):
    from copy import deepcopy
    from aiqa.worker.http_client import WorkerHttpError,RetryClass
    f=platform;w=worker(f);choose(f,w);handler,sent=handler_for(f,w,tmp_path,monkeypatch)
    def ack(argv,timeout):sent.append(tuple(argv));return subprocess.CompletedProcess(argv,0,'','')
    handler.driver._runner=ack
    commit=w.client.commit_evidence;packets=[];blocked=[True];finishes=[];finish=w.client.finish_attempt
    def lose(**payload):
        receipt=commit(**payload)
        if payload['events']:
            packets.append(deepcopy(payload))
            if blocked[0]:raise WorkerHttpError('synthetic lost observed ACK',retry_class=RetryClass.timeout)
        return receipt
    def remember(**kwargs):finishes.append(kwargs);return finish(**kwargs)
    monkeypatch.setattr(w.client,'commit_evidence',lose);monkeypatch.setattr(w.client,'finish_attempt',remember)
    started=start(f);assert started.status_code==201
    runtime=WorkerRuntime(w.client,WorkerRuntimeConfig(w.boot,frozenset({'recording'})),handler,inventory_provider=lambda:w.payload)
    report=runtime.run_once()
    assert not report.finished and report.reason=='evidence_commit_pending',report
    assert finishes==[] and runtime.pending_finish is None
    calls=(len(sent),len(f['model_sent']))
    pending=runtime.run_once()
    assert not pending.finished and pending.reason=='evidence_commit_pending'
    assert runtime.claims==1 and finishes==[] and calls==(len(sent),len(f['model_sent']))
    blocked[0]=False
    if recovery_mode=='loop':
        recovered=runtime.run_once()
        assert recovered.finished and runtime.claims==1
    else:
        if recovery_mode=='external_receipt':
            with sqlite3.connect(f['database']) as db:
                attempt=db.execute('SELECT attempt_id,generation FROM attempts WHERE job_id=?',(started.json()['job_id'],)).fetchone()
            from aiqa.worker.step_evidence import StepEvidenceCommitter
            claim={'project_id':f['project'],'job_id':started.json()['job_id'],'attempt_id':attempt[0],'generation':attempt[1],'worker_id':w.worker_id}
            path=tmp_path/'mobile-agent'/f['project']/attempt[0]/'session/evidence-delivery.json'
            assert StepEvidenceCommitter(w.client,claim,namespace='mobile',pending_path=path).resume_pending() is not None
        recovered=runtime.confirm_pending_evidence()
        assert recovered is not None and recovered['status']=='error'
    assert len(finishes)==1 and finishes[0]['payload']['last_ack_seq']==2
    assert all(p==packets[0] for p in packets)
    assert calls==(len(sent),len(f['model_sent']))==(1,1)
    assert runtime.total_actions==2 and runtime.finished==1 and runtime.pending_evidence is False
    assert recording_state(f,started.json()['recording_id'])==('error','stopped','stored','incomplete')


def test_repeated_ack_journal_failure_cannot_erase_pending_cursor_recovery(platform,tmp_path,monkeypatch):
    import aiqa.worker.step_evidence as delivery
    f=platform;w=worker(f);choose(f,w);handler,sent=handler_for(f,w,tmp_path,monkeypatch)
    def ack(argv,timeout):sent.append(tuple(argv));return subprocess.CompletedProcess(argv,0,'','')
    handler.driver._runner=ack
    write=delivery.atomic_write;blocked=[True];finishes=[];finish=w.client.finish_attempt
    def disk(path,data):
        state=json.loads(data)
        if blocked[0] and state['pending_seq'] is None and state['entries']:
            raise OSError('synthetic ACK receipt fsync failure')
        return write(path,data)
    def remember(**kwargs):finishes.append(kwargs);return finish(**kwargs)
    monkeypatch.setattr(delivery,'atomic_write',disk);monkeypatch.setattr(w.client,'finish_attempt',remember)
    started=start(f);assert started.status_code==201
    runtime=WorkerRuntime(w.client,WorkerRuntimeConfig(w.boot,frozenset({'recording'})),handler,inventory_provider=lambda:w.payload)
    report=runtime.run_once()
    assert not report.finished and report.reason=='evidence_commit_pending',report
    assert finishes==[] and runtime.pending_finish is None
    blocked[0]=False
    receipt=runtime.confirm_pending_evidence()
    assert receipt is not None and receipt['status']=='error'
    assert len(finishes)==1 and finishes[0]['payload']['last_ack_seq']==2
    assert len(sent)==1 and len(f['model_sent'])==1 and runtime.total_actions==2


def test_visible_ack_after_uncertain_journal_rename_uses_saved_cursor(platform,tmp_path,monkeypatch):
    import aiqa.worker.step_evidence as delivery
    f=platform;w=worker(f);choose(f,w);handler,sent=handler_for(f,w,tmp_path,monkeypatch)
    def ack(argv,timeout):sent.append(tuple(argv));return subprocess.CompletedProcess(argv,0,'','')
    handler.driver._runner=ack
    write=delivery.atomic_write;finishes=[];finish=w.client.finish_attempt
    def uncertain(path,data):
        write(path,data)
        state=json.loads(data)
        if state['pending_seq'] is None and state['entries']:
            raise OSError('synthetic failure after receipt rename')
    def remember(**kwargs):finishes.append(kwargs);return finish(**kwargs)
    monkeypatch.setattr(delivery,'atomic_write',uncertain);monkeypatch.setattr(w.client,'finish_attempt',remember)
    started=start(f);assert started.status_code==201
    runtime=WorkerRuntime(w.client,WorkerRuntimeConfig(w.boot,frozenset({'recording'})),handler,inventory_provider=lambda:w.payload)
    report=runtime.run_once()
    assert report.finished and len(finishes)==1,report
    assert finishes[0]['payload']['last_ack_seq']==2 and runtime.pending_finish is None
    assert finishes[0]['payload']['outcome']=='error'
    assert len(sent)==1 and len(f['model_sent'])==1 and runtime.total_actions==2
