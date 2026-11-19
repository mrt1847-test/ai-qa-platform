"""An explicit exclusion keeps its reason and does not count as a successful run."""
import asyncio
import sqlite3

import httpx
from test_rx86_healing_execution import healing_execution
from test_rx93_healing_resolution import healing_metadata
from ux_support import session, ux_app


def test_confirmed_exclusion_is_stored_and_a_missing_reason_is_rejected(healing_execution):
    fixture = healing_execution
    kept = fixture["item"]
    omitted = {**kept, "entry_id": "entry-2"}

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=fixture["app"]), base_url="http://127.0.0.1") as client:
            headers = await session(client, fixture["project"])
            common = {
                "name": "일부 실행",
                "purpose": "regression",
                "source": "selection",
                "failure_policy": "continue",
                "self_healing_enabled": False,
                "release_label": "",
                "selection": {"items": [kept, omitted]},
            }
            missing = await client.post(
                f"/api/v1/projects/{fixture['project']}/execution-previews",
                json={**common, "exclusions": [{"entry_id": "entry-2", "reason": "  ", "confirmed": True}]},
                headers=headers,
            )
            preview = await client.post(
                f"/api/v1/projects/{fixture['project']}/execution-previews",
                json={**common, "exclusions": [{"entry_id": "entry-2", "reason": "이번 배포에서 제외", "confirmed": True}]},
                headers=headers,
            )
            assert preview.status_code == 200, preview.text
            body = preview.json()
            admitted = await client.post(
                f"/api/v1/projects/{fixture['project']}/executions",
                json={
                    **common,
                    "preview_hash": body["preview_hash"],
                    "items": body["resolved_items"],
                    "exclusions": [{"entry_id": "entry-2", "reason": "이번 배포에서 제외", "confirmed": True}],
                },
                headers={**headers, "Idempotency-Key": "exclude-one"},
            )
            page = await client.get(f"/ui/projects/{fixture['project']}/executions/{admitted.json()['execution_id']}")
            with sqlite3.connect(fixture["database"]) as db:
                stored = db.execute("SELECT entry_id, reason FROM execution_exclusions").fetchall()
                runs = db.execute("SELECT COUNT(*) FROM case_runs").fetchone()[0]
                calls = db.execute("SELECT COUNT(*) FROM model_call_facts").fetchone()[0]
            return missing.status_code, body, admitted.status_code, page.text, stored, runs, calls

    status, body, admitted, page, stored, runs, calls = asyncio.run(scenario())
    assert status == 422
    assert body["ready"] is True and body["silent_exclusions"] == 0
    assert [item["entry_id"] for item in body["resolved_items"]] == ["entry-1"]
    assert body["exclusions"] == [{"entry_id": "entry-2", "reason": "이번 배포에서 제외"}]
    assert admitted == 201
    assert stored == [("entry-2", "이번 배포에서 제외")]
    assert runs == 1 and calls == 0
    assert "제외는 실행 성공이 아닙니다." in page
    assert "제외 entry-2 · 이번 배포에서 제외" in page
    assert "성공 2" not in page
