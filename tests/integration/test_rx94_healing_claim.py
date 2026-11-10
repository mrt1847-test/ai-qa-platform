"""Claim validates fixed healing metadata before taking a device lease."""
import asyncio
import json
import sqlite3
from dataclasses import replace
from datetime import datetime,timezone
from uuid import UUID,uuid4

import httpx
import pytest
from aiqa.domain.executions import validate_claim_snapshot
from aiqa.store.models import JobSpec,WorkerScope
from aiqa.store.queue import claim_queued_job
from ux_support import session,DATA
from test_rx86_healing_execution import healing_execution,healing_metadata,ux_app,_common


@pytest.fixture
def admitted_healing(healing_execution):
    f=healing_execution
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=f["app"]),base_url="http://127.0.0.1") as client:
            headers=await session(client,f["project"])
            dataset=await client.post(f"/api/v1/projects/{f['project']}/datasets",json=DATA,headers={**headers,"Idempotency-Key":"dataset"})
            assert dataset.status_code==201,dataset.text
            f["item"]["dataset_version_id"]=dataset.json()["id"]
            preview=await client.post(f"/api/v1/projects/{f['project']}/execution-previews",json={**_common(release_label="2026.11-healing"),"selection":{"items":[f["item"]]}},headers=headers)
            body=preview.json();assert body["ready"],body
            result=await client.post(f"/api/v1/projects/{f['project']}/executions",json={**_common(release_label="2026.11-healing"),"preview_hash":body["preview_hash"],"items":body["resolved_items"]},headers={**headers,"Idempotency-Key":"claim-admit"})
            assert result.status_code==201,result.text
            return result.json()
    receipt=asyncio.run(scenario());f["receipt"]=receipt
    return f


def _job(db,f):
    row=db.execute("SELECT purpose,case_run_id,payload_hash,source_refs,limits,status FROM jobs WHERE job_id=?",(f["receipt"]["job_ids"][0],)).fetchone()
    return JobSpec(UUID(f["project"]),UUID(f["receipt"]["job_ids"][0]),row[0],None,UUID(row[1]),row[2],row[3],row[4],row[5])


def test_valid_on_snapshot_can_claim_without_looking_up_latest(admitted_healing):
    f=admitted_healing
    with sqlite3.connect(f["database"]) as db:
        job=_job(db,f)
        newer=str(uuid4())
        db.execute("INSERT INTO binding_revisions SELECT project_id,binding_id,?,2,role,provider,endpoint_kind,endpoint,'new-model',key_ref_id,key_revision,prompt_hash,tariff_id,compatibility_status,?,actor_id,created_at FROM binding_revisions WHERE revision_id=?",(newer,"sha256:"+"d"*64,f["revision"]))
        db.execute("UPDATE model_bindings SET latest_revision_id=?,next_revision=3 WHERE binding_id=?",(newer,f["binding"]))
        assert validate_claim_snapshot(job,db).status=="ALLOWED"
        token=db.execute("SELECT token_id FROM worker_tokens LIMIT 1").fetchone()[0]
        lease=claim_queued_job(db,WorkerScope("worker-w2002",(UUID(f["project"]),),("regression",),token),datetime.now(timezone.utc))
        assert lease is not None and str(lease.job_id)==f["receipt"]["job_ids"][0]
        assert str(lease.physical_key_id)==f["item"]["resource_id"]


@pytest.mark.parametrize("mutation",["key_revoked","key_removed","binding_id","binding_revision","binding_hash","key_revision","resolution_caps","resolution_hash","policy_hash","schema","missing_resolution","flag_type","silent_off","case_version","approval","budget","lost_on_metadata","lost_on_digest"])
def test_invalidated_or_corrupt_on_pin_is_blocked_before_lease(admitted_healing,mutation):
    f=admitted_healing
    with sqlite3.connect(f["database"]) as db:
        job=_job(db,f);limits=json.loads(job.limits)
        if mutation=="key_revoked":db.execute("UPDATE secret_refs SET availability='unavailable' WHERE ref_id=?",(f["key"],))
        elif mutation=="key_removed":db.execute("DELETE FROM secret_refs WHERE ref_id=?",(f["key"],))
        elif mutation=="binding_id":limits["healing_binding"]["binding_id"]=str(uuid4())
        elif mutation=="binding_revision":limits["healing_binding"]["revision_id"]=str(uuid4())
        elif mutation=="binding_hash":limits["healing_binding"]["content_hash"]="changed"
        elif mutation=="key_revision":limits["healing_binding"]["key_revision"]=2
        elif mutation=="resolution_caps":limits["healing_resolution"]["effective_limits"]["max_model_calls_per_item"]=2
        elif mutation=="resolution_hash":limits["healing_snapshot"]="changed"
        elif mutation=="policy_hash":limits["healing_policy_hash"]="changed"
        elif mutation=="schema":limits["healing_schema"]="unknown"
        elif mutation=="missing_resolution":limits.pop("healing_resolution")
        elif mutation=="flag_type":limits["self_healing_enabled"]="true"
        elif mutation=="silent_off":limits["self_healing_enabled"]=False
        elif mutation=="case_version":limits["execution_snapshot"]["case_version_id"]=str(uuid4())
        elif mutation=="approval":limits["approval_id"]=str(uuid4())
        elif mutation=="budget":limits["budget"]="2.00"
        elif mutation in {"lost_on_metadata","lost_on_digest"}:
            for name in ("healing_schema","healing_resolution","healing_binding","healing_policy_hash","policy_ref"):limits.pop(name,None)
            limits["self_healing_enabled"]=False
            if mutation=="lost_on_digest":limits.pop("healing_snapshot",None)
        changed=json.dumps(limits,separators=(",",":"))
        assert validate_claim_snapshot(replace(job,limits=changed),db).status=="BLOCKED"
        db.execute("UPDATE jobs SET limits=? WHERE job_id=?",(changed,str(job.job_id)))
        token=db.execute("SELECT token_id FROM worker_tokens LIMIT 1").fetchone()[0]
        lease=claim_queued_job(db,WorkerScope("worker-w2002",(UUID(f["project"]),),("regression",),token),datetime.now(timezone.utc))
        assert lease is None
        assert db.execute("SELECT COUNT(*) FROM leases").fetchone()[0]==0
        assert db.execute("SELECT status FROM jobs WHERE job_id=?",(str(job.job_id),)).fetchone()[0]=="queued"


def test_off_legacy_claim_does_not_require_healing_keys(healing_execution):
    f=healing_execution
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=f["app"]),base_url="http://127.0.0.1") as client:
            headers=await session(client,f["project"])
            with sqlite3.connect(f["database"]) as db:db.execute("DELETE FROM secret_refs WHERE ref_id=?",(f["key"],))
            common=_common(self_healing_enabled=False)
            preview=await client.post(f"/api/v1/projects/{f['project']}/execution-previews",json={**common,"selection":{"items":[f["item"]]}},headers=headers)
            body=preview.json();assert body["ready"]
            result=await client.post(f"/api/v1/projects/{f['project']}/executions",json={**common,"preview_hash":body["preview_hash"],"items":body["resolved_items"]},headers=headers)
            assert result.status_code==201,result.text
            f["receipt"]=result.json()
    asyncio.run(scenario())
    with sqlite3.connect(f["database"]) as db:
        job=_job(db,f)
        assert validate_claim_snapshot(job,db).status=="ALLOWED"
        legacy=json.loads(job.limits)
        for name in ("release_label","execution_snapshot","actor"):legacy.pop(name,None)
        assert validate_claim_snapshot(replace(job,limits=json.dumps(legacy)),db).status=="ALLOWED"


def test_same_configuration_rerun_keeps_on_pins_and_stored_receipt(admitted_healing):
    f=admitted_healing
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=f["app"]),base_url="http://127.0.0.1") as client:
            headers=await session(client,f["project"])
            url=f"/api/v1/executions/{f['receipt']['execution_id']}/reruns?project_id={f['project']}"
            body={"scope":"all","reason":"same configuration"}
            first=await client.post(url,json=body,headers={**headers,"Idempotency-Key":"on-rerun"})
            assert first.status_code in (200,201),first.text
            preview=first.json();assert preview["ready"] and preview["self_healing_enabled"] is True
            assert preview["resolved_items"][0]["healing_binding"]["revision_id"]==f["revision"]
            with sqlite3.connect(f["database"]) as db:
                job_id=db.execute("SELECT job_id FROM jobs ORDER BY rowid DESC LIMIT 1").fetchone()[0]
                row=db.execute("SELECT purpose,case_run_id,payload_hash,source_refs,limits,status FROM jobs WHERE job_id=?",(job_id,)).fetchone()
                spec=JobSpec(UUID(f["project"]),UUID(job_id),row[0],None,UUID(row[1]),row[2],row[3],row[4],row[5])
                assert validate_claim_snapshot(spec,db).status=="ALLOWED"
                snapshot=json.loads(row[4]);assert snapshot["budget"]=="0.50" and snapshot["self_healing_enabled"] is True
                assert snapshot["original_execution_id"]==f["receipt"]["execution_id"]
                db.execute("UPDATE secret_refs SET availability='unavailable' WHERE ref_id=?",(f["key"],))
                count=db.execute("SELECT COUNT(*) FROM executions").fetchone()[0]
            repeat=await client.post(url,json=body,headers={**headers,"Idempotency-Key":"on-rerun"})
            assert repeat.status_code==200 and repeat.json()["ready"] is True
            assert repeat.json()["self_healing_enabled"] is True
            assert repeat.json()==preview
            assert preview["release_label"]=="2026.11-healing" and preview["release_floor_runs"]==30
            assert preview["resolved_items"][0]["dataset_version_id"]==f["item"]["dataset_version_id"]
            assert repeat.json()["resolved_items"][0]["healing_binding"]==preview["resolved_items"][0]["healing_binding"]
            rejected=await client.post(url,json=body,headers={**headers,"Idempotency-Key":"new-on-rerun"})
            assert rejected.status_code in (200,422)
            if rejected.status_code==200:assert rejected.json()["ready"] is False
            with sqlite3.connect(f["database"]) as db:
                assert db.execute("SELECT COUNT(*) FROM executions").fetchone()[0]==count
                assert validate_claim_snapshot(spec,db).status=="BLOCKED"
    asyncio.run(scenario())


@pytest.mark.parametrize("damage",["flag_false","flag_string","snapshot_hash","outer_budget","package_hash"])
def test_damaged_parent_cannot_create_a_clean_rerun(admitted_healing,damage):
    f=admitted_healing
    with sqlite3.connect(f["database"]) as db:
        job=_job(db,f);limits=json.loads(job.limits)
        if damage=="flag_false":limits["self_healing_enabled"]=False
        elif damage=="flag_string":limits["self_healing_enabled"]="true"
        elif damage=="snapshot_hash":limits["healing_snapshot"]="changed"
        elif damage=="outer_budget":limits["budget"]="2.00"
        elif damage=="package_hash":limits["replay_package_hash"]="changed"
        db.execute("UPDATE jobs SET limits=? WHERE job_id=?",(json.dumps(limits),str(job.job_id)))
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=f["app"]),base_url="http://127.0.0.1") as client:
            headers=await session(client,f["project"])
            response=await client.post(f"/api/v1/executions/{f['receipt']['execution_id']}/reruns?project_id={f['project']}",json={"scope":"all","reason":"retry"},headers=headers)
            assert response.status_code in (200,422)
            if response.status_code==200:assert response.json()["ready"] is False
    asyncio.run(scenario())
    with sqlite3.connect(f["database"]) as db:assert db.execute("SELECT COUNT(*) FROM executions").fetchone()[0]==1
