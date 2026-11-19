"""The next API claim does not inherit the previous claim's budget or clock."""
import asyncio
import sqlite3
from datetime import datetime, timezone
from uuid import UUID, uuid4

import httpx
from aiqa.api.auth import bound_auth_store, enroll_worker
from aiqa.store.models import Actor
from test_rx86_healing_execution import _common, healing_execution, healing_metadata
from test_rx_34 import _replay
from ux_support import session, ux_app


def _release(client, token, project, claim):
    return client.post(
        "/api/v1/worker/cleanup-confirmations",
        headers={"Authorization": "Bearer " + token, "Idempotency-Key": "reuse-" + claim["job_id"]},
        json={
            "project_id": project,
            "job_id": claim["job_id"],
            "attempt_id": claim["attempt_id"],
            "generation": claim["generation"],
            "physical_key_id": claim["physical_key_id"],
            "proof_refs": ["adb:released"],
            "now": datetime.now(timezone.utc).isoformat(),
        },
    )


def test_second_api_claim_does_not_inherit_the_previous_budget(healing_execution, tmp_path):
    fixture = healing_execution

    async def scenario():
        store = fixture["app"].state.open_store()
        try:
            with bound_auth_store(store):
                token = enroll_worker(Actor(uuid4(), UUID(fixture["project"]), True), "worker-w2002", "regression")
        finally:
            store.close()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=fixture["app"]), base_url="http://127.0.0.1") as client:
            headers = await session(client, fixture["project"])
            claims = []
            for index in (1, 2):
                body = {**_common(self_healing_enabled=False, name=f"재사용 {index}"), "selection": {"items": [fixture["item"]]}}
                preview = await client.post(f"/api/v1/projects/{fixture['project']}/execution-previews", json=body, headers=headers)
                assert preview.status_code == 200 and preview.json()["ready"], preview.text
                admitted = await client.post(
                    f"/api/v1/projects/{fixture['project']}/executions",
                    json={**body, "preview_hash": preview.json()["preview_hash"], "items": preview.json()["resolved_items"]},
                    headers={**headers, "Idempotency-Key": f"reuse-admit-{index}"},
                )
                assert admitted.status_code == 201, admitted.text
            for index in (1, 2):
                claimed = await client.post(
                    "/api/v1/worker/claims",
                    json={"project_id": fixture["project"], "boot_id": "fixture-boot", "now": datetime.now(timezone.utc).isoformat()},
                    headers={"Authorization": "Bearer " + token, "Idempotency-Key": f"reuse-claim-{index}"},
                )
                assert claimed.status_code == 200, (index, claimed.status_code, claimed.text)
                claim = claimed.json()
                claims.append(claim)
                if index == 1:
                    released = await _release(client, token, fixture["project"], claim)
                    assert released.status_code == 200 and released.json()["released"] is True, released.text
                    with sqlite3.connect(fixture["database"]) as db:
                        db.execute(
                            "UPDATE jobs SET status='completed' WHERE job_id=? AND status='preparing'",
                            (claim["job_id"],),
                        )
                        db.commit()
            return claims

    claims = asyncio.run(scenario())
    assert claims[0]["attempt_id"] != claims[1]["attempt_id"]
    assert claims[0]["snapshot"]["replay_package_hash"] == claims[1]["snapshot"]["replay_package_hash"]
    handler, calls = _replay(tmp_path)
    handler.context.mono_seconds = 100.0
    for claim in claims:
        claim["snapshot"]["serial"] = handler.context.expected_serial
    handler.healer_calls = 4
    first = handler.handle(claims[0])
    assert first.outcome == "completed" and first.actions == 1 and handler.healer_calls == 0
    handler.context.mono_seconds = 100000.0
    handler.healer_calls = 4
    handler.dispatch_count = 9
    second = handler.handle(claims[1])
    assert second.outcome == "completed" and second.actions == 1
    assert handler.dispatch_count == 1 and handler.healer_calls == handler.authoring_calls_seen == handler.verifier_calls == 0
    assert handler.stopped_reason == "" and len(calls) == 2
    with sqlite3.connect(fixture["database"]) as db:
        assert db.execute("SELECT COUNT(*) FROM item_finalizations WHERE core_result='PASS'").fetchone()[0] == 0
