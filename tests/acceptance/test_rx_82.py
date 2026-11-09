"""Release labels survive real admission and every item finalization boundary."""
import asyncio
import importlib.util
import json
import sqlite3
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from ux_support import session, ux_app


def _helpers(name, file):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(file))
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("source", ["single", "selection", "suite"])
def test_release_label_persists_from_admission_through_skip_and_cancel(ux_app, source):
    app, project, database=ux_app
    w20=_helpers("rx82_w20","test_w20.py")
    version,case=asyncio.run(w20._case(app,project))
    environment,resource,busy=(str(uuid4()) for _ in range(3))
    seed=w20._seed(database,project,case,version,environment,resource,busy)

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://127.0.0.1") as client:
            headers=await session(client,project)
            items=[dict(entry_id=f"item-{i}",case_version_id=seed["old"],approval_id=seed["old_approval"],
                        environment_revision_id=environment,resource_id=resource,install_policy="none")
                   for i in range(1 if source=="single" else 2)]
            common=dict(name="November release",purpose="regression",source=source,
                        failure_policy="continue",self_healing_enabled=False,exclusions=[],release_label="  2026.11  ")
            selection={"items":items}
            suite_version=None
            if source=="suite":
                created=await client.post(f"/api/v1/projects/{project}/suites",
                    json={"name":"배포 회귀","target_kind":"web"},headers={**headers,"Idempotency-Key":"label-suite"})
                suite=created.json()
                entries=[dict(item,case_id=case,data_name=item["entry_id"],reset_policy="keep",failure_policy="continue",target_kind="web")
                         for item in items]
                saved=await client.post(f"/api/v1/suites/{suite['suite_id']}/versions",
                    json={"project_id":project,"expected_version_id":suite["version_id"],"entries":entries},
                    headers={**headers,"Idempotency-Key":"label-suite-version"})
                assert saved.status_code==201,saved.text
                suite_version=saved.json()["suite_version_id"]
                selection={"suite_version_id":suite_version}
            preview=await client.post(f"/api/v1/projects/{project}/execution-previews",
                json={**common,"selection":selection},headers=headers)
            assert preview.status_code==200,preview.text
            ready=preview.json()
            assert ready["ready"],ready
            assert ready["release_label"]=="2026.11"
            payload={**common,"preview_hash":ready["preview_hash"],"items":ready["resolved_items"]}
            if suite_version:payload["suite_version_id"]=suite_version
            admitted=await client.post(f"/api/v1/projects/{project}/executions",json=payload,
                                      headers={**headers,"Idempotency-Key":"label-admit"})
            assert admitted.status_code==201,admitted.text
            receipt=admitted.json()
            changed={**payload,"release_label":"2026.12"}
            reused=await client.post(f"/api/v1/projects/{project}/executions",json=changed,
                                     headers={**headers,"Idempotency-Key":"label-admit"})
            assert reused.status_code==409,reused.text
            stale=await client.post(f"/api/v1/projects/{project}/executions",json=changed,
                                    headers={**headers,"Idempotency-Key":"label-stale"})
            assert stale.status_code==409,stale.text
            with sqlite3.connect(database) as connection:
                limits=[json.loads(row[0]) for row in connection.execute(
                    "SELECT limits FROM jobs WHERE job_id IN ("+",".join("?" for _ in receipt["job_ids"])+")",
                    receipt["job_ids"])]
            assert all(limit.get("release_label")=="2026.11" for limit in limits),limits
            skipped=await client.post(f"/api/v1/case-runs/{receipt['item_ids'][0]}/skip?project_id={project}",
                json={"reason":"운영자가 범위 확인 후 제외"},headers={**headers,"Idempotency-Key":"label-skip"})
            assert skipped.status_code in (200,202),skipped.text
            url=f"/api/v1/executions/{receipt['execution_id']}/cancel?project_id={project}"
            cancelled=await client.post(url,json={},headers={**headers,"Idempotency-Key":"label-cancel"})
            assert cancelled.status_code in ((409,) if len(items)==1 else (200,202)),cancelled.text
            again=await client.post(url,json={},headers={**headers,"Idempotency-Key":"label-cancel"})
            assert again.status_code in ((409,) if len(items)==1 else (200,202)),again.text
            with sqlite3.connect(database) as connection:
                rows=connection.execute(
                    "SELECT release_label,core_result FROM item_finalizations JOIN case_runs USING(project_id,case_run_id) WHERE execution_id=? ORDER BY case_runs.rowid",
                    (receipt["execution_id"],)).fetchall()
            assert rows==[("2026.11","SKIPPED")]+[("2026.11","CANCELLED")]*(len(items)-1),rows
            with sqlite3.connect(database) as connection:
                clocks=connection.execute("SELECT created_seq,finalized_seq FROM item_finalizations JOIN case_runs USING(project_id,case_run_id) WHERE execution_id=?",(receipt["execution_id"],)).fetchall()
                assert all(created==receipt["committed_seq"] and finalized>created for created,finalized in clocks),clocks

            from datetime import datetime, timedelta, timezone
            from aiqa.contracts.reports import AnalyticsQuery
            from aiqa.domain.analytics import read_analytics
            from aiqa.store.models import Actor, Transaction
            today=datetime.now(timezone.utc).date()
            with sqlite3.connect(database) as connection:
                as_of=connection.execute("SELECT MAX(finalized_seq) FROM item_finalizations").fetchone()[0]
                query=AnalyticsQuery(UUID(project),(today-timedelta(days=1)).isoformat(),
                                     (today+timedelta(days=1)).isoformat(),as_of,release_label="2026.11")
                report=read_analytics(Transaction(connection),Actor(uuid4(),UUID(project),True),query)
                assert report.sample_count==len(items)
                from dataclasses import replace
                missing=read_analytics(Transaction(connection),Actor(uuid4(),UUID(project),True),
                                       replace(query,release_label="another-release"))
                assert missing.sample_count==0
            if source=="single":
                # A response accepted just before an upgrade must remain recoverable.
                from aiqa.domain.hashing import canonical_hash
                legacy=await client.post(f"/api/v1/projects/{project}/executions",json=payload,
                                         headers={**headers,"Idempotency-Key":"label-legacy"})
                assert legacy.status_code==201,legacy.text
                old_receipt=legacy.json()
                old_body={key:payload.get(key) for key in
                          ("failure_policy","name","preview_hash","items","exclusions","purpose","source")}
                old_body.update(self_healing_enabled=False,suite_version_id=None)
                old_hash=canonical_hash(old_body,"canon-json-v1")
                with sqlite3.connect(database) as connection:
                    connection.execute("UPDATE job_receipts SET body_hash=? WHERE execution_id=?",
                                       (old_hash,old_receipt["execution_id"]))
                    for job in old_receipt["job_ids"]:
                        raw=json.loads(connection.execute("SELECT limits FROM jobs WHERE job_id=?",(job,)).fetchone()[0])
                        raw.pop("release_label")
                        connection.execute("UPDATE jobs SET limits=?,payload_hash=? WHERE job_id=?",
                                           (json.dumps(raw),old_hash,job))
                repeated=await client.post(f"/api/v1/projects/{project}/executions",json=payload,
                                           headers={**headers,"Idempotency-Key":"label-legacy"})
                assert repeated.status_code==200,repeated.text
                assert repeated.json()["execution_id"]==old_receipt["execution_id"]
                with sqlite3.connect(database) as connection:
                    original=json.loads(connection.execute("SELECT limits FROM jobs WHERE job_id=?",
                                                           (old_receipt["job_ids"][0],)).fetchone()[0])
                    assert "release_label" not in original  # replay never relabels an old run


    asyncio.run(exercise())


@pytest.mark.parametrize("outcome", ["completed","error","cancelled"])
def test_worker_finish_and_remaining_dispositions_keep_release_label(ux_app, outcome):
    from test_rx_72 import _device, _execution, _claim, _finish, _release, _WORKER
    from aiqa.store.models import WorkerScope

    _,project,database=ux_app
    resource=_device(database,project)
    graph=_execution(database,project,str(uuid4()),resource,"stop_on_non_pass",2)
    # Explicit seed only: the production admission snapshot is tested above.
    with sqlite3.connect(database) as connection:
        for job in graph["jobs"]:
            limits=json.loads(connection.execute("SELECT limits FROM jobs WHERE job_id=?",(job,)).fetchone()[0])
            limits["release_label"]="2026.11"
            limits["commit_seq"]=1
            connection.execute("UPDATE jobs SET limits=? WHERE job_id=?",(json.dumps(limits),job))
    worker=WorkerScope(_WORKER,(UUID(project),),("regression",))
    first=_claim(database,worker)
    assert first is not None
    kwargs=dict(outcome=outcome,evidence_complete=outcome=="completed",key="label-finish",
                required_violation=outcome=="error")
    _finish(database,worker,first,**kwargs)
    _finish(database,worker,first,**kwargs)
    if outcome=="completed":
        _release(database,first)
        second=_claim(database,worker)
        assert second is not None
        _finish(database,worker,second,outcome="completed",evidence_complete=True,key="label-finish-2")
    with sqlite3.connect(database) as connection:
        rows=connection.execute("SELECT f.release_label,f.core_result FROM item_finalizations f JOIN case_runs r USING(project_id,case_run_id) WHERE r.execution_id=? ORDER BY r.rowid",(graph["execution_id"][0],)).fetchall()
    expected={"completed":["PASS","PASS"],"error":["FAIL","NOT_RUN"],"cancelled":["CANCELLED","CANCELLED"]}[outcome]
    assert rows==[("2026.11",result) for result in expected],rows
    with sqlite3.connect(database) as connection:
        clocks=connection.execute("SELECT created_seq,finalized_seq FROM item_finalizations JOIN case_runs USING(project_id,case_run_id) WHERE execution_id=?",(graph["execution_id"][0],)).fetchall()
        assert all(created==1 and finalized>created for created,finalized in clocks),clocks
