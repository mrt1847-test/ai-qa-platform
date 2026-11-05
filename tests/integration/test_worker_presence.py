import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import httpx

from aiqa.api.auth import bound_auth_store, enroll_worker
from aiqa.domain.resource_readiness import resource_readiness
from aiqa.store.database import _migration_env, migrate_store
from aiqa.store.queue import claim_queued_job
from aiqa.store.models import Actor, WorkerScope
from aiqa.worker.control import RunControl
from ux_support import ux_app
from worker_presence_support import seed_resource_alias


def test_heartbeat_fences_queued_work_across_disconnect(ux_app, monkeypatch):
    app, project, _ = ux_app
    project_id = UUID(project)
    store = app.state.open_store()
    with bound_auth_store(store):
        token = enroll_worker(Actor(uuid4(), project_id, True), "pc", "resource_probe")
    resource = str(uuid4())
    now = datetime(2026, 11, 3, tzinfo=timezone.utc)
    monkeypatch.setattr("aiqa.api.worker._server_now", lambda: now, raising=False)
    scope = WorkerScope("pc", (project_id,), ("resource_probe",))
    with store.transaction() as db:
        db.execute("INSERT INTO physical_resource_keys VALUES(?, 'pc', 'device')", (resource,))
        seed_resource_alias(db, project, resource, display_name="PC", target_kind="web")
        db.execute("INSERT INTO resource_inventory VALUES(?, 'ready', '', '', '[]', '', '2099-01-01')", (resource,))

    async def heartbeat(client, **extra):
        return await client.post("/api/v1/worker/heartbeats", headers={"Authorization": f"Bearer {token}"},
                                 json={"boot_id": "boot-1", **extra})

    async def claim(client, boot_id):
        return await client.post(
            "/api/v1/worker/claims",
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid4())},
            json={"boot_id": boot_id, "now": "2026-11-03T00:00:00+00:00"},
        )

    async def exercise():
        nonlocal now
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as client:
            with store.transaction() as db:
                assert not resource_readiness(db, project_id, resource, "web", now=now).ready
            assert (await heartbeat(client, project_id=str(uuid4()))).status_code == 403
            assert (await heartbeat(client, worker_id="someone-else")).status_code == 403
            assert (await heartbeat(client, purpose="regression")).status_code == 403
            assert (await heartbeat(client, boot_id="x" * 129)).status_code == 422
            response = await heartbeat(client, observed_at="2099-01-01")
            assert response.status_code == 200, response.text
            assert response.json()["last_seen"] == now.isoformat()
            with store.transaction() as db:
                assert resource_readiness(db, project_id, resource, "web", now=now + timedelta(seconds=44.999)).ready
                db.execute("""INSERT INTO jobs(project_id,job_id,purpose,payload_hash,source_refs,limits,status)
                              VALUES(?,?,'resource_probe','hash',?,'{}','queued')""",
                           (project, str(uuid4()), f'["{resource}"]'))
            now += timedelta(seconds=45)
            with store.transaction() as db:
                assert not resource_readiness(db, project_id, resource, "web", now=now).ready
                assert claim_queued_job(db, scope, now) is None
            assert (await claim(client, "boot-1")).status_code == 204
            assert (await heartbeat(client)).status_code == 200
            # Drop work queued during the dead session so reconnect cannot inherit it.
            with store.transaction() as db:
                db.execute("DELETE FROM jobs WHERE status = 'queued'")
            assert (await claim(client, "boot-1")).status_code == 204
            assert (await heartbeat(client, boot_id="boot-2")).status_code == 200
            assert (await heartbeat(client, boot_id="boot-1")).status_code == 403
            with store.transaction() as db:
                assert claim_queued_job(db, scope, now) is None
                assert db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 0
                fresh_job = str(uuid4())
                db.execute("""INSERT INTO jobs(project_id,job_id,purpose,payload_hash,source_refs,limits,status)
                              VALUES(?,?,'resource_probe','hash',?,'{}','queued')""",
                           (project, fresh_job, f'["{resource}"]'))
            assert (await claim(client, "boot-1")).status_code == 204
            claimed = await claim(client, "boot-2")
            assert claimed.status_code == 200, claimed.text
            assert claimed.json()["job_id"] == fresh_job
            assert claimed.json()["expires_at"] == (now + timedelta(seconds=45)).isoformat()
            assert (await heartbeat(client, boot_id="boot-3")).status_code == 200
            renewed = await client.post(
                "/api/v1/worker/lease-renewals",
                headers={"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid4())},
                json={"project_id": project, "job_id": fresh_job, "generation": 1},
            )
            assert renewed.status_code == 409
            with store.transaction() as db:
                control = RunControl(db, project_id, UUID(fresh_job), "before_dispatch", wall_clock=lambda: now)
                assert control.authorize_dispatch().reason == "stale_worker_session"
                db.execute("DELETE FROM worker_tokens")
                assert not resource_readiness(db, project_id, resource, "web", now=now).ready
            assert (await heartbeat(client)).status_code == 401

    try:
        asyncio.run(exercise())
    finally:
        store.close()


def test_admitted_trial_claims_the_resource_in_its_snapshot(ux_app):
    import sqlite3

    from acceptance.test_w17 import _case, _enqueue_twice, _packages, _preview

    app, project, database = ux_app
    version, case = asyncio.run(_case(app, project))
    environment, resource = str(uuid4()), str(uuid4())
    ready_version, _, _ = _packages(database, project, case, version, environment, resource)
    preview = asyncio.run(_preview(app, project, ready_version, environment, resource, False))
    created, _ = asyncio.run(_enqueue_twice(app, project, preview))
    with sqlite3.connect(database) as connection:
        scope = WorkerScope("worker-w1701", (UUID(project),), ("trial",))
        lease = claim_queued_job(connection, scope, datetime.now(timezone.utc))
        assert lease is not None
        assert str(lease.job_id) == created["job_ids"][0]
        assert str(lease.physical_key_id) == resource


def test_presence_upgrade_keeps_existing_registration_and_rejects_naive_clock(ux_app):
    import pytest

    from aiqa.store.database import StorageConfig, open_store
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.store.models import ProjectCreate
    from aiqa.worker.presence import get_presence

    _, _, database = ux_app
    store = open_store(StorageConfig(database.parent, database.with_name("previous.sqlite"),
                                     database.parent / "artifacts", database.parent / "spool"))
    try:
        env = _migration_env()
        with store.transaction() as db:
            env.ensure_history(db)
            for revision, apply in env.revisions():
                if revision == "0037_worker_presence":
                    break
                apply(db)
                db.execute("INSERT INTO schema_migrations VALUES (?, 'fixture')", (revision,))
        actor = Actor(uuid4(), None, True)
        with bind_store(store):
            project = create_project(actor, ProjectCreate("Existing", "existing", "", "web"))
        with bound_auth_store(store):
            enroll_worker(Actor(actor.actor_id, project.project_id, True), "existing-worker", "recording")
        migrate_store(store)
        with store.transaction() as db:
            assert db.execute("SELECT COUNT(*) FROM worker_tokens").fetchone()[0] == 1
            assert get_presence(db, "existing-worker", datetime.now(timezone.utc)).state == "unknown"
            with pytest.raises(ValueError, match="timezone"):
                get_presence(db, "existing-worker", datetime(2026, 11, 3))
    finally:
        store.close()
