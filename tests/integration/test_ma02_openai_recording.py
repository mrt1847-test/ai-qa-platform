"""MA02a normal recording admission and authority at the actual OpenAI send boundary."""
from dataclasses import replace
from types import SimpleNamespace
import json,sqlite3
import httpx,pytest
from aiqa.config import ModelProviderSettings
from aiqa.models.broker import ServerModelGateway
from aiqa.models.provider_http import build_provider_from_settings
import test_rx98_model_requests as seed
from test_rx97_recording_pin import recording,ux_app
from unit.test_openai_provider_settings import response


@pytest.fixture
def openai_job(recording,monkeypatch,request):
    changes=getattr(request,'param',{})
    original=seed._new_revision
    def revision(*args,**kwargs):return original(*args,**{**kwargs,'provider':'openai','endpoint':'https://api.openai.com','endpoint_kind':'https','model':'gpt-6-luna',**changes})
    monkeypatch.setattr(seed,'_new_revision',revision)
    f=recording;sent=[];mode={'status':200,'after':None}
    def handle(req):
        sent.append(req)
        if mode['after']:mode['after']()
        raw=response();raw['output'][-1]['content'][0]['text']='finish()'
        if mode.get('omit_usage'):raw.pop('usage')
        return httpx.Response(mode['status'],json=raw)
    transport=httpx.MockTransport(handle);original_start=seed.start
    def prepared_start(f,*args,**kwargs):
        settings=replace(f['app'].state.settings,model_provider=ModelProviderSettings(mode='openai'))
        f['app'].state.settings=settings
        provider=build_provider_from_settings(settings,transport=transport)
        f['app'].state.model_gateway=ServerModelGateway(provider=provider,resolver=f['app'].state.secret_resolver)
        return original_start(f,*args,**kwargs)
    with monkeypatch.context() as initial:
        initial.setattr(seed,'start',prepared_start)
        f=seed.model_job.__wrapped__(recording,SimpleNamespace(param='operational'))
    provider=f['app'].state.model_gateway.provider
    f.update(provider=provider,openai_sent=sent,openai_transport=transport,openai_mode=mode)
    seed.ack(f)
    return f


@pytest.mark.parametrize('openai_job',[{},{'endpoint':'https://api.openai.com/v1/responses'}],indirect=True)
def test_normal_openai_recording_uses_pinned_secret_and_image(openai_job):
    f=openai_job;result=seed.post(f)
    assert result.status_code==200,result.text
    assert result.json()['content']=='finish()' and result.json()['provider_dispatched'] is True
    assert len(f['openai_sent'])==f['provider'].call_count==1
    request=f['openai_sent'][0];body=json.loads(request.content)
    assert str(request.url)=='https://api.openai.com/v1/responses'
    assert request.headers['Authorization']=='Bearer synthetic-RX98-private'
    assert body['model']=='gpt-6-luna' and any(c['type']=='input_image' for c in body['input'][0]['content'])
    f['app'].state.model_gateway=ServerModelGateway(provider=f['provider'],resolver=f['resolver'])
    again=seed.post(f);assert again.status_code==200 and again.json()['replayed']
    assert len(f['openai_sent'])==1


@pytest.mark.parametrize('when',['prepare','reply'])
def test_cancel_at_prepare_is_free_but_cancel_after_send_is_consumed(openai_job,monkeypatch,when):
    f=openai_job
    def cancel():seed.mutate(f,"UPDATE jobs SET status='cancel_requested' WHERE job_id=?",(f['job']['job_id'],))
    if when=='prepare':
        client=httpx.Client
        def prepare(*args,**kwargs):
            if kwargs.get('transport') is f['openai_transport']:cancel()
            return client(*args,**kwargs)
        monkeypatch.setattr(httpx,'Client',prepare)
    else:f['openai_mode']['after']=cancel
    result=seed.post(f)
    assert result.status_code==403,result.text
    assert result.json()['error']['provider_dispatched'] is (when=='reply')
    assert len(f['openai_sent'])==(1 if when=='reply' else 0)
    with sqlite3.connect(f['database']) as c:charged=c.execute('SELECT COALESCE(SUM(charged),0) FROM model_request_receipts').fetchone()[0]
    assert charged==(1 if when=='reply' else 0)


@pytest.mark.parametrize('openai_job',[{'endpoint':'https://other.invalid'},{'provider':'operational'}],indirect=True)
def test_provider_or_binding_mismatch_never_sends(openai_job):
    f=openai_job
    result=seed.post(f);assert result.status_code==503,result.text
    assert not result.json()['error']['provider_dispatched'] and f['openai_sent']==[]


@pytest.mark.parametrize('change',['lease','key','frame'])
def test_final_boundary_rejects_authority_changes_without_a_send(openai_job,monkeypatch,change):
    from datetime import datetime,timedelta,timezone
    f=openai_job;client=httpx.Client
    def prepare(*args,**kwargs):
        if kwargs.get('transport') is f['openai_transport']:
            if change=='lease':seed.mutate(f,'UPDATE leases SET expires_at=?',((datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(),))
            elif change=='key':seed.mutate(f,"UPDATE secret_refs SET availability='revoked' WHERE ref_id=?",(str(f['secret'].ref_id),))
            else:monkeypatch.setattr('aiqa.models.model_observations._now',lambda:datetime.now(timezone.utc)+timedelta(seconds=31))
        return client(*args,**kwargs)
    monkeypatch.setattr(httpx,'Client',prepare)
    result=seed.post(f)
    assert result.status_code==403,result.text
    assert result.json()['error']['provider_dispatched'] is False and f['openai_sent']==[]
    with sqlite3.connect(f['database']) as c:assert c.execute('SELECT SUM(charged) FROM model_request_receipts').fetchone()[0]==0



def test_actual_token_measurements_are_durable_and_not_added_twice(openai_job):
    f=openai_job;result=seed.post(f);assert result.status_code==200,result.text
    body=result.json();usage=body['usage']
    assert body['measurement_status']=='measured'
    assert (usage['input_tokens'],usage['output_tokens'],usage['cached_input_tokens'],usage['reasoning_tokens'],usage['total_tokens'])==(100,20,50,5,120)
    assert usage['token_scope']=='call' and usage['cost_status']=='unknown' and usage['reserved_cost'] is None
    call_id=__import__('uuid').UUID(f['payload']['call_id'])
    assert f['app'].state.model_gateway.call_tokens(__import__('uuid').UUID(f['project']),call_id)==(100,20,50,None)
    f['app'].state.model_gateway=ServerModelGateway(provider=f['provider'],resolver=f['resolver'])
    again=seed.post(f)
    assert again.status_code==200 and again.json()['replayed'] and again.json()['usage']==usage
    assert len(f['openai_sent'])==1
    with sqlite3.connect(f['database']) as c:
        row=c.execute('SELECT charged,response_json FROM model_request_receipts').fetchone()
    persisted=json.loads(row[1])
    assert row[0]==1 and persisted['usage']['input_tokens']==100 and persisted['usage']['total_tokens']==120


def test_invalid_response_usage_is_unknown_and_consumed_once(openai_job):
    f=openai_job;f['openai_mode']['omit_usage']=True
    result=seed.post(f);assert result.status_code==502,result.text
    assert result.json()['error']['provider_dispatched'] is True
    assert 'usage' not in result.json()  # Unusable provider response: omitted counts mean unknown, not zero.
    f['app'].state.model_gateway=ServerModelGateway(provider=f['provider'],resolver=f['resolver'])
    again=seed.post(f);assert again.status_code==502 and again.json()['error']['replayed']
    assert len(f['openai_sent'])==1
    with sqlite3.connect(f['database']) as c:
        charged,input_tokens,output_tokens=c.execute("SELECT charged,json_extract(response_json,'$.usage.input_tokens'),json_extract(response_json,'$.usage.output_tokens') FROM model_request_receipts").fetchone()
    assert charged==1 and input_tokens is None and output_tokens is None



def test_openai_pin_cannot_fall_through_to_operational_transport(openai_job):
    from aiqa.models.provider_http import OperationalProviderHttp
    f=openai_job;sent=[]
    other=OperationalProviderHttp(allow_live=True,base_url='https://api.openai.com',transport=httpx.MockTransport(lambda r:(sent.append(r) or httpx.Response(200,json={'content':'finish()','provider_request_id':'wrong','actual_model':'gpt-6-luna'}))))
    f['app'].state.model_gateway=ServerModelGateway(provider=other,resolver=f['resolver'])
    result=seed.post(f)
    assert result.status_code==503 and result.json()['error']['provider_dispatched'] is False
    assert sent==[]


def test_successful_but_late_measurements_survive_restart_without_action(openai_job):
    f=openai_job;f['openai_mode']['after']=lambda:seed.mutate(f,"UPDATE jobs SET status='cancel_requested' WHERE job_id=?",(f['job']['job_id'],))
    first=seed.post(f);assert first.status_code==403,first.text
    assert 'finish()' not in first.text and first.json()['error']['provider_dispatched'] is True
    assert first.json()['usage']['input_tokens']==100 and first.json()['usage']['output_tokens']==20
    f['app'].state.model_gateway=ServerModelGateway(provider=f['provider'],resolver=f['resolver'])
    again=seed.post(f)
    assert again.status_code==403 and again.json()['usage']==first.json()['usage'] and len(f['openai_sent'])==1
    with sqlite3.connect(f['database']) as c:body=json.loads(c.execute('SELECT response_json FROM model_request_receipts').fetchone()[0])
    assert body['usage']['cached_input_tokens']==50 and body['usage']['reasoning_tokens']==5 and 'content' not in body


def test_identical_concurrent_retry_reports_pending_not_unsent_conflict(openai_job,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
    from threading import Barrier,Event,Lock
    import aiqa.models.model_observations as module
    from model_observation_support import prepare_frame
    f=openai_job;body={**f['payload'],'model_observation_id':prepare_frame(f,f['payload'])}
    original=module.load_authoring_observation;barrier=Barrier(2);lock=Lock();initial=[0];release=Event();entered=Event()
    def capture(*args,**kwargs):
        result=original(*args,**kwargs);synchronize=False
        with lock:
            if initial[0]<2:initial[0]+=1;synchronize=True
        if synchronize:barrier.wait(timeout=10)
        return result
    monkeypatch.setattr(module,'load_authoring_observation',capture)
    def pending():entered.set();assert release.wait(timeout=10)
    f['openai_mode']['after']=pending
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(seed.post,f,body) for _ in range(2)]
        try:
            assert entered.wait(timeout=10)
            done,_=wait(futures,timeout=5,return_when=FIRST_COMPLETED)
            assert len(done)==1
            response=next(iter(done)).result()
            assert response.status_code==503,response.text
            assert response.json()['error']['provider_dispatched'] is None
        finally:release.set()
        results=[future.result(timeout=10) for future in futures]
    assert sorted(r.status_code for r in results)==[200,503] and len(f['openai_sent'])==1



def test_provider_replacement_after_initial_validation_is_not_adopted(openai_job,monkeypatch):
    import aiqa.models.recording_requests as module
    from aiqa.models.openai_server import OpenAIServerProvider
    f=openai_job;gateway=f['app'].state.model_gateway;original=module._provider_endpoint;changed=[False]
    replacement=OpenAIServerProvider(transport=f['openai_transport'])
    def gate(provider,grant):
        original(provider,grant)
        if not changed[0]:changed[0]=True;gateway.provider=replacement
    monkeypatch.setattr(module,'_provider_endpoint',gate)
    result=seed.post(f)
    assert result.status_code==503,result.text
    assert result.json()['error']['provider_dispatched'] is False and f['openai_sent']==[]
