from dataclasses import replace
from uuid import uuid4
import json
import pytest
from aiqa.contracts.models import RoleBinding
from aiqa.models.broker import ModelRequestDenied,ModelRequestConflict
from aiqa.models.provider_http import FixtureProviderHttp
from test_ma01_openai_factory import gateway_state
from unit.test_mobile_agent_context import intent,frame


def configure(f,*,role='authoring',model='gpt-6-luna'):
    from aiqa.models.mobile_agent_context import build_mobile_agent_context
    policy=replace(f['policy'],purpose='recording',bindings=(RoleBinding(role,1,model,str(f['ref'].ref_id)),),secret_refs={role:f['ref']},max_calls=2)
    f['gateway'].register_policy(policy)
    request=replace(f['request'],purpose='recording',role=role,owner_kind='authoring',owner_id='item',check_id=None,episode_id=None)
    context=build_mobile_agent_context(intent=intent(),current=frame(),history=())
    return request,context


def send(f,request,context,key='context',**kwargs):
    return f['gateway'].handle(f['worker'],request,project_id=f['project'],item_id='item',idempotency_key=key,
        actor_id=f['actor'].actor_id,store=f['store'],mobile_context=context,**kwargs)


def test_gateway_resolves_server_secret_and_measures_original_context(gateway_state):
    f=gateway_state;request,context=configure(f)
    result=send(f,request,context);again=send(f,request,context)
    assert result.allowed and again.replayed and len(f['sent'])==1
    assert json.loads(f['sent'][0].content)['input']==list(context.messages())
    assert result.usage['input_tokens']==100 and result.usage['output_tokens']==20
    assert f['gateway'].usage_for(f['project'],'item')['authoring_calls']==1


def test_context_content_is_part_of_gateway_idempotency(gateway_state):
    from aiqa.models.mobile_agent_context import build_mobile_agent_context
    f=gateway_state;request,context=configure(f);send(f,request,context)
    changed=build_mobile_agent_context(intent=replace(intent(),objective='Different goal'),current=frame(),history=())
    with pytest.raises(ModelRequestConflict):send(f,request,changed)
    assert len(f['sent'])==1


@pytest.mark.parametrize('bad',['provider','role','model','observation','dict'])
def test_gateway_context_cannot_be_sent_through_other_protocols(gateway_state,bad):
    f=gateway_state
    request,context=configure(f,role='maintenance' if bad=='role' else 'authoring',model='other' if bad=='model' else 'gpt-6-luna')
    if bad=='provider':f['gateway'].provider=FixtureProviderHttp()
    if bad=='dict':context={'messages':'worker override'}
    kwargs={'observation':frame()} if bad=='observation' else {}
    with pytest.raises(ModelRequestDenied) as exc:send(f,request,context,**kwargs)
    assert exc.value.provider_dispatched is False and len(f['sent'])==0
    assert f['gateway'].usage_for(f['project'],'item')['provider_calls']==0


def test_internal_context_preserves_last_send_authority_and_quota(gateway_state):
    f=gateway_state;request,context=configure(f)
    count=[0]
    def boundary():
        count[0]+=1
        if count[0]==2:raise ModelRequestDenied('cancelled')
    with pytest.raises(ModelRequestDenied,match='cancelled'):send(f,request,context,before_provider=boundary)
    assert count[0]==2 and len(f['sent'])==0
    assert f['gateway'].usage_for(f['project'],'item')['provider_calls']==0
    assert send(f,replace(request,call_id=uuid4()),context,key='fresh').allowed
    assert len(f['sent'])==1


def test_cached_context_receipt_still_rejects_mixed_observation(gateway_state):
    f=gateway_state;request,context=configure(f)
    first=send(f,request,context)
    with pytest.raises(ModelRequestDenied) as exc:send(f,request,context,observation=frame())
    assert exc.value.provider_dispatched is False
    assert first.allowed and send(f,request,context).replayed and len(f['sent'])==1
