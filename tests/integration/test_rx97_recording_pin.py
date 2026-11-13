"""Normal browser recording freezes model metadata, never a model or secret value."""
import asyncio
import copy
import json
import sqlite3
from datetime import datetime, timezone
from uuid import UUID, uuid4

import httpx
import pytest
from ux_support import session, ux_app
from test_w16 import _binding, _resource
from aiqa.api.auth import bound_auth_store, enroll_worker
from aiqa.domain.hashing import canonical_hash
from aiqa.store.models import Actor
from aiqa.worker.android_jobs import server_model_plan_provider
from aiqa.worker.runner import verify_job_snapshot


def _new_revision(c,project,**changes):
    cursor=c.execute("SELECT * FROM binding_revisions WHERE project_id=? ORDER BY revision DESC LIMIT 1",(project,))
    row=dict(zip((col[0] for col in cursor.description),cursor.fetchone()))
    row.update(revision_id=str(uuid4()),revision=row["revision"]+1,created_at=datetime.now(timezone.utc).isoformat())
    row.update(changes)
    c.execute("INSERT INTO binding_revisions ("+",".join(row)+") VALUES ("+",".join("?" for _ in row)+")",tuple(row.values()))
    c.execute("UPDATE model_bindings SET latest_revision_id=?,next_revision=? WHERE project_id=? AND binding_id=?",
              (row["revision_id"],row["revision"]+1,project,row["binding_id"]))
    return row


@pytest.fixture
def recording(ux_app,request):
    app,project,database=ux_app
    _resource(database,project)
    _binding(database,project,str(uuid4()))
    physical=str(uuid4())
    with sqlite3.connect(database) as c:
        c.execute("INSERT INTO physical_resource_keys VALUES (?, 'worker-w1605', 'native-pin')",(physical,))
        from worker_presence_support import seed_resource_alias
        seed_resource_alias(c,project,physical)
        c.execute("INSERT INTO resource_inventory VALUES (?, 'ready', '', '', '[]', '', '')",(physical,))
        c.execute("INSERT OR IGNORE INTO secret_refs VALUES (?, 'ref-w1605', 1, 'fixture', 'available', ?, ?)",
                  (project,datetime.now(timezone.utc).isoformat(),str(uuid4())))
        _new_revision(c,project,revision_id="rev-seven",revision=7)
    caps={"timeout_seconds":31,"max_actions":4,"max_model_calls":3,"budget":"0.70","currency":"USD"}
    target_refs={}
    if hasattr(request,"param"):
        field,value=request.param
        if field=="target_secret":
            ref_id=str(uuid4())
            with sqlite3.connect(database) as c:
                c.execute("INSERT INTO secret_refs VALUES (?, ?, 1, 'target secret', 'available', ?, ?)",
                    (project,ref_id,datetime.now(timezone.utc).isoformat(),str(uuid4())))
            target_refs={"target":{"project_id":project,"ref_id":ref_id,"revision":1}}
        else:caps[field]=value
    async def prepare():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://127.0.0.1") as client:
            headers=await session(client,project)
            case=await client.post(f"/api/v1/projects/{project}/cases",json={"name":"Model pin","tc_reference":None},headers=headers)
            assert case.status_code==201,case.text
            case_id=case.json()["case_id"]
            version=await client.post(f"/api/v1/projects/{project}/cases/{case_id}/versions",
                json={"definition":{"objective":"Check saved target","steps":[],"final_expected":[],"secret_refs":target_refs},
                      "settings":{"target_kind":"web","limits":caps}},
                headers={**headers,"Idempotency-Key":"pin-version"})
            assert version.status_code==201,version.text
            return {"case_id":case_id,"input_case_version_id":version.json()["id"],
                    "input_version_hash":version.json()["content_hash"],"resource_id":physical}
    body=asyncio.run(prepare())
    return {"app":app,"project":project,"database":database,"body":body}


def request(f,*,key="start-pin",body=None,path=None):
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=f["app"]),base_url="http://127.0.0.1") as client:
            headers=await session(client,f["project"])
            return await client.post(path or f"/api/v1/projects/{f['project']}/recordings",
                json=body or f["body"],headers={**headers,"Idempotency-Key":key})
    return asyncio.run(scenario())


def limits_for(f,job):
    with sqlite3.connect(f["database"]) as c:
        return json.loads(c.execute("SELECT limits FROM jobs WHERE job_id=?",(job,)).fetchone()[0])


def state(f):
    with sqlite3.connect(f["database"]) as c:
        return [c.execute("SELECT COUNT(*) FROM "+t+" WHERE project_id=?",(f["project"],)).fetchone()[0]
                for t in ["case_versions","recordings","jobs","job_receipts","recording_intents"]]+[
                c.execute("SELECT latest_draft_version_id,next_revision,lock_version FROM automation_cases WHERE case_id=?",(f["body"]["case_id"],)).fetchone()]


def test_start_pins_exact_model_key_input_and_narrow_caps(recording):
    f=recording
    result=request(f,body={**f["body"],"authoring_binding":{"revision":99},"key_present":True})
    assert result.status_code==201,result.text
    limits=limits_for(f,result.json()["job_id"])
    assert limits["authoring_schema"]=="authoring-admission-v1"
    assert limits["authoring_binding"]=={"binding_id":"bind-w1605","revision_id":"rev-seven","revision":7,
        "role":"authoring","key_ref_id":"ref-w1605","key_revision":1,"content_hash":"hash"}
    assert limits["input_case_version_id"]==f["body"]["input_case_version_id"]
    assert limits["input_version_hash"]==f["body"]["input_version_hash"]
    assert {k:limits[k] for k in ["timeout_seconds","max_actions","max_model_calls","budget","currency"]}=={
        "timeout_seconds":31,"max_actions":4,"max_model_calls":3,"budget":"0.70","currency":"USD"}
    assert limits["policy_ref"].startswith("authoring-admission-v1:sha256:")
    assert "endpoint" not in json.dumps(limits) and "secret_value" not in json.dumps(limits)
    assert not f["app"].state.model_gateway._policies


@pytest.mark.parametrize("change",["missing_key","revoked_key","foreign_key","incompatible","role_changed","old_only"])
def test_invalid_current_model_blocks_start_and_rerecord_atomically(recording,change):
    f=recording
    with sqlite3.connect(f["database"]) as c:
        if change in {"missing_key","foreign_key"}:c.execute("DELETE FROM secret_refs WHERE project_id=?",(f["project"],))
        elif change=="revoked_key":c.execute("UPDATE secret_refs SET availability='revoked' WHERE project_id=?",(f["project"],))
        elif change=="incompatible":_new_revision(c,f["project"],compatibility_status="incompatible")
        elif change=="role_changed":_new_revision(c,f["project"],role="verification")
        elif change=="old_only":c.execute("UPDATE model_bindings SET latest_revision_id='no-longer-authoring' WHERE project_id=?",(f["project"],))
    if change=="foreign_key":
        from aiqa.domain.projects import bind_store,create_project
        from aiqa.store.models import ProjectCreate
        store=f["app"].state.open_store()
        try:
            with bind_store(store):other=create_project(Actor(uuid4(),None,True),ProjectCreate("Other","other","scope","web"))
            with store.transaction() as c:
                c.execute("INSERT INTO secret_refs VALUES (?, 'ref-w1605', 1, 'foreign', 'available', ?, ?)",(str(other.project_id),datetime.now(timezone.utc).isoformat(),str(uuid4())))
        finally:store.close()
    before=state(f)
    result=request(f)
    assert result.status_code==422,result.text
    assert state(f)==before
    body={"project_id":f["project"],"base_version_id":f["body"]["input_case_version_id"],
        "expected_head":f["body"]["input_case_version_id"],"reason":"fresh recording","resource_id":f["body"]["resource_id"],
        "web_url":"http://127.0.0.1/","data_name":"","reset_policy":"keep",
        "confirm_device":True,"confirm_target":True,"confirm_data":True,"confirm_reset":True}
    result=request(f,key="rerecord-pin",body=body,path=f"/api/v1/cases/{f['body']['case_id']}/rerecordings")
    assert result.status_code==422,result.text
    assert state(f)==before


def test_receipt_replay_survives_key_revocation_and_binding_rotation(recording):
    f=recording;first=request(f)
    assert first.status_code==201,first.text
    saved=limits_for(f,first.json()["job_id"])
    before=state(f)
    with sqlite3.connect(f["database"]) as c:
        c.execute("UPDATE secret_refs SET availability='revoked' WHERE project_id=?",(f["project"],))
        c.execute("UPDATE model_bindings SET latest_revision_id='different' WHERE project_id=?",(f["project"],))
    again=request(f)
    assert again.status_code==200,again.text
    assert again.json()["job_id"]==first.json()["job_id"] and again.json()["replayed"] is True
    assert limits_for(f,first.json()["job_id"])==saved and state(f)==before
    changed=request(f,body={**f["body"],"resource_id":"another-resource"})
    assert changed.status_code==409,changed.text
    assert request(f,key="new-start").status_code==422


@pytest.mark.parametrize("recording",[("budget","0"),("max_model_calls",0)],indirect=True)
def test_zero_model_budget_preflight_and_start_agree(recording):
    f=recording
    before=state(f)
    preview=request(f,path=f"/api/v1/projects/{f['project']}/recording-previews")
    assert preview.status_code==200,preview.text
    assert preview.json()["ready"] is False
    assert any(r["code"]=="budget" for r in preview.json()["reasons"])
    assert request(f).status_code==422
    assert state(f)==before
    rerun=request(f,key="zero-rerecord",body=rerecord_body(f),path=f"/api/v1/cases/{f['body']['case_id']}/rerecordings")
    assert rerun.status_code==422,rerun.text
    assert state(f)==before


def claim(f):
    store=f["app"].state.open_store()
    try:
        with bound_auth_store(store):token=enroll_worker(Actor(uuid4(),UUID(f["project"]),True),"worker-w1605","recording")
    finally:store.close()
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=f["app"]),base_url="http://127.0.0.1") as client:
            result=await client.post("/api/v1/worker/claims",json={"project_id":f["project"],"boot_id":"fixture-boot","now":datetime.now(timezone.utc).isoformat()},
                headers={"Authorization":"Bearer "+token,"Idempotency-Key":"pin-claim"})
            assert result.status_code==200,result.text
            return result.json()
    return asyncio.run(scenario())


def test_actual_claim_fixes_policy_and_android_provider_revision(recording):
    f=recording;result=request(f);assert result.status_code==201,result.text
    job=claim(f);snapshot=job["snapshot"]
    assert snapshot["policy_ref"]==snapshot["limits"]["policy_ref"]
    assert snapshot["policy_ref"].startswith("authoring-admission-v1:")
    assert verify_job_snapshot(snapshot,frozenset({"recording"})).supported
    calls=[]
    class Client:
        def commit_evidence(self,**kwargs):
            return {"late":False,"attempt_id":job["attempt_id"],"artifact_ids":[str(uuid4())]}
        def register_model_observation(self,**kwargs):
            payload=kwargs["payload"]
            return {"observation_id":str(uuid4()),"artifact_id":payload["artifact_id"],"image_hash":payload["image_hash"],
                "geometry_hash":canonical_hash(payload["geometry"],"canon-json-v1")}
        def request_model(self,**kwargs):calls.append(kwargs);return {"allowed":True,"action_allowed":True,"content":"finish()"}
    from test_rx_65 import _observation
    assert server_model_plan_provider(Client(),binding_revision=1)({**job,"observation":_observation()})=="finish()"
    assert calls[0]["payload"]["binding_revision"]==7
    for mutation in ["binding","budget","remove_pin","typed_revision","input_hash"]:
        bad=copy.deepcopy(snapshot)
        if mutation=="binding":bad["limits"]["authoring_binding"]["key_revision"]=99
        elif mutation=="budget":bad["limits"]["budget"]="2.00"
        elif mutation=="remove_pin":bad["limits"]={"timeout_seconds":31}
        elif mutation=="typed_revision":bad["limits"]["authoring_binding"]["revision"]=True
        elif mutation=="input_hash":bad["limits"]["input_version_hash"]="changed"
        checked=verify_job_snapshot(bad,frozenset({"recording"}))
        assert checked.supported is False and checked.reason=="authoring_pin_invalid",mutation
        with pytest.raises(ValueError):server_model_plan_provider(Client())({**job,"snapshot":bad})
    assert len(calls)==1


def rerecord_body(f):
    return {"project_id":f["project"],"base_version_id":f["body"]["input_case_version_id"],
        "expected_head":f["body"]["input_case_version_id"],"reason":"repeat with current model","resource_id":f["body"]["resource_id"],
        "web_url":"http://127.0.0.1/","data_name":"","reset_policy":"keep",
        "confirm_device":True,"confirm_target":True,"confirm_data":True,"confirm_reset":True}


def test_rerecord_fixes_new_revision_and_reuses_saved_pin_on_retry(recording):
    f=recording
    with sqlite3.connect(f["database"]) as c:new=_new_revision(c,f["project"])
    body=rerecord_body(f);path=f"/api/v1/cases/{f['body']['case_id']}/rerecordings"
    first=request(f,key="rerecord-valid",body=body,path=path)
    assert first.status_code==201,first.text
    saved=limits_for(f,first.json()["job_id"])
    assert saved["authoring_binding"]["revision_id"]==new["revision_id"]
    assert saved["input_case_version_id"]!=body["base_version_id"]
    assert {k:saved[k] for k in ["timeout_seconds","max_actions","max_model_calls","budget","currency"]}=={
        "timeout_seconds":31,"max_actions":4,"max_model_calls":3,"budget":"0.70","currency":"USD"}
    with sqlite3.connect(f["database"]) as c:
        row=c.execute("SELECT input_case_version_id,base_case_version_id FROM recordings WHERE recording_id=?",(first.json()["recording_id"],)).fetchone()
        assert row==(saved["input_case_version_id"],body["base_version_id"])
        c.execute("UPDATE secret_refs SET availability='revoked' WHERE project_id=?",(f["project"],))
    before=state(f)
    again=request(f,key="rerecord-valid",body=body,path=path)
    assert again.status_code==200,again.text
    assert again.json()["job_id"]==first.json()["job_id"] and again.json()["replayed"]
    assert state(f)==before and limits_for(f,first.json()["job_id"])==saved


def test_legacy_receipt_without_pin_remains_readable(recording):
    from aiqa.contracts.jobs import IdempotencyKey,JobSubmission
    from aiqa.recording.service import RecordingStartInput,start_recording
    from aiqa.store.models import Transaction
    from aiqa.store.queue import enqueue_job
    f=recording;actor=Actor(uuid4(),UUID(f["project"]),True);project=UUID(f["project"])
    spec=RecordingStartInput(UUID(f["body"]["case_id"]),UUID(f["body"]["input_case_version_id"]),f["body"]["input_version_hash"],f["body"]["resource_id"])
    store=f["app"].state.open_store()
    try:
        with store.transaction() as c:
            first=enqueue_job(Transaction(c),JobSubmission(project,"recording",spec.case_id,spec.input_case_version_id,(spec.resource_id,),'{"timeout_seconds":31}'),IdempotencyKey(actor.actor_id,project,"enqueue_job","old-pin"))
            c.execute("DELETE FROM secret_refs WHERE project_id=?",(f["project"],))
        with store.transaction() as c:again=start_recording(c,actor,project,spec,"old-pin")
        assert again.job_id==first.job_id and again.replayed
        assert limits_for(f,str(first.job_id))=={"timeout_seconds":31}
    finally:store.close()
    assert verify_job_snapshot({"purpose":"recording","digest":"sha256:"+"a"*64,"limits":{"timeout_seconds":31}},frozenset({"recording"})).supported


def test_partial_nested_policy_marker_cannot_look_like_legacy(recording):
    f=recording;assert request(f).status_code==201
    snapshot=claim(f)["snapshot"]
    snapshot.pop("policy_ref")
    snapshot["limits"]={"policy_ref":snapshot["limits"]["policy_ref"],"timeout_seconds":31}
    checked=verify_job_snapshot(snapshot,frozenset({"recording"}))
    assert checked.supported is False and checked.reason=="authoring_pin_invalid"


@pytest.mark.parametrize("recording",[("budget","20.00")],indirect=True)
def test_recording_budget_never_exceeds_global_cap(recording):
    f=recording;response=request(f);assert response.status_code==201,response.text
    assert limits_for(f,response.json()["job_id"])["budget"]=="2.00"


def test_rerecord_pin_hash_matches_the_entire_new_saved_input(recording):
    from aiqa.domain.hashing import execution_snapshot_hash
    f=recording;body=rerecord_body(f);body["objective_diff"]="Verify a revised objective"
    response=request(f,key="new-content-hash",body=body,path=f"/api/v1/cases/{f['body']['case_id']}/rerecordings")
    assert response.status_code==201,response.text
    limits=limits_for(f,response.json()["job_id"])
    with sqlite3.connect(f["database"]) as c:
        row=c.execute("SELECT definition_json,settings_json,recorded_steps_json,content_hash FROM case_versions WHERE version_id=?",(limits["input_case_version_id"],)).fetchone()
        base=c.execute("SELECT content_hash FROM case_versions WHERE version_id=?",(body["base_version_id"],)).fetchone()[0]
    assert row[3]==execution_snapshot_hash(json.loads(row[0]),json.loads(row[1]),json.loads(row[2]))
    assert limits["input_version_hash"]==row[3] and row[3]!=base


def test_recording_pin_cannot_be_reused_for_another_purpose(recording):
    f=recording;assert request(f).status_code==201
    snapshot=claim(f)["snapshot"];snapshot["purpose"]="trial"
    checked=verify_job_snapshot(snapshot,frozenset({"recording","trial"}))
    assert not checked.supported and checked.reason=="authoring_pin_invalid"
