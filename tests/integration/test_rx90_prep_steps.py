"""Execution preparation shares four steps and a server-backed final confirmation."""
import asyncio

import httpx
from test_rx86_healing_execution import healing_execution
from test_rx93_healing_resolution import healing_metadata
from ux_support import session, ux_app


def test_trial_selection_and_suite_pages_share_the_four_steps(ux_app):
    app, project, _ = ux_app

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as client:
            headers = await session(client, project)
            created = await client.post(f"/api/v1/projects/{project}/cases", json={"name": "시범"}, headers=headers)
            case = created.json()["case_id"]
            suite = (await client.post(
                f"/api/v1/projects/{project}/suites",
                json={"name": "월간", "target_kind": "web"},
                headers=headers,
            )).json()
            pages = [
                await client.get(f"/ui/projects/{project}/cases/{case}/execution-setup"),
                await client.get(f"/ui/projects/{project}/execution-setup", params={"case_id": case}),
                await client.get(f"/ui/projects/{project}/suites/{suite['suite_id']}/execution-setup"),
            ]
            assert [page.status_code for page in pages] == [200, 200, 200]
            return [page.text for page in pages]

    for page in asyncio.run(exercise()):
        assert "1 대상" in page and "2 환경·데이터" in page
        assert "3 사전 점검" in page and "4 최종 확인" in page
        assert 'data-prep-back' in page and 'data-prep-edit' in page and "취소" in page
        assert "/static/execution_prep.js" in page
        assert "조용히 제외" in page or "자동으로 제외하지 않습니다" in page


def test_preview_confirmation_reports_caps_without_calling_a_model(healing_execution):
    fixture = healing_execution

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=fixture["app"]), base_url="http://127.0.0.1") as client:
            headers = await session(client, fixture["project"])
            body = {
                "name": "정식",
                "purpose": "regression",
                "source": "selection",
                "failure_policy": "continue",
                "self_healing_enabled": True,
                "release_label": "2026.11",
                "exclusions": [],
                "selection": {"items": [fixture["item"]]},
            }
            response = await client.post(
                f"/api/v1/projects/{fixture['project']}/execution-previews",
                json=body,
                headers=headers,
            )
            assert response.status_code == 200, response.text
            import sqlite3
            with sqlite3.connect(fixture["database"]) as db:
                calls = db.execute("SELECT COUNT(*) FROM model_call_facts").fetchone()[0]
            return response.json(), calls

    preview, calls = asyncio.run(scenario())
    confirmation = preview["confirmation"]
    item = confirmation["items"][0]
    assert confirmation["calls_are_estimated"] is True
    assert confirmation["actor_call_cap"] == 0
    assert confirmation["failure_policy"] == "continue"
    assert confirmation["release_label"] == "2026.11"
    assert item["approval_id"] == fixture["item"]["approval_id"]
    assert item["case_version_id"] == fixture["item"]["case_version_id"]
    assert item["resource_id"] == fixture["item"]["resource_id"]
    assert item["execution_limits"]["max_model_calls"] >= 1
    assert item["healing_enabled"] is True
    assert item["healing_limits"]["max_model_calls_per_item"] >= 1
    assert item["healing_limits"]["max_seconds"] >= 1
    assert calls == 0
