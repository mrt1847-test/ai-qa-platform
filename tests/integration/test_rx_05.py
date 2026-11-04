"""RX-05: RemoteLeaseGuard, journal ambiguity, and cleanup confirmation."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from aiqa.api.app import create_app
from aiqa.api.auth import bound_auth_store, enroll_worker
from aiqa.config import load_settings
from aiqa.domain.projects import bind_store, create_project
from aiqa.store.database import migrate_store
from aiqa.store.models import Actor, ProjectCreate
from aiqa.store.queue import claim_queued_job
from aiqa.worker.control import RemoteLeaseGuard, RunControl
from aiqa.worker.dispatch_journal import DispatchJournal
from aiqa.worker.runner import LEASE_MARGIN_SECONDS, WATCHDOG_SECONDS, MonotonicInstant


def test_remote_lease_guard_budgets_and_clock() -> None:
    guard = RemoteLeaseGuard()
    assert guard.heartbeat_seconds == 10
    assert guard.lease_seconds == 45
    assert guard.watchdog_seconds == WATCHDOG_SECONDS
    assert guard.action_margin_seconds == LEASE_MARGIN_SECONDS
    guard.note_heartbeat(MonotonicInstant(0.0))
    assert guard.authorize(MonotonicInstant(5.0), 45.0).allowed is True
    assert guard.authorize(MonotonicInstant(6.0), 9.0).reason == "lease_margin"
    guard2 = RemoteLeaseGuard()
    guard2.note_heartbeat(MonotonicInstant(0.0))
    assert guard2.authorize(MonotonicInstant(WATCHDOG_SECONDS), 45.0).reason == "watchdog"
    guard3 = RemoteLeaseGuard()
    guard3.note_heartbeat(MonotonicInstant(10.0))
    with pytest.raises(ValueError):
        guard3.authorize(MonotonicInstant(5.0), 45.0)


def test_started_only_becomes_unknown_and_blocks_retry(tmp_path: Path) -> None:
    journal = DispatchJournal(tmp_path / "dispatch.jsonl")
    journal.append("attempt-1", "action-1", "planned")
    journal.append("attempt-1", "action-1", "dispatch_started")
    assert journal.is_ambiguous("attempt-1", "action-1") is True
    assert journal.mark_started_only_unknown("attempt-1", "action-1") == "unknown"
    assert journal.states("action-1", "attempt-1")[-1] == "unknown"
    assert journal.is_ambiguous("attempt-1", "action-1") is True
    with pytest.raises(Exception):
        journal.append("attempt-1", "action-1", "dispatch_started")


def test_cleanup_confirmation_and_fences(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "runtime"
    settings = load_settings(
        {"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}
    )
    app = create_app(settings)
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("정리", "rx05", "rx", "android"))
    actor = Actor(owner.actor_id, project.project_id, True)
    worker_id = str(uuid4())
    with bound_auth_store(store):
        token = enroll_worker(actor, worker_id, "resource_probe")
    resource = str(uuid4())
    now = datetime(2026, 11, 3, 16, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("aiqa.api.worker._server_now", lambda: now)
    with store.transaction() as connection:
        connection.execute(
            "INSERT INTO physical_resource_keys (physical_key_id, worker_id, native_id) VALUES (?, ?, ?)",
            (resource, worker_id, "emulator-5580"),
        )
        connection.execute(
            "INSERT INTO resource_aliases (project_id, physical_key_id, display_name, target_kind) VALUES (?, ?, ?, ?)",
            (str(project.project_id), resource, "AIQA", "android"),
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
        "cancel_blocks_next": True,
        "late_generation_rejected": True,
        "ambiguous_blocks_reclaim": True,
        "cleanup_releases": True,
        "reclaim_after_cleanup": True,
        "replay_cleanup": True,
        "migration": True,
    }


async def _exercise(app, project_id, worker_id: str, resource: str, token: str, now: datetime, root: Path):
    origin = "http://127.0.0.1"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        assert (
            await client.post(
                "/api/v1/worker/heartbeats",
                headers={"Authorization": f"Bearer {token}"},
                json={"boot_id": "boot-rx05"},
            )
        ).status_code == 200
        store = app.state.open_store()
        try:
            with store.transaction() as connection:
                job_id = str(uuid4())
                connection.execute(
                    """
                    INSERT INTO jobs (project_id, job_id, purpose, payload_hash, source_refs, limits, status)
                    VALUES (?, ?, 'resource_probe', 'hash', ?, '{}', 'queued')
                    """,
                    (str(project_id), job_id, json.dumps([resource])),
                )
        finally:
            store.close()
        claimed = await client.post(
            "/api/v1/worker/claims",
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "rx05-claim"},
            json={"boot_id": "boot-rx05", "now": now.isoformat()},
        )
        assert claimed.status_code == 200, claimed.text
        body = claimed.json()
        acked = await client.post(
            "/api/v1/worker/attempt-acks",
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "rx05-ack"},
            json={
                "project_id": body["project_id"],
                "job_id": body["job_id"],
                "generation": body["generation"],
                "runner_nonce": str(uuid4()),
                "now": now.isoformat(),
            },
        )
        assert acked.status_code == 200, acked.text

        store = app.state.open_store()
        try:
            with store.transaction() as connection:
                connection.execute(
                    "UPDATE jobs SET status = 'cancel_requested' WHERE job_id = ?",
                    (body["job_id"],),
                )
                from uuid import UUID

                control = RunControl(connection, project_id, UUID(body["job_id"]), "before_dispatch")
                cancel_blocks = control.authorize_dispatch().allowed is False
        finally:
            store.close()

        late = await client.post(
            "/api/v1/worker/cleanup-confirmations",
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "rx05-late"},
            json={
                "project_id": body["project_id"],
                "job_id": body["job_id"],
                "attempt_id": body["attempt_id"],
                "generation": body["generation"] + 1,
                "physical_key_id": resource,
                "proof_refs": ["proc:1"],
                "now": now.isoformat(),
            },
        )

        store = app.state.open_store()
        try:
            with store.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO jobs (project_id, job_id, purpose, payload_hash, source_refs, limits, status)
                    VALUES (?, ?, 'resource_probe', 'hash2', ?, '{}', 'queued')
                    """,
                    (str(project_id), str(uuid4()), json.dumps([resource])),
                )
                from aiqa.store.models import WorkerScope

                scope = WorkerScope(worker_id, (project_id,), ("resource_probe",))
                blocked = claim_queued_job(connection, scope, now, boot_id="boot-rx05")
        finally:
            store.close()

        cleaned = await client.post(
            "/api/v1/worker/cleanup-confirmations",
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "rx05-clean"},
            json={
                "project_id": body["project_id"],
                "job_id": body["job_id"],
                "attempt_id": body["attempt_id"],
                "generation": body["generation"],
                "physical_key_id": resource,
                "proof_refs": ["proc:1"],
                "now": now.isoformat(),
            },
        )
        replay = await client.post(
            "/api/v1/worker/cleanup-confirmations",
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "rx05-clean2"},
            json={
                "project_id": body["project_id"],
                "job_id": body["job_id"],
                "attempt_id": body["attempt_id"],
                "generation": body["generation"],
                "physical_key_id": resource,
                "proof_refs": ["proc:1"],
                "now": now.isoformat(),
            },
        )
        store = app.state.open_store()
        try:
            with store.transaction() as connection:
                from aiqa.store.models import WorkerScope
                from uuid import UUID

                connection.execute(
                    "UPDATE jobs SET status = 'cancelled' WHERE job_id = ?",
                    (body["job_id"],),
                )
                scope = WorkerScope(worker_id, (project_id,), ("resource_probe",))
                reclaimed = claim_queued_job(connection, scope, now, boot_id="boot-rx05")
                migrated = connection.execute(
                    "SELECT 1 FROM schema_migrations WHERE id = ?",
                    ("0041_cleanup_confirmations",),
                ).fetchone()
                leases = connection.execute(
                    "SELECT COUNT(*) FROM leases WHERE physical_key_id = ?",
                    (resource,),
                ).fetchone()[0]
        finally:
            store.close()

        return {
            "cancel_blocks_next": cancel_blocks,
            "late_generation_rejected": late.status_code == 409,
            "ambiguous_blocks_reclaim": blocked is None,
            "cleanup_releases": cleaned.status_code == 200 and cleaned.json()["released"] is True,
            "reclaim_after_cleanup": reclaimed is not None and leases == 1,
            "replay_cleanup": replay.status_code == 200 and replay.json()["replayed"] is True,
            "migration": migrated is not None,
        }
