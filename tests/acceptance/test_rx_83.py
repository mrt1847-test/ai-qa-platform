"""Cumulative analysis can be opened and filtered using the normal HTML UI."""
import asyncio
import importlib.util
import json
import sqlite3
from html.parser import HTMLParser
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from ux_support import session, ux_app


class Form(HTMLParser):
    def __init__(self):
        super().__init__()
        self.fields={}
        self.submit=False
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag in {"input","select"} and "name" in attrs:
            self.fields[attrs["name"]]=attrs.get("value","")
        if tag=="button" and attrs.get("type")=="submit":
            self.submit=True


def test_analytics_has_default_entry_and_filter_controls(ux_app):
    app,project,_=ux_app
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://127.0.0.1") as client:
            await session(client,project)
            page=await client.get(f"/ui/projects/{project}/analytics")
            assert page.status_code==200,page.text
            form=Form();form.feed(page.text)
            assert form.submit
            assert {"from","to","as_of","purpose","include_trial","criteria","release_label",
                    "case","version","verification","data","env","build","model"} <= set(form.fields)
            assert "빈 표본은 비율을 내지 않습니다" in page.text
            assert "표본 0" in page.text
            listed=await client.get(f"/ui/projects/{project}/reports")
            assert f"/ui/projects/{project}/analytics" in listed.text
    asyncio.run(exercise())


def test_release_filter_and_invalid_input_are_retained(ux_app):
    app,project,database=ux_app
    spec=importlib.util.spec_from_file_location("rx83_w24",Path(__file__).with_name("test_w24.py"))
    helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    seed=helper._analytics_graph(database,project,str(uuid4()))
    with sqlite3.connect(database) as connection:
        for job,raw in connection.execute("SELECT job_id,limits FROM jobs WHERE project_id=?",(project,)).fetchall():
            limits=json.loads(raw);limits["release_label"]="release-a"
            connection.execute("UPDATE jobs SET limits=? WHERE job_id=?",(json.dumps(limits),job))
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://127.0.0.1") as client:
            headers=await session(client,project)
            params={"from":"2026-11-01","to":"2026-11-02","as_of":"15",
                    "purpose":"regression","case":seed["case"],"release_label":"release-a"}
            api=await client.get(f"/api/v1/projects/{project}/analytics",params=params,headers=headers)
            assert api.status_code==200,api.text
            assert api.json()["sample_count"]==4
            page=await client.get(f"/ui/projects/{project}/analytics",params=params)
            assert page.status_code==200,page.text
            form=Form();form.feed(page.text)
            assert form.fields["release_label"]=="release-a"
            assert form.fields["case"]==seed["case"]
            assert "表" not in page.text
            empty=await client.get(f"/api/v1/projects/{project}/analytics",
                                   params={**params,"release_label":"release-b"},headers=headers)
            assert empty.json()["sample_count"]==0
            for change in [{"from":"2026-99-99"},{"from":"2026-11-03"},{"as_of":"-1"}]:
                bad={**params,**change}
                api=await client.get(f"/api/v1/projects/{project}/analytics",params=bad,headers=headers)
                assert api.status_code==422,api.text
                page=await client.get(f"/ui/projects/{project}/analytics",params=bad)
                assert page.status_code==422,page.text
                form=Form();form.feed(page.text)
                assert form.submit and form.fields["release_label"]=="release-a"
                assert all(form.fields[key]==value for key,value in change.items())
    asyncio.run(exercise())

@pytest.mark.parametrize("change", [
    {"as_of":"²"}, {"as_of":str(2**80)}, {"from":"0001-01-01"},
])
def test_invalid_analytics_boundaries_return_422(ux_app, change):
    app,project,_=ux_app
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://127.0.0.1") as client:
            headers=await session(client,project)
            params={"from":"2026-11-01","to":"2026-11-02","as_of":"1",**change}
            api=await client.get(f"/api/v1/projects/{project}/analytics",params=params,headers=headers)
            assert api.status_code==422,api.text
            page=await client.get(f"/ui/projects/{project}/analytics",params=params)
            assert page.status_code==422,page.text
            form=Form();form.feed(page.text)
            assert all(form.fields[key]==value for key,value in change.items())
    asyncio.run(exercise())
