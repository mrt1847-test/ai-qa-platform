"""W07 resource inventory tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import UUID, uuid4

from aiqa.store.models import Actor, ProjectCreate


def test_w07_01(tmp_path: Path) -> None:
    import asyncio

    import httpx

    from aiqa.api.app import create_app
    from aiqa.api.auth import bound_auth_store, enroll_worker
    from aiqa.config import load_settings
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.store.database import migrate_store
    from aiqa.worker.resources import report_inventory

    assert callable(report_inventory)
    root = tmp_path / "runtime"
    app = create_app(
        load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)})
    )
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project_a = create_project(owner, ProjectCreate("Alpha", "w0701a", "a", "web"))
        project_b = create_project(owner, ProjectCreate("Beta", "w0701b", "b", "web"))
    worker = str(uuid4())
    with bound_auth_store(store):
        token_a = enroll_worker(Actor(owner.actor_id, project_a.project_id, True), worker, "resource_probe")
        token_b = enroll_worker(Actor(owner.actor_id, project_b.project_id, True), worker, "resource_probe")
    store.close()
    secret = "CDP-SECRET-W07-01"
    serial = "SERIAL-W07-01"
    statuses = asyncio.run(
        _report(app, project_a.project_id, project_b.project_id, token_a, token_b, serial, secret)
    )
    database = (root / "db" / "aiqa.sqlite").read_bytes()
    with sqlite3.connect(root / "db" / "aiqa.sqlite") as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM physical_resource_keys WHERE native_id = ?",
            (serial,),
        ).fetchone()
        leases = connection.execute(
            """
            SELECT COUNT(*) FROM leases
            WHERE physical_key_id IN (
                SELECT physical_key_id FROM physical_resource_keys WHERE native_id = ?
            )
            """,
            (serial,),
        ).fetchone()
    assert count is not None and leases is not None
    assert secret.encode() not in database
    observed = {
        "physical_resource_count": int(count[0]),
        "alias_double_booking": int(leases[0]) > 1,
        "ui_raw_handle": any(secret in body for body in statuses),
    }
    assert observed == {
        "physical_resource_count": 1,
        "alias_double_booking": False,
        "ui_raw_handle": False,
    }


async def _report(
    app: object,
    project_a: UUID,
    project_b: UUID,
    token_a: str,
    token_b: str,
    serial: str,
    secret: str,
) -> list[str]:
    import httpx
    from fastapi import FastAPI

    assert isinstance(app, FastAPI)
    transport = httpx.ASGITransport(app=app)
    bodies: list[str] = []
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
        for project_id, token, state, name in (
            (project_a, token_a, "offline", "pixel-a"),
            (project_b, token_b, "unauthorized", "pixel-b"),
            (project_a, token_a, "busy", "pixel-a"),
            (project_b, token_b, "busy", "pixel-b"),
        ):
            response = await client.post(
                "/api/v1/worker/inventory",
                headers={"Authorization": f"Bearer {token}", "Idempotency-Key": f"{state}-{name}"},
                json={
                    "project_id": str(project_id),
                    "native_id": serial,
                    "target_kind": "android",
                    "state": state,
                    "os_build": "test-build",
                    "geometry": '{"width": 100, "height": 200}',
                    "permissions": "[]",
                    "ime": "none",
                    "observed_at": "2026-11-01T00:00:00+00:00",
                    "display_name": name,
                    "raw_handle": secret,
                },
            )
            assert response.status_code == 200, response.text
            bodies.append(response.text)
    return bodies
