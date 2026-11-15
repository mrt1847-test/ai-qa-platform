from dataclasses import replace
import base64,hashlib,json,sqlite3
import httpx,pytest
import test_rx98_model_requests as seed
from test_rx97_recording_pin import recording,ux_app
from test_ma03b_mobile_history import engine_job,prepare,complete_step,commit,proof_parts
from aiqa.adapters.mobile_agent_upstream import load_protocol
from aiqa.store.artifacts import resolve_stored
from unit.test_mobile_agent_context import reply
from unit.test_openai_provider_settings import response


def test_marked_normal_api_sends_original_prompt_and_acknowledged_history(engine_job):
    f=engine_job;old,parts=complete_step(f);commit(f,parts,'after-'+old['call_id']);current,_=prepare(f)
    result=seed.post(f,current,key='second-original');assert result.status_code==200,result.text
    sent=[json.loads(req.content) for req in f['openai_sent']]
    assert sent[0]['input'][0]=={'role':'system','content':[{'type':'input_text','text':load_protocol().SYSTEM_PROMPT}]}
    assert 'text' in sent[0] and 'objective:spoof' not in json.dumps(sent)
    assert [m['role'] for m in sent[1]['input']]==['system','user','assistant','user']
    assert sent[1]['input'][2]['phase']=='final_answer'


def test_missing_native_ack_is_a_free_normal_api_refusal(engine_job):
    f=engine_job;old,parts=complete_step(f);current,_=prepare(f)
    result=seed.post(f,current,key='no-ack')
    assert result.status_code==403 and result.json()['error']['provider_dispatched'] is False
    assert len(f['openai_sent'])==1


def test_history_log_tamper_during_http_preparation_never_sends(engine_job,monkeypatch):
    f=engine_job;old,parts=complete_step(f);commit(f,parts,'after-'+old['call_id']);current,_=prepare(f)
    store=f['app'].state.open_store()
    try:
        with store.transaction() as c:key=c.execute("SELECT object_key FROM artifact_objects WHERE project_id=? AND action_id=? AND role='log'",(f['project'],'ma-'+old['call_id'])).fetchone()[0]
        path=resolve_stored(store.config.artifacts_dir,key)
    finally:store.close()
    client=httpx.Client
    def change(*args,**kwargs):
        if kwargs.get('transport') is f['provider']._transport:path.write_bytes(b'tampered')
        return client(*args,**kwargs)
    monkeypatch.setattr(httpx,'Client',change)
    result=seed.post(f,current,key='tampered-prepare')
    assert result.status_code==403 and result.json()['error']['provider_dispatched'] is False
    assert len(f['openai_sent'])==1


def respond(f,content,*,model='gpt-6-luna'):
    def transport(req):
        f['openai_sent'].append(req);raw=response();raw['model']=model;raw['output'][-1]['content'][0]['text']=content
        return httpx.Response(200,json=raw)
    f['provider']._transport=httpx.MockTransport(transport)


@pytest.mark.parametrize('action',[{'action':'click','coordinate':[1001,0]},{'action':'type','text':'unbound-value'},{'action':'terminate','status':[]},{'action':'terminate','status':{}}])
def test_invalid_final_action_keeps_measured_usage_without_authorizing_action(engine_job,action):
    f=engine_job;current,_=prepare(f);respond(f,reply(action))
    result=seed.post(f,current,key='bad-action');body=result.json()
    assert result.status_code==502 and body['error']['provider_dispatched'] is True
    assert 'content' not in body and body['usage']['input_tokens']==100 and body['usage']['tokens_complete']
    again=seed.post(f,current,key='bad-action');assert again.status_code==502 and len(f['openai_sent'])==1
    with sqlite3.connect(f['database']) as c:
        assert c.execute('SELECT SUM(charged) FROM model_request_receipts').fetchone()[0]==1


def test_terminal_model_reply_does_not_create_a_human_approval(engine_job):
    f=engine_job;current,_=prepare(f);respond(f,reply({'action':'terminate','status':'success'}))
    result=seed.post(f,current,key='finish');assert result.status_code==200,result.text
    with sqlite3.connect(f['database']) as c:assert c.execute('SELECT COUNT(*) FROM approval_events').fetchone()[0]==0


def test_cached_action_can_only_be_read_after_execution_evidence(engine_job):
    f=engine_job;old,parts=complete_step(f);key='model-'+old['call_id']
    before=seed.post(f,old,key=key);assert before.json()['replayed'] and before.json()['action_allowed']
    commit(f,parts,'after-'+old['call_id'])
    after=seed.post(f,old,key=key)
    assert after.status_code==200 and after.json()['replayed'] and after.json()['action_allowed'] is False
    assert len(f['openai_sent'])==1


def test_response_validation_cannot_return_an_expired_action(engine_job,monkeypatch):
    from datetime import datetime,timedelta,timezone
    import aiqa.models.mobile_agent_context as context
    f=engine_job;current,_=prepare(f);validate=context.validate_mobile_agent_reply;now=datetime.now(timezone.utc)
    def slow(**kwargs):
        result=validate(**kwargs)
        monkeypatch.setattr('aiqa.models.model_observations._now',lambda:now+timedelta(seconds=31))
        return result
    monkeypatch.setattr(context,'validate_mobile_agent_reply',slow)
    result=seed.post(f,current,key='expired-validation');body=result.json()
    assert result.status_code==403 and body['error']['provider_dispatched'] is True
    assert body['usage']['input_tokens']==100 and 'content' not in body


def test_unknown_native_log_disables_cached_action_without_a_second_send(engine_job):
    f=engine_job;old,parts=complete_step(f)
    raw=json.loads(base64.b64decode(parts[1]['body_b64']));raw['state']='unknown'
    encoded=json.dumps(raw).encode();parts[1].update(body_b64=base64.b64encode(encoded).decode(),declared_hash='sha256:'+hashlib.sha256(encoded).hexdigest(),declared_length=len(encoded))
    commit(f,[parts[1]],'unknown-native')
    result=seed.post(f,old,key='model-'+old['call_id'])
    assert result.status_code==200 and result.json()['action_allowed'] is False and len(f['openai_sent'])==1


def test_durable_history_survives_gateway_restart_without_rebilling_old_call(engine_job):
    from aiqa.models.broker import ServerModelGateway
    f=engine_job;old,parts=complete_step(f);commit(f,parts,'after-'+old['call_id'])
    f['app'].state.model_gateway=ServerModelGateway(provider=f['provider'],resolver=f['resolver'])
    cached=seed.post(f,old,key='model-'+old['call_id']);assert cached.status_code==200 and cached.json()['replayed']
    current,_=prepare(f);result=seed.post(f,current,key='after-restart')
    assert result.status_code==200,result.text
    body=json.loads(f['openai_sent'][-1].content)
    assert body['input'][2]['role']=='assistant' and result.json()['usage']['authoring_calls']==2
    assert len(f['openai_sent'])==2


def test_reported_model_mismatch_withholds_action_but_keeps_measured_usage(engine_job):
    f=engine_job;current,_=prepare(f);respond(f,reply(),model='unexpected-model')
    result=seed.post(f,current,key='model-mismatch');body=result.json()
    assert result.status_code==502 and body['error']['provider_dispatched'] is True
    assert body['actual_model']=='unexpected-model' and body['usage']['input_tokens']==100 and 'content' not in body
    assert seed.post(f,current,key='model-mismatch').status_code==502 and len(f['openai_sent'])==1
