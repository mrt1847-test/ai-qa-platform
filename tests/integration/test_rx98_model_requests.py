"""Normal browser recording -> claim/ACK -> durable authoring, without test policy grants."""
import asyncio
import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import UUID,uuid4

import httpx
import pytest
from aiqa.api.auth import bound_auth_store,enroll_worker
from aiqa.models.broker import ServerModelGateway
from aiqa.models.provider_http import FixtureProviderHttp,ProviderHttpError,ProviderHttpResult
from aiqa.config import load_settings,WorkerClientSettings
from aiqa.security.secrets import MemorySecretBackend,bind_secret_store,build_server_secret_resolver
from aiqa.store.models import Actor,SecretInput
from aiqa.worker.http_client import WorkerHttpClient,WorkerHttpError,SyncASGITransport
from aiqa.worker.android_jobs import server_model_plan_provider
from test_rx97_recording_pin import recording,ux_app,request as start,_new_revision


class SimulatedCrash(BaseException):pass


class Provider(FixtureProviderHttp):
    def __init__(self):super().__init__();self.mode="ok";self.after=None;self.sent=0
    def complete(self,**kw):
        self.sent+=1
        result=super().complete(**kw)
        if self.after:self.after()
        if self.mode=="timeout":raise ProviderHttpError("provider_timeout",status=504)
        if self.mode=="crash":raise SimulatedCrash()
        if self.mode=="error":raise RuntimeError("sensitive upstream error")
        text="finish()" if self.mode!="echo" else kw["secret"]
        return ProviderHttpResult(text,result.provider_request_id,200,kw["model"])


@pytest.fixture
def model_job(recording,request):
    f=recording;app=f["app"];provider=Provider();backend=MemorySecretBackend()
    settings=load_settings({"AIQA_HOST":"127.0.0.1","AIQA_PORT":"8000","AIQA_RUNTIME_ROOT":str(f["database"].parent.parent),"AIQA_MODEL_PRICE_MODE":"estimate"})
    http_sends=[];http_mode={"value":"ok"}
    operational=getattr(request,"param",None)=="operational"
    if operational:
        from aiqa.models.provider_http import OperationalProviderHttp
        def respond(req):
            http_sends.append(req)
            if http_mode["value"]=="timeout":raise httpx.ReadTimeout("mock timeout")
            body=json.loads(req.content)
            return httpx.Response(200,json={"content":"finish()","provider_request_id":str(uuid4()),"actual_model":body["model"]})
        provider=OperationalProviderHttp(allow_live=True,base_url="https://model.invalid",transport=httpx.MockTransport(respond))
    app.state.settings=settings
    resolver=build_server_secret_resolver(settings,backend=backend);app.state.secret_resolver=resolver
    app.state.model_gateway=ServerModelGateway(provider=provider,resolver=resolver)
    store=app.state.open_store()
    try:
        with store.transaction() as c:actor=Actor(UUID(c.execute("SELECT actor_id FROM case_versions WHERE version_id=?",(f["body"]["input_case_version_id"],)).fetchone()[0]),UUID(f["project"]),True)
        with bind_secret_store(store):secret=resolver.put(actor,SecretInput(value="synthetic-RX98-private",name="author"))
        with store.transaction() as c:binding=_new_revision(c,f["project"],key_ref_id=str(secret.ref_id),key_revision=secret.revision,model="author-rev8",**({"endpoint":"https://model.invalid","endpoint_kind":"https","provider":"operational"} if operational else {}))
        with bound_auth_store(store):token=enroll_worker(actor,"worker-w1605","recording")
    finally:store.close()
    response=start(f);assert response.status_code==201,response.text
    async def claim():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://127.0.0.1") as c:
            headers={"Authorization":"Bearer "+token,"Idempotency-Key":"normal-claim"}
            hb=await c.post("/api/v1/worker/heartbeats",json={"boot_id":"fixture-boot"},headers=headers);assert hb.status_code==200,hb.text
            r=await c.post("/api/v1/worker/claims",json={"project_id":f["project"],"boot_id":"fixture-boot"},headers=headers)
            assert r.status_code==200,r.text
            return r.json()
    job=asyncio.run(claim())
    f.update(provider=provider,backend=backend,resolver=resolver,token=token,job=job,secret=secret,binding=binding,http_sends=http_sends,http_mode=http_mode,actor=actor)
    f["payload"]={"project_id":f["project"],"item_id":job["attempt_id"],"call_id":str(uuid4()),"purpose":"recording",
        "role":"authoring","owner_kind":"authoring","owner_id":job["attempt_id"],"binding_revision":binding["revision"],
        "generation":job["generation"],"sanitized_inputs":["observation_id:normal","objective:spoof"],"token_output_limit":64,
        "deadline":"2099-01-01T00:00:00+00:00","intent_hash":job["snapshot"]["intent_hash"],"actor_id":str(uuid4())}
    return f


def post(f,payload=None,key="model-call",token=None,path="/api/v1/worker/model-requests"):
    body=dict(payload or f["payload"])
    if (path=="/api/v1/worker/model-requests" and f.get("_auto_observations",True)
        and "model_observation_id" not in body and body.get("item_id")==f["job"]["attempt_id"]
        and body.get("project_id")==f["project"] and body.get("role")=="authoring"
        and body.get("purpose")=="recording" and body.get("owner_id")==f["job"]["attempt_id"]
        and body.get("generation")==f["job"]["generation"] and body.get("binding_revision")==f["binding"]["revision"]):
        from model_observation_support import prepare_frame
        try:body["model_observation_id"]=prepare_frame(f,body)
        except WorkerHttpError:pass  # Still test the real model endpoint's independent denial.
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=f["app"]),base_url="http://127.0.0.1") as c:
            return await c.post(path,json=body,headers={"Authorization":"Bearer "+(token or f["token"]),"Idempotency-Key":key})
    return asyncio.run(run())


def ack(f):
    job=f["job"]
    r=post(f,{"project_id":f["project"],"job_id":job["job_id"],"generation":job["generation"],"runner_nonce":str(uuid4())},key="ack-normal",path="/api/v1/worker/attempt-acks")
    assert r.status_code==200,r.text


def mutate(f,sql,args=()):
    with sqlite3.connect(f["database"]) as c:c.execute(sql,args)


def test_normal_authoring_and_replay_survive_gateway_restart(model_job):
    f=model_job;ack(f)
    assert not f["app"].state.model_gateway._policies
    first=post(f);assert first.status_code==200,first.text
    body=first.json();assert body["content"]=="finish()" and body["actual_model"]=="author-rev8"
    assert body["usage"]["authoring_calls"]==1
    assert body["usage"]["cost_status"]=="unknown" and body["usage"]["reserved_cost"] is None
    assert body["measurement_status"]=="unreported" and body["usage"]["price_mode"]=="estimate"
    sent=f["provider"].calls[0].sanitized_inputs
    assert "objective:Check saved target" in sent and "objective:spoof" not in sent
    f["app"].state.model_gateway=ServerModelGateway(provider=f["provider"],resolver=f["resolver"])
    again=post(f);assert again.status_code==200,again.text
    assert again.json()["replayed"] is True and f["provider"].sent==1
    for n in range(2):
        r=post(f,{**f["payload"],"call_id":str(uuid4())},key=f"next-{n}");assert r.status_code==200,r.text
        f["app"].state.model_gateway=ServerModelGateway(provider=f["provider"],resolver=f["resolver"])
    quota=post(f,{**f["payload"],"call_id":str(uuid4())},key="quota")
    assert quota.status_code==403 and f["provider"].sent==3
    assert quota.json()["error"]["provider_dispatched"] is False


@pytest.mark.parametrize("change",["unacked","worker","generation","missing_generation","owner","purpose","role","revision","intent","expired","cancelled","stale_boot","key_revoked","os_key_missing","strict_price","endpoint"])
def test_invalid_authoring_requests_never_reach_provider(model_job,change):
    f=model_job;body=dict(f["payload"]);token=None
    if change!="unacked":ack(f)
    if change=="worker":
        store=f["app"].state.open_store()
        try:
            with bound_auth_store(store):token=enroll_worker(Actor(uuid4(),UUID(f["project"]),True),"other-worker","recording")
        finally:store.close()
    elif change=="generation":body["generation"]=2
    elif change=="missing_generation":body.pop("generation")
    elif change=="owner":body["owner_id"]=str(uuid4())
    elif change=="purpose":body["purpose"]="regression"
    elif change=="role":body["role"]="maintenance"
    elif change=="revision":body["binding_revision"]=1
    elif change=="intent":body["intent_hash"]="changed"
    elif change=="expired":mutate(f,"UPDATE leases SET expires_at=?",((datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(),))
    elif change=="cancelled":mutate(f,"UPDATE jobs SET status='cancel_requested' WHERE job_id=?",(f["job"]["job_id"],))
    elif change=="stale_boot":
        r=post(f,{"boot_id":"new-boot"},path="/api/v1/worker/heartbeats");assert r.status_code==200
    elif change=="key_revoked":mutate(f,"UPDATE secret_refs SET availability='revoked' WHERE ref_id=?",(str(f["secret"].ref_id),))
    elif change=="os_key_missing":f["backend"]._values.clear()
    elif change=="strict_price":f["app"].state.settings=replace(f["app"].state.settings,model_price_mode="strict")
    elif change=="endpoint":
        from aiqa.models.provider_http import OperationalProviderHttp
        f["app"].state.model_gateway=ServerModelGateway(provider=OperationalProviderHttp(allow_live=True,base_url="https://other.invalid"),resolver=f["resolver"])
    result=post(f,body,token=token)
    assert result.status_code in {403,409,503},result.text
    assert f["provider"].sent==0
    assert result.json()["error"]["provider_dispatched"] is False


def test_timeout_and_same_call_retries_are_durably_counted(model_job):
    f=model_job;ack(f);f["provider"].mode="timeout"
    first=post(f);assert first.status_code==504,first.text
    assert first.json()["error"]["provider_dispatched"] is True
    f["app"].state.model_gateway=ServerModelGateway(provider=f["provider"],resolver=f["resolver"])
    again=post(f);assert again.status_code==504 and again.json()["error"]["replayed"] is True
    assert f["provider"].sent==1
    assert post(f,key="same-call-other-key").status_code==409
    changed=post(f,{**f["payload"],"token_output_limit":32});assert changed.status_code==409
    assert f["provider"].sent==1


def test_late_cancelled_response_cannot_drive_an_action(model_job):
    f=model_job;ack(f)
    f["provider"].after=lambda:mutate(f,"UPDATE jobs SET status='cancel_requested' WHERE job_id=?",(f["job"]["job_id"],))
    r=post(f);assert r.status_code==403,r.text
    assert r.json()["error"]["message"]=="response_late" and r.json()["error"]["provider_dispatched"] is True
    assert "finish()" not in r.text and f["provider"].sent==1


def test_server_secret_never_enters_response_or_durable_receipt(model_job):
    f=model_job;ack(f);f["provider"].mode="echo"
    r=post(f);assert r.status_code==200,r.text
    assert "synthetic-RX98-private" not in r.text
    with sqlite3.connect(f["database"]) as c:
        rows=c.execute("SELECT response_json FROM model_request_receipts").fetchall()
    assert rows and "synthetic-RX98-private" not in json.dumps(rows)


def test_http_worker_uses_claim_generation_and_error_accounting(model_job):
    f=model_job;ack(f);f["provider"].mode="timeout"
    client=WorkerHttpClient(WorkerClientSettings(base_url="https://127.0.0.1",token=f["token"]),transport=SyncASGITransport(f["app"]))
    try:
        from test_rx_65 import _observation
        with pytest.raises(WorkerHttpError) as caught:server_model_plan_provider(client)({**f["job"],"observation":_observation()})
        assert caught.value.provider_dispatched is True
        assert caught.value.reason=="provider_timeout" and f["provider"].sent==1
    finally:client.close()


@pytest.mark.parametrize("model_job",["operational"],indirect=True)
def test_operational_http_sends_distinct_calls_with_distinct_identities(model_job):
    f=model_job;ack(f)
    for n in range(2):
        response=post(f,{**f["payload"],"call_id":str(uuid4())},key=f"http-{n}")
        assert response.status_code==200,response.text
    assert len(f["http_sends"])==2
    keys=[r.headers["Idempotency-Key"] for r in f["http_sends"]]
    assert len(set(keys))==2
    assert all(r.url==httpx.URL("https://model.invalid/v1/complete") for r in f["http_sends"])
    assert all(r.headers["Authorization"]=="Bearer synthetic-RX98-private" for r in f["http_sends"])


@pytest.mark.parametrize("model_job",["operational"],indirect=True)
def test_operational_http_timeout_is_a_consumed_504(model_job):
    f=model_job;ack(f);f["http_mode"]["value"]="timeout"
    r=post(f);assert r.status_code==504,r.text
    assert r.json()["error"]["provider_dispatched"] is True and len(f["http_sends"])==1
    assert post(f).status_code==504 and len(f["http_sends"])==1


def test_pending_send_survives_process_memory_loss_without_resend(model_job):
    f=model_job;ack(f);f["provider"].mode="crash"
    with pytest.raises(BaseExceptionGroup):post(f)
    f["provider"].mode="ok"
    f["app"].state.model_gateway=ServerModelGateway(provider=f["provider"],resolver=f["resolver"])
    r=post(f);assert r.status_code==503 and r.json()["error"]["provider_dispatched"] is None
    assert r.json()["error"]["message"]=="dispatch_unknown"
    r=post(f,{**f["payload"],"call_id":str(uuid4())},key="next-after-crash")
    assert r.status_code==409 and f["provider"].sent==1
    with sqlite3.connect(f["database"]) as c:assert c.execute("SELECT SUM(charged) FROM model_request_receipts").fetchone()[0]==1


def test_concurrent_attempt_calls_are_serialized_without_a_long_db_transaction(model_job):
    from concurrent.futures import ThreadPoolExecutor
    f=model_job;ack(f);other=[]
    def during_send():
        with ThreadPoolExecutor(max_workers=1) as pool:
            other.append(pool.submit(post,f,{**f["payload"],"call_id":str(uuid4())},"concurrent").result(timeout=5))
    f["provider"].after=during_send
    r=post(f);assert r.status_code==200,r.text
    assert other[0].status_code==409 and f["provider"].sent==1
    with sqlite3.connect(f["database"]) as c:assert c.execute("SELECT COUNT(*) FROM model_request_receipts").fetchone()[0]==1


def test_receipt_body_hash_includes_presented_intent(model_job):
    f=model_job;ack(f);assert post(f).status_code==200
    r=post(f,{**f["payload"],"intent_hash":"different"})
    assert r.status_code==409 and f["provider"].sent==1


def test_old_receipt_is_readable_but_not_executable_after_key_revocation(model_job):
    f=model_job;ack(f);assert post(f).status_code==200
    mutate(f,"UPDATE secret_refs SET availability='revoked' WHERE ref_id=?",(str(f["secret"].ref_id),))
    r=post(f);assert r.status_code==200,r.text
    assert r.json()["content"]=="finish()" and r.json()["replayed"] is True
    assert r.json()["action_allowed"] is False
    assert f["provider"].sent==1


def test_receipt_replay_still_requires_recording_token_purpose(model_job):
    f=model_job;ack(f);assert post(f).status_code==200
    store=f["app"].state.open_store()
    try:
        with bound_auth_store(store):token=enroll_worker(f["actor"],"worker-w1605","resource_probe")
    finally:store.close()
    r=post(f,token=token)
    assert r.status_code==403 and f["provider"].sent==1


def test_unexpected_provider_failure_is_unknown_not_a_free_retry(model_job):
    f=model_job;ack(f);f["provider"].mode="error"
    r=post(f);assert r.status_code==503 and r.json()["error"]["provider_dispatched"] is None
    assert "sensitive upstream error" not in r.text
    assert post(f).status_code==503 and f["provider"].sent==1


@pytest.mark.parametrize("mode",[None,"strict","estimate","invalid"])
def test_price_mode_is_explicit_server_configuration(tmp_path,mode):
    from aiqa.config import SettingsError
    env={"AIQA_HOST":"127.0.0.1","AIQA_PORT":"8000","AIQA_RUNTIME_ROOT":str(tmp_path/"runtime")}
    if mode is not None:env["AIQA_MODEL_PRICE_MODE"]=mode
    if mode=="invalid":
        with pytest.raises(SettingsError):load_settings(env)
    else:assert load_settings(env).model_price_mode==(mode or "strict")


@pytest.mark.parametrize("action_allowed",[False,None])
def test_worker_rejects_historical_response_without_live_action_permission(model_job,action_allowed):
    from aiqa.adapters.mobile_agent_android import MobileAgentRejected
    from test_rx_65 import _observation
    f=model_job;ack(f);inner=SyncASGITransport(f["app"])
    def respond(request):
        if request.url.path=="/api/v1/worker/model-requests":
            body={"allowed":True,"content":"finish()"}
            if action_allowed is not None:body["action_allowed"]=action_allowed
            return httpx.Response(200,json=body)
        return inner.handle_request(request)
    with WorkerHttpClient(WorkerClientSettings("https://127.0.0.1",f["token"]),transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(MobileAgentRejected):
            server_model_plan_provider(client)({**f["job"],"observation":_observation()})
    assert f["provider"].sent==0


@pytest.mark.parametrize("change",["deadline","foreign_project","expired_response"])
def test_deadlines_and_project_scope_fail_closed(model_job,change):
    f=model_job;ack(f);body=dict(f["payload"])
    if change=="deadline":body["deadline"]=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
    elif change=="foreign_project":body["project_id"]=str(uuid4())
    else:f["provider"].after=lambda:mutate(f,"UPDATE leases SET expires_at=?",((datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(),))
    r=post(f,body);assert r.status_code==403,r.text
    error=r.json()["error"]
    assert error["provider_dispatched"] is (change=="expired_response")
    assert UUID(error["request_id"])
    assert f["provider"].sent==(1 if change=="expired_response" else 0)


def test_pre_send_secret_failure_is_not_charged_and_new_request_can_retry(model_job):
    f=model_job;ack(f);saved=dict(f["backend"]._values);f["backend"]._values.clear()
    r=post(f);assert r.status_code==503 and r.json()["error"]["provider_dispatched"] is False
    f["backend"]._values.update(saved)
    for n in range(3):
        r=post(f,{**f["payload"],"call_id":str(uuid4())},key=f"after-secret-{n}")
        assert r.status_code==200,r.text
    assert f["provider"].sent==3
    with sqlite3.connect(f["database"]) as c:assert c.execute("SELECT SUM(charged) FROM model_request_receipts").fetchone()[0]==3


def test_model_rotation_does_not_replace_the_admitted_revision(model_job):
    f=model_job;ack(f)
    with sqlite3.connect(f["database"]) as c:_new_revision(c,f["project"],model="different-model",key_ref_id=str(uuid4()))
    r=post(f);assert r.status_code==200,r.text
    assert r.json()["actual_model"]=="author-rev8"


def test_provider_wait_does_not_block_worker_heartbeats(model_job):
    import threading
    f=model_job;ack(f);release=threading.Event();started=threading.Event();finished=threading.Event()
    def wait():
        started.set();release.wait(timeout=2);finished.set()
    f["provider"].after=wait
    from model_observation_support import prepare_frame
    f["payload"]={**f["payload"],"model_observation_id":prepare_frame(f,f["payload"])}
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=f["app"]),base_url="http://127.0.0.1") as c:
            headers={"Authorization":"Bearer "+f["token"],"Idempotency-Key":"waiting-provider"}
            task=asyncio.create_task(c.post("/api/v1/worker/model-requests",json=f["payload"],headers=headers))
            try:
                for _ in range(30):
                    await asyncio.sleep(0.01)
                    if started.is_set():break
                assert started.is_set() and not finished.is_set(),"provider blocked the API event loop until it finished"
                heartbeat=await c.post("/api/v1/worker/heartbeats",json={"boot_id":"fixture-boot"},headers=headers)
                assert heartbeat.status_code==200
            finally:release.set()
            response=await task
            assert response.status_code==200,response.text
    asyncio.run(scenario())


def test_cancel_after_secret_resolution_blocks_before_provider_send(model_job):
    f=model_job;ack(f);resolver=f["resolver"]
    class Resolver:
        def resolve_for_server(self,*args,**kwargs):
            secret=resolver.resolve_for_server(*args,**kwargs)
            mutate(f,"UPDATE jobs SET status='cancel_requested' WHERE job_id=?",(f["job"]["job_id"],))
            return secret
    f["app"].state.model_gateway.resolver=Resolver()
    r=post(f);assert r.status_code==403,r.text
    assert r.json()["error"]["provider_dispatched"] is False
    assert f["provider"].sent==0


@pytest.mark.parametrize("model_job",["operational"],indirect=True)
def test_fixture_provider_cannot_substitute_for_operational_binding(model_job):
    f=model_job;ack(f);provider=FixtureProviderHttp()
    f["app"].state.model_gateway=ServerModelGateway(provider=provider,resolver=f["resolver"])
    response=post(f)
    assert response.status_code==503,response.text
    assert response.json()["error"]["provider_dispatched"] is False
    assert provider.call_count==0 and not f["http_sends"]
    with sqlite3.connect(f["database"]) as c:
        assert c.execute("SELECT COUNT(*) FROM model_request_receipts").fetchone()[0]==0


def test_unknown_owner_request_cannot_block_heartbeat_during_model_send(model_job):
    import threading
    f=model_job;ack(f);release=threading.Event();started=threading.Event();finished=threading.Event()
    def wait():
        started.set();release.wait(timeout=2);finished.set()
    f["provider"].after=wait
    from model_observation_support import prepare_frame
    f["payload"]={**f["payload"],"model_observation_id":prepare_frame(f,f["payload"])}
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=f["app"]),base_url="http://127.0.0.1") as c:
            headers={"Authorization":"Bearer "+f["token"],"Idempotency-Key":"slow-owner"}
            model=asyncio.create_task(c.post("/api/v1/worker/model-requests",json=f["payload"],headers=headers))
            try:
                for _ in range(30):
                    await asyncio.sleep(0.01)
                    if started.is_set():break
                assert started.is_set() and not finished.is_set()
                other=str(uuid4())
                unknown=asyncio.create_task(c.post("/api/v1/worker/model-requests",
                    json={**f["payload"],"item_id":other,"owner_id":other,"call_id":str(uuid4()),"intent_hash":None},
                    headers={**headers,"Idempotency-Key":"unknown-owner"}))
                await asyncio.sleep(0.05)
                heartbeat=await c.post("/api/v1/worker/heartbeats",json={"boot_id":"fixture-boot"},headers=headers)
                assert heartbeat.status_code==200
                assert not finished.is_set(),"unknown model owner blocked the ASGI loop on the gateway lock"
                rejected=await unknown
                assert rejected.status_code==404
            finally:release.set()
            result=await model
            assert result.status_code==200,result.text
    asyncio.run(scenario())
