"""Cumulative observations use the same cohort and provide usable result drilldown."""
import asyncio
import json
import sqlite3
from uuid import uuid4

import httpx
from ux_support import session, ux_app


def _seed(database,project,count=1):
    from test_w24 import _observation_graph
    seeds=[_observation_graph(database,project,str(uuid4()),"PASS") for _ in range(count)]
    missed={seed["missed"] for seed in seeds}
    with sqlite3.connect(database) as connection:
        for job,item,raw in connection.execute("SELECT job_id,case_run_id,limits FROM jobs WHERE project_id=?",(project,)).fetchall():
            limits=json.loads(raw);limits["release_label"]="release-b" if item in missed else "release-a"
            connection.execute("UPDATE jobs SET limits=? WHERE job_id=?",(json.dumps(limits),job))
    return seeds


def test_observation_api_matches_release_and_latest_completed_cohort(ux_app):
    app,project,database=ux_app
    seed=_seed(database,project)[0]
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://127.0.0.1") as client:
            headers=await session(client,project)
            params={"from":"2026-11-01","to":"2026-11-02","as_of":"15","release_label":"release-a"}
            response=await client.get(f"/api/v1/projects/{project}/observations",params=params,headers=headers)
            assert response.status_code==200,response.text
            rows=response.json()["items"]
            assert len(rows)==5
            assert seed["missed"] not in {item["case_run_id"] for item in rows}
            assert next(item for item in rows if item["case_run_id"]==seed["pending"])["result"] is None
            latest=await client.get(f"/api/v1/projects/{project}/observations",
                                   params={**params,"criteria":"latest_terminal"},headers=headers)
            assert len(latest.json()["items"])==4
            report=await client.get(f"/api/v1/projects/{project}/analytics",
                                   params={**params,"criteria":"latest_terminal"},headers=headers)
            assert report.json()["sample_count"]==len(latest.json()["items"])
            empty=await client.get(f"/api/v1/projects/{project}/observations",
                                  params={**params,"case":"missing-case"},headers=headers)
            assert empty.json()["items"]==[]
            detail=await client.get(f"/ui/projects/{project}/case-runs/{seed['pending']}")
            assert detail.status_code==200,detail.text
            assert 'data-qa-result="실패"' in detail.text
            assert "실행 결과" in detail.text

            foreign=await client.get(f"/api/v1/projects/{uuid4()}/observations",params=params,headers=headers)
            assert foreign.status_code==404
    asyncio.run(exercise())


def test_observation_table_paginates_without_losing_filters(ux_app):
    app,project,database=ux_app
    _seed(database,project,6)
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://127.0.0.1") as client:
            await session(client,project)
            params={"from":"2026-11-01","to":"2026-11-02","as_of":"15","release_label":"release-a","limit":"25"}
            first=await client.get(f"/ui/projects/{project}/analytics",params=params)
            assert first.status_code==200,first.text
            assert first.text.count("data-observation-row")==25
            assert "전체 30개 중 1–25" in first.text
            assert "현재 저장 결과" in first.text
            assert "release_label=release-a" in first.text and "page=2" in first.text
            second=await client.get(f"/ui/projects/{project}/analytics",params={**params,"page":"2"})
            assert second.status_code==200,second.text
            assert second.text.count("data-observation-row")==5
            assert "전체 30개 중 26–30" in second.text
            assert f"/ui/projects/{project}/case-runs/" in second.text
            for change in [{"page":"0"},{"page":"3"},{"limit":"101"},{"limit":"²"}]:
                bad=await client.get(f"/ui/projects/{project}/analytics",params={**params,**change})
                assert bad.status_code==422,bad.text
                assert 'value="release-a"' in bad.text
                assert "조건으로 조회" in bad.text
    asyncio.run(exercise())


def test_latest_cohort_keeps_last_completed_before_newer_open_item(ux_app):
    app,project,database=ux_app
    seed=_seed(database,project)[0]
    new_items={}
    with sqlite3.connect(database) as connection:
        case,version,raw=connection.execute(
            "SELECT r.case_id,r.case_version_id,j.limits FROM case_runs r JOIN jobs j USING(project_id,case_run_id) WHERE r.case_run_id=?",
            (seed["original"],)).fetchone()
        for name,stamp,result,created,finalized in [
            ("candidate","2026-11-01T00:01:00+00:00","PASS",2,3),
            ("future","2026-11-01T00:02:00+00:00","FAIL",10,20),
            ("unfinished","2026-11-01T00:03:00+00:00",None,10,None),
        ]:
            execution,item,job=(str(uuid4()) for _ in range(3))
            new_items[name]=item
            limits=json.loads(raw);limits["commit_seq"]=created
            connection.execute("INSERT INTO executions (project_id,execution_id,name,purpose,source,suite_version_id,scope_requested_at) VALUES (?,?,?,'regression','selection',NULL,?)",(project,execution,name,stamp))
            connection.execute("INSERT INTO case_runs (project_id,execution_id,case_run_id,case_id,case_version_id,purpose,requested_at) VALUES (?,?,?,?,?,'regression',?)",(project,execution,item,case,version,stamp))
            connection.execute("INSERT INTO jobs (project_id,job_id,purpose,recording_id,case_run_id,payload_hash,source_refs,limits,status) VALUES (?,?,'regression',NULL,?,'fixture','[]',?,?)",(project,job,item,json.dumps(limits),"completed" if result else "running"))
            if result:
                connection.execute("INSERT INTO item_finalizations (project_id,case_run_id,created_seq,finalized_seq,release_label,content_hash,core_result,denominator) VALUES (?,?,?,?,?,?,?,1)",(project,item,created,finalized,"release-a",name,result))

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://127.0.0.1") as client:
            headers=await session(client,project)
            params={"from":"2026-11-01","to":"2026-11-02","as_of":"15","release_label":"release-a","criteria":"latest_terminal"}
            for as_of,chosen,absent,count in [
                ("15",new_items["candidate"],new_items["future"],4),
                ("25",new_items["future"],new_items["candidate"],5),
            ]:
                current={**params,"as_of":as_of}
                rows=(await client.get(f"/api/v1/projects/{project}/observations",params=current,headers=headers)).json()["items"]
                ids={row["case_run_id"] for row in rows}
                assert chosen in ids and absent not in ids and seed["original"] not in ids
                assert new_items["unfinished"] not in ids and len(ids)==count
                report=(await client.get(f"/api/v1/projects/{project}/analytics",params=current,headers=headers)).json()
                assert report["sample_count"]==count
                assert report["first_satisfied"]==(2 if as_of=="15" else 1)
                page=await client.get(f"/ui/projects/{project}/analytics",params=current)
                assert f'data-observation-row="{chosen}"' in page.text
                assert f'data-observation-row="{absent}"' not in page.text
    asyncio.run(exercise())
