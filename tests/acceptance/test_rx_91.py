"""Rejected recording intent returns422 and rolls back every admission write."""
import asyncio
import importlib.util
import sqlite3
from pathlib import Path
from uuid import uuid4

import httpx
from ux_support import session, ux_app


def test_intent_rejection_rolls_back_recording_and_rerecording(ux_app,monkeypatch):
    app,project,database=ux_app
    spec=importlib.util.spec_from_file_location("rx91_w31",Path(__file__).with_name("test_w31.py"))
    helpers=importlib.util.module_from_spec(spec);spec.loader.exec_module(helpers)
    seed=asyncio.run(helpers._prepare(app,project,database,str(uuid4())))
    from aiqa.recording.intent import IntentRejected
    seen=[]
    def reject(*args,**kwargs):
        seen.append(True)
        raise IntentRejected("content_hash is invalid")
    monkeypatch.setattr("aiqa.recording.intent.freeze_intent_for_version",reject)

    def snapshot():
        with sqlite3.connect(database) as connection:
            counts=tuple(connection.execute("SELECT COUNT(*) FROM "+table+" WHERE project_id=?",(project,)).fetchone()[0]
                         for table in ["case_versions","recordings","jobs","job_receipts"])
            state=connection.execute("SELECT latest_draft_version_id,next_revision,lock_version FROM automation_cases WHERE project_id=? AND case_id=?",(project,seed["case_id"])).fetchone()
            clock=connection.execute("SELECT commit_seq FROM project_commit_clock WHERE project_id=?",(project,)).fetchone()
            return counts,state,clock
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://127.0.0.1") as client:
            headers=await session(client,project)
            with sqlite3.connect(database) as connection:
                digest=connection.execute("SELECT content_hash FROM case_versions WHERE version_id=?",(seed["version_id"],)).fetchone()[0]
            before=snapshot()
            recording={"case_id":seed["case_id"],"input_case_version_id":seed["version_id"],
                       "input_version_hash":digest,"resource_id":"key-w3105"}
            rerecord=helpers._rerecord(project,seed["version_id"],"")
            rerecord.pop("repair_proposal_id")
            for key,url,payload in [
                ("intent-start",f"/api/v1/projects/{project}/recordings",recording),
                ("intent-rerecord",f"/api/v1/cases/{seed['case_id']}/rerecordings",rerecord),
            ]:
                for _ in range(2):
                    response=await client.post(url,json=payload,headers={**headers,"Idempotency-Key":key})
                    assert response.status_code==422,response.text
                    assert response.json()["error"]["message"]=="content_hash is invalid"
                    assert snapshot()==before
            assert len(seen)==4
    asyncio.run(exercise())
