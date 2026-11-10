"""A provider response, not an injected fixture target, determines a healing proposal."""
import json
from dataclasses import replace
from uuid import UUID,uuid4

import pytest
from aiqa.api.app import create_app
from aiqa.config import load_settings
from aiqa.contracts.models import OwnedEpisode,RoleBinding
from aiqa.domain.projects import bind_store,create_project
from aiqa.healing.targets import validate_healing_proposal
from aiqa.healing.service import HealingService,run_replay_verify_and_heal
from aiqa.models.broker import AttemptModelPolicy,ServerModelGateway,WorkerModelCallBridge
from aiqa.models.provider_http import ProviderHttpResult
from aiqa.security.secrets import MemorySecretBackend,bind_secret_store,build_server_secret_resolver
from aiqa.store.database import migrate_store
from aiqa.store.models import Actor,ProjectCreate,SecretInput,SecretRef,WorkerScope
from test_rx_54 import _Allow,_Script,_broker,_checks,_context,_payload,_heal_screen,_failed_obs


class PayloadProvider:
    kind="fixture"
    def __init__(self):self.content=json.dumps(_payload());self.calls=[];self.timeout=False
    def complete(self,*,model,role,secret,sanitized_inputs,token_output_limit):
        self.calls.append(role)
        if self.timeout:raise TimeoutError("provider timed out")
        return ProviderHttpResult(self.content,"fixture-response",200,model)
    @property
    def call_count(self):return len(self.calls)


@pytest.fixture
def provider_bridge(tmp_path):
    settings=load_settings({"AIQA_HOST":"127.0.0.1","AIQA_PORT":"8000","AIQA_RUNTIME_ROOT":str(tmp_path/"runtime")})
    store=create_app(settings).state.open_store();migrate_store(store)
    with bind_store(store):project=create_project(Actor(uuid4(),None,True),ProjectCreate("Response proof","response-proof","","web"))
    actor=Actor(uuid4(),project.project_id,True)
    resolver=build_server_secret_resolver(settings,backend=MemorySecretBackend())
    with bind_secret_store(store):
        saved=resolver.put(actor,SecretInput(value="synthetic-provider-key",name="Fixture"))
    ref=SecretRef(project.project_id,saved.ref_id,saved.revision)
    provider=PayloadProvider();gateway=ServerModelGateway(provider=provider,resolver=resolver)
    policy=AttemptModelPolicy(project_id=project.project_id,item_id="item-1",purpose="regression",healing_enabled=True,max_calls=1,budget="0.50",bindings=(RoleBinding("healing",1,"fixture",str(ref.ref_id)),),checks=(),episodes=(OwnedEpisode("episode-1","item-1"),),secret_refs={"healing":ref})
    gateway.register_policy(policy)
    bridge=WorkerModelCallBridge(gateway,WorkerScope("fixture-worker",(project.project_id,),("regression",)),project_id=project.project_id,item_id="item-1",actor_id=actor.actor_id,purpose="regression",store=store)
    yield provider,bridge,gateway,project.project_id
    store.close()


def _run(bridge,**changes):
    args=dict(checks=_checks(),observation=_failed_obs(),control=_Allow(),broker=_broker(),transport=_Script(),healing_enabled=True,heal_budget_remaining=1,approved_failure_reason="target_not_found",healable_check_id="check-1",approved_package_digest="sha256:original-package",healing_context=_context(),heal_observation=_heal_screen(),worker_model_call=bridge)
    args.update(changes)
    return run_replay_verify_and_heal(**args)


def test_real_gateway_content_is_used_and_context_is_immutable(provider_bridge):
    provider,bridge,gateway,project=provider_bridge
    context=replace(_context(),payload={})
    result=_run(bridge,healing_context=context)
    assert result.record.proposal_accepted is True
    assert context.payload=={}
    assert provider.calls==["healing"]
    assert gateway.usage_for(project,"item-1")["healing_calls"]==1
    assert result.record.healer_calls==1 and result.success is False
    assert result.record.original_failure=="target_not_found"
    assert result.record.package_digest_after=="sha256:original-package"
    assert any(check.status=="violated" for check in result.check_results)


@pytest.mark.parametrize("content",["not json","null","[]","true",'{"value":NaN}',json.dumps(_payload())[:-1]+',"action":"click"}'])
def test_invalid_provider_json_never_falls_back_to_static_payload(provider_bridge,content):
    provider,bridge,gateway,project=provider_bridge;provider.content=content
    result=_run(bridge)
    assert result.record.proposal_admitted is False and result.record.proposal_accepted is False
    assert result.record.attempt_result=="invalid_response"
    assert result.record.healer_calls==1 and provider.calls==["healing"]
    assert gateway.usage_for(project,"item-1")["healing_calls"]==1
    assert result.success is False and result.record.package_digest_after=="sha256:original-package"


@pytest.mark.parametrize("change",[{"locator":"#unrelated"},{"action":"submit"},{"input":"different"},{"path":"/another"},{"role":"link","name":"Other","container":"else","resource_id":"other","text":"Other","context":"else"},{"coordinates":[999,999]}])
def test_provider_target_must_match_the_observed_approved_target(provider_bridge,change):
    provider,bridge,_,_=provider_bridge;provider.content=json.dumps({**_payload(),**change})
    result=_run(bridge)
    assert result.record.proposal_accepted is False
    assert result.record.healer_calls==1 and result.success is False
    assert result.record.package_digest_after=="sha256:original-package"


@pytest.mark.parametrize("changes",[{"healing_enabled":False},{"heal_budget_remaining":0},{"approved_failure_reason":None}])
def test_disallowed_recovery_does_not_call_the_provider(provider_bridge,changes):
    provider,bridge,gateway,project=provider_bridge
    result=_run(bridge,**changes)
    assert provider.calls==[] and result.record.healer_calls==0
    assert gateway.usage_for(project,"item-1")["healing_calls"]==0


def test_provider_timeout_retains_original_failure_and_counts_consumed_attempt(provider_bridge):
    provider,bridge,gateway,project=provider_bridge;provider.timeout=True
    result=_run(bridge)
    assert result.record.attempt_result=="timed_out" and result.record.healer_calls==1
    assert result.record.proposal_accepted is False and result.success is False
    assert result.record.original_failure=="target_not_found"
    assert gateway.usage_for(project,"item-1")["healing_calls"]==1
    again=_run(bridge)
    assert again.record.attempt_result=="rejected_policy" and again.record.healer_calls==0
    assert provider.calls==["healing"]


def test_observed_locator_is_required_even_for_a_plausible_identity():
    from dataclasses import replace
    observation=_heal_screen();body=json.loads(observation.dom);body["elements"][0].pop("locator")
    proposed=HealingService(_broker()).propose(_context())
    decision=validate_healing_proposal(proposed,replace(observation,dom=json.dumps(body)))
    assert decision.accepted is False and "locator" in decision.reasons


@pytest.mark.parametrize("field",["basis","kind"])
@pytest.mark.parametrize("value",[[],{}])
def test_wrong_shape_provider_fields_are_rejected_not_raised(provider_bridge,field,value):
    provider,bridge,_,_=provider_bridge;provider.content=json.dumps({**_payload(),field:value})
    result=_run(bridge)
    assert result.record.proposal_accepted is False and result.record.proposal_admitted is False
    assert result.record.healer_calls==1 and result.success is False


@pytest.mark.parametrize("overflow",['1e400','{"nested":[1e400]}'])
def test_exponent_overflow_is_not_accepted_in_provider_json(provider_bridge,overflow):
    provider,bridge,_,_=provider_bridge;provider.content=json.dumps(_payload())[:-1]+',"extra":'+overflow+'}'
    result=_run(bridge)
    assert result.record.proposal_accepted is False and result.record.attempt_result=="invalid_response"
    assert result.record.healer_calls==1


def test_candidate_locator_must_be_unique_across_different_identities():
    observation=_heal_screen();body=json.loads(observation.dom)
    other={**body["elements"][0],"role":"link","name":"Other","container":"else","resource_id":"id.other","text":"Other","context":"else"}
    body["elements"].insert(0,other)
    proposed=HealingService(_broker()).propose(_context())
    result=validate_healing_proposal(proposed,replace(observation,dom=json.dumps(body)))
    assert result.accepted is False and "locator" in result.reasons


@pytest.mark.parametrize("kind",[[],{}])
def test_observed_target_kind_is_typed(kind):
    observation=_heal_screen();body=json.loads(observation.dom);body["elements"][0]["kind"]=kind
    result=validate_healing_proposal(HealingService(_broker()).propose(_context()),replace(observation,dom=json.dumps(body)))
    assert result.accepted is False


@pytest.mark.parametrize("failure,attempt",[("timeout","timed_out"),("envelope","invalid_response"),("http","provider_failed"),("quota","provider_failed")])
def test_http_provider_failure_consumes_one_attempt_and_retry_quota(provider_bridge,failure,attempt):
    import httpx
    from aiqa.models.provider_http import OperationalProviderHttp
    _,bridge,gateway,project=provider_bridge
    sent=[]
    def receive(request):
        sent.append(request.url.path)
        if failure=="timeout":raise httpx.ReadTimeout("fixture",request=request)
        if failure=="envelope":return httpx.Response(200,json={"bad":"envelope"})
        return httpx.Response(429 if failure=="quota" else 503,json={})
    provider=OperationalProviderHttp(allow_live=True,base_url="https://provider.example",transport=httpx.MockTransport(receive))
    gateway.provider=provider
    first=_run(bridge)
    assert first.record.attempt_result==attempt and first.record.healer_calls==1
    assert first.record.proposal_accepted is False and first.success is False
    assert gateway.usage_for(project,"item-1")["healing_calls"]==1
    again=_run(bridge)
    assert again.record.attempt_result=="rejected_policy" and again.record.healer_calls==0
    assert sent==["/v1/complete"]
    assert provider.call_count==1


def test_pre_dispatch_model_denial_does_not_consume_a_call(provider_bridge):
    provider,bridge,gateway,project=provider_bridge;bridge.binding_revision=999
    result=_run(bridge)
    assert result.record.attempt_result=="rejected_policy" and result.record.healer_calls==0
    assert provider.calls==[] and gateway.usage_for(project,"item-1")["healing_calls"]==0
