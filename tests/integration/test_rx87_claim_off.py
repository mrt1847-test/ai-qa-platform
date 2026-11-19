"""An OFF API claim stays at actor zero, and a failed check is not replayed or carried forward."""
import copy
import asyncio
from datetime import datetime, timezone
from uuid import UUID, uuid4

import httpx
from aiqa.adapters.mobile_agent_android import MobileAgentRejected
from aiqa.api.auth import bound_auth_store, enroll_worker
from aiqa.store.models import Actor
from test_rx86_healing_execution import _common, healing_execution, healing_metadata
from ux_support import session, ux_app
from test_rx_34 import _replay


def _off_claim(healing_execution):
    fixture = healing_execution
    store = fixture["app"].state.open_store()
    try:
        with bound_auth_store(store):
            token = enroll_worker(Actor(uuid4(), UUID(fixture["project"]), True), "worker-w2002", "regression")
    finally:
        store.close()

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=fixture["app"]), base_url="http://127.0.0.1") as client:
            headers = await session(client, fixture["project"])
            body = {**_common(self_healing_enabled=False), "selection": {"items": [fixture["item"]]}}
            preview = await client.post(f"/api/v1/projects/{fixture['project']}/execution-previews", json=body, headers=headers)
            assert preview.status_code == 200 and preview.json()["ready"] and preview.json()["self_healing_enabled"] is False, preview.text
            admitted = await client.post(
                f"/api/v1/projects/{fixture['project']}/executions",
                json={**body, "preview_hash": preview.json()["preview_hash"], "items": preview.json()["resolved_items"]},
                headers={**headers, "Idempotency-Key": "off-claim"},
            )
            assert admitted.status_code == 201, admitted.text
            import sqlite3
            from aiqa.domain.executions import validate_claim_snapshot
            from aiqa.store.models import JobSpec
            with sqlite3.connect(fixture["database"]) as db:
                row = db.execute("SELECT job_id, purpose, payload_hash, source_refs, limits, status, case_run_id FROM jobs").fetchone()
                spec = JobSpec(UUID(fixture["project"]), UUID(row[0]), row[1], None, UUID(row[6]), row[2], row[3], row[4], row[5])
                decision = validate_claim_snapshot(spec, db)
            assert decision.status == "ALLOWED", decision.status
            claimed = await client.post(
                "/api/v1/worker/claims",
                json={"project_id": fixture["project"], "boot_id": "fixture-boot", "now": datetime.now(timezone.utc).isoformat()},
                headers={"Authorization": "Bearer " + token, "Idempotency-Key": "off-worker-claim"},
            )
            assert claimed.status_code == 200, claimed.text
            return claimed.json()

    return asyncio.run(scenario())


def test_off_claim_is_actor_zero_and_a_failed_check_is_not_carried(healing_execution, tmp_path, monkeypatch):
    claim = _off_claim(healing_execution)
    handler, calls = _replay(tmp_path)
    claim["snapshot"]["serial"] = handler.context.expected_serial
    saved = copy.deepcopy(claim)
    played = handler.handle(claim)
    assert played.outcome == "completed" and played.actions == len(calls) == 1
    assert handler._healing_pin.enabled is False
    assert handler.authoring_calls_seen == handler.healer_calls == handler.verifier_calls == 0

    failed_handler, failed_calls = _replay(tmp_path / "failed")
    failed_handler.context.expected_serial = saved["snapshot"]["serial"]
    seen = []
    def reject(**kwargs):
        seen.append(kwargs)
        raise MobileAgentRejected("text_mismatch")
    monkeypatch.setattr(failed_handler.adapter, "replay_step", reject)
    failed = failed_handler.handle(saved)
    assert len(seen) == 1
    assert failed.actions == 0 and failed_calls == []
    assert failed_handler.healer_calls == failed_handler.authoring_calls_seen == 0
    assert failed_handler.original_failure == "text_mismatch"

    nxt = {**saved, "snapshot": {**saved["snapshot"], "serial": "other-device"}}
    reset = failed_handler.handle(nxt)
    assert reset.actions == 0 and reset.outcome == "error"
    assert failed_handler.original_failure == ""
    assert failed_handler.healer_calls == failed_handler.authoring_calls_seen == failed_handler.verifier_calls == 0
    assert failed_handler.dispatch_count == 0 and failed_calls == []
