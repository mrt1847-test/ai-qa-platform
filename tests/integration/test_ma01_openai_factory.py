"""MA01 normal app factory -> secret resolver -> gateway -> bounded OpenAI HTTP seam."""
from dataclasses import replace
from uuid import uuid4
import httpx,pytest
from aiqa.api.app import create_app
from aiqa.config import load_settings
from aiqa.contracts.models import RoleBinding
from aiqa.domain.projects import bind_store,create_project
from aiqa.models.broker import ModelRequestDenied
from aiqa.security.secrets import MemorySecretBackend,bind_secret_store
from aiqa.store.database import migrate_store
from aiqa.store.models import Actor,ProjectCreate,SecretInput,SecretRef,WorkerScope
from test_rx_45 import _env,_policy,_req
from unit.test_openai_provider_settings import response


@pytest.fixture
def gateway_state(tmp_path,monkeypatch):
    sent=[];client=httpx.Client;mode={"status":200}
    def handle(req):
        sent.append(req)
        assert req.headers['Authorization']=='Bearer synthetic-server-only'
        return httpx.Response(mode["status"],json=response())
    def bounded(*args,**kwargs):kwargs['transport']=httpx.MockTransport(handle);return client(*args,**kwargs)
    monkeypatch.setattr(httpx,'Client',bounded)
    settings=load_settings(_env(tmp_path,AIQA_MODEL_PROVIDER_MODE='openai'))
    app=create_app(settings,secret_backend=MemorySecretBackend())
    gateway=app.state.model_gateway;provider=gateway.provider
    assert provider.kind=='openai'
    store=app.state.open_store()
    try:
        migrate_store(store);owner=Actor(uuid4(),None,True)
        with bind_store(store):project=create_project(owner,ProjectCreate('MA01','ma01','','android'))
        actor=Actor(owner.actor_id,project.project_id,True)
        with bind_secret_store(store):
            secret=app.state.secret_resolver.put(actor,SecretInput(value='synthetic-server-only',name='model'))
        ref=SecretRef(project.project_id,secret.ref_id,secret.revision)
        policy=replace(_policy(project.project_id,'item',ref,max_calls=1),bindings=(RoleBinding('verification',1,'gpt-6-luna',str(ref.ref_id)),))
        gateway.register_policy(policy)
        worker=WorkerScope(str(uuid4()),frozenset({project.project_id}),frozenset({'regression','recording'}),None)
        request=_req()
        def send(req,key):return gateway.handle(worker,req,project_id=project.project_id,item_id='item',idempotency_key=key,actor_id=actor.actor_id,store=store)
        yield {'send':send,'request':request,'provider':provider,'sent':sent,'mode':mode,'gateway':gateway,'project':project.project_id,'policy':policy,'ref':ref}
    finally:store.close()


def test_normal_app_factory_resolves_server_secret_and_keeps_gateway_guards(gateway_state):
    f=gateway_state;send=f['send'];provider=f['provider'];sent=f['sent']
    first=send(f['request'],'once');again=send(f['request'],'once')
    assert first.content=='key(4)' and again.replayed and len(sent)==provider.call_count==1
    assert 'synthetic-server-only' not in repr(first)
    with pytest.raises(ModelRequestDenied,match='quota'):send(_req(),'next')
    assert len(sent)==1


def test_predispatch_failure_does_not_consume_item_quota(gateway_state):
    f=gateway_state
    with pytest.raises(ModelRequestDenied) as error:f['send'](replace(f['request'],token_output_limit=8),'invalid')
    assert error.value.provider_dispatched is False
    assert f['gateway'].usage_for(f['project'],'item')['verification_calls']==0
    assert f['sent']==[] and f['provider'].call_count==0
    assert f['send'](f['request'],'corrected').allowed and len(f['sent'])==1


def test_actual_http_failure_consumes_item_quota_without_retry(gateway_state):
    f=gateway_state;f['mode']['status']=503
    with pytest.raises(ModelRequestDenied) as error:f['send'](f['request'],'sent-error')
    assert error.value.provider_dispatched is True
    assert len(f['sent'])==f['provider'].call_count==1
    assert f['gateway'].usage_for(f['project'],'item')['verification_calls']==1
    with pytest.raises(ModelRequestDenied,match='quota'):f['send'](_req(),'next')
    assert len(f['sent'])==1


def test_admitted_maintenance_role_reaches_server_openai(gateway_state):
    f=gateway_state;ref=f['ref']
    policy=replace(f['policy'],purpose='recording',bindings=(RoleBinding('maintenance',1,'gpt-6-luna',str(ref.ref_id)),),secret_refs={'maintenance':ref})
    f['gateway'].register_policy(policy)
    request=replace(f['request'],purpose='recording',role='maintenance')
    receipt=f['send'](request,'maintenance')
    assert receipt.allowed and len(f['sent'])==1 and f['provider'].calls_for('maintenance')==1
