"""Explicit formal healing is resolved server-side and pinned before admission."""
import asyncio
import json
import sqlite3
from uuid import uuid4

import httpx
import pytest
from ux_support import ux_app, session
from test_rx93_healing_resolution import healing_metadata
from test_w20 import _seed


@pytest.fixture
def healing_execution(ux_app,healing_metadata):
    app,project,database=ux_app
    _,_,binding,revision,key,settings=healing_metadata
    async def create():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://127.0.0.1") as client:
            headers=await session(client,project)
            created=await client.post(f"/api/v1/projects/{project}/cases",json={"name":"Healable case"},headers=headers)
            case=created.json()["case_id"]
            saved=await client.post(f"/api/v1/projects/{project}/cases/{case}/versions",json={"definition":{"final_expected":[{"id":"check-1","kind":"text","expected":"Done"}]},"settings":settings},headers={**headers,"Idempotency-Key":"version"})
            assert saved.status_code==201,saved.text
            return saved.json()["id"],case
    version,case=asyncio.run(create())
    environment,resource=map(str,(uuid4(),uuid4()))
    seed=_seed(database,project,case,version,environment,resource)
    item={"entry_id":"entry-1","case_version_id":seed["version_id"],"approval_id":seed["approval_id"],"environment_revision_id":environment,"resource_id":resource}
    return dict(app=app,project=project,database=database,item=item,input_version=version,binding=binding,revision=revision,key=key,case=case)


def _common(**changes):
    return {"name":"Healing run","purpose":"regression","source":"single","failure_policy":"continue","exclusions":[],"self_healing_enabled":True,**changes}


@pytest.mark.parametrize("source",["single","selection","suite"])
@pytest.mark.parametrize("purpose",["regression","reverification"])
def test_formal_on_pins_policy_binding_and_limits_through_admission(healing_execution,source,purpose):
    f=healing_execution
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=f["app"]),base_url="http://127.0.0.1") as client:
            headers=await session(client,f["project"])
            common=_common(source=source,purpose=purpose)
            selection={"items":[f["item"]]}
            suite=None
            if source=="suite":
                created=await client.post(f"/api/v1/projects/{f['project']}/suites",json={"name":"Healing suite","target_kind":"web"},headers=headers)
                body=created.json()
                saved=await client.post(f"/api/v1/suites/{body['suite_id']}/versions",json={"project_id":f["project"],"expected_version_id":body["version_id"],"entries":[{**f["item"],"case_id":f["case"],"data_name":"default","reset_policy":"keep","failure_policy":"continue","target_kind":"web"}]},headers={**headers,"Idempotency-Key":"suite-save"})
                assert saved.status_code==201,saved.text
                suite=saved.json()["suite_version_id"];selection={"suite_version_id":suite}
            preview=await client.post(f"/api/v1/projects/{f['project']}/execution-previews",json={**common,"selection":selection},headers=headers)
            assert preview.status_code==200,preview.text
            body=preview.json();assert body["ready"] and body["self_healing_enabled"] is True,body
            item=body["resolved_items"][0]
            assert item["healing_resolution"]["effective_enabled"] is True
            assert item["healing_resolution"]["effective_limits"]["max_model_calls_per_item"]==1
            assert item["healing_resolution"]["effective_limits"]["max_seconds"]==15
            assert item["healing_binding"]["revision_id"]==f["revision"]
            assert item["healing_binding"]["key_ref_id"]==f["key"]
            payload={**common,"preview_hash":body["preview_hash"],"items":body["resolved_items"]}
            if suite:payload["suite_version_id"]=suite
            url=f"/api/v1/projects/{f['project']}/executions"
            first=await client.post(url,json=payload,headers={**headers,"Idempotency-Key":"admit"})
            assert first.status_code==201,first.text
            repeat=await client.post(url,json=payload,headers={**headers,"Idempotency-Key":"admit"})
            assert repeat.status_code==200 and repeat.json()["replayed"] is True
            changed=await client.post(url,json={**payload,"self_healing_enabled":False},headers={**headers,"Idempotency-Key":"admit"})
            assert changed.status_code==409,changed.text
            with sqlite3.connect(f["database"]) as db:
                snapshot=json.loads(db.execute("SELECT limits FROM jobs WHERE job_id=?",(first.json()["job_ids"][0],)).fetchone()[0])
                assert snapshot["self_healing_enabled"] is True
                assert snapshot["healing_resolution"]==item["healing_resolution"]
                assert snapshot["healing_binding"]==item["healing_binding"]
                assert snapshot["healing_snapshot"]==item["healing_policy_hash"]
                assert snapshot["budget"]=="0.50" and snapshot["max_model_calls"]==4
                assert db.execute("SELECT COUNT(*) FROM executions").fetchone()[0]==1
                assert db.execute("SELECT COUNT(*) FROM model_call_facts").fetchone()[0]==0
    asyncio.run(scenario())


@pytest.mark.parametrize("flag",[None,"true",1,[],{}])
def test_healing_flag_is_a_strict_boolean_for_preview_and_admission(healing_execution,flag):
    f=healing_execution
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=f["app"]),base_url="http://127.0.0.1") as client:
            headers=await session(client,f["project"])
            for endpoint,body in [("execution-previews",{"selection":{"items":[f["item"]]}}),("executions",{"items":[f["item"]],"preview_hash":"invalid"})]:
                response=await client.post(f"/api/v1/projects/{f['project']}/{endpoint}",json={**_common(self_healing_enabled=flag),**body},headers=headers)
                assert response.status_code==422,response.text
    asyncio.run(scenario())


@pytest.mark.parametrize("purpose",["trial","regression"])
def test_trial_forces_off_and_omitted_flag_keeps_legacy_off_shape(healing_execution,purpose):
    f=healing_execution
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=f["app"]),base_url="http://127.0.0.1") as client:
            headers=await session(client,f["project"])
            payload={**_common(purpose=purpose),"selection":{"items":[f["item"]]}}
            if purpose!="trial":payload.pop("self_healing_enabled")
            first=await client.post(f"/api/v1/projects/{f['project']}/execution-previews",json=payload,headers=headers)
            assert first.status_code==200,first.text
            body=first.json();assert body["ready"] and body["self_healing_enabled"] is False
            assert "healing_resolution" not in body["resolved_items"][0] and "healing_binding" not in body["resolved_items"][0]
            explicit=await client.post(f"/api/v1/projects/{f['project']}/execution-previews",json={**payload,"self_healing_enabled":False},headers=headers)
            assert explicit.json()["preview_hash"]==body["preview_hash"]
    asyncio.run(scenario())


def test_key_unavailable_blocks_entire_selection_and_stale_admission(healing_execution):
    f=healing_execution
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=f["app"]),base_url="http://127.0.0.1") as client:
            headers=await session(client,f["project"])
            common=_common(source="selection")
            selection={"items":[f["item"],{**f["item"],"entry_id":"entry-2","case_version_id":f["input_version"],"approval_id":str(uuid4())}]}
            bad=await client.post(f"/api/v1/projects/{f['project']}/execution-previews",json={**common,"selection":selection},headers=headers)
            assert bad.status_code==200 and bad.json()["ready"] is False
            assert len(bad.json()["resolved_items"])==2
            assert any(b.get("entry_id")=="entry-2" for b in bad.json()["blockers"])
            preview=await client.post(f"/api/v1/projects/{f['project']}/execution-previews",json={**_common(),"selection":{"items":[f["item"]]}},headers=headers)
            ready=preview.json();assert ready["ready"]
            payload={**_common(),"preview_hash":ready["preview_hash"],"items":ready["resolved_items"]}
            with sqlite3.connect(f["database"]) as db:db.execute("UPDATE secret_refs SET availability='unavailable' WHERE ref_id=?",(f["key"],))
            blocked=await client.post(f"/api/v1/projects/{f['project']}/execution-previews",json={**_common(),"selection":{"items":[f["item"]]}},headers=headers)
            assert blocked.json()["ready"] is False
            assert any(b["code"]=="HEALING_KEY_UNAVAILABLE" for b in blocked.json()["blockers"])
            response=await client.post(f"/api/v1/projects/{f['project']}/executions",json=payload,headers=headers)
            assert response.status_code==422
            with sqlite3.connect(f["database"]) as db:assert db.execute("SELECT COUNT(*) FROM executions").fetchone()[0]==0
    asyncio.run(scenario())


def test_changed_binding_echo_is_rejected_and_on_off_previews_differ(healing_execution):
    f=healing_execution
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=f["app"]),base_url="http://127.0.0.1") as client:
            headers=await session(client,f["project"])
            previews=[]
            for enabled in (False,True):
                response=await client.post(f"/api/v1/projects/{f['project']}/execution-previews",json={**_common(self_healing_enabled=enabled),"selection":{"items":[f["item"]]}},headers=headers)
                previews.append(response.json())
            assert previews[0]["preview_hash"]!=previews[1]["preview_hash"]
            body=previews[1];item=body["resolved_items"][0]
            item["healing_binding"]={**item["healing_binding"],"revision_id":str(uuid4())}
            result=await client.post(f"/api/v1/projects/{f['project']}/executions",json={**_common(),"preview_hash":body["preview_hash"],"items":[item]},headers=headers)
            assert result.status_code==422,result.text
    asyncio.run(scenario())


@pytest.mark.parametrize("field,value",[("key_revision",True),("effective_enabled",1),("max_episodes_per_item",True),("max_episodes_per_item",1.0)])
def test_pin_echo_uses_typed_comparison(healing_execution,field,value):
    f=healing_execution
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=f["app"]),base_url="http://127.0.0.1") as client:
            headers=await session(client,f["project"])
            response=await client.post(f"/api/v1/projects/{f['project']}/execution-previews",json={**_common(),"selection":{"items":[f["item"]]}},headers=headers)
            body=response.json();item=body["resolved_items"][0]
            if field=="key_revision":item["healing_binding"][field]=value
            elif field=="effective_enabled":item["healing_resolution"][field]=value
            else:item["healing_resolution"]["effective_limits"][field]=value
            result=await client.post(f"/api/v1/projects/{f['project']}/executions",json={**_common(),"preview_hash":body["preview_hash"],"items":[item]},headers=headers)
            assert result.status_code==422,result.text
    asyncio.run(scenario())


@pytest.mark.parametrize("purpose",["trial","regression"])
def test_blocked_off_previews_keep_legacy_blocker_shape(healing_execution,purpose):
    f=healing_execution
    with sqlite3.connect(f["database"]) as db:db.execute("UPDATE resource_inventory SET state='offline'")
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=f["app"]),base_url="http://127.0.0.1") as client:
            headers=await session(client,f["project"])
            response=await client.post(f"/api/v1/projects/{f['project']}/execution-previews",json={**_common(purpose=purpose,self_healing_enabled=False),"selection":{"items":[f["item"]]}},headers=headers)
            body=response.json();assert body["ready"] is False
            assert body["blockers"] and all(set(b)=={"code","message"} for b in body["blockers"])
    asyncio.run(scenario())
