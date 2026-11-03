"""Execution availability is independent of stored device observations."""
import asyncio
from datetime import datetime, timedelta, timezone
import sqlite3
from uuid import UUID, uuid4

import httpx

from aiqa.store.models import WorkerScope
from aiqa.store.queue import claim_queued_job
from ux_support import session, ux_app
from worker_presence_support import seed_inventory, seed_presence


def test_resource_response_and_environment_show_server_connection_state(ux_app):
    app, project, database = ux_app
    now = datetime.now(timezone.utc)
    states = {
        "ready": ("online", "ready", True),
        "cleanup": ("online", "cleanup_pending", False),
        "busy": ("online", "busy", False),
        "offline": ("offline", "ready", False),
        "unknown": ("unknown", "ready", False),
        "quarantine": ("online", "quarantine", False),
    }
    with sqlite3.connect(database) as db:
        for worker, (connection, state, _) in states.items():
            device = str(uuid4())
            db.execute("INSERT INTO worker_enrollments VALUES (?, ?, ?, ?)", (str(uuid4()), worker, project, now.isoformat()))
            db.execute("INSERT INTO physical_resource_keys VALUES (?, ?, 'device')", (device, worker))
            db.execute("INSERT INTO resource_aliases VALUES (?, ?, ?, 'web')", (project, device, worker))
            seed_inventory(db, device)
            db.execute("UPDATE resource_inventory SET observed_at='2099-01-01T00:00:00Z' WHERE physical_key_id=?", (device,))
            if state == "quarantine":
                db.execute("INSERT INTO resource_quarantine VALUES (?, 'expired', ?)", (device, now.isoformat()))
            if connection != "unknown":
                seed_presence(db, project, worker, now - timedelta(seconds=46) if connection == "offline" else now)
            if state in {"busy", "cleanup_pending"}:
                db.execute(
                    """INSERT INTO jobs(project_id,job_id,purpose,payload_hash,source_refs,limits,status)
                       VALUES(?,?,'resource_probe','fixture',?,'{}','queued')""",
                    (project, str(uuid4()), f'["{device}"]'),
                )
                lease = claim_queued_job(db, WorkerScope(worker, (UUID(project),), ("resource_probe",)), now)
                assert lease is not None
                if state == "cleanup_pending":
                    db.execute("UPDATE jobs SET status='completed' WHERE job_id=?", (str(lease.job_id),))

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as client:
            assert (await client.get(f"/api/v1/projects/{project}/resources")).status_code == 401
            await session(client, project)
            response = await client.get(f"/api/v1/projects/{project}/resources")
            assert response.status_code == 200
            assert response.headers["cache-control"] == "no-store"
            rows = response.json()["resources"]
            assert {r["worker_id"]: (r["connection_state"], r["state"], r["can_execute"]) for r in rows} == states
            offline = next(r for r in rows if r["worker_id"] == "offline")
            assert offline["last_seen"] != offline["observed_at"]
            assert offline["can_diagnose"] is False
            assert offline["block_reason"]
            assert (await client.get(f"/api/v1/resources/{offline['resource_id']}/preview",
                                     params={"project_id": project})).status_code == 200
            assert all(not ({"token_id", "boot_id", "session_id", "endpoint"} & r.keys()) for r in rows)
            page = await client.get(f"/ui/projects/{project}/environments")
            assert page.status_code == 200
            assert "PC 마지막 응답" in page.text
            assert "저장된 최근 관찰" in page.text
            assert "이전 작업의 기기 정리" in page.text
            assert offline["block_reason"] in page.text

    asyncio.run(exercise())
