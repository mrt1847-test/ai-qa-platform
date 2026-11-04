"""RX-02: enrollment codes, exchange, revoke, and permission fences."""

from __future__ import annotations

import asyncio
import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import httpx

from aiqa.api.app import create_app
from aiqa.api.auth import AuthRequired, bound_auth_store, enroll_worker, worker_scope_from_token
from aiqa.config import load_settings
from aiqa.domain.projects import bind_store, create_project
from aiqa.security.worker_enrollment import (
    EnrollmentCodeRejected,
    EnrollmentDenied,
    exchange_enrollment_code,
    issue_enrollment_code,
)
from aiqa.store.database import migrate_store
from aiqa.store.models import Actor, ProjectCreate


def test_issue_exchange_rejects_reuse_expiry_and_non_admin(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    app = create_app(
        load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)})
    )
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("발급", "rx02", "rx", "android"))
        other = create_project(owner, ProjectCreate("다른", "rx02b", "other", "android"))
    admin = Actor(owner.actor_id, project.project_id, True)
    stranger = Actor(uuid4(), project.project_id, False)
    now = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
    worker_id = f"worker-{uuid4()}"
    with store.transaction() as connection:
        try:
            issue_enrollment_code(connection, stranger, worker_id, "resource_probe", now=now)
            non_admin = False
        except EnrollmentDenied:
            non_admin = True
        issued = issue_enrollment_code(
            connection, admin, worker_id, "resource_probe", now=now, ttl=timedelta(minutes=5)
        )
        exchanged = exchange_enrollment_code(connection, issued.code, worker_id, now=now)
        try:
            exchange_enrollment_code(connection, issued.code, worker_id, now=now)
            reused = False
        except EnrollmentCodeRejected:
            reused = True
        expired = issue_enrollment_code(
            connection,
            Actor(owner.actor_id, other.project_id, True),
            f"other-{uuid4()}",
            "resource_probe",
            now=now,
            ttl=timedelta(seconds=1),
        )
        try:
            exchange_enrollment_code(
                connection, expired.code, expired.worker_id, now=now + timedelta(seconds=2)
            )
            expired_ok = True
        except EnrollmentCodeRejected:
            expired_ok = False
        wrong = issue_enrollment_code(
            connection, admin, f"bound-{uuid4()}", "resource_probe", now=now
        )
        try:
            exchange_enrollment_code(connection, wrong.code, "someone-else", now=now)
            wrong_worker = True
        except EnrollmentCodeRejected:
            wrong_worker = False
        code_hashed = connection.execute(
            "SELECT 1 FROM worker_enrollment_codes WHERE code_hash = ?",
            (hashlib.sha256(issued.code.encode()).hexdigest(),),
        ).fetchone()
        raw_code = connection.execute(
            "SELECT 1 FROM worker_enrollment_codes WHERE code_hash = ?",
            (issued.code,),
        ).fetchone()
        raw_token = connection.execute(
            "SELECT 1 FROM worker_tokens WHERE token_hash = ?",
            (exchanged.token,),
        ).fetchone()
        connection.execute(
            "UPDATE worker_tokens SET expires_at = ? WHERE token_hash = ?",
            (
                (now - timedelta(seconds=1)).isoformat(),
                hashlib.sha256(exchanged.token.encode()).hexdigest(),
            ),
        )
        fresh = issue_enrollment_code(
            connection, admin, f"fresh-{uuid4()}", "resource_probe", now=now
        )
        live = exchange_enrollment_code(connection, fresh.code, fresh.worker_id, now=now)
    import aiqa.api.auth as auth_api

    previous = auth_api._now
    auth_api._now = lambda: now
    try:
        with bound_auth_store(store):
            try:
                worker_scope_from_token(exchanged.token)
                expired_token_rejected = False
            except AuthRequired:
                expired_token_rejected = True
            permitted = worker_scope_from_token(live.token)
    finally:
        auth_api._now = previous
    store.close()
    assert non_admin is True
    assert reused is True
    assert expired_ok is False
    assert wrong_worker is False
    assert expired_token_rejected is True
    assert code_hashed is not None
    assert raw_code is None
    assert raw_token is None
    assert permitted.worker_id == live.worker_id
    assert permitted.permitted_projects == (project.project_id,)
    assert exchanged.project_id == project.project_id
    assert exchanged.project_id != other.project_id


def test_api_exchange_and_revoke_blocks_claim_and_marks_cleanup(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "runtime"
    settings = load_settings(
        {"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}
    )
    app = create_app(settings)
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("교환", "rx02c", "ex", "android"))
    actor = Actor(owner.actor_id, project.project_id, True)
    worker_id = str(uuid4())
    with bound_auth_store(store):
        legacy = enroll_worker(actor, worker_id, "resource_probe")
    resource = str(uuid4())
    now = datetime(2026, 11, 3, 13, 0, tzinfo=timezone.utc)
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

    observed = asyncio.run(
        _exercise_api(app, project.project_id, worker_id, resource, legacy, now)
    )
    assert observed == {
        "code_issued": True,
        "exchange_ok": True,
        "reuse_rejected": True,
        "claim_before_revoke": True,
        "renew_before_revoke": True,
        "revoke_ok": True,
        "claim_after_revoke": False,
        "renew_after_revoke": False,
            "cleanup_pending": True,
            "raw_code_absent": True,
        }


async def _exercise_api(app, project_id, worker_id: str, resource: str, legacy: str, now: datetime):
    origin = "http://127.0.0.1"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        issued = await client.post(
            "/api/v1/session/nonces",
            json={"origin": origin, "project_id": str(project_id)},
            headers={"Idempotency-Key": "rx02-nonce", "Origin": origin},
        )
        booted = await client.post(
            "/api/v1/session/bootstrap",
            json={"nonce": issued.json()["nonce"]},
            headers={"Idempotency-Key": "rx02-boot", "Origin": origin},
        )
        client.cookies.set("aiqa_session", booted.cookies["aiqa_session"])
        headers = {"Origin": origin, "X-CSRF-Token": booted.json()["csrf_token"]}

        code_worker = str(uuid4())
        coded = await client.post(
            f"/api/v1/projects/{project_id}/worker-enrollment-codes",
            json={"worker_id": code_worker, "purpose": "resource_probe", "expires_in_seconds": 600},
            headers={**headers, "Idempotency-Key": "rx02-code"},
        )
        assert coded.status_code == 201, coded.text
        code = coded.json()["code"]
        exchanged = await client.post(
            "/api/v1/worker/enrollments/exchange",
            json={"code": code, "worker_id": code_worker},
            headers={"Idempotency-Key": "rx02-exchange"},
        )
        assert exchanged.status_code == 201, exchanged.text
        token = exchanged.json()["token"]
        reused = await client.post(
            "/api/v1/worker/enrollments/exchange",
            json={"code": code, "worker_id": code_worker},
            headers={"Idempotency-Key": "rx02-reuse"},
        )

        beat = await client.post(
            "/api/v1/worker/heartbeats",
            headers={"Authorization": f"Bearer {legacy}"},
            json={"boot_id": "boot-rx02"},
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
                    (str(project_id), job_id, f'["{resource}"]'),
                )
        finally:
            store.close()

        claimed = await client.post(
            "/api/v1/worker/claims",
            headers={"Authorization": f"Bearer {legacy}", "Idempotency-Key": "rx02-claim"},
            json={"boot_id": "boot-rx02", "now": now.isoformat()},
        )
        lease = claimed.json() if claimed.status_code == 200 else {}
        renewed = await client.post(
            "/api/v1/worker/lease-renewals",
            headers={"Authorization": f"Bearer {legacy}", "Idempotency-Key": "rx02-renew"},
            json={
                "project_id": lease.get("project_id"),
                "job_id": lease.get("job_id"),
                "generation": lease.get("generation", 1),
                "now": now.isoformat(),
            },
        )
        revoked = await client.post(
            f"/api/v1/workers/{worker_id}/revoke",
            json={"project_id": str(project_id)},
            headers={**headers, "Idempotency-Key": "rx02-revoke"},
        )
        claim_after = await client.post(
            "/api/v1/worker/claims",
            headers={"Authorization": f"Bearer {legacy}", "Idempotency-Key": "rx02-claim2"},
            json={"boot_id": "boot-rx02", "now": now.isoformat()},
        )
        renew_after = await client.post(
            "/api/v1/worker/lease-renewals",
            headers={"Authorization": f"Bearer {legacy}", "Idempotency-Key": "rx02-renew2"},
            json={
                "project_id": lease.get("project_id"),
                "job_id": lease.get("job_id"),
                "generation": lease.get("generation", 1),
                "now": now.isoformat(),
            },
        )
        with sqlite3.connect(Path(app.state.settings.runtime_root) / "db" / "aiqa.sqlite") as connection:
            status = connection.execute(
                "SELECT status FROM jobs WHERE job_id = ?", (lease.get("job_id"),)
            ).fetchone()
            code_row = connection.execute(
                "SELECT code_hash FROM worker_enrollment_codes WHERE code_hash = ?",
                (hashlib.sha256(code.encode()).hexdigest(),),
            ).fetchone()
            raw_code = connection.execute(
                "SELECT 1 FROM worker_enrollment_codes WHERE code_hash = ?",
                (code,),
            ).fetchone()
        return {
            "code_issued": coded.status_code == 201 and bool(code),
            "exchange_ok": exchanged.status_code == 201 and bool(token),
            "reuse_rejected": reused.status_code == 403,
            "claim_before_revoke": claimed.status_code == 200,
            "renew_before_revoke": renewed.status_code == 200,
            "revoke_ok": revoked.status_code == 200,
            "claim_after_revoke": claim_after.status_code == 200,
            "renew_after_revoke": renew_after.status_code == 200,
            "cleanup_pending": status is not None and status[0] == "cancel_requested",
            "raw_code_absent": code_row is not None and raw_code is None,
        }
