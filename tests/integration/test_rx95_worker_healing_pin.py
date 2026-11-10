"""Worker validates ON metadata before a platform handler can actuate."""
import asyncio
import copy
from datetime import datetime,timezone
from uuid import UUID,uuid4

import httpx
import pytest
from aiqa.api.auth import bound_auth_store,enroll_worker
from aiqa.store.models import Actor
from aiqa.worker.runner import verify_job_snapshot
from test_rx94_healing_claim import admitted_healing,healing_execution,healing_metadata,ux_app


@pytest.fixture
def healing_claim(admitted_healing):
    f=admitted_healing
    store=f["app"].state.open_store()
    try:
        with bound_auth_store(store): token=enroll_worker(Actor(uuid4(),UUID(f["project"]),True),"worker-w2002","regression")
    finally:store.close()
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=f["app"]),base_url="http://127.0.0.1") as client:
            response=await client.post("/api/v1/worker/claims",json={"project_id":f["project"],"boot_id":"fixture-boot","now":datetime.now(timezone.utc).isoformat()},headers={"Authorization":"Bearer "+token,"Idempotency-Key":"worker-healing-claim"})
            assert response.status_code==200,response.text
            return response.json()
    return asyncio.run(scenario())


def test_real_claim_metadata_resolves_to_bounded_worker_pin(healing_claim):
    from aiqa.worker.healing_pin import resolve_claim_healing_pin
    snapshot=healing_claim["snapshot"]
    pin=resolve_claim_healing_pin(snapshot)
    assert pin.enabled is True
    assert pin.policy.effective_limits["max_model_calls_per_item"]==1
    assert pin.policy.effective_limits["max_seconds"]==15
    assert pin.binding["revision_id"]==snapshot["limits"]["healing_binding"]["revision_id"]
    assert verify_job_snapshot(snapshot,frozenset({"regression"})).supported is True
    snapshot["limits"]["healing_resolution"]["effective_limits"]["max_model_calls_per_item"]=2
    assert pin.policy.effective_limits["max_model_calls_per_item"]==1


@pytest.mark.parametrize("mutation",["missing_limits","missing_schema","schema","flag_type","flag_mismatch","missing_binding","revision","binding_role","key_revision","hash","cap_type","cap_zero","cap_exceeded","budget","budget_type","budget_exceeded","package_mismatch","trial"])
def test_worker_rejects_bad_pin_before_adapter_dispatch(healing_claim,mutation):
    snapshot=copy.deepcopy(healing_claim["snapshot"])
    limits=snapshot["limits"];policy=limits["healing_resolution"]
    if mutation=="missing_limits":snapshot.pop("limits")
    elif mutation=="missing_schema":limits.pop("healing_schema")
    elif mutation=="schema":limits["healing_schema"]="other"
    elif mutation=="flag_type":snapshot["self_healing_enabled"]="true"
    elif mutation=="flag_mismatch":limits["self_healing_enabled"]=False
    elif mutation=="missing_binding":limits.pop("healing_binding")
    elif mutation=="revision":limits["healing_binding"]["revision_id"]=str(uuid4())
    elif mutation=="binding_role":limits["healing_binding"]["role"]="verification"
    elif mutation=="key_revision":limits["healing_binding"]["key_revision"]=0
    elif mutation=="hash":limits["healing_snapshot"]="changed"
    elif mutation=="cap_type":policy["effective_limits"]["max_model_calls_per_item"]=True
    elif mutation=="cap_zero":policy["effective_limits"]["max_model_calls_per_item"]=0
    elif mutation=="cap_exceeded":policy["effective_limits"]["max_model_calls_per_item"]=3
    elif mutation=="budget":policy["effective_limits"]["budget"]="NaN"
    elif mutation=="budget_type":policy["effective_limits"]["budget"]=True
    elif mutation=="budget_exceeded":policy["effective_limits"]["budget"]="2.00"
    elif mutation=="package_mismatch":snapshot["replay_package_hash"]="different"
    elif mutation=="trial":snapshot["purpose"]="trial"
    checked=verify_job_snapshot(snapshot,frozenset({"trial","regression"}))
    assert checked.supported is False and checked.reason=="healing_pin_invalid"


def test_off_legacy_snapshot_needs_no_model_metadata():
    from aiqa.worker.healing_pin import resolve_claim_healing_pin
    for snapshot in ({"purpose":"regression"},{"purpose":"trial","self_healing_enabled":False,"limits":{"self_healing_enabled":False}}):
        pin=resolve_claim_healing_pin(snapshot)
        assert pin.enabled is False and pin.policy is None and pin.binding is None


def test_claim_digest_references_the_fixed_healing_policy(healing_claim):
    snapshot=healing_claim["snapshot"]
    assert isinstance(snapshot.get("policy_ref"),str) and snapshot["policy_ref"].startswith("healing-admission-v1:sha256:")
    assert snapshot["policy_ref"]==snapshot["limits"]["policy_ref"]
    for field,value in (("key_ref_id",str(uuid4())),("content_hash","sha256:"+"e"*64)):
        changed=copy.deepcopy(snapshot)
        changed["limits"]["healing_binding"][field]=value
        checked=verify_job_snapshot(changed,frozenset({"regression"}))
        assert checked.supported is False and checked.reason=="healing_pin_invalid"


def test_worker_cannot_downgrade_an_on_claim_with_retained_outer_policy_ref(healing_claim):
    snapshot=copy.deepcopy(healing_claim["snapshot"])
    snapshot["self_healing_enabled"]=False
    for name in ("healing_schema","healing_resolution","healing_binding","policy_ref"):snapshot["limits"].pop(name,None)
    snapshot["limits"]["self_healing_enabled"]=False
    checked=verify_job_snapshot(snapshot,frozenset({"regression"}))
    assert checked.supported is False and checked.reason=="healing_pin_invalid"
