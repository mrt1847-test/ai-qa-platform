"""Selected-case regression is a real UI path, without silently dropping cases."""
import asyncio
import importlib.util
from pathlib import Path
from uuid import uuid4

import httpx
from ux_support import session, ux_app


def test_selected_execution_requires_exact_project_selection(ux_app):
    app, project, database = ux_app
    spec = importlib.util.spec_from_file_location("ux03_seed", Path(__file__).with_name("test_ux_03.py"))
    helpers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helpers)
    seed = helpers._seed(database, project, str(uuid4()))

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as client:
            headers = await session(client, project)
            draft = await client.post(f"/api/v1/projects/{project}/cases",json={"name":"승인 전 케이스"},headers=headers)
            assert draft.status_code == 201, draft.text
            draft_id = draft.json()["case_id"]
            base = f"/ui/projects/{project}/execution-setup"
            selected = [seed["case_id"], draft_id]
            page = await client.get(base, params=[("case_id", value) for value in selected])
            assert page.status_code == 200, page.text
            assert 'id="selection-execution"' in page.text
            assert 'data-count="2"' in page.text
            assert all(f'data-entry-id="{value}"' in page.text for value in selected)
            assert seed["version_v2"] in page.text
            assert seed["approval_v2"] in page.text
            assert seed["version_v4"] not in page.text  # current pointer, never latest event by timestamp
            assert "승인 전 케이스" in page.text and "승인본이 없습니다" in page.text
            assert 'id="enqueue-selection" type="button" disabled' in page.text
            for ids in [[],[seed["case_id"]]*2,[str(uuid4())],[str(uuid4()) for _ in range(101)]]:
                response=await client.get(base,params=[("case_id",value) for value in ids])
                assert response.status_code in (404,422), response.text
            listing=await client.get(f"/ui/projects/{project}/cases")
            assert 'id="selected-regression"' in listing.text
            before=await client.get(f"/api/v1/projects/{project}/executions",headers=headers)
            assert before.json()["items"] == []
    asyncio.run(exercise())
