"""RX-28: execution PC registration UI — issue/copy/cancel/revoke gates."""

from __future__ import annotations

import asyncio
import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import httpx

from aiqa.api.auth import bound_auth_store, enroll_worker
from aiqa.domain.projects import bind_store, create_project, grant_membership
from aiqa.store.database import migrate_store
from aiqa.store.models import Actor, ProjectCreate, Transaction
from ux_support import session, ux_app
from worker_presence_support import seed_inventory, seed_presence, seed_resource_alias


def test_rx_28_admin_registration_viewer_denied_revoke_blocks(ux_app) -> None:
    asyncio.run(_exercise(ux_app))


async def _exercise(ux_app) -> None:
    app, project, database = ux_app
    origin = "http://127.0.0.1"
    worker_id = f"pc-{uuid4()}"
    now = datetime.now(timezone.utc)
    device = str(uuid4())

    with sqlite3.connect(database) as db:
        db.execute(
            "INSERT INTO worker_enrollments VALUES (?, ?, ?, ?)",
            (str(uuid4()), worker_id, project, now.isoformat()),
        )
        db.execute("INSERT INTO physical_resource_keys VALUES (?, ?, 'device')", (device, worker_id))
        seed_resource_alias(db, project, device, display_name=worker_id, target_kind="web")
        seed_inventory(db, device)
        seed_presence(db, project, worker_id, now)
        db.commit()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=origin
    ) as client:
        headers = await session(client, project)
        page = await client.get(f"/ui/projects/{project}/environments")
        assert page.status_code == 200
        assert 'data-pc-registration' in page.text
        assert "접속용 브라우저 PC에 설치할 필요는 없습니다" in page.text
        assert "등록 코드 발급" in page.text
        assert 'accesskey="i"' in page.text
        assert 'accesskey="c"' in page.text
        assert 'accesskey="x"' in page.text
        assert 'accesskey="r"' in page.text
        assert "pc_availability.js" in page.text

        issued = await client.post(
            f"/api/v1/projects/{project}/worker-enrollment-codes",
            headers={**headers, "Idempotency-Key": "rx28-issue"},
            json={"worker_id": f"new-{uuid4()}", "purpose": "resource_probe", "expires_in_seconds": 900},
        )
        assert issued.status_code == 201, issued.text
        code = issued.json()["code"]
        assert code
        assert issued.json()["expires_at"]

        cancelled = await client.post(
            f"/api/v1/projects/{project}/worker-enrollment-codes/cancel",
            headers={**headers, "Idempotency-Key": "rx28-cancel"},
            json={"worker_id": issued.json()["worker_id"]},
        )
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["cancelled"] >= 1

        with sqlite3.connect(database) as db:
            row = db.execute(
                "SELECT consumed_at FROM worker_enrollment_codes WHERE code_hash=?",
                (hashlib.sha256(code.encode()).hexdigest(),),
            ).fetchone()
            assert row is not None and row[0] is not None

        # Fresh credential then revoke → worker API blocked, execute false.
        store = app.state.open_store()
        migrate_store(store)
        with bound_auth_store(store):
            credential = enroll_worker(Actor(uuid4(), UUID(project), True), f"live-{uuid4()}", "resource_probe")
        live_worker = None
        with store.transaction() as connection:
            live_worker = str(
                connection.execute(
                    """
                    SELECT worker_enrollments.worker_id
                    FROM worker_tokens
                    JOIN worker_enrollments ON worker_enrollments.enrollment_id = worker_tokens.enrollment_id
                    WHERE worker_tokens.token_hash = ?
                    """,
                    (hashlib.sha256(credential.encode()).hexdigest(),),
                ).fetchone()[0]
            )
        store.close()

        revoke = await client.post(
            f"/api/v1/workers/{live_worker}/revoke",
            headers={**headers, "Idempotency-Key": "rx28-revoke-live"},
            json={"project_id": project},
        )
        assert revoke.status_code == 200, revoke.text

        blocked = await client.post(
            "/api/v1/worker/inventory",
            headers={"Authorization": f"Bearer {credential}", "Idempotency-Key": "rx28-inv"},
            json={
                "project_id": project,
                "native_id": "web-rx28",
                "target_kind": "web",
                "state": "ready",
                "os_build": "build-1",
                "geometry": "100x100",
                "permissions": "[]",
                "ime": "none",
                "observed_at": now.isoformat(),
                "display_name": "폐기 후",
                "raw_handle": None,
            },
        )
        assert blocked.status_code in {401, 403}, blocked.text

        revoke_seeded = await client.post(
            f"/api/v1/workers/{worker_id}/revoke",
            headers={**headers, "Idempotency-Key": "rx28-revoke"},
            json={"project_id": project},
        )
        assert revoke_seeded.status_code == 200, revoke_seeded.text

        resources = await client.get(f"/api/v1/projects/{project}/resources", headers=headers)
        assert resources.status_code == 200
        row = next(item for item in resources.json()["resources"] if item["worker_id"] == worker_id)
        assert row["can_execute"] is False
        assert row["connection_state"] != "online"

    # Viewer / non-admin: no controls, API 403.
    viewer_id = uuid4()
    session_id = str(uuid4())
    csrf = "viewer-csrf-token"
    with sqlite3.connect(database) as db:
        grant_membership(
            Transaction(db),
            UUID(project),
            viewer_id,
            "viewer",
            now=now,
        )
        db.execute(
            """
            INSERT INTO browser_sessions (
                session_id, origin, csrf_hash, actor_id, project_scope, is_local_owner, expires_at
            ) VALUES (?, ?, ?, ?, ?, 0, ?)
            """,
            (
                session_id,
                origin,
                hashlib.sha256(csrf.encode()).hexdigest(),
                str(viewer_id),
                project,
                (now + timedelta(hours=1)).isoformat(),
            ),
        )
        db.commit()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=origin
    ) as client:
        client.cookies.set("aiqa_session", session_id)
        client.cookies.set("aiqa_csrf", csrf)
        page = await client.get(f"/ui/projects/{project}/environments")
        assert page.status_code == 200
        assert "data-pc-registration-denied" in page.text
        assert "등록 코드 발급" not in page.text
        assert 'data-pc-action="issue"' not in page.text

        denied = await client.post(
            f"/api/v1/projects/{project}/worker-enrollment-codes",
            headers={
                "Origin": origin,
                "X-CSRF-Token": csrf,
                "Idempotency-Key": "rx28-viewer",
            },
            json={"worker_id": f"viewer-{uuid4()}", "purpose": "resource_probe"},
        )
        assert denied.status_code == 403, denied.text

        revoke_denied = await client.post(
            f"/api/v1/workers/{worker_id}/revoke",
            headers={
                "Origin": origin,
                "X-CSRF-Token": csrf,
                "Idempotency-Key": "rx28-viewer-revoke",
            },
            json={"project_id": project},
        )
        assert revoke_denied.status_code == 403, revoke_denied.text


def test_rx_28_admin_membership_may_issue_without_local_owner(tmp_path) -> None:
    from aiqa.api.app import create_app
    from aiqa.config import load_settings
    from aiqa.security.worker_enrollment import issue_enrollment_code

    root = tmp_path / "runtime"
    app = create_app(
        load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)})
    )
    store = app.state.open_store()
    migrate_store(store)
    owner = Actor(uuid4(), None, True)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("RX28", "rx28", "", "web"))
    admin_id = uuid4()
    now = datetime.now(timezone.utc)
    with store.transaction() as connection:
        grant_membership(Transaction(connection), project.project_id, admin_id, "admin", now=now)
        admin = Actor(admin_id, project.project_id, False)
        issued = issue_enrollment_code(connection, admin, f"w-{uuid4()}", "resource_probe", now=now)
        assert issued.code
        viewer = Actor(uuid4(), project.project_id, False)
        grant_membership(Transaction(connection), project.project_id, viewer.actor_id, "viewer", now=now)
        try:
            issue_enrollment_code(connection, viewer, f"w-{uuid4()}", "resource_probe", now=now)
            denied = False
        except Exception:
            denied = True
        assert denied is True
    store.close()
