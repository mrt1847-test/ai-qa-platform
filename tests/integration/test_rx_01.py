"""RX-01: worker incarnation is separate from server boot."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx

from aiqa.api.app import create_app
from aiqa.api.auth import bound_auth_store, enroll_worker
from aiqa.api.lifecycle import start_api
from aiqa.config import load_settings
from aiqa.domain.projects import bind_store, create_project
from aiqa.store.database import migrate_store
from aiqa.store.models import Actor, ProjectCreate, WorkerIncarnation
from aiqa.worker.service import bind_claim_store, reconcile_jobs


def test_worker_incarnation_shape() -> None:
    item = WorkerIncarnation("worker-a", "session-b", "boot-c")
    assert (item.worker_id, item.session_id, item.boot_id) == ("worker-a", "session-b", "boot-c")


def test_server_restart_keeps_worker_lease_worker_restart_blocks(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "runtime"
    settings = load_settings(
        {"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}
    )
    app = create_app(settings)
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("세대", "rx01", "rx", "android"))
    actor = Actor(owner.actor_id, project.project_id, True)
    worker_id = str(uuid4())
    with bound_auth_store(store):
        token = enroll_worker(actor, worker_id, "resource_probe")
    resource = str(uuid4())
    now = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
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

    claimed, acked, incarnation = asyncio.run(
        _claim_and_ack(app, token, worker_id, resource, str(project.project_id), "boot-worker-1", now)
    )
    assert claimed.status_code == 200, claimed.text
    assert acked.status_code == 200, acked.text
    assert incarnation.worker_id == worker_id
    assert incarnation.boot_id == "boot-worker-1"

    with sqlite3.connect(root / "db" / "aiqa.sqlite") as connection:
        row = connection.execute(
            """
            SELECT worker_id, session_id, boot_id FROM attempt_incarnations
            WHERE attempt_id = ?
            """,
            (claimed.json()["attempt_id"],),
        ).fetchone()
        host = connection.execute(
            "SELECT boot_id FROM runner_hosts WHERE attempt_id = ?",
            (claimed.json()["attempt_id"],),
        ).fetchone()
        status_after_claim = connection.execute(
            "SELECT status FROM jobs WHERE job_id = ?", (claimed.json()["job_id"],)
        ).fetchone()[0]
    assert row is not None
    assert row[0] == worker_id and row[2] == "boot-worker-1"
    assert host is None
    assert status_after_claim == "preparing"

    monkeypatch.setattr("aiqa.api.lifecycle.host_boot_id", lambda: "server-boot-after-restart")
    store = app.state.open_store()
    with bind_claim_store(store):
        report = reconcile_jobs(now)
    store.close()
    with sqlite3.connect(root / "db" / "aiqa.sqlite") as connection:
        status = connection.execute(
            "SELECT status FROM jobs WHERE job_id = ?", (claimed.json()["job_id"],)
        ).fetchone()[0]
    assert status == "preparing"
    assert report.queued_preserved is True

    renewed_before = asyncio.run(_renew(app, token, claimed.json(), now))
    assert renewed_before.status_code == 200, renewed_before.text

    restarted = asyncio.run(_heartbeat(app, token, "boot-worker-2"))
    assert restarted.status_code == 200, restarted.text
    renewed_after = asyncio.run(_renew(app, token, claimed.json(), now))
    assert renewed_after.status_code == 409
    forged = asyncio.run(_ack(app, token, claimed.json(), str(uuid4()), now))
    assert forged.status_code == 409

    store = app.state.open_store()
    with bind_claim_store(store):
        reconcile_jobs(now)
    store.close()
    with sqlite3.connect(root / "db" / "aiqa.sqlite") as connection:
        lost = connection.execute(
            "SELECT status FROM jobs WHERE job_id = ?", (claimed.json()["job_id"],)
        ).fetchone()[0]
        attempts = connection.execute(
            "SELECT COUNT(*) FROM attempts WHERE job_id = ?", (claimed.json()["job_id"],)
        ).fetchone()[0]
    assert lost == "lost"
    assert attempts == 1


def test_legacy_runner_hosts_still_use_server_boot(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    settings = load_settings(
        {"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}
    )
    app = create_app(settings)
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("레거시", "rx01b", "legacy", "web"))
    actor = Actor(owner.actor_id, project.project_id, True)
    worker_id = str(uuid4())
    with bound_auth_store(store):
        enroll_worker(actor, worker_id, "structure")
    live_job = str(uuid4())
    reboot_job = str(uuid4())
    reboot_attempt = str(uuid4())
    with store.transaction() as connection:
        for job_id, label in ((live_job, "live"), (reboot_job, "reboot")):
            connection.execute(
                """
                INSERT INTO jobs (project_id, job_id, purpose, payload_hash, source_refs, limits, status)
                VALUES (?, ?, 'structure', ?, ?, '{}', 'running')
                """,
                (str(project.project_id), job_id, f"hash-{label}", f'["{label}"]'),
            )
            connection.execute(
                """
                INSERT INTO leases (project_id, job_id, generation, worker_id, physical_key_id, expires_at)
                VALUES (?, ?, 1, ?, NULL, ?)
                """,
                (str(project.project_id), job_id, worker_id, "2026-11-03T13:00:00+00:00"),
            )
        live_attempt = str(uuid4())
        connection.execute(
            """
            INSERT INTO attempts (project_id, attempt_id, job_id, generation, physical_key_id)
            VALUES (?, ?, ?, 1, NULL)
            """,
            (str(project.project_id), live_attempt, live_job),
        )
        connection.execute(
            """
            INSERT INTO attempts (project_id, attempt_id, job_id, generation, physical_key_id)
            VALUES (?, ?, ?, 1, NULL)
            """,
            (str(project.project_id), reboot_attempt, reboot_job),
        )
        connection.execute(
            """
            INSERT INTO attempt_runners (project_id, attempt_id, runner_nonce, acked_at)
            VALUES (?, ?, ?, ?)
            """,
            (str(project.project_id), live_attempt, str(uuid4()), "2026-11-03T12:00:10+00:00"),
        )
        connection.execute(
            """
            INSERT INTO attempt_runners (project_id, attempt_id, runner_nonce, acked_at)
            VALUES (?, ?, ?, ?)
            """,
            (str(project.project_id), reboot_attempt, str(uuid4()), "2026-11-03T12:00:10+00:00"),
        )
        connection.execute(
            "INSERT INTO runner_hosts (project_id, attempt_id, boot_id) VALUES (?, ?, ?)",
            (str(project.project_id), live_attempt, "same-server-boot"),
        )
        connection.execute(
            "INSERT INTO runner_hosts (project_id, attempt_id, boot_id) VALUES (?, ?, ?)",
            (str(project.project_id), reboot_attempt, "old-server-boot"),
        )
    store.close()

    import aiqa.api.lifecycle as lifecycle

    lifecycle._boot_id = "same-server-boot"
    try:
        start_api(settings, datetime(2026, 11, 3, 12, 0, 20, tzinfo=timezone.utc))
    finally:
        lifecycle._boot_id = None

    with sqlite3.connect(root / "db" / "aiqa.sqlite") as connection:
        statuses = {
            job_id: connection.execute(
                "SELECT status FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()[0]
            for job_id in (live_job, reboot_job)
        }
        assert connection.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE id = ?",
            ("0038_worker_attempt_incarnation",),
        ).fetchone()[0] == 1
    assert statuses == {live_job: "running", reboot_job: "lost"}


async def _claim_and_ack(
    app, token: str, worker_id: str, resource: str, project_id: str, boot_id: str, now: datetime
):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        beat = await client.post(
            "/api/v1/worker/heartbeats",
            headers={"Authorization": f"Bearer {token}"},
            json={"boot_id": boot_id},
        )
        assert beat.status_code == 200, beat.text
        store = app.state.open_store()
        try:
            with store.transaction() as connection:
                job_id = str(uuid4())
                connection.execute(
                    """
                    INSERT INTO jobs (project_id, job_id, purpose, payload_hash, source_refs, limits, status)
                    VALUES (?, ?, 'resource_probe', 'hash', ?, '{}', 'queued')
                    """,
                    (project_id, job_id, f'["{resource}"]'),
                )
        finally:
            store.close()
        claimed = await client.post(
            "/api/v1/worker/claims",
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "rx01-claim"},
            json={"boot_id": boot_id, "now": now.isoformat()},
        )
        assert claimed.status_code == 200, claimed.text
        lease = claimed.json()
        acked = await client.post(
            "/api/v1/worker/attempt-acks",
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "rx01-ack"},
            json={
                "project_id": lease["project_id"],
                "job_id": lease["job_id"],
                "generation": lease["generation"],
                "runner_nonce": str(uuid4()),
                "now": now.isoformat(),
            },
        )
        store = app.state.open_store()
        try:
            with store.transaction() as connection:
                row = connection.execute(
                    "SELECT session_id, boot_id FROM worker_presence WHERE worker_id = ?",
                    (worker_id,),
                ).fetchone()
        finally:
            store.close()
        incarnation = WorkerIncarnation(worker_id, row[0], row[1])
        return claimed, acked, incarnation


async def _heartbeat(app, token: str, boot_id: str):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        return await client.post(
            "/api/v1/worker/heartbeats",
            headers={"Authorization": f"Bearer {token}"},
            json={"boot_id": boot_id},
        )


async def _renew(app, token: str, lease: dict, now: datetime):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        return await client.post(
            "/api/v1/worker/lease-renewals",
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid4())},
            json={
                "project_id": lease["project_id"],
                "job_id": lease["job_id"],
                "generation": lease["generation"],
                "now": now.isoformat(),
            },
        )


async def _ack(app, token: str, lease: dict, nonce: str, now: datetime):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        return await client.post(
            "/api/v1/worker/attempt-acks",
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid4())},
            json={
                "project_id": lease["project_id"],
                "job_id": lease["job_id"],
                "generation": lease["generation"],
                "runner_nonce": nonce,
                "now": now.isoformat(),
            },
        )
