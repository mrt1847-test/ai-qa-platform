"""Bound before-frame failures remain reviewable without inventing a native action."""
import base64,hashlib,json,sqlite3
from copy import deepcopy
import httpx,pytest
from test_ma04_engine_authority import platform,ux_app,worker,choose
from test_ma05_failure_state import handler_for,recording_state
from test_ma05_failure_evidence import facts,read_log,run
from aiqa.worker.http_client import WorkerHttpError,RetryClass


def fail_authoring(f,w,handler,monkeypatch,mode):
    calls=[];original=w.client.request_model
    def request(**kwargs):
        calls.append(deepcopy(kwargs))
        reply=original(**kwargs)
        if mode=='lost':raise WorkerHttpError('raw-provider-debug-do-not-store',retry_class=RetryClass.timeout)
        if mode=='receipt':return {**reply,'actual_model':'invalid-receipt-model'}
        if mode=='truncated':
            from aiqa.adapters.mobile_agent_upstream import render_reply
            return {**reply,'content':render_reply(reply['content']).replace('</tool_call>','')}
        return reply
    monkeypatch.setattr(w.client,'request_model',request)
    if mode=='fence':
        gate=handler._recording_gate
        def refuse(claim,*,phase):
            if phase=='before_model':raise ValueError('raw-fence-debug-do-not-store')
            return gate(claim,phase=phase)
        monkeypatch.setattr(handler,'_recording_gate',refuse)
    if mode=='provider':
        def reject(req):f['model_sent'].append(req);return httpx.Response(503,json={'error':{'message':'raw-provider-debug-do-not-store'}})
        f['app'].state.model_gateway.provider._transport=httpx.MockTransport(reject)
    return calls,original


@pytest.mark.parametrize('mode',['fence','provider','receipt','lost','truncated'])
def test_pre_turn_authoring_failure_stores_bound_diagnostic_without_native(platform,tmp_path,monkeypatch,mode):
    f=platform;w=worker(f);choose(f,w);handler,sent=handler_for(f,w,tmp_path,monkeypatch)
    calls,_=fail_authoring(f,w,handler,monkeypatch,mode)
    started,report=run(f,w,handler)
    action,objects,events=facts(f)
    assert action[1:]==('planned',0)
    assert [role for role,_,_ in objects]==['before','log']
    log=read_log(f,objects)
    assert log=={'schema':'mobile-agent-authoring-failure-v1','call_id':action[0][3:],'action_id':action[0],
        'state':'planned','native_calls':0,'native':None,'before_image_hash':objects[0][2],
        'stage':'authoring','outcome':'no_accepted_action','reason':'authoring_unavailable'}
    assert 'raw-' not in json.dumps(log)
    assert sent==[] and report.actions==1 and events==0
    assert len(calls)==len(f['model_sent'])==(0 if mode=='fence' else 1)
    assert handler.session_result.native_actions==0 and handler.session_result.action_mapping=='{}'
    assert not handler.session_result.evidence_complete and handler.session_result.model_requests==(0 if mode=='fence' else 1)
    assert recording_state(f,started['recording_id'])==('error','stopped','stored','incomplete')
    with sqlite3.connect(f['database']) as db:
        for table in ('recording_manifests','replay_packages','approval_events'):
            assert db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]==0


@pytest.mark.parametrize('mode',['lost','receipt','truncated'])
def test_diagnostic_consumes_cached_reply_without_reexecuting_action(platform,tmp_path,monkeypatch,mode):
    f=platform;w=worker(f);choose(f,w);handler,sent=handler_for(f,w,tmp_path,monkeypatch)
    calls,original=fail_authoring(f,w,handler,monkeypatch,mode)
    commit=w.client.commit_evidence;replies=[]
    def publish(**payload):
        ack=commit(**payload)
        if any(p['filename'].endswith('-authoring-failure.log') for p in payload['artifacts']):
            replies.append(original(**calls[0]))
        return ack
    monkeypatch.setattr(w.client,'commit_evidence',publish)
    run(f,w,handler)
    assert len(replies)==1 and replies[0]['replayed'] is True and replies[0]['action_allowed'] is False
    assert len(calls)==1 and len(f['model_sent'])==1 and sent==[]


@pytest.mark.parametrize('tamper',['call','before_hash','count','native','stage','extra','duplicate','owner'])
def test_authoring_diagnostic_rejects_unbound_or_extra_facts(platform,tmp_path,monkeypatch,tamper):
    f=platform;w=worker(f);choose(f,w);handler,_=handler_for(f,w,tmp_path,monkeypatch)
    fail_authoring(f,w,handler,monkeypatch,'fence')
    commit=w.client.commit_evidence;denied=[]
    def publish(**payload):
        if any(p['filename'].endswith('-authoring-failure.log') for p in payload['artifacts']):
            bad=deepcopy(payload);bad['idempotency_key']+='-bad-'+tamper
            part=bad['artifacts'][0];doc=json.loads(base64.b64decode(part['body_b64']))
            if tamper=='call':doc['call_id']='00000000-0000-4000-8000-000000000000'
            elif tamper=='before_hash':doc['before_image_hash']='sha256:'+'00'*32
            elif tamper=='count':doc['native_calls']=True
            elif tamper=='native':doc['native']={'kind':'tap','x':1,'y':1}
            elif tamper=='stage':doc['stage']='native'
            elif tamper=='extra':doc['raw_exception']='must not accept'
            elif tamper=='owner':part['owner_kind']='ITEM'
            raw=json.dumps(doc).encode()
            if tamper=='duplicate':raw=raw[:-1]+b',"stage":"authoring"}'
            part.update(body_b64=base64.b64encode(raw).decode(),declared_hash='sha256:'+hashlib.sha256(raw).hexdigest(),declared_length=len(raw))
            try:denied.append(('accepted',commit(**bad)))
            except WorkerHttpError as exc:denied.append(('rejected',exc.status_code))
        return commit(**payload)
    monkeypatch.setattr(w.client,'commit_evidence',publish)
    run(f,w,handler)
    assert denied==[('rejected',422)],denied
    action,objects,_=facts(f);assert action[1:]==('planned',0) and len(objects)==2


def test_before_model_failure_diagnostic_also_blocks_fresh_model_call(platform,tmp_path,monkeypatch):
    from datetime import datetime,timezone,timedelta
    from uuid import uuid4
    from test_rx_65 import _observation
    from aiqa.worker.model_observations import upload_authoring_observation
    f=platform;w=worker(f);choose(f,w);handler,_=handler_for(f,w,tmp_path,monkeypatch)
    _,original=fail_authoring(f,w,handler,monkeypatch,'fence')
    handle=handler.handle;claims=[]
    def remember(job):claims.append(deepcopy(job));return handle(job)
    monkeypatch.setattr(handler,'handle',remember)
    commit=w.client.commit_evidence;results=[]
    def publish(**payload):
        ack=commit(**payload)
        if any(p['filename'].endswith('-authoring-failure.log') for p in payload['artifacts']):
            claim=claims[0];pin=claim['snapshot']['limits']
            request={'call_id':str(uuid4()),'purpose':'recording','role':'authoring','owner_kind':'authoring','owner_id':claim['attempt_id'],
                'generation':claim['generation'],'binding_revision':pin['authoring_binding']['revision'],'intent_hash':claim['snapshot']['intent_hash'],
                'deadline':(datetime.now(timezone.utc)+timedelta(seconds=10)).isoformat(),'token_output_limit':512}
            try:
                bound=upload_authoring_observation(w.client,claim,_observation(),request)
                request.update(model_observation_id=bound['observation_id'],sanitized_inputs=bound['sanitized_inputs'])
                original(project_id=claim['project_id'],item_id=claim['attempt_id'],payload=request,idempotency_key='forbidden-fresh-call')
                results.append('allowed')
            except WorkerHttpError:results.append('denied')
        return ack
    monkeypatch.setattr(w.client,'commit_evidence',publish)
    run(f,w,handler)
    assert results==['denied'] and f['model_sent']==[],results


def test_authoring_diagnostic_lost_ack_reuses_frozen_packet(platform,tmp_path,monkeypatch):
    f=platform;w=worker(f);choose(f,w);handler,sent=handler_for(f,w,tmp_path,monkeypatch)
    calls,_=fail_authoring(f,w,handler,monkeypatch,'lost')
    commit=w.client.commit_evidence;packets=[]
    def lose(**payload):
        receipt=commit(**payload)
        if any(p['filename'].endswith('-authoring-failure.log') for p in payload['artifacts']):
            packets.append(deepcopy(payload))
            if len(packets)<=2:raise WorkerHttpError('lost log ACK',retry_class=RetryClass.timeout)
        return receipt
    monkeypatch.setattr(w.client,'commit_evidence',lose)
    started,report=run(f,w,handler)
    assert report.finished and len(packets)==3 and all(p==packets[0] for p in packets)
    assert len(calls)==len(f['model_sent'])==1 and sent==[]
    assert recording_state(f,started['recording_id'])==('error','stopped','stored','incomplete')


def test_authoring_diagnostic_is_readable_when_execution_pc_is_offline(platform,tmp_path,monkeypatch):
    import asyncio
    from datetime import datetime,timezone,timedelta
    from ux_support import session
    f=platform;w=worker(f);choose(f,w);handler,sent=handler_for(f,w,tmp_path,monkeypatch)
    fail_authoring(f,w,handler,monkeypatch,'fence')
    started,_=run(f,w,handler);action,_,_=facts(f)
    with sqlite3.connect(f['database']) as db:
        log_id=db.execute("SELECT artifact_id FROM artifact_objects WHERE action_id=? AND role='log'",(action[0],)).fetchone()[0]
        db.execute('UPDATE worker_presence SET last_seen=? WHERE project_id=? AND worker_id=?',((datetime.now(timezone.utc)-timedelta(minutes=3)).isoformat(),f['project'],w.worker_id))
    async def read():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=f['app']),base_url='http://127.0.0.1') as c:
            headers=await session(c,f['project'])
            timeline=await c.get(f"/api/v1/projects/{f['project']}/recordings/{started['recording_id']}/timeline",headers=headers)
            log=await c.get('/api/v1/artifacts/'+log_id,headers=headers)
            return timeline,log
    timeline,log=asyncio.run(read())
    assert timeline.status_code==log.status_code==200
    saved=next(item for item in timeline.json()['actions'] if item['action_id']==action[0])
    assert saved['dispatch_state']=='planned' and saved['before']=='stored' and saved['log']=='stored'
    assert saved['after']=='missing' and log.json()['schema']=='mobile-agent-authoring-failure-v1'
    assert sent==[] and f['model_sent']==[]
