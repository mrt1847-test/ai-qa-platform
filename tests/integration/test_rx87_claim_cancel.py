"""Cancel and lease return leave the approved package and a stored failure unchanged."""
import asyncio
import copy
import sqlite3
from datetime import datetime, timezone
from uuid import UUID, uuid4

import httpx
from aiqa.api.auth import bound_auth_store, enroll_worker
from aiqa.store.models import Actor
from test_rx86_healing_execution import _common, healing_execution, healing_metadata
from test_rx_34 import _replay
from ux_support import session, ux_app


def test_cancel_and_cleanup_keep_the_package_and_the_failure(healing_execution, tmp_path):
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
            body = {**_common(self_healing_enabled=False), "selection": {"items": [fixture["item"]]}}
            preview = await client.post(f"/api/v1/projects/{fixture['project']}/execution-previews", json=body, headers=headers)
            assert preview.status_code == 200 and preview.json()["self_healing_enabled"] is False, preview.text
            admitted = await client.post(
                f"/api/v1/projects/{fixture['project']}/executions",
                json={**body, "preview_hash": preview.json()["preview_hash"], "items": preview.json()["resolved_items"]},
                headers={**headers, "Idempotency-Key": "cancel-admit"},
            )
            assert admitted.status_code == 201, admitted.text
            execution_id = admitted.json()["execution_id"]
            claimed = await client.post(
                "/api/v1/worker/claims",
                json={"project_id": fixture["project"], "boot_id": "fixture-boot", "now": datetime.now(timezone.utc).isoformat()},
                headers={"Authorization": "Bearer " + token, "Idempotency-Key": "cancel-claim"},
            )
            assert claimed.status_code == 200, claimed.text
            claim = claimed.json()
            package = claim["snapshot"]["replay_package_hash"]
            with sqlite3.connect(fixture["database"]) as db:
                case_run = db.execute("SELECT case_run_id FROM jobs WHERE job_id=?", (claim["job_id"],)).fetchone()[0]
                before = db.execute("SELECT limits FROM jobs WHERE job_id=?", (claim["job_id"],)).fetchone()[0]
                db.execute(
                    """INSERT INTO item_finalizations
                       (project_id, case_run_id, created_seq, finalized_seq, release_label, content_hash, core_result, denominator)
                       VALUES (?, ?, 1, 1, '', ?, 'FAIL', 1)""",
                    (fixture["project"], case_run, "FAIL:" + case_run),
                )
                db.commit()
            cancelled = await client.post(
                f"/api/v1/executions/{execution_id}/cancel",
                params={"project_id": fixture["project"]},
                headers={**headers, "Idempotency-Key": "cancel-run"},
                json={},
            )
            cleanup = await client.post(
                "/api/v1/worker/cleanup-confirmations",
                headers={"Authorization": "Bearer " + token, "Idempotency-Key": "cancel-cleanup"},
                json={
                    "project_id": fixture["project"],
                    "job_id": claim["job_id"],
                    "attempt_id": claim["attempt_id"],
                    "generation": claim["generation"],
                    "physical_key_id": claim["physical_key_id"],
                    "proof_refs": ["adb:released"],
                    "now": datetime.now(timezone.utc).isoformat(),
                },
            )
            with sqlite3.connect(fixture["database"]) as db:
                after = db.execute("SELECT limits FROM jobs WHERE job_id=?", (claim["job_id"],)).fetchone()[0]
                result = db.execute(
                    "SELECT core_result FROM item_finalizations WHERE case_run_id=?", (case_run,)
                ).fetchone()[0]
                leases = db.execute("SELECT COUNT(*) FROM leases WHERE job_id=?", (claim["job_id"],)).fetchone()[0]
            return claim, package, before, after, result, cancelled.status_code, cleanup.status_code, cleanup.json(), leases

    claim, package, before, after, result, cancel_status, cleanup_status, cleanup_body, leases = asyncio.run(scenario())
    assert cancel_status == 409
    assert result == "FAIL" and before == after and package in after
    assert cleanup_status == 200 and cleanup_body["released"] is True and cleanup_body["quarantined"] is False
    assert leases == 0

    snapshot = copy.deepcopy(claim["snapshot"])
    handler, calls = _replay(tmp_path)
    snapshot["serial"] = handler.context.expected_serial
    snapshot["cancel_requested"] = True
    stopped = handler.handle({**claim, "snapshot": snapshot})
    assert stopped.actions == 0 and calls == [] and handler.healer_calls == 0
    assert snapshot["replay_package_hash"] == package

    leased, lease_calls = _replay(tmp_path / "lease")
    open_snapshot = copy.deepcopy(claim["snapshot"])
    open_snapshot["serial"] = leased.context.expected_serial
    leased.context.lease_remaining_seconds = 0
    expired = leased.handle({**claim, "snapshot": open_snapshot})
    assert expired.actions == 0 and lease_calls == [] and leased.stopped_reason == "lease_margin"
    assert leased.healer_calls == 0 and open_snapshot["replay_package_hash"] == package
