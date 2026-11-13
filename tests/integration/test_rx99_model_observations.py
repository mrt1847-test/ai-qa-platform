"""Trusted observation artifact registration precedes any visual authoring request."""
import base64
import hashlib
import json
import sqlite3
from dataclasses import asdict
from datetime import datetime,timedelta,timezone
from uuid import uuid4

import pytest
from aiqa.domain.hashing import canonical_hash
from aiqa.worker.http_client import WorkerHttpClient,WorkerClientSettings,SyncASGITransport
from test_rx98_model_requests import model_job,recording,ux_app,ack,post,mutate
from test_rx_65 import _observation


@pytest.fixture(autouse=True)
def explicit_observation_references(model_job):
    model_job["_auto_observations"]=False


def upload_image(f,observation=None,*,body=None):
    obs=observation or _observation();png=obs.png if body is None else body
    digest="sha256:"+hashlib.sha256(png).hexdigest()
    with WorkerHttpClient(WorkerClientSettings("https://127.0.0.1",f["token"]),transport=SyncASGITransport(f["app"])) as client:
        r=client.commit_evidence(sanitized=True,project_id=f["project"],job_id=f["job"]["job_id"],generation=f["job"]["generation"],
            now=datetime.now(timezone.utc).isoformat(),events=[],artifacts=[{"filename":"model-frame.png","media_type":"image/png",
                "declared_hash":digest,"declared_length":len(png),"body_b64":base64.b64encode(png).decode("ascii"),
                "owner_kind":"REC","attempt_id":f["job"]["attempt_id"],"role":"source"}],idempotency_key="frame-"+digest)
    assert r["late"] is False and len(r["artifact_ids"])==1,r
    return {**f["payload"],"artifact_id":r["artifact_ids"][0],"image_hash":digest,"geometry":asdict(obs.geometry),
        "source_observation_id":obs.observation_id,"captured_at":obs.captured_at},png


def register(f,payload,key="register-frame"):
    return post(f,payload,key=key,path="/api/v1/worker/model-observations")


def test_registers_exact_ready_image_without_actions_or_provider(model_job):
    f=model_job;ack(f);payload,png=upload_image(f)
    r=register(f,payload);assert r.status_code==201,r.text
    body=r.json();assert body["image_hash"]==payload["image_hash"] and body["artifact_id"]==payload["artifact_id"]
    assert body["geometry_hash"]==canonical_hash(payload["geometry"],"canon-json-v1")
    with sqlite3.connect(f["database"]) as c:
        assert c.execute("SELECT COUNT(*) FROM actions WHERE attempt_id=?",(f["job"]["attempt_id"],)).fetchone()[0]==0
        assert c.execute("SELECT COUNT(*) FROM model_observations").fetchone()[0]==1
    assert f["provider"].sent==0
    again=register(f,payload);assert again.status_code==200 and again.json()["observation_id"]==body["observation_id"]
    assert again.json()["replayed"] is True


@pytest.mark.parametrize("change",["hash","geometry","wrong_attempt","expired","future_capture","old_capture","bad_png","no_ack"])
def test_invalid_or_stale_observation_never_becomes_model_input(model_job,change):
    f=model_job
    if change!="no_ack":ack(f)
    payload,png=upload_image(f,body=b"bad png" if change=="bad_png" else None)
    if change=="hash":payload["image_hash"]="sha256:"+"a"*64
    elif change=="geometry":payload["geometry"]["physical_width"]=2
    elif change=="wrong_attempt":payload["item_id"]=str(uuid4());payload["owner_id"]=payload["item_id"]
    elif change=="expired":mutate(f,"UPDATE leases SET expires_at=?",((datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(),))
    elif change=="future_capture":payload["captured_at"]=(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat()
    elif change=="old_capture":payload["captured_at"]=(datetime.now(timezone.utc)-timedelta(minutes=5)).isoformat()
    r=register(f,payload);assert r.status_code in {403,422},r.text
    assert f["provider"].sent==0
    with sqlite3.connect(f["database"]) as c:assert c.execute("SELECT COUNT(*) FROM model_observations").fetchone()[0]==0


def test_registration_key_cannot_be_rebound_to_other_frame(model_job):
    f=model_job;ack(f);payload,png=upload_image(f)
    first=register(f,payload);assert first.status_code==201,first.text
    changed=dict(payload);changed["source_observation_id"]=str(uuid4())
    r=register(f,changed);assert r.status_code==409,r.text
    assert f["provider"].sent==0


@pytest.mark.parametrize("recording",[("target_secret",True)],indirect=True)
def test_known_sensitive_capture_requires_proven_pixel_coverage(model_job):
    f=model_job;ack(f)
    assert f["job"]["snapshot"]["intent"]["secret_refs"]
    # Simulate an otherwise authorized worker bypassing its local sanitize gate.
    # The registration gate independently refuses this frame for model use.
    payload,png=upload_image(f)
    r=register(f,payload);assert r.status_code==403,r.text
    assert r.json()["error"]["message"]=="pixel_coverage_unavailable"
    assert f["provider"].sent==0


class TraceTransport(__import__('httpx').BaseTransport):
    def __init__(self,app):
        self.inner=SyncASGITransport(app);self.requests=[]
    def handle_request(self,request):
        self.requests.append(request)
        return self.inner.handle_request(request)


def test_worker_uploads_and_registers_current_frame_before_model(model_job):
    from aiqa.worker.android_jobs import server_model_plan_provider
    f=model_job;ack(f);obs=_observation();transport=TraceTransport(f["app"])
    with WorkerHttpClient(WorkerClientSettings("https://127.0.0.1",f["token"]),transport=transport) as client:
        text=server_model_plan_provider(client)({**f["job"],"observation":obs})
    assert text=="finish()"
    paths=[r.url.path for r in transport.requests]
    assert paths==["/api/v1/worker/evidence-commits","/api/v1/worker/model-observations","/api/v1/worker/model-requests"]
    model=json.loads(transport.requests[-1].content)
    with sqlite3.connect(f["database"]) as c:
        row=c.execute("SELECT observation_id,image_hash FROM model_observations").fetchone()
    assert model["model_observation_id"]==row[0] and row[1]=="sha256:"+hashlib.sha256(obs.png).hexdigest()
    assert "body_b64" not in model and "synthetic-RX98-private" not in json.dumps(model)


@pytest.mark.parametrize("recording",[("target_secret",True)],indirect=True)
def test_worker_sensitive_frame_opens_no_upload_or_model_request(model_job):
    from aiqa.worker.android_jobs import server_model_plan_provider
    from aiqa.worker.http_client import SanitizationRequired
    f=model_job;ack(f);transport=TraceTransport(f["app"])
    with WorkerHttpClient(WorkerClientSettings("https://127.0.0.1",f["token"]),transport=transport) as client:
        with pytest.raises(SanitizationRequired):server_model_plan_provider(client)({**f["job"],"observation":_observation()})
    assert not transport.requests and f["provider"].sent==0


def test_worker_invalid_capture_opens_no_upload_or_model_request(model_job):
    from dataclasses import replace
    from aiqa.worker.android_jobs import server_model_plan_provider
    from aiqa.worker.http_client import SanitizationRequired
    f=model_job;ack(f);transport=TraceTransport(f["app"])
    with WorkerHttpClient(WorkerClientSettings("https://127.0.0.1",f["token"]),transport=transport) as client:
        with pytest.raises(SanitizationRequired):server_model_plan_provider(client)({**f["job"],"observation":replace(_observation(),png=b"bad")})
    assert not transport.requests and f["provider"].sent==0


@pytest.mark.parametrize("model_job",["operational"],indirect=True)
def test_provider_receives_the_exact_server_image_not_worker_urls(model_job):
    f=model_job;ack(f)
    for n,fill in enumerate([b"\xff\x00\x00",b"\x00\xff\x00"]):
        obs=_observation(fill=fill)
        f["payload"]={**f["payload"],"call_id":str(uuid4())}
        payload,png=upload_image(f,obs)
        receipt=register(f,payload,key=f"frame-{n}")
        assert receipt.status_code==201,receipt.text
        body={**f["payload"],"model_observation_id":receipt.json()["observation_id"],"images":[{"url":"https://untrusted.invalid/raw"}]}
        result=post(f,body,key=f"visual-{n}")
        assert result.status_code==200,result.text
        actual=json.loads(f["http_sends"][-1].content)
        images=actual.get("images")
        assert images and len(images)==1,"provider received only digests, not a visual observation"
        assert base64.b64decode(images[0]["data_base64"])==png
        assert images[0]["hash"]==payload["image_hash"] and images[0]["media_type"]=="image/png"
        assert canonical_hash(images[0]["geometry"],"canon-json-v1")==receipt.json()["geometry_hash"]
        assert "untrusted.invalid" not in json.dumps(actual)
        again=post(f,body,key=f"visual-{n}")
        assert again.status_code==200 and again.json()["replayed"] is True
    assert len(f["http_sends"])==2


@pytest.mark.parametrize("change",["missing_ref","wrong_ref","wrong_call","damaged_file","expired_frame"])
def test_unbound_observation_never_reaches_the_model(model_job,change,monkeypatch):
    f=model_job;ack(f);payload,png=upload_image(f)
    receipt=register(f,payload);assert receipt.status_code==201,receipt.text
    body={**f["payload"],"model_observation_id":receipt.json()["observation_id"]}
    if change=="missing_ref":body.pop("model_observation_id")
    elif change=="wrong_ref":body["model_observation_id"]=str(uuid4())
    elif change=="wrong_call":body["call_id"]=str(uuid4())
    elif change=="damaged_file":
        from aiqa.store.artifacts import resolve_stored
        store=f["app"].state.open_store()
        try:
            with store.transaction() as c:key=c.execute("SELECT object_key FROM artifact_objects WHERE artifact_id=?",(payload["artifact_id"],)).fetchone()[0]
            path=resolve_stored(store.config.artifacts_dir,key);assert path is not None
            path.write_bytes(b"corrupted")
        finally:store.close()
    else:monkeypatch.setattr("aiqa.models.model_observations._now",lambda:datetime.now(timezone.utc)+timedelta(seconds=31),raising=False)
    r=post(f,body)
    assert r.status_code==403,r.text
    assert r.json()["error"]["provider_dispatched"] is False and f["provider"].sent==0


def test_observation_receipts_are_immutable(model_job):
    f=model_job;ack(f);payload,png=upload_image(f)
    assert register(f,payload).status_code==201
    with sqlite3.connect(f["database"]) as c:
        for sql in ["UPDATE model_observations SET geometry_hash='changed'","DELETE FROM model_observations"]:
            with pytest.raises(sqlite3.IntegrityError):c.execute(sql)


def test_identical_parallel_registration_returns_one_observation(model_job,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    import aiqa.models.model_observations as module
    f=model_job;ack(f);payload,png=upload_image(f);barrier=threading.Barrier(2)
    original=module.read_validated_image
    def synchronized(*args,**kwargs):
        result=original(*args,**kwargs);barrier.wait(timeout=5);return result
    monkeypatch.setattr(module,"read_validated_image",synchronized)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(register,f,payload) for _ in range(2)]
        results=[future.result(timeout=10) for future in futures]
    assert sorted(r.status_code for r in results)==[200,201]
    assert len({r.json()["observation_id"] for r in results})==1
    assert f["provider"].sent==0


@pytest.mark.parametrize("lost_path",["evidence-commits","model-observations"])
def test_lost_preparation_response_reuses_exact_evidence_and_observation(model_job,lost_path):
    import httpx
    from aiqa.worker.model_observations import upload_authoring_observation
    from aiqa.worker.http_client import WorkerHttpError
    f=model_job;ack(f);obs=_observation()
    class LoseOnce(TraceTransport):
        def __init__(self,app):super().__init__(app);self.lost=False;self.original=None
        def handle_request(self,request):
            response=super().handle_request(request)
            if request.url.path.endswith('/'+lost_path) and not self.lost:
                assert response.status_code in (200,201)
                self.lost=True;self.original=response.json()
                raise httpx.ReadError('mock response lost',request=request)
            return response
    transport=LoseOnce(f['app'])
    with WorkerHttpClient(WorkerClientSettings('https://127.0.0.1',f['token']),transport=transport) as client:
        with pytest.raises(WorkerHttpError) as lost:
            upload_authoring_observation(client,f['job'],obs,f['payload'])
        assert lost.value.provider_dispatched is False
        recovered=upload_authoring_observation(client,f['job'],obs,f['payload'])
        again=upload_authoring_observation(client,f['job'],obs,f['payload'])
    commits=[r for r in transport.requests if r.url.path.endswith('/evidence-commits')]
    assert len(commits)==3
    assert len({r.headers['Idempotency-Key'] for r in commits})==1
    assert len({r.content for r in commits})==1
    assert recovered['observation_id']==again['observation_id']
    if lost_path=='model-observations':assert recovered['observation_id']==transport.original['observation_id']
    else:assert recovered['artifact_id']==transport.original['artifact_ids'][0]
    with sqlite3.connect(f['database']) as c:
        assert c.execute('SELECT COUNT(*) FROM model_observations').fetchone()[0]==1
        assert c.execute('SELECT COUNT(*) FROM artifact_objects').fetchone()[0]==1
    assert f['provider'].sent==0
    model={**f['payload'],'sanitized_inputs':recovered['sanitized_inputs'],'model_observation_id':recovered['observation_id']}
    assert post(f,model).status_code==200
    replay=post(f,model);assert replay.status_code==200 and replay.json()['replayed'] is True
    assert f['provider'].sent==1
