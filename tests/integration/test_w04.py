"""W04-01: the API process owns a migrated SQLite file and a restarted process can read it."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

import httpx

from aiqa.api.app import create_app
from aiqa.api.auth import authorize_browser, authorize_worker, bootstrap_browser_session
from aiqa.config import load_settings
from aiqa.domain.projects import bind_store, create_project, next_commit_seq
from aiqa.security.secrets import bind_secret_store, discard_os_secret, put_secret, resolve_secret
from aiqa.store.database import StorageConfig, migrate_store, open_store
from aiqa.store.models import Actor, ProjectCreate, RuntimeScope, SecretRef

REPO = Path(__file__).resolve().parents[2]
_PROJECT_ID = "proj-restart"
_PROJECT_NAME = "kept"


def _worker_opens_db() -> bool:
    script = """
import sqlite3
from unittest.mock import patch
with patch("sqlite3.connect", side_effect=AssertionError("worker db")):
    import aiqa.worker
    import aiqa.worker.isolated_web
print("closed")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode != 0 or "closed" not in result.stdout


def _run_store(local: Path, mode: str) -> subprocess.CompletedProcess[str]:
    script = local.parent / f"store_{mode}.py"
    script.write_text(
        """
import json
import sqlite3
import sys

from aiqa.api.app import create_app
from aiqa.config import load_settings
from aiqa.store.database import migrate_store

mode = sys.argv[1]
settings = load_settings(None)
app = create_app(settings)
store = app.state.open_store()
revision = migrate_store(store)
if mode == "write":
    store.put_project_row("proj-restart", "kept")
    orphan_rejected = False
    try:
        store.put_note("missing-project", "nope")
    except sqlite3.IntegrityError:
        orphan_rejected = True
    store.close()
    print(json.dumps({"revision": revision.id, "orphan_rejected": orphan_rejected}))
else:
    row = store.get_project_row("proj-restart")
    print(json.dumps({
        "name": None if row is None else row[1],
        "foreign_keys": store.foreign_keys_enabled(),
        "journal_mode": store.journal_mode(),
        "in_transaction": store.in_transaction(),
        "revision": revision.id,
        "database_path": str(store.config.database_path),
        "artifacts_dir": str(store.config.artifacts_dir),
        "spool_dir": str(store.config.spool_dir),
    }))
    store.close()
""",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["LOCALAPPDATA"] = str(local)
    env.pop("AIQA_RUNTIME_ROOT", None)
    env["AIQA_HOST"] = "127.0.0.1"
    env["AIQA_PORT"] = "8000"
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(script), mode],
        cwd=local.parent,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_w04_01(tmp_path: Path) -> None:
    assert callable(open_store)
    assert callable(migrate_store)
    local = tmp_path / "LocalAppData"
    untouched = tmp_path / "untouched-local"
    settings = load_settings({"LOCALAPPDATA": str(untouched), "AIQA_HOST": "127.0.0.1"})
    app = create_app(settings)
    connects = {"n": 0}
    real_connect = sqlite3.connect

    def track_connect(*args, **kwargs):
        connects["n"] += 1
        return real_connect(*args, **kwargs)

    async def read_health() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            return await client.get("/api/v1/health")

    with patch("sqlite3.connect", track_connect):
        health = asyncio.run(read_health())
    assert health.status_code == 200
    assert health.json() == {"status": "ok", "component": "api"}
    assert connects["n"] == 0
    assert not (untouched / "AIQA").exists()

    refused = False
    try:
        StorageConfig.from_settings(
            load_settings(
                {
                    "AIQA_HOST": "127.0.0.1",
                    "AIQA_RUNTIME_ROOT": r"C:\Users\example\OneDrive\AIQA",
                }
            )
        )
    except Exception:
        refused = True
    assert refused

    written = _run_store(local, "write")
    assert written.returncode == 0, written.stderr
    write_payload = json.loads(written.stdout)
    assert write_payload["orphan_rejected"] is True
    assert write_payload["revision"]

    read = _run_store(local, "read")
    assert read.returncode == 0, read.stderr
    payload = json.loads(read.stdout)
    root = local / "AIQA"
    assert Path(payload["database_path"]) == root / "db" / "aiqa.sqlite"
    assert Path(payload["artifacts_dir"]) == root / "artifacts"
    assert Path(payload["spool_dir"]) == root / "spool"
    assert Path(payload["artifacts_dir"]).is_dir()
    assert Path(payload["spool_dir"]).is_dir()
    assert payload["journal_mode"] == "wal"
    assert payload["in_transaction"] is False
    assert REPO not in Path(payload["database_path"]).resolve().parents

    observed = {
        "foreign_keys": payload["foreign_keys"],
        "restart_preserves_row": payload["name"] == _PROJECT_NAME
        and payload["revision"] == write_payload["revision"],
        "worker_opens_db": _worker_opens_db(),
    }
    assert observed == {
        "foreign_keys": 1,
        "restart_preserves_row": True,
        "worker_opens_db": False,
    }


def _project_body(name: str, key: str) -> dict[str, object]:
    return {
        "name": name,
        "key": key,
        "description": f"{name} description",
        "target": "web",
        "actor": {
            "actor_id": "11111111-1111-4111-8111-111111111111",
            "project_scope": None,
            "is_local_owner": True,
        },
    }


def test_w04_02(tmp_path: Path) -> None:
    assert callable(create_project)
    assert callable(next_commit_seq)
    root = tmp_path / "runtime"
    settings = load_settings(
        {
            "AIQA_HOST": "127.0.0.1",
            "AIQA_PORT": "8000",
            "AIQA_RUNTIME_ROOT": str(root),
        }
    )
    app = create_app(settings)
    database = root / "db" / "aiqa.sqlite"

    async def run() -> tuple[httpx.Response, httpx.Response, httpx.Response, httpx.Response, httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            created_a = await client.post(
                "/api/v1/projects",
                json=_project_body("A", "key-a"),
                headers={"Origin":"http://127.0.0.1", "Idempotency-Key": "create-a"},
            )
            origin='http://127.0.0.1'
            nonce=await client.post('/api/v1/session/nonces',json={'origin':origin,'project_id':created_a.json()['project_id']},headers={'Origin':origin,'Idempotency-Key':'create-b-nonce'})
            boot=await client.post('/api/v1/session/bootstrap',json={'nonce':nonce.json()['nonce']},headers={'Origin':origin,'Idempotency-Key':'create-b-bootstrap'})
            auth={'Origin':origin,'X-CSRF-Token':boot.json()['csrf_token']}
            created_b = await client.post(
                "/api/v1/projects",
                json=_project_body("B", "key-b"),
                headers={**auth,"Idempotency-Key": "create-b"},
            )
            duplicate = await client.post(
                "/api/v1/projects",
                json=_project_body("A again", "key-a"),
                headers={**auth,"Idempotency-Key": "create-dup"},
            )
            audit_b = created_b.json()["audit_id"]
            project_a = created_a.json()["project_id"]
            cross = await client.get(f"/api/v1/projects/{project_a}/audits/{audit_b}")
            origin='http://127.0.0.1'
            issued=await client.post('/api/v1/session/nonces',json={'origin':origin,'project_id':project_a},headers={'Origin':origin,'Idempotency-Key':'cross-nonce'})
            booted=await client.post('/api/v1/session/bootstrap',json={'nonce':issued.json()['nonce']},headers={'Origin':origin,'Idempotency-Key':'cross-boot'})
            client.cookies.set('aiqa_session',booted.cookies['aiqa_session'])
            denied = await client.post(
                f"/api/v1/projects/{project_a}/audits/{audit_b}/links",
                json={"note": "other-project"},
                headers={"Idempotency-Key": "link-cross", "Origin":origin,"X-CSRF-Token":booted.json()["csrf_token"]},
            )
            return created_a, created_b, duplicate, cross, denied

    created_a, created_b, duplicate, cross, denied = asyncio.run(run())
    assert created_a.status_code == 201
    assert created_b.status_code == 201
    assert created_a.json()["name"] == "A"
    assert created_b.json()["commit_seq"] == 1
    assert denied.status_code == 404

    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        links = connection.execute("SELECT COUNT(*) FROM project_audit_links").fetchone()
        audits = connection.execute("SELECT COUNT(*) FROM project_audits").fetchone()
        clock = connection.execute(
            "SELECT commit_seq FROM project_commit_clock WHERE project_id = ?",
            (created_a.json()["project_id"],),
        ).fetchone()
        projects = connection.execute("SELECT COUNT(*) FROM projects").fetchone()
    assert projects is not None and int(projects[0]) == 2
    assert audits is not None and int(audits[0]) == 2
    assert clock is not None and int(clock[0]) == 1
    link_count = 0 if links is None else int(links[0])

    observed = {
        "duplicate_key_status": duplicate.status_code,
        "cross_project_denied": cross.status_code == 404,
        "rollback_partial_rows": link_count + max(int(clock[0]) - 1, 0),
    }
    assert observed == {
        "duplicate_key_status": 409,
        "cross_project_denied": True,
        "rollback_partial_rows": 0,
    }


def test_w04_03(tmp_path: Path) -> None:
    assert callable(bootstrap_browser_session)
    assert callable(authorize_browser)
    assert callable(authorize_worker)
    root = tmp_path / "runtime"
    settings = load_settings(
        {
            "AIQA_HOST": "127.0.0.1",
            "AIQA_PORT": "8000",
            "AIQA_RUNTIME_ROOT": str(root),
        }
    )
    connects = {"n": 0}
    real_connect = sqlite3.connect

    def track_connect(*args, **kwargs):
        connects["n"] += 1
        return real_connect(*args, **kwargs)

    with patch("sqlite3.connect", track_connect):
        app = create_app(settings)

        async def read_health() -> httpx.Response:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
                return await client.get("/api/v1/health")

        health = asyncio.run(read_health())
    assert health.status_code == 200
    assert connects["n"] == 0
    assert not root.exists()

    actor = Actor(
        actor_id=UUID("11111111-1111-4111-8111-111111111111"),
        project_scope=None,
        is_local_owner=True,
    )
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project_a = create_project(actor, ProjectCreate("A", "auth-a", "a", "web"))
        project_b = create_project(actor, ProjectCreate("B", "auth-b", "b", "web"))
    store.close()
    origin = "http://127.0.0.1:8000"

    async def run() -> dict[str, object]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            issued = await client.post(
                "/api/v1/session/nonces",
                json={"origin": origin, "project_id": str(project_a.project_id)},
                headers={"Idempotency-Key": "nonce-1", "Origin": origin},
            )
            nonce = issued.json()["nonce"]
            leaked = await client.post(
                f"/api/v1/session/bootstrap?nonce={nonce}",
                json={"nonce": nonce},
                headers={"Idempotency-Key": "boot-query", "Origin": origin},
            )
            booted = await client.post(
                "/api/v1/session/bootstrap",
                json={"nonce": nonce},
                headers={"Idempotency-Key": "boot-body", "Origin": origin},
            )
            reused = await client.post(
                "/api/v1/session/bootstrap",
                json={"nonce": nonce},
                headers={"Idempotency-Key": "boot-again", "Origin": origin},
            )
            csrf = booted.json()["csrf_token"]
            client.cookies.set("aiqa_session", booted.cookies["aiqa_session"])
            missing_csrf = await client.post(
                f"/api/v1/projects/{project_a.project_id}/approvals",
                json={},
                headers={"Idempotency-Key": "approve-csrf", "Origin": origin},
            )
            foreign = await client.post(
                f"/api/v1/projects/{project_a.project_id}/approvals",
                json={},
                headers={
                    "Idempotency-Key": "approve-origin",
                    "Origin": "https://evil.example",
                    "X-CSRF-Token": csrf,
                },
            )
            hidden = await client.post(
                f"/api/v1/projects/{project_b.project_id}/approvals",
                json={},
                headers={"Idempotency-Key": "approve-other", "Origin": origin, "X-CSRF-Token": csrf},
            )
            enrolled = await client.post(
                "/api/v1/workers/enrollments",
                json={"worker_id": "worker-1", "purpose": "recording"},
                headers={"Idempotency-Key": "enroll-1", "Origin": origin, "X-CSRF-Token": csrf},
            )
            token = enrolled.json()["token"]
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as worker:
            denied = await worker.post(
                f"/api/v1/projects/{project_a.project_id}/approvals",
                json={},
                headers={"Idempotency-Key": "approve-worker", "Authorization": f"Bearer {token}"},
            )
        return {
            "issued": issued,
            "nonce": nonce,
            "leaked": leaked,
            "booted": booted,
            "reused": reused,
            "csrf": csrf,
            "missing_csrf": missing_csrf,
            "foreign": foreign,
            "hidden": hidden,
            "enrolled": enrolled,
            "token": token,
            "denied": denied,
        }

    result = asyncio.run(run())
    assert result["issued"].status_code == 201
    assert result["leaked"].status_code == 400
    assert result["nonce"] not in result["leaked"].text
    assert "localStorage" not in result["booted"].text
    assert result["booted"].status_code == 201
    assert result["reused"].status_code == 401
    assert result["hidden"].status_code == 404
    assert result["enrolled"].status_code == 201
    assert "access-control-allow-origin" not in {name.lower() for name in result["foreign"].headers}
    database = root / "db" / "aiqa.sqlite"
    stored = database.read_bytes()
    assert result["nonce"].encode() not in stored
    assert str(result["csrf"]).encode() not in stored
    assert str(result["token"]).encode() not in stored

    issued_again = asyncio.run(_issue_expired(app, origin, project_a.project_id))
    assert issued_again == 401

    observed = {
        "csrf_rejected": result["missing_csrf"].status_code == 403,
        "foreign_origin_rejected": result["foreign"].status_code == 403,
        "worker_approval_denied": result["denied"].status_code == 403,
    }
    assert observed == {
        "csrf_rejected": True,
        "foreign_origin_rejected": True,
        "worker_approval_denied": True,
    }


async def _issue_expired(app: object, origin: str, project_id: UUID) -> int:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        issued = await client.post(
            "/api/v1/session/nonces",
            json={"origin": origin, "project_id": str(project_id)},
            headers={"Idempotency-Key": "nonce-old", "Origin": origin},
        )
        nonce = issued.json()["nonce"]
    database = app.state.settings.runtime_root / "db" / "aiqa.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE browser_nonces SET expires_at = ? WHERE used_at IS NULL",
            ("2000-01-01T00:00:00+00:00",),
        )
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        expired = await client.post(
            "/api/v1/session/bootstrap",
            json={"nonce": nonce},
            headers={"Idempotency-Key": "boot-old", "Origin": origin},
        )
    return expired.status_code


_PLAIN = "plain-secret-w04-04-VALUE-9f3a"
_ROTATED = "rotated-secret-w04-04-VALUE-c2e1"


def test_w04_04(tmp_path: Path) -> None:
    assert callable(put_secret)
    assert callable(resolve_secret)
    root = tmp_path / "runtime"
    settings = load_settings(
        {
            "AIQA_HOST": "127.0.0.1",
            "AIQA_PORT": "8000",
            "AIQA_RUNTIME_ROOT": str(root),
        }
    )
    app = create_app(settings)
    actor = Actor(
        actor_id=UUID("11111111-1111-4111-8111-111111111111"),
        project_scope=None,
        is_local_owner=True,
    )
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project_a = create_project(actor, ProjectCreate("A", "secret-a", "a", "web"))
        project_b = create_project(actor, ProjectCreate("B", "secret-b", "b", "web"))
    store.close()
    origin = "http://127.0.0.1:8000"
    messages: list[str] = []

    class _Grab(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            messages.append(record.getMessage())

    logger = logging.getLogger("aiqa.security.secrets")
    handler = _Grab()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    created_ref: SecretRef | None = None
    try:
        result = asyncio.run(_secret_http(app, origin, project_a.project_id))
        assert result["created"].status_code == 201, result["created"].text
        assert result["rotated"].status_code == 201, result["rotated"].text
        created = result["created"].json()
        rotated = result["rotated"].json()
        created_ref = SecretRef(
            project_id=project_a.project_id,
            ref_id=UUID(created["ref_id"]),
            revision=int(created["revision"]),
        )
        rotated_ref = SecretRef(
            project_id=project_a.project_id,
            ref_id=created_ref.ref_id,
            revision=int(rotated["revision"]),
        )
        read_text = result["read"].text
        store = app.state.open_store()
        migrate_store(store)
        with bind_secret_store(store):
            owned = resolve_secret(created_ref, RuntimeScope(project_id=project_a.project_id, actor_id=actor.actor_id))
            owned_new = resolve_secret(
                rotated_ref, RuntimeScope(project_id=project_a.project_id, actor_id=actor.actor_id)
            )
            try:
                resolve_secret(
                    rotated_ref, RuntimeScope(project_id=project_b.project_id, actor_id=actor.actor_id)
                )
                cross_ok = True
            except Exception:
                cross_ok = False
        store.close()
        assert owned.value == _PLAIN
        assert owned_new.value == _ROTATED
        blob = b""
        for path in (root / "db").glob("aiqa.sqlite*"):
            blob += path.read_bytes()
        observed = {
            "read_returns_plaintext": _PLAIN in read_text or _ROTATED in read_text,
            "db_has_plaintext": _PLAIN.encode() in blob or _ROTATED.encode() in blob,
            "cross_project_resolve": cross_ok,
            "revision_changes": int(rotated["revision"]) != int(created["revision"]),
        }
        assert observed == {
            "read_returns_plaintext": False,
            "db_has_plaintext": False,
            "cross_project_resolve": False,
            "revision_changes": True,
        }
        assert messages
        assert all(_PLAIN not in message and _ROTATED not in message for message in messages)
        assert _PLAIN not in result["created"].text
        assert _ROTATED not in result["rotated"].text
    finally:
        logger.removeHandler(handler)
        if created_ref is not None:
            store = app.state.open_store()
            try:
                with bind_secret_store(store):
                    discard_os_secret(created_ref)
                    discard_os_secret(
                        SecretRef(
                            project_id=created_ref.project_id,
                            ref_id=created_ref.ref_id,
                            revision=created_ref.revision + 1,
                        )
                    )
            finally:
                store.close()


async def _secret_http(app: object, origin: str, project_id: UUID) -> dict[str, httpx.Response]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        issued = await client.post(
            "/api/v1/session/nonces",
            json={"origin": origin, "project_id": str(project_id)},
            headers={"Idempotency-Key": "secret-nonce", "Origin": origin},
        )
        nonce = issued.json()["nonce"]
        booted = await client.post(
            "/api/v1/session/bootstrap",
            json={"nonce": nonce},
            headers={"Idempotency-Key": "secret-boot", "Origin": origin},
        )
        csrf = booted.json()["csrf_token"]
        client.cookies.set("aiqa_session", booted.cookies["aiqa_session"])
        headers = {"Origin": origin, "X-CSRF-Token": csrf}
        created = await client.post(
            f"/api/v1/projects/{project_id}/secret-refs",
            json={"name": "login", "value": _PLAIN},
            headers={**headers, "Idempotency-Key": "secret-create"},
        )
        ref_id = created.json()["ref_id"]
        rotated = await client.post(
            f"/api/v1/projects/{project_id}/secret-refs/{ref_id}/rotations",
            json={"value": _ROTATED},
            headers={**headers, "Idempotency-Key": "secret-rotate"},
        )
        read = await client.get(
            f"/api/v1/projects/{project_id}/secret-refs/{ref_id}",
            headers={**headers, "Idempotency-Key": "secret-read"},
        )
    return {"created": created, "rotated": rotated, "read": read}
