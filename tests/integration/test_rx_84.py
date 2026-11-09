"""As-of analytics uses admission creation and only already finalized results."""
import asyncio
import json
import sqlite3
from uuid import UUID, uuid4

import httpx
import pytest
from ux_support import session, ux_app


@pytest.mark.parametrize("future_result",["FAIL","PASS"])
def test_analytics_does_not_use_future_terminal_results(ux_app,monkeypatch,future_result):
    import test_w24 as helpers
    original=helpers._run
    def with_future_result(*args):
        values=list(args)
        if values[5]=="pending":values[9]=future_result
        return original(*values)
    monkeypatch.setattr(helpers,"_run",with_future_result)
    app,project,database=ux_app
    seed=helpers._observation_graph(database,project,str(uuid4()),"PASS")
    with sqlite3.connect(database) as connection:
        for key,duration in [("original",100),("rerun",200),("pending",99999)]:
            job,raw=connection.execute("SELECT job_id,limits FROM jobs WHERE case_run_id=?",(seed[key],)).fetchone()
            limits=json.loads(raw);limits["duration_ms"]=duration
            connection.execute("UPDATE jobs SET limits=? WHERE job_id=?",(json.dumps(limits),job))

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://127.0.0.1") as client:
            headers=await session(client,project)
            params={"from":"2026-11-01","to":"2026-11-02","as_of":"15"}
            old=await client.get(f"/api/v1/projects/{project}/analytics",params=params,headers=headers)
            assert old.status_code==200,old.text
            assert old.json()["denominator"]==6
            assert old.json()["rates"]==pytest.approx([5/6,1/4,1/6])
            assert old.json()["p50"]==100 and old.json()["p95"]==200
            assert old.json()["first_satisfied"]==1
            latest=await client.get(f"/api/v1/projects/{project}/analytics",
                params={**params,"criteria":"latest_terminal"},headers=headers)
            assert latest.json()["sample_count"]==5
            future=await client.get(f"/api/v1/projects/{project}/analytics",
                params={**params,"as_of":"20"},headers=headers)
            assert future.json()["rates"]==pytest.approx([1,2/5 if future_result=="PASS" else 1/5,2/6 if future_result=="PASS" else 1/6])
            assert future.json()["p50"]==200 and future.json()["p95"]==99999
            assert future.json()["first_satisfied"]==(2 if future_result=="PASS" else 1)
            before=await client.get(f"/api/v1/projects/{project}/analytics",
                params={**params,"as_of":"0"},headers=headers)
            assert before.json()["denominator"]==0
            assert before.json()["rates"] is None
            before_page=await client.get(f"/ui/projects/{project}/analytics",params={**params,"as_of":"0"})
            assert "분모가 없어 비율을 계산하지 않습니다" in before_page.text
    asyncio.run(exercise())


def test_unfinished_admitted_items_are_in_the_asof_denominator(ux_app):
    from test_rx_72 import _device, _execution
    from aiqa.contracts.reports import AnalyticsQuery
    from aiqa.domain.analytics import query_observations, read_analytics
    from aiqa.store.models import Actor, Transaction

    _,project,database=ux_app
    key=_device(database,project)
    graph=_execution(database,project,str(uuid4()),key,"continue",2)
    with sqlite3.connect(database) as connection:
        for job in graph["jobs"]:
            limits=json.loads(connection.execute("SELECT limits FROM jobs WHERE job_id=?",(job,)).fetchone()[0])
            limits["commit_seq"]=1
            connection.execute("UPDATE jobs SET limits=? WHERE job_id=?",(json.dumps(limits),job))
        query=AnalyticsQuery(UUID(project),"2026-11-01","2026-11-02",1)
        actor=Actor(uuid4(),UUID(project),True)
        page=query_observations(Transaction(connection),actor,query)
        assert len(page.items)==2
        assert all(item.in_denominator and not item.terminal and item.result is None for item in page.items)
        report=read_analytics(Transaction(connection),actor,query)
        assert report.denominator==2 and report.rates[0]==0
