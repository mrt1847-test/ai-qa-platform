import json
from pathlib import Path
import httpx
import pytest

from aiqa.models.openai_http import OpenAIProviderHttp, load_local_api_key
from aiqa.models.provider_http import ProviderHttpError


def response():
    return {'id':'resp_test','model':'gpt-5-mini','status':'completed','output':[{'type':'reasoning'},
        {'type':'message','role':'assistant','content':[{'type':'output_text','text':'key(4)'}]}],
        'usage':{'input_tokens':120,'output_tokens':15,'total_tokens':135}}


def test_load_key_file_without_execution_or_error_disclosure(tmp_path):
    p=tmp_path/'local.env';p.write_text('# local\nOPENAI_API_KEY="private-test"\n',encoding='utf-8')
    assert load_local_api_key(p)=='private-test'
    p.write_text('OPENAI_API_KEY=private-test\nOPENAI_API_KEY=other\n',encoding='utf-8')
    with pytest.raises(ValueError) as exc:load_local_api_key(p)
    assert 'private-test' not in str(exc.value)


def test_direct_openai_request_is_opt_in_and_returns_usage():
    seen=[]
    def handle(req):
        seen.append(req)
        return httpx.Response(200,json=response())
    port=OpenAIProviderHttp(allow_live=True,max_calls=1,transport=httpx.MockTransport(handle))
    result=port.complete(model='gpt-5-mini',role='authoring',secret='private-test',sanitized_inputs=('one back',),token_output_limit=512)
    assert result.content=='key(4)' and result.input_tokens==120 and result.output_tokens==15
    assert str(seen[0].url)=='https://api.openai.com/v1/responses'
    body=json.loads(seen[0].content)
    assert body['store'] is False and body['max_output_tokens']==512
    assert body['input'][0]['content'][0]['text']=='one back'
    with pytest.raises(ProviderHttpError):port.complete(model='gpt-5-mini',role='authoring',secret='private-test',sanitized_inputs=(),token_output_limit=512)
    assert len(seen)==1 and 'private-test' not in repr(port.calls)


@pytest.mark.parametrize('status',[401,429,503])
def test_error_latches_without_retry_or_secret_in_error(status):
    seen=[]
    def handle(req):
        seen.append(req);return httpx.Response(status,json={'error':{'message':'private-test'}})
    port=OpenAIProviderHttp(allow_live=True,transport=httpx.MockTransport(handle))
    for _ in range(2):
        with pytest.raises(ProviderHttpError) as exc:port.complete(model='gpt-5-mini',role='authoring',secret='private-test',sanitized_inputs=(),token_output_limit=512)
        assert 'private-test' not in str(exc.value)
    assert len(seen)==1


@pytest.mark.parametrize('damage',['incomplete','refusal','no_usage','bad_usage'])
def test_non_actionable_response_cannot_produce_a_native_plan(damage):
    raw=response()
    if damage=='incomplete':raw['status']='incomplete'
    elif damage=='refusal':raw['output'][1]['content']=[{'type':'refusal','refusal':'no'}]
    elif damage=='no_usage':raw.pop('usage')
    else:raw['usage']['input_tokens']=True
    port=OpenAIProviderHttp(allow_live=True,transport=httpx.MockTransport(lambda r:httpx.Response(200,json=raw)))
    with pytest.raises(ProviderHttpError):port.complete(model='gpt-5-mini',role='authoring',secret='private-test',sanitized_inputs=(),token_output_limit=512)


def test_disabled_port_sends_nothing():
    seen=[]
    port=OpenAIProviderHttp(transport=httpx.MockTransport(lambda r:seen.append(r)))
    with pytest.raises(ProviderHttpError):port.complete(model='gpt-5-mini',role='authoring',secret='private-test',sanitized_inputs=(),token_output_limit=512)
    assert not seen


def test_observation_is_encoded_as_image_and_hash_drift_sends_nothing():
    import hashlib,struct,zlib
    from dataclasses import asdict,replace
    from aiqa.contracts.actions import CaptureGeometry
    from aiqa.contracts.model_observations import ProviderObservation
    def chunk(name,data):return struct.pack('>I',len(data))+name+data+struct.pack('>I',zlib.crc32(name+data)&0xffffffff)
    png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',2,2,8,2,0,0,0))+chunk(b'IDAT',zlib.compress((b'\x00'+b'\xff'*6)*2))+chunk(b'IEND',b'')
    obs=ProviderObservation(png,'sha256:'+hashlib.sha256(png).hexdigest(),asdict(CaptureGeometry(2,2,2,2,'identity',0,(0,0,2,2))),'2026-11-15T00:00:00+00:00')
    seen=[]
    def handle(req):seen.append(req);return httpx.Response(200,json=response())
    port=OpenAIProviderHttp(allow_live=True,transport=httpx.MockTransport(handle))
    port.complete(model='gpt-5-mini',role='authoring',secret='private-test',sanitized_inputs=('one back',),token_output_limit=512,observation=obs)
    content=json.loads(seen[0].content)['input'][0]['content']
    assert content[-1]['type']=='input_image' and content[-1]['image_url'].startswith('data:image/png;base64,')
    with pytest.raises(ProviderHttpError):port.complete(model='gpt-5-mini',role='authoring',secret='private-test',sanitized_inputs=('one back',),token_output_limit=512,observation=replace(obs,image_hash='sha256:'+'0'*64))
    assert len(seen)==1


def test_completed_envelope_with_incomplete_message_cannot_return_action():
    raw=response();raw['output'][1]['status']='incomplete'
    port=OpenAIProviderHttp(allow_live=True,transport=httpx.MockTransport(lambda r:httpx.Response(200,json=raw)))
    with pytest.raises(ProviderHttpError):port.complete(model='gpt-5-mini',role='authoring',secret='private-test',sanitized_inputs=(),token_output_limit=512)


@pytest.mark.parametrize('damage',['changed','multiple','different_action'])
def test_smoke_rechecks_pinned_single_back_before_dispatch(tmp_path,damage):
    import runpy,hashlib
    from test_rx87_native_trace import mapping
    module=runpy.run_path(str(Path('tools/android_openai_smoke.py')))
    raw=json.loads(mapping());raw['events']=raw['events'][-1:];raw['events'][0]['line']=1;raw['native_action_count']=1
    path=tmp_path/'trace.json';path.write_text(json.dumps(raw),encoding='utf-8')
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    if damage=='changed':path.write_text('{}',encoding='utf-8')
    elif damage=='multiple':
        from test_rx87_native_trace import mapping
        path.write_text(mapping(),encoding='utf-8');digest=hashlib.sha256(path.read_bytes()).hexdigest()
    else:
        raw['events'][0]['native']['keycode']=66;raw['events'][0]['action']='key';raw['events'][0]['target']='66'
        path.write_text(json.dumps(raw),encoding='utf-8');digest=hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):module['load_pinned_back'](path,digest)


def test_smoke_rejects_zero_or_blocked_dispatch():
    import runpy
    from types import SimpleNamespace
    module=runpy.run_path(str(Path('tools/android_openai_smoke.py')))
    with pytest.raises(ValueError):module['require_acknowledged'](SimpleNamespace(native_calls=0,outcome='blocked',argv=()))


@pytest.mark.parametrize('effort',['none','low'])
def test_luna_uses_explicit_supported_effort_and_measures_reasoning(effort):
    seen=[];raw=response();raw['model']='gpt-6-luna';raw['usage']['output_tokens_details']={'reasoning_tokens':10}
    raw['usage']['input_tokens_details']={'cached_tokens':20}
    def handle(req):seen.append(req);return httpx.Response(200,json=raw)
    port=OpenAIProviderHttp(allow_live=True,reasoning_effort=effort,max_calls=10,transport=httpx.MockTransport(handle))
    result=port.complete(model='gpt-6-luna',role='authoring',secret='private-test',sanitized_inputs=('task',),token_output_limit=1024)
    assert json.loads(seen[0].content)['reasoning']=={'effort':effort}
    assert result.reasoning_tokens==10 and result.cached_input_tokens==20


@pytest.mark.parametrize('value',[True,0,13])
def test_luna_evaluation_call_cap_is_bounded(value):
    with pytest.raises(ValueError):OpenAIProviderHttp(allow_live=True,max_calls=value)


def test_luna_rejects_unsupported_effort_before_http():
    with pytest.raises(ValueError):OpenAIProviderHttp(allow_live=True,reasoning_effort='minimal')


def test_send_boundary_can_cancel_before_any_chargeable_request():
    seen=[]
    port=OpenAIProviderHttp(allow_live=True,transport=httpx.MockTransport(lambda r:seen.append(r)))
    def deny():raise RuntimeError('deadline')
    with pytest.raises(RuntimeError):port.complete(model='gpt-6-luna',role='authoring',secret='private-test',sanitized_inputs=('task',),token_output_limit=1024,before_send=deny)
    assert not seen and port.call_count==0


def test_upstream_conversation_preserves_system_history_and_images():
    seen=[]
    conversation=({'role':'system','content':[{'type':'input_text','text':'original tool prompt'}]},
                  {'role':'user','content':[{'type':'input_text','text':'goal'}]},
                  {'role':'assistant','content':[{'type':'output_text','text':'original prior action'}]},
                  {'role':'user','content':[{'type':'input_text','text':'current screen'}]})
    port=OpenAIProviderHttp(allow_live=True,transport=httpx.MockTransport(lambda req:(seen.append(req) or httpx.Response(200,json=response()))))
    port.complete(model='gpt-6-luna',role='authoring',secret='private-test',sanitized_inputs=(),token_output_limit=1024,conversation=conversation)
    assert json.loads(seen[0].content)['input']==list(conversation)


def test_upstream_conversation_rejects_remote_image_without_sending():
    seen=[];port=OpenAIProviderHttp(allow_live=True,transport=httpx.MockTransport(lambda r:seen.append(r)))
    conversation=({'role':'user','content':[{'type':'input_image','image_url':'https://outside/image.png','detail':'high'}]},)
    with pytest.raises(ProviderHttpError):port.complete(model='gpt-6-luna',role='authoring',secret='private-test',sanitized_inputs=(),token_output_limit=1024,conversation=conversation)
    assert not seen and port.call_count==0


def test_send_fence_runs_after_client_preparation(monkeypatch):
    actual=httpx.Client;prepared=[];seen=[]
    def client(*args,**kwargs):prepared.append(True);return actual(*args,**kwargs)
    monkeypatch.setattr(httpx,'Client',client)
    port=OpenAIProviderHttp(allow_live=True,transport=httpx.MockTransport(lambda req:(seen.append(req) or httpx.Response(200,json=response()))))
    def fence():assert prepared, 'client preparation must precede final send fence'
    port.complete(model='gpt-6-luna',role='authoring',secret='private-test',sanitized_inputs=(),token_output_limit=1024,before_send=fence)
    assert len(seen)==1


def test_non_actionable_paid_response_is_preserved_for_diagnosis():
    raw=response();raw['status']='incomplete';saved=[]
    port=OpenAIProviderHttp(allow_live=True,response_sink=saved.append,transport=httpx.MockTransport(lambda r:httpx.Response(200,json=raw)))
    with pytest.raises(ProviderHttpError):port.complete(model='gpt-6-luna',role='authoring',secret='private-test',sanitized_inputs=(),token_output_limit=1024)
    assert json.loads(saved[0])['status']=='incomplete' and port.call_count==1


def test_mobile_agent_response_is_constrained_to_one_tool():
    seen=[];port=OpenAIProviderHttp(allow_live=True,transport=httpx.MockTransport(lambda req:(seen.append(req) or httpx.Response(200,json=response()))))
    port.complete(model='gpt-6-luna',role='authoring',secret='private-test',sanitized_inputs=(),token_output_limit=1024,conversation=({'role':'user','content':[{'type':'input_text','text':'goal'}]},),mobile_action_format=True)
    fmt=json.loads(seen[0].content)['text']['format']
    assert fmt['type']=='json_schema' and fmt['strict'] is True
    assert fmt['schema']['properties']['name']['enum']==['mobile_use']
    assert 'anyOf' in fmt['schema']['properties']['arguments']


def test_luna_commentary_cannot_be_concatenated_into_the_final_action():
    raw=response();raw['model']='gpt-6-luna';raw['output']=[
        {'type':'message','role':'assistant','status':'completed','phase':'commentary','content':[{'type':'output_text','text':'I will choose an action.'}]},
        {'type':'message','role':'assistant','status':'completed','phase':'final_answer','content':[{'type':'output_text','text':'key(4)'}]}]
    port=OpenAIProviderHttp(allow_live=True,transport=httpx.MockTransport(lambda r:httpx.Response(200,json=raw)))
    result=port.complete(model='gpt-6-luna',role='authoring',secret='private-test',sanitized_inputs=(),token_output_limit=1024)
    assert result.content=='key(4)'
