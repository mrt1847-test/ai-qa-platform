"""Formal preparation shows a default-off healing choice and the server's own blocks."""
import asyncio
import sqlite3

import httpx
from test_rx86_healing_execution import healing_execution
from test_rx93_healing_resolution import healing_metadata
from ux_support import session, ux_app


def _input_tag(page: str, element_id: str) -> str:
    start = page.index(f'id="{element_id}"')
    return page[page.rfind("<input", 0, start): page.index(">", start) + 1]


def test_suite_and_selection_default_off_while_trial_stays_disabled(ux_app):
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
            suite_page = await client.get(f"/ui/projects/{project}/suites/{suite['suite_id']}/execution-setup")
            selection = await client.get(f"/ui/projects/{project}/execution-setup", params={"case_id": case})
            trial = await client.get(f"/ui/projects/{project}/cases/{case}/execution-setup")
            assert suite_page.status_code == selection.status_code == trial.status_code == 200
            return suite_page.text, selection.text, trial.text

    suite, selection, trial = asyncio.run(exercise())
    for page in (suite, selection):
        tag = _input_tag(page, "healing-toggle")
        assert 'name="healing_enabled"' in tag and 'data-default="off"' in tag
        assert "checked" not in tag and "disabled" not in tag
        assert "/static/suite_execution.js" in page
    trial_tag = _input_tag(trial, "healing-toggle")
    assert "disabled" in trial_tag and "checked" not in trial_tag
    assert "시범 healing은 꺼져 있습니다." in trial


def test_same_approval_off_calls_no_model_and_on_reports_server_conditions(healing_execution):
    fixture = healing_execution

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=fixture["app"]), base_url="http://127.0.0.1") as client:
            headers = await session(client, fixture["project"])
            selection = {"items": [fixture["item"]]}
            results = {}
            for enabled in (False, True):
                response = await client.post(
                    f"/api/v1/projects/{fixture['project']}/execution-previews",
                    json={
                        "name": "정식",
                        "purpose": "regression",
                        "source": "selection",
                        "failure_policy": "continue",
                        "self_healing_enabled": enabled,
                        "exclusions": [],
                        "selection": selection,
                    },
                    headers=headers,
                )
                assert response.status_code == 200, response.text
                results[enabled] = response.json()
            with sqlite3.connect(fixture["database"]) as db:
                db.execute("UPDATE secret_refs SET availability='unavailable' WHERE ref_id=?", (fixture["key"],))
            blocked = await client.post(
                f"/api/v1/projects/{fixture['project']}/execution-previews",
                json={
                    "name": "정식",
                    "purpose": "regression",
                    "source": "selection",
                    "failure_policy": "continue",
                    "self_healing_enabled": True,
                    "exclusions": [],
                    "selection": selection,
                },
                headers=headers,
            )
            with sqlite3.connect(fixture["database"]) as db:
                calls = db.execute("SELECT COUNT(*) FROM model_call_facts").fetchone()[0]
                executions = db.execute("SELECT COUNT(*) FROM executions").fetchone()[0]
        return results, blocked.json(), calls, executions

    results, blocked, calls, executions = asyncio.run(scenario())
    off, on = results[False], results[True]
    assert off["ready"] is True and off["self_healing_enabled"] is False
    assert "healing_resolution" not in off["resolved_items"][0]
    assert on["ready"] is True and on["self_healing_enabled"] is True
    resolution = on["resolved_items"][0]["healing_resolution"]
    binding = on["resolved_items"][0]["healing_binding"]
    assert resolution["effective_enabled"] is True
    assert resolution["effective_limits"]["max_episodes_per_item"] >= 1
    assert resolution["effective_limits"]["max_model_calls_per_item"] >= 1
    assert binding["key_ref_id"] == fixture["key"]
    assert blocked["ready"] is False
    assert any(item["code"] == "HEALING_KEY_UNAVAILABLE" for item in blocked["blockers"])
    assert calls == 0 and executions == 0
