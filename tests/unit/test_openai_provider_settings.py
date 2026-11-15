"""MA01: explicit server OpenAI settings and independent, bounded provider sends."""
import json
from pathlib import Path
import httpx,pytest
from aiqa.config import ModelProviderSettings,SettingsError,load_settings
from aiqa.models.provider_http import build_provider_from_settings,ProviderHttpError


def env(tmp_path,**extra):return {'AIQA_HOST':'127.0.0.1','AIQA_PORT':'8000','AIQA_RUNTIME_ROOT':str(tmp_path),**extra}


def response():
 return {'id':'response-fixture','model':'gpt-6-luna','status':'completed',
  'output':[{'type':'message','role':'assistant','phase':'commentary','content':[{'type':'output_text','text':'progress'}]},
            {'type':'message','role':'assistant','phase':'final_answer','content':[{'type':'output_text','text':'key(4)'}]}],
  'usage':{'input_tokens':100,'output_tokens':20,'total_tokens':120,'output_tokens_details':{'reasoning_tokens':5},'input_tokens_details':{'cached_tokens':50}}}


def complete(provider,**extra):return provider.complete(model='gpt-6-luna',role='authoring',secret='synthetic-not-a-real-key',sanitized_inputs=('goal',),token_output_limit=512,**extra)


def test_factory_is_fixture_by_default_and_openai_requires_explicit_mode(tmp_path,monkeypatch):
 import aiqa.models.openai_http as module
 def deny(*a,**kw):raise AssertionError('factory must not read local keys')
 monkeypatch.setattr(module,'load_local_api_key',deny)
 assert build_provider_from_settings(load_settings(env(tmp_path))).kind=='fixture'
 settings=load_settings(env(tmp_path,AIQA_MODEL_PROVIDER_MODE='openai'))
 provider=build_provider_from_settings(settings,transport=httpx.MockTransport(lambda req:(_ for _ in ()).throw(AssertionError('factory must not send'))))
 assert provider.kind=='openai' and provider.call_count==0
 assert settings.model_provider.base_url=='https://api.openai.com' and settings.model_provider.complete_path=='/v1/responses'


@pytest.mark.parametrize('extra',[
 {'AIQA_MODEL_PROVIDER_BASE_URL':'https://wrong.example'},
 {'AIQA_MODEL_PROVIDER_BASE_URL':'https://api.openai.com/extra'},
 {'AIQA_MODEL_PROVIDER_COMPLETE_PATH':'/v1/complete'},
 {'AIQA_MODEL_PROVIDER_VERIFY_TLS':'false'},
 {'AIQA_MODEL_PROVIDER_CA_BUNDLE':'other.pem'},
 {'AIQA_MODEL_PROVIDER_TIMEOUT_SECONDS':'nan'},
 {'AIQA_MODEL_PROVIDER_TIMEOUT_SECONDS':'inf'},
 {'AIQA_MODEL_PROVIDER_TIMEOUT_SECONDS':'0'},
 {'AIQA_MODEL_PROVIDER_TIMEOUT_SECONDS':'61'},
])
def test_openai_settings_reject_ignored_or_unsafe_configuration(tmp_path,extra):
 with pytest.raises(SettingsError):load_settings(env(tmp_path,AIQA_MODEL_PROVIDER_MODE='openai',**extra))


def test_server_provider_has_no_global_twelve_call_limit_and_preserves_usage(tmp_path):
 seen=[]
 def handle(request):seen.append(request);return httpx.Response(200,json=response())
 settings=load_settings(env(tmp_path,AIQA_MODEL_PROVIDER_MODE='openai',AIQA_MODEL_PROVIDER_TIMEOUT_SECONDS='1.25'))
 p=build_provider_from_settings(settings,transport=httpx.MockTransport(handle))
 for i in range(13):
  result=complete(p)
  assert result.content=='key(4)' and result.input_tokens==100 and result.output_tokens==20
  assert result.reasoning_tokens==5 and result.cached_input_tokens==50
 assert len(seen)==p.call_count==p.calls_for('authoring')==13
 assert all(str(r.url)=='https://api.openai.com/v1/responses' and r.headers['Authorization']=='Bearer synthetic-not-a-real-key' for r in seen)
 assert seen[0].extensions['timeout']['read']==1.25
 assert json.loads(seen[0].content)['store'] is False
 assert 'synthetic-not-a-real-key' not in repr(vars(p))


def test_single_send_failure_does_not_retry_or_latch_unrelated_requests(tmp_path):
 seen=[]
 def handle(req):
  seen.append(req)
  return httpx.Response(503) if len(seen)==1 else httpx.Response(200,json=response())
 p=build_provider_from_settings(load_settings(env(tmp_path,AIQA_MODEL_PROVIDER_MODE='openai')),transport=httpx.MockTransport(handle))
 with pytest.raises(ProviderHttpError):complete(p)
 assert len(seen)==p.call_count==1
 assert complete(p).content=='key(4)' and len(seen)==p.call_count==2


def test_invalid_or_cancelled_request_is_not_counted_as_dispatched(tmp_path):
 seen=[]
 p=build_provider_from_settings(load_settings(env(tmp_path,AIQA_MODEL_PROVIDER_MODE='openai')),transport=httpx.MockTransport(lambda r:seen.append(r)))
 with pytest.raises(ProviderHttpError):complete(p,observation=object())
 def cancelled():raise RuntimeError('cancelled before send')
 with pytest.raises(RuntimeError):complete(p,before_send=cancelled)
 assert p.call_count==0 and seen==[]
