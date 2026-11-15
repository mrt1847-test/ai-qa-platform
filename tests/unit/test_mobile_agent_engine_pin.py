from copy import deepcopy
import hashlib,json
from pathlib import Path
import pytest
from aiqa.contracts.authoring import authoring_policy_ref,validate_authoring_pin
from aiqa.domain.hashing import canonical_hash
from aiqa.recording.model_pin import freeze_authoring_limits


def inputs():
    binding={'binding_id':'binding','revision_id':'rev','revision':1,'role':'authoring','content_hash':'sha256:binding','key_ref_id':'ref','key_revision':1}
    caps={'timeout_seconds':30,'max_actions':4,'max_model_calls':8,'budget':'0.70','currency':'USD'}
    return binding,caps


def limits(**kwargs):
    binding,caps=inputs()
    return freeze_authoring_limits(binding,caps,'version','sha256:version',**kwargs)


def snapshot(pin):
    return {'purpose':'recording','limits':pin,'policy_ref':pin['policy_ref'],
        'intent':{'case_version_id':'version','content_hash':'sha256:version'}}


def test_engine_ref_exactly_identifies_the_actual_manifest_and_runner():
    from aiqa.contracts.mobile_agent_engine import mobile_agent_engine_ref,require_mobile_agent_engine
    from aiqa.adapters.mobile_agent_upstream import COMMIT
    ref=mobile_agent_engine_ref()
    assert ref['upstream_commit']==COMMIT=='81fa28b564ef7a695521500bc15a0e1324b2b394'
    assert ref['manifest_sha256']==hashlib.sha256(Path('third_party/mobile_agent/manifest.json').read_bytes()).hexdigest()
    assert ref['kind']=='mobile-agent-v3.5' and ref['protocol']=='mobile-agent-parent-rpc-v1'
    assert require_mobile_agent_engine(ref)==ref
    ref['kind']='changed'
    assert mobile_agent_engine_ref()['kind']=='mobile-agent-v3.5'


def test_legacy_policy_hash_is_preserved_exactly_without_engine_marker():
    pin=limits()
    fields=('authoring_schema','authoring_binding','input_case_version_id','input_version_hash','timeout_seconds','max_actions','max_model_calls','budget','currency')
    original='authoring-admission-v1:'+canonical_hash({key:pin.get(key) for key in fields},'canon-json-v1')
    assert pin['policy_ref']==original and 'authoring_engine' not in pin
    assert validate_authoring_pin(snapshot(pin))==pin


def test_new_engine_is_hashed_frozen_and_validated_without_alias():
    from aiqa.contracts.mobile_agent_engine import mobile_agent_engine_ref
    ref=mobile_agent_engine_ref();pin=limits(engine_ref=ref)
    assert pin['authoring_engine']==ref and pin['policy_ref']!=limits()['policy_ref']
    detached=validate_authoring_pin(snapshot(pin))
    ref['protocol']='changed';detached['authoring_engine']['kind']='changed'
    assert pin['authoring_engine']['kind']=='mobile-agent-v3.5'
    assert pin['authoring_engine']['protocol']=='mobile-agent-parent-rpc-v1'
    assert pin['policy_ref']==authoring_policy_ref(pin)


@pytest.mark.parametrize('bad',[None,{},[],{'kind':'mobile-agent-v3.5'}])
def test_partial_engine_marker_never_downgrades_to_legacy(bad):
    pin=limits();pin['authoring_engine']=bad
    pin['policy_ref']=authoring_policy_ref(pin)
    with pytest.raises(ValueError):validate_authoring_pin(snapshot(pin))
    with pytest.raises(ValueError):validate_authoring_pin({'purpose':'recording','limits':{'authoring_engine':bad}})


@pytest.mark.parametrize('change',[{'upstream_commit':'0'*40},{'manifest_sha256':'0'*64},{'protocol':'unknown'},
    {'kind':'other'},{'extra':'ignored'}])
def test_unknown_or_tampered_ref_is_refused_even_with_recomputed_hash(change):
    from aiqa.contracts.mobile_agent_engine import mobile_agent_engine_ref
    ref={**mobile_agent_engine_ref(),**change}
    with pytest.raises(ValueError):limits(engine_ref=ref)
    pin=limits();pin['authoring_engine']=ref;pin['policy_ref']=authoring_policy_ref(pin)
    with pytest.raises(ValueError):validate_authoring_pin(snapshot(pin))


def test_legacy_recording_caps_refuse_original_engine_without_explicit_support():
    from aiqa.contracts.mobile_agent_engine import mobile_agent_engine_ref
    from aiqa.worker.recording_limits import resolve_recording_limits
    pin=limits(engine_ref=mobile_agent_engine_ref())
    with pytest.raises(ValueError,match='recording engine unsupported'):
        resolve_recording_limits(snapshot(pin),worker_actions=4,worker_seconds=30)
    allowed=resolve_recording_limits(snapshot(pin),worker_actions=4,worker_seconds=30,supported_engine=mobile_agent_engine_ref())
    assert allowed.max_actions==4 and allowed.max_model_calls==8


def test_legacy_plan_provider_never_sends_a_different_engine_protocol():
    from aiqa.contracts.mobile_agent_engine import mobile_agent_engine_ref
    from aiqa.worker.android_jobs import server_model_plan_provider
    from aiqa.adapters.mobile_agent_android import MobileAgentRejected
    pin=limits(engine_ref=mobile_agent_engine_ref())
    class Client:
        def __getattr__(self,name):raise AssertionError('legacy transport must not be used')
    with pytest.raises(MobileAgentRejected,match='recording engine unsupported'):
        server_model_plan_provider(Client())({'project_id':'project','attempt_id':'attempt','snapshot':snapshot(pin)})


def test_validated_pin_extensions_are_detached_from_the_claim():
    from aiqa.contracts.mobile_agent_engine import mobile_agent_engine_ref
    pin=limits(engine_ref=mobile_agent_engine_ref());pin['extra']={'nested':['original']}
    checked=validate_authoring_pin(snapshot(pin))
    checked['extra']['nested'].append('changed')
    assert pin['extra']=={'nested':['original']}
