"""Saved-suite regression has a reachable, revision-pinned browser entry."""
import asyncio
from uuid import uuid4

import httpx
from ux_support import session, ux_app


def test_suite_execution_setup_is_scoped_and_does_not_admit_on_get(ux_app):
    app, project, _ = ux_app

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as client:
            headers = await session(client, project)
            created = await client.post(
                f"/api/v1/projects/{project}/suites",
                json={"name": "월간 회귀", "target_kind": "web"},
                headers=headers,
            )
            assert created.status_code == 201, created.text
            suite = created.json()
            path = f"/ui/projects/{project}/suites/{suite['suite_id']}/execution-setup"
            page = await client.get(path)
            assert page.status_code == 200
            assert 'id="suite-execution"' in page.text
            assert f'data-version="{suite["version_id"]}"' in page.text
            assert "저장된 구성 0개" in page.text
            assert 'id="enqueue-suite" type="button" disabled' in page.text
            assert "/static/suite_execution.js" in page.text
            listing = await client.get(f"/ui/projects/{project}/suites")
            editor = await client.get(f"/ui/projects/{project}/suites/{suite['suite_id']}")
            assert path in listing.text and path in editor.text
            hidden = await client.get(path.replace(project, str(uuid4())))
            assert hidden.status_code == 404
            missing = await client.get(path.replace(suite["suite_id"], str(uuid4())))
            assert missing.status_code == 404
            executions = await client.get(f"/api/v1/projects/{project}/executions", headers=headers)
            assert executions.json()["items"] == []

    asyncio.run(exercise())
