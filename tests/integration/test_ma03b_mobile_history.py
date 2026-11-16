from dataclasses import asdict,fields,replace
from datetime import datetime,timezone
from uuid import UUID,uuid4
import base64,hashlib,json
import httpx,pytest
from aiqa.api.auth import bound_auth_store,worker_scope_from_token
from aiqa.config import WorkerClientSettings
from aiqa.models.broker import ServerModelGateway,WorkerModelRequest,ModelRequestDenied
from aiqa.models.openai_server import OpenAIServerProvider
from aiqa.worker.http_client import WorkerHttpClient,SyncASGITransport
from test_rx97_recording_pin import recording,ux_app
from test_ma02_openai_recording import openai_job
import test_rx98_model_requests as seed
from unit.test_openai_provider_settings import response
from unit.test_mobile_agent_context import reply
from test_rx_65 import _observation


def sha(raw):return 'sha256:'+hashlib.sha256(raw).hexdigest()


@pytest.fixture
def engine_job(recording,monkeypatch,request):
    import sqlite3,asyncio
    from ux_support import session
    f=recording
    with sqlite3.connect(f['database']) as db:
        row=db.execute('SELECT definition_json,settings_json FROM case_versions WHERE version_id=?',(f['body']['input_case_version_id'],)).fetchone()
        definition=json.loads(row[0]);settings=json.loads(row[1])
    if settings['target_kind']!='android':
        settings.update(target_kind='android',android_package='com.example.saved')
        async def save():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=f['app']),base_url='http://127.0.0.1') as c:
                headers=await session(c,f['project'])
                response=await c.post(f"/api/v1/projects/{f['project']}/cases/{f['body']['case_id']}/versions",json={
                    'definition':definition,'settings':settings,'parent_version_id':f['body']['input_case_version_id'],'expected_head':f['body']['input_case_version_id']},
                    headers={**headers,'Idempotency-Key':'original-android-input'})
                assert response.status_code==201,response.text
                return response.json()
        saved=asyncio.run(save());f['body'].update(input_case_version_id=saved['id'],input_version_hash=saved['content_hash'])
    with sqlite3.connect(f['database']) as db:
        db.execute("UPDATE resource_aliases SET target_kind='android' WHERE project_id=? AND physical_key_id=?",(f['project'],f['body']['resource_id']))
        from authoring_metadata_support import seed_recording_capability
        seed_recording_capability(db,f['project'],f['body']['resource_id'],mode='original')
    f=openai_job.__wrapped__(recording,monkeypatch,request)
    def http(req):
        f['openai_sent'].append(req);raw=response();raw['output'][-1]['content'][0]['text']=reply()
        return httpx.Response(200,json=raw)
    f['provider']=OpenAIServerProvider(transport=httpx.MockTransport(http))
    f['app'].state.model_gateway=ServerModelGateway(provider=f['provider'],resolver=f['resolver'])
    f['_auto_observations']=False
    return f


def client(f):return WorkerHttpClient(WorkerClientSettings('https://127.0.0.1',f['token']),transport=SyncASGITransport(f['app']))


def part(f,call_id,role,raw,media):
    return {'filename':str(call_id)+'-'+role+'.'+('png' if media=='image/png' else 'log'),'media_type':media,
        'declared_hash':sha(raw),'declared_length':len(raw),'body_b64':base64.b64encode(raw).decode(),
        'owner_kind':'REC','attempt_id':f['job']['attempt_id'],'action_id':'ma-'+str(call_id),'role':role}


def commit(f,parts,key):
    with client(f) as c:return c.commit_evidence(sanitized=True,project_id=f['project'],job_id=f['job']['job_id'],generation=f['job']['generation'],
        now=datetime.now(timezone.utc).isoformat(),events=[],artifacts=parts,idempotency_key=key)


def prepare(f,*,source_id=None):
    payload={**f['payload'],'call_id':str(uuid4())};obs=_observation(obs_id=source_id)
    ack=commit(f,[part(f,payload['call_id'],'before',obs.png,'image/png')],'before-'+payload['call_id'])
    with client(f) as c:
        registered=c.register_model_observation(project_id=f['project'],item_id=f['job']['attempt_id'],
            payload={**payload,'artifact_id':ack['artifact_ids'][0],'image_hash':sha(obs.png),'geometry':asdict(obs.geometry),
                'captured_at':obs.captured_at,'source_observation_id':obs.observation_id},idempotency_key='observation-'+payload['call_id'])
    payload['model_observation_id']=registered['observation_id']
    return payload,obs


def request(payload):
    args={field.name:payload[field.name] for field in fields(WorkerModelRequest) if field.name in payload}
    args['call_id']=UUID(args['call_id']);args['sanitized_inputs']=tuple(args['sanitized_inputs'])
    return WorkerModelRequest(**args)


def load(f,payload):
    from aiqa.models.mobile_agent_history import load_mobile_agent_history
    store=f['app'].state.open_store()
    try:
        with bound_auth_store(store):worker=worker_scope_from_token(f['token'])
        return load_mobile_agent_history(store,worker,request(payload),UUID(f['project']),f['job']['attempt_id'])
    finally:store.close()


def proof_parts(f,payload,obs,*,native_x=50):
    from aiqa.replay.android_plan import build_typed_android_action
    action=build_typed_android_action('tap',width=100,height=200,rotation=0,x=native_x,y=100)
    after=_observation(fill=b'\x00\xff\x00')
    log={'schema':'mobile-agent-step-v1','call_id':payload['call_id'],'action_id':'ma-'+payload['call_id'],
        'state':'observed','native_calls':1,'native':asdict(action),'before_image_hash':sha(obs.png),'after_image_hash':sha(after.png)}
    parts=[part(f,payload['call_id'],'after',after.png,'image/png'),part(f,payload['call_id'],'log',json.dumps(log).encode(),'text/plain')]
    return parts


def complete_step(f,*,native_x=50):
    payload,obs=prepare(f);result=seed.post(f,payload,key='model-'+payload['call_id']);assert result.status_code==200,result.text
    return payload,proof_parts(f,payload,obs,native_x=native_x)


def test_first_context_uses_authorized_frozen_intent_and_current_image(engine_job):
    f=engine_job;payload,obs=prepare(f);state=load(f,payload)
    assert state.step_count==0 and len(state.context.messages())==2 and len(state.fingerprint)>64
    assert 'objective:spoof' not in json.dumps(state.context.messages())


def test_model_proposal_without_native_ack_cannot_be_history(engine_job):
    f=engine_job;old,parts=complete_step(f);current,_=prepare(f)
    with pytest.raises(ModelRequestDenied,match='mobile_history_ack_required'):load(f,current)


def test_only_same_action_acked_native_and_screen_log_enters_history(engine_job):
    f=engine_job;old,parts=complete_step(f);commit(f,parts,'after-'+old['call_id']);current,_=prepare(f)
    state=load(f,current)
    assert state.step_count==1 and [m['role'] for m in state.context.messages()]==['system','user','assistant','user']
    assert '<tool_call>' in state.context.messages()[2]['content'][0]['text']


def test_wrong_physical_native_ack_is_not_a_completed_step(engine_job):
    f=engine_job;old,parts=complete_step(f,native_x=51);commit(f,parts,'after-'+old['call_id']);current,_=prepare(f)
    with pytest.raises(ModelRequestDenied,match='mobile_history_ack_invalid'):load(f,current)


def test_current_registration_must_follow_previous_ack(engine_job):
    f=engine_job;old,parts=complete_step(f);current,_=prepare(f);commit(f,parts,'after-'+old['call_id'])
    with pytest.raises(ModelRequestDenied,match='mobile_history_order'):load(f,current)


def test_each_history_capture_must_follow_the_previous_native_ack(engine_job):
    # Normal model API now rejects this sequence before the second send. Seed a
    # completed proposal through store primitives to retain producer fault coverage.
    from aiqa.store.model_requests import settle_request
    f=engine_job;one,parts1=complete_step(f);two,obs=prepare(f);reserve_current(f,two)
    store=f['app'].state.open_store()
    try:
        with store.transaction() as connection:
            body=json.loads(connection.execute('SELECT response_json FROM model_request_receipts WHERE project_id=? AND call_id=?',
                (f['project'],one['call_id'])).fetchone()[0])
            body.update(call_id=two['call_id'],model_observation_id=two['model_observation_id'],provider_request_id='fixture-imported-proposal')
            settle_request(connection,UUID(f['project']),f['job']['attempt_id'],'reserved',200,body,True,datetime.now(timezone.utc))
    finally:store.close()
    parts2=proof_parts(f,two,obs)
    commit(f,parts1,'after-'+one['call_id']);commit(f,parts2,'after-'+two['call_id']);current,_=prepare(f)
    with pytest.raises(ModelRequestDenied,match='mobile_history_order'):load(f,current)


def test_two_acked_turns_form_an_ordered_history(engine_job):
    f=engine_job
    for _ in range(2):
        old,parts=complete_step(f);commit(f,parts,'after-'+old['call_id'])
    current,_=prepare(f)
    assert load(f,current).step_count==2


def test_paid_failed_proposal_is_not_skipped_to_continue(engine_job):
    f=engine_job;payload,obs=prepare(f)
    f['provider']._transport=httpx.MockTransport(lambda req:httpx.Response(503))
    failed=seed.post(f,payload,key='failed-model');assert failed.status_code==503
    current,_=prepare(f)
    with pytest.raises(ModelRequestDenied,match='mobile_history_incomplete'):load(f,current)


def test_pending_other_call_never_becomes_a_completed_turn(engine_job):
    from aiqa.models.recording_authorization import authorize_recording
    from aiqa.store.model_requests import reserve_request,request_fingerprint
    from aiqa.domain.hashing import canonical_hash
    f=engine_job;payload,_=prepare(f);req=request(payload);store=f['app'].state.open_store()
    try:
        with bound_auth_store(store):worker=worker_scope_from_token(f['token'])
        with store.transaction() as connection:
            grant=authorize_recording(connection,worker,req,UUID(f['project']),f['job']['attempt_id'],datetime.now(timezone.utc))
            fingerprint=canonical_hash({'request':request_fingerprint(req,UUID(f['project']),f['job']['attempt_id']),
                'intent_hash':payload['intent_hash']},'canon-json-v1')
            reserve_request(connection,UUID(f['project']),f['job']['attempt_id'],'pending',req,worker.worker_id,fingerprint,grant,datetime.now(timezone.utc))
    finally:store.close()
    current,_=prepare(f)
    with pytest.raises(ModelRequestDenied,match='mobile_history_incomplete'):load(f,current)


def test_tampered_durable_native_log_cannot_be_history(engine_job):
    from aiqa.store.artifacts import resolve_stored
    f=engine_job;old,parts=complete_step(f);commit(f,parts,'after-'+old['call_id']);current,_=prepare(f)
    store=f['app'].state.open_store()
    try:
        with store.transaction() as connection:
            key=connection.execute("SELECT object_key FROM artifact_objects WHERE project_id=? AND action_id=? AND role='log'",
                (f['project'],'ma-'+old['call_id'])).fetchone()[0]
        path=resolve_stored(store.config.artifacts_dir,key);path.write_bytes(b'tampered fixture')
    finally:store.close()
    with pytest.raises(ModelRequestDenied,match='mobile_history_ack_invalid'):load(f,current)


def test_old_history_image_is_context_but_current_image_still_must_be_fresh(engine_job,monkeypatch):
    import sys
    from datetime import timedelta
    f=engine_job;observe=_observation
    with monkeypatch.context() as patch:
        patch.setattr(sys.modules[__name__],'_observation',lambda **kw:replace(observe(**kw),captured_at=(datetime.now(timezone.utc)-timedelta(seconds=10)).isoformat()))
        old,parts=complete_step(f);commit(f,parts,'after-'+old['call_id'])
    current,_=prepare(f);now=datetime.now(timezone.utc)
    monkeypatch.setattr('aiqa.models.model_observations._now',lambda:now+timedelta(seconds=25))
    assert load(f,current).step_count==1
    monkeypatch.setattr('aiqa.models.model_observations._now',lambda:now+timedelta(seconds=31))
    with pytest.raises(ModelRequestDenied,match='observation_'):load(f,current)


def test_history_disk_and_pixel_processing_do_not_hold_db_writer(engine_job,monkeypatch):
    import aiqa.models.mobile_agent_history as history
    f=engine_job;old,parts=complete_step(f);commit(f,parts,'after-'+old['call_id']);current,_=prepare(f)
    store=f['app'].state.open_store();reads=[];builds=[]
    read=history.read_validated_image;build=history.build_mobile_agent_context
    def check_read(*args,**kwargs):
        assert not store.in_transaction();reads.append(1);return read(*args,**kwargs)
    def check_build(*args,**kwargs):
        assert not store.in_transaction();builds.append(1);return build(*args,**kwargs)
    monkeypatch.setattr(history,'read_validated_image',check_read);monkeypatch.setattr(history,'build_mobile_agent_context',check_build)
    try:
        with bound_auth_store(store):worker=worker_scope_from_token(f['token'])
        assert history.load_mobile_agent_history(store,worker,request(current),UUID(f['project']),f['job']['attempt_id']).step_count==1
        assert reads and builds
    finally:store.close()


def test_ack_evidence_cannot_precede_the_model_proposal(engine_job):
    f=engine_job;old,obs=prepare(f);parts=proof_parts(f,old,obs);commit(f,parts,'premature-ack')
    result=seed.post(f,old,key='late-proposal');assert result.status_code==200
    current,_=prepare(f)
    with pytest.raises(ModelRequestDenied,match='mobile_history_order'):load(f,current)


def test_next_frame_registered_during_ack_staging_is_not_after_ack(engine_job,monkeypatch):
    from aiqa.store import evidence
    f=engine_job;old,parts=complete_step(f);finalize=evidence._commit_evidence_metadata;during=[]
    def bracket(binding,lease,**kwargs):
        if not during and any(part.role=='after' for part in kwargs['artifacts']):
            during.append(None);during[0]=prepare(f)[0]
        return finalize(binding,lease,**kwargs)
    monkeypatch.setattr(evidence,'_commit_evidence_metadata',bracket)
    commit(f,parts,'staged-after')
    with pytest.raises(ModelRequestDenied,match='mobile_history_order'):load(f,during[0])


def test_final_snapshot_wait_cannot_return_an_expired_current_frame(engine_job,monkeypatch):
    import aiqa.models.mobile_agent_history as history
    from datetime import timedelta
    f=engine_job;current,_=prepare(f);snapshot=history._snapshot;count=[0];now=datetime.now(timezone.utc)
    def slow(*args,**kwargs):
        value=snapshot(*args,**kwargs);count[0]+=1
        if count[0]==2:monkeypatch.setattr('aiqa.models.model_observations._now',lambda:now+timedelta(seconds=31))
        return value
    monkeypatch.setattr(history,'_snapshot',slow)
    with pytest.raises(ModelRequestDenied,match='observation_'):load(f,current)
    assert count[0]==2


def test_same_capture_id_cannot_be_reregistered_as_a_new_current_frame(engine_job):
    f=engine_job;old,parts=complete_step(f);commit(f,parts,'after-'+old['call_id'])
    store=f['app'].state.open_store()
    try:
        with store.transaction() as connection:
            source=connection.execute('SELECT source_observation_id FROM model_observations WHERE project_id=? AND call_id=?',(f['project'],old['call_id'])).fetchone()[0]
    finally:store.close()
    current,_=prepare(f,source_id=source)
    with pytest.raises(ModelRequestDenied,match='mobile_history_observation'):load(f,current)


def test_over_nested_ack_json_is_a_controlled_refusal():
    from aiqa.models.mobile_agent_history import _json
    with pytest.raises(ValueError):_json('['*1100+'0'+']'*1100)


def reserve_current(f,payload,*,foreign=None):
    from aiqa.models.recording_authorization import authorize_recording
    from aiqa.store.model_requests import reserve_request,request_fingerprint
    from aiqa.domain.hashing import canonical_hash
    req=request(payload);store=f['app'].state.open_store()
    try:
        with bound_auth_store(store):worker=worker_scope_from_token(f['token'])
        with store.transaction() as connection:
            grant=authorize_recording(connection,worker,req,UUID(f['project']),f['job']['attempt_id'],datetime.now(timezone.utc))
            fingerprint=canonical_hash({'request':request_fingerprint(req,UUID(f['project']),f['job']['attempt_id']),
                'intent_hash':payload['intent_hash']},'canon-json-v1')
            if foreign=='policy':grant=replace(grant,policy_ref='foreign-policy')
            reserve_request(connection,UUID(f['project']),f['job']['attempt_id'],'reserved',req,
                'foreign-worker' if foreign=='worker' else worker.worker_id,fingerprint,grant,datetime.now(timezone.utc))
    finally:store.close()


def test_own_matching_pending_reservation_preserves_history_snapshot(engine_job):
    f=engine_job;current,_=prepare(f);before=load(f,current);reserve_current(f,current);after=load(f,current)
    assert before.fingerprint==after.fingerprint and after.step_count==0


@pytest.mark.parametrize('foreign',['worker','policy'])
def test_pending_rows_from_another_worker_or_policy_are_not_own_reservation(engine_job,foreign):
    f=engine_job;current,_=prepare(f);reserve_current(f,current,foreign=foreign)
    with pytest.raises(ModelRequestDenied,match='mobile_history_scope'):load(f,current)


def test_returned_frame_must_match_exact_registered_identity(engine_job,monkeypatch):
    import aiqa.models.mobile_agent_history as history
    from datetime import timedelta
    f=engine_job;current,_=prepare(f);real=history.load_authoring_observation
    def shifted(*args,**kwargs):return replace(real(*args,**kwargs),captured_at=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat())
    monkeypatch.setattr(history,'load_authoring_observation',shifted)
    with pytest.raises(ModelRequestDenied,match='observation_'):load(f,current)


def test_legacy_receipt_without_server_finalization_time_is_not_ack_proof(engine_job):
    f=engine_job;old,parts=complete_step(f);commit(f,parts,'after-'+old['call_id']);current,_=prepare(f)
    store=f['app'].state.open_store()
    try:
        with store.transaction() as connection:
            row=connection.execute('SELECT response_body FROM evidence_commit_requests WHERE project_id=? AND request_key=?',
                (f['project'],'after-'+old['call_id'])).fetchone()
            body=json.loads(row[0]);assert 'server_committed_at' in body;body.pop('server_committed_at')
            connection.execute('UPDATE evidence_commit_requests SET response_body=? WHERE project_id=? AND request_key=?',
                (json.dumps(body),f['project'],'after-'+old['call_id']))
    finally:store.close()
    with pytest.raises(ModelRequestDenied,match='mobile_history_ack_required'):load(f,current)
