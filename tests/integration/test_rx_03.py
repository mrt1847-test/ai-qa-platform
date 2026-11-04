"""RX-03: claim receipts, JobSpecSnapshot, and idempotent replay."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import httpx

from aiqa.api.app import create_app
from aiqa.api.auth import bound_auth_store, enroll_worker
from aiqa.config import load_settings
from aiqa.contracts.worker_attempt import ClaimReceipt, JobSpecSnapshot
from aiqa.domain.projects import bind_store, create_project
from aiqa.store.database import migrate_store
from aiqa.store.models import Actor, ProjectCreate
from aiqa.worker.control import RunControl


def test_snapshot_contract_shape() -> None:
    job_id = uuid4()
    attempt_id = uuid4()
    snapshot = JobSpecSnapshot(job_id, attempt_id, "resource_probe", "target", "rev", "policy", "sha256:abc")
    receipt = ClaimReceipt(
        uuid4(), job_id, 1, "worker", None, "2026-11-03T13:00:00+00:00", attempt_id, "s", "b", snapshot, False
    )
    assert receipt.snapshot.digest.startswith("sha256:") or receipt.snapshot.digest == "sha256:abc"
    assert receipt.replayed is False


def test_claim_receipt_replay_conflict_snapshot_and_expiry(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "runtime"
    settings = load_settings(
        {"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}
    )
    app = create_app(settings)
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("영수증", "rx03", "rx", "android"))
    actor = Actor(owner.actor_id, project.project_id, True)
    worker_id = str(uuid4())
    with bound_auth_store(store):
        token = enroll_worker(actor, worker_id, "resource_probe")
    resource = str(uuid4())
    now = datetime(2026, 11, 3, 14, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("aiqa.api.worker._server_now", lambda: now)
    with store.transaction() as connection:
        connection.execute(
            "INSERT INTO physical_resource_keys (physical_key_id, worker_id, native_id) VALUES (?, ?, ?)",
            (resource, worker_id, "emulator-5580"),
        )
        connection.execute(
            "INSERT INTO resource_aliases (project_id, physical_key_id, display_name, target_kind) VALUES (?, ?, ?, ?)",
            (str(project.project_id), resource, "별칭A", "android"),
        )
        connection.execute(
            """
            INSERT INTO resource_inventory (
                physical_key_id, state, os_build, geometry, permissions, ime, observed_at
            ) VALUES (?, 'ready', '', '', '[]', '', ?)
            """,
            (resource, now.isoformat()),
        )
    store.close()

    observed = asyncio.run(_exercise(app, project.project_id, worker_id, resource, token, now, root))
    assert observed == {
        "first_claim": True,
        "replay_same_attempt": True,
        "attempts": 1,
        "conflict": True,
        "scope_forged": True,
        "snapshot_stable": True,
        "canonical_target": True,
        "ack_ok": True,
        "expired_dispatch_blocked": True,
        "migration": True,
    }


async def _exercise(app, project_id, worker_id: str, resource: str, token: str, now: datetime, root: Path):
    origin = "http://127.0.0.1"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        beat = await client.post(
            "/api/v1/worker/heartbeats",
            headers={"Authorization": f"Bearer {token}"},
            json={"boot_id": "boot-rx03"},
        )
        assert beat.status_code == 200, beat.text
        store = app.state.open_store()
        try:
            with store.transaction() as connection:
                job_id = str(uuid4())
                connection.execute(
                    """
                    INSERT INTO jobs (project_id, job_id, purpose, payload_hash, source_refs, limits, status)
                    VALUES (?, ?, 'resource_probe', 'hash', ?, ?, 'queued')
                    """,
                    (
                        str(project_id),
                        job_id,
                        f'["{resource}"]',
                        json.dumps({"policy_ref": "policy-v1"}),
                    ),
                )
        finally:
            store.close()

        first = await client.post(
            "/api/v1/worker/claims",
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "rx03-claim"},
            json={"boot_id": "boot-rx03", "now": now.isoformat()},
        )
        assert first.status_code == 200, first.text
        body = first.json()
        digest = body["snapshot"]["digest"]
        attempt_id = body["attempt_id"]

        store = app.state.open_store()
        try:
            with store.transaction() as connection:
                connection.execute(
                    "UPDATE projects SET name = ? WHERE project_id = ?",
                    ("이름변경", str(project_id)),
                )
        finally:
            store.close()

        replay = await client.post(
            "/api/v1/worker/claims",
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "rx03-claim"},
            json={"boot_id": "boot-rx03", "now": now.isoformat()},
        )
        conflict = await client.post(
            "/api/v1/worker/claims",
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "rx03-claim"},
            json={"boot_id": "boot-other", "now": now.isoformat()},
        )
        forged = await client.post(
            "/api/v1/worker/claims",
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "rx03-forged"},
            json={"boot_id": "boot-rx03", "project_id": str(uuid4()), "now": now.isoformat()},
        )
        acked = await client.post(
            "/api/v1/worker/attempt-acks",
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "rx03-ack"},
            json={
                "project_id": body["project_id"],
                "job_id": body["job_id"],
                "generation": body["generation"],
                "runner_nonce": str(uuid4()),
                "now": now.isoformat(),
            },
        )

        store = app.state.open_store()
        try:
            with store.transaction() as connection:
                attempts = connection.execute(
                    "SELECT COUNT(*) FROM attempts WHERE job_id = ?", (body["job_id"],)
                ).fetchone()[0]
                connection.execute(
                    "UPDATE claim_receipts SET expires_at = ? WHERE attempt_id = ?",
                    ((now - timedelta(seconds=1)).isoformat(), attempt_id),
                )
                connection.execute(
                    "UPDATE leases SET expires_at = ? WHERE job_id = ?",
                    ((now + timedelta(seconds=45)).isoformat(), body["job_id"]),
                )
                control = RunControl(
                    connection,
                    project_id,
                    UUID(body["job_id"]),
                    "before_dispatch",
                    wall_clock=lambda: now,
                )
                blocked = control.authorize_dispatch()
                migrated = connection.execute(
                    "SELECT 1 FROM schema_migrations WHERE id = ?",
                    ("0040_claim_receipts",),
                ).fetchone()
        finally:
            store.close()

        return {
            "first_claim": body["replayed"] is False and body["snapshot"]["purpose"] == "resource_probe",
            "replay_same_attempt": replay.status_code == 200
            and replay.json()["attempt_id"] == attempt_id
            and replay.json()["replayed"] is True,
            "attempts": attempts,
            "conflict": conflict.status_code == 409,
            "scope_forged": forged.status_code == 409,
            "snapshot_stable": replay.json()["snapshot"]["digest"] == digest,
            "canonical_target": body["snapshot"]["target_ref"] == resource,
            "ack_ok": acked.status_code == 200,
            "expired_dispatch_blocked": blocked.allowed is False and blocked.reason == "expired_claim_receipt",
            "migration": migrated is not None,
        }
