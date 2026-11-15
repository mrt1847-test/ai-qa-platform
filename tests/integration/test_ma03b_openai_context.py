from dataclasses import replace
import json
import httpx,pytest
from aiqa.models.openai_server import OpenAIServerProvider
from aiqa.models.provider_http import ProviderHttpError
from unit.test_mobile_agent_context import intent,frame,reply
from unit.test_openai_provider_settings import response


def setup():
    from aiqa.models.mobile_agent_context import build_mobile_agent_context
    sent=[]
    def transport(request):sent.append(request);return httpx.Response(200,json=response())
    provider=OpenAIServerProvider(transport=httpx.MockTransport(transport))
    context=build_mobile_agent_context(intent=intent(),current=frame(),history=())
    options=dict(model='gpt-6-luna',role='authoring',secret='synthetic-context-key',sanitized_inputs=(),token_output_limit=256,mobile_context=context)
    return provider,sent,options


def test_server_port_sends_original_context_as_single_action_format():
    provider,sent,options=setup();result=provider.complete(**options)
    body=json.loads(sent[0].content)
    assert body['input']==list(options['mobile_context'].messages())
    assert body['input'][0]['role']=='system' and body['text']['format']['type']=='json_schema'
    assert body['store'] is False and body['model']=='gpt-6-luna'
    assert provider.call_count==1 and result.input_tokens==100
    assert sent[0].headers['Authorization']=='Bearer synthetic-context-key'


@pytest.mark.parametrize('change',[{'model':'other'},{'role':'verification'},{'sanitized_inputs':('worker instruction',)},
    {'observation':frame()},{'mobile_context':({'role':'system','content':'worker override'},)}])
def test_context_cannot_mix_fields_or_downgrade_model_role(change):
    provider,sent,options=setup()
    with pytest.raises(ProviderHttpError) as exc:provider.complete(**{**options,**change})
    assert exc.value.provider_dispatched is False and sent==[] and provider.call_count==0


def test_context_send_still_obeys_last_boundary():
    provider,sent,options=setup()
    def refuse():raise PermissionError('cancelled')
    with pytest.raises(PermissionError):provider.complete(**options,before_send=refuse)
    assert sent==[] and provider.call_count==0


def test_server_typing_literals_come_from_frozen_variables_not_smoke_fixture():
    from aiqa.models.mobile_agent_context import build_mobile_agent_context
    provider,sent,options=setup()
    options['mobile_context']=build_mobile_agent_context(intent=replace(intent(),variables={'query':'keyboard'}),current=frame(),history=())
    provider.complete(**options)
    variants=json.loads(sent[0].content)['text']['format']['schema']['properties']['arguments']['anyOf']
    typing=next(v for v in variants if v['properties']['action']['enum']==['type'])
    assert typing['properties']['text']['enum']==['keyboard']


def test_server_without_literal_variables_does_not_allow_a_fixture_search_term():
    from aiqa.models.mobile_agent_context import build_mobile_agent_context
    provider,sent,options=setup()
    options['mobile_context']=build_mobile_agent_context(intent=replace(intent(),variables={}),current=frame(),history=())
    provider.complete(**options)
    variants=json.loads(sent[0].content)['text']['format']['schema']['properties']['arguments']['anyOf']
    assert all(v['properties']['action']['enum']!=['type'] for v in variants)
