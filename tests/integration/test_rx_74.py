"""RX-74: APK bytes and build metadata survive API restart and are served to other processes."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import sqlite3
import zipfile
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest

from aiqa.api.app import create_app
from aiqa.api.app_builds import pin_build_hash
from aiqa.config import WorkerClientSettings, load_settings
from aiqa.domain.projects import bind_store, create_project
from aiqa.environments import app_builds as app_builds_module
from aiqa.environments.app_builds import (
    ApkInspectionSpec,
    FixtureInstallDriver,
    get_app_build,
    load_app_build_bytes,
    register_app_build,
)
from aiqa.store.artifacts import ArtifactRejected
from aiqa.store.database import migrate_store
from aiqa.store.models import Actor, ProjectCreate
from aiqa.worker.android_jobs import (
    AppInstallHandler,
    build_android_support_handlers,
    http_app_build_fetcher,
)
from aiqa.worker.http_client import SyncASGITransport, WorkerHttpClient, WorkerHttpError
from ux_support import session


def _apk_bytes(marker: bytes = b"dex") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("AndroidManifest.xml", b"<manifest/>")
        archive.writestr("classes.dex", marker)
    return buffer.getvalue()


def _digest(body: bytes) -> str:
    return "sha256:" + hashlib.sha256(body).hexdigest()


def _make_app(root: Path):
    return create_app(
        load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)})
    )


def _project(app, name: str) -> str:
    owner = Actor(uuid4(), None, True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        created = create_project(owner, ProjectCreate("앱", name, "durable", "android"))
    store.close()
    return str(created.project_id)


def _upload(client, project_id: str, headers: dict[str, str], body: bytes, key: str):
    return client.post(
        f"/api/v1/projects/{project_id}/app-builds",
        json={
            "filename": "demo.apk",
            "body_base64": base64.b64encode(body).decode("ascii"),
            "declared_length": len(body),
            "tool_path": "fixture-meta",
        },
        headers={**headers, "Idempotency-Key": key},
    )


async def _enroll(client, project_id: str, headers: dict[str, str], key: str) -> str:
    response = await client.post(
        f"/api/v1/projects/{project_id}/worker-enrollments",
        json={"worker_id": str(uuid4()), "purpose": "resource_probe"},
        headers={**headers, "Idempotency-Key": key},
    )
    assert response.status_code == 201, response.text
    return response.json()["credential"]


async def _phase_upload(app, project_id: str, body: bytes) -> dict[str, object]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        headers = await session(client, project_id)
        token = await _enroll(client, project_id, headers, "rx74-enroll")
        first = await _upload(client, project_id, headers, body, "rx74-up-1")
        assert first.status_code == 201, first.text
        # Concurrent duplicate requests with different idempotency keys.
        dupes = await asyncio.gather(
            _upload(client, project_id, headers, body, "rx74-up-2"),
            _upload(client, project_id, headers, body, "rx74-up-3"),
        )
        return {
            "token": token,
            "first": first.json(),
            "dupes": [item.json() for item in dupes],
            "dupe_status": [item.status_code for item in dupes],
        }


async def _phase_after_restart(app, project_id: str, other_project: str, token: str, build_id: str, body: bytes):
    transport = httpx.ASGITransport(app=app)
    bearer = {"Authorization": f"Bearer {token}"}
    seen: dict[str, object] = {}
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        listed = await client.get(f"/api/v1/projects/{project_id}/app-builds", headers=bearer)
        seen["list_status"] = listed.status_code
        seen["list"] = listed.json()
        meta = await client.get(f"/api/v1/projects/{project_id}/app-builds/{build_id}", headers=bearer)
        seen["meta_status"] = meta.status_code
        seen["meta"] = meta.json()
        content = await client.get(f"/api/v1/projects/{project_id}/app-builds/{build_id}/content", headers=bearer)
        seen["content_status"] = content.status_code
        seen["content_bytes"] = content.content
        seen["content_hash_header"] = content.headers.get("content-hash")
        seen["x_content_hash_header"] = content.headers.get("x-content-hash")
        # Worker token for project A must not read through project B.
        cross_worker = await client.get(
            f"/api/v1/projects/{other_project}/app-builds/{build_id}/content", headers=bearer
        )
        seen["cross_worker_status"] = cross_worker.status_code
        # Unauthenticated callers are refused.
        seen["anon_status"] = (
            await client.get(f"/api/v1/projects/{project_id}/app-builds/{build_id}/content")
        ).status_code
        bad = await client.get(
            f"/api/v1/projects/{project_id}/app-builds/{build_id}/content",
            headers={"Authorization": "Bearer not-a-token"},
        )
        seen["bad_token_status"] = bad.status_code
        # Browser session of project A (new session after restart).
        headers = await session(client, project_id)
        sess_meta = await client.get(f"/api/v1/projects/{project_id}/app-builds/{build_id}")
        seen["session_meta_status"] = sess_meta.status_code
        sess_content = await client.get(f"/api/v1/projects/{project_id}/app-builds/{build_id}/content")
        seen["session_content_bytes"] = sess_content.content
        del headers
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as other:
        await session(other, other_project)
        cross_session = await other.get(f"/api/v1/projects/{other_project}/app-builds/{build_id}/content")
        seen["cross_session_status"] = cross_session.status_code
        cross_meta = await other.get(f"/api/v1/projects/{other_project}/app-builds/{build_id}")
        seen["cross_meta_status"] = cross_meta.status_code
        cross_list = await other.get(f"/api/v1/projects/{other_project}/app-builds")
        seen["cross_list"] = cross_list.json()
        foreign = await other.get(f"/api/v1/projects/{project_id}/app-builds/{build_id}/content")
        seen["foreign_scope_status"] = foreign.status_code
    return seen


def test_rx_74_upload_survives_restart_and_serves_bytes(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    app = _make_app(root)
    project_id = _project(app, "rx74-a")
    other_project = _project(app, "rx74-b")
    body = _apk_bytes()
    digest = _digest(body)
    app_builds_module._known.clear()

    uploaded = asyncio.run(_phase_upload(app, project_id, body))
    first = uploaded["first"]
    assert first["replayed"] is False
    assert first["body_hash"] == digest
    assert first["content_hash"] == digest
    assert first["ready"] is True
    build_id = first["build_id"]

    # Duplicate bodies replay the same build and receipt; exactly one durable row remains.
    for dupe in uploaded["dupes"]:
        assert dupe["build_id"] == build_id
        assert dupe["job_id"] == first["job_id"]
        assert dupe["replayed"] is True
    assert uploaded["dupe_status"] == [201, 201]
    database = root / "db" / "aiqa.sqlite"
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            "SELECT build_id, content_hash, object_key, byte_length, ready, package_name, inspect_job_id "
            "FROM app_builds WHERE project_id = ?",
            (project_id,),
        ).fetchall()
    assert len(rows) == 1
    row = rows[0]
    assert row[0] == build_id
    assert row[1] == digest
    assert row[2] is not None and row[2].endswith(".apk")
    assert row[3] == len(body)
    assert row[4] == 1
    assert row[5] == "com.example.app"
    assert row[6] == first["job_id"]

    # The APK file is on disk under the artifact root with matching bytes and hash.
    stored = app.state.open_store().config.artifacts_dir / row[2]
    assert stored.read_bytes() == body
    assert _digest(stored.read_bytes()) == digest

    # Simulate API restart: process cache is gone and a fresh app opens the same store.
    app_builds_module._known.clear()
    assert get_app_build(UUID(project_id), UUID(build_id)) is None
    restarted = _make_app(root)
    seen = asyncio.run(
        _phase_after_restart(restarted, project_id, other_project, uploaded["token"], build_id, body)
    )

    assert seen["list_status"] == 200
    assert [item["build_id"] for item in seen["list"]["items"]] == [build_id]
    assert seen["list"]["items"][0]["content_hash"] == digest
    assert seen["meta_status"] == 200
    assert seen["meta"]["build_id"] == build_id
    assert seen["meta"]["content_hash"] == digest
    assert seen["meta"]["package_name"] == "com.example.app"
    assert seen["meta"]["filename"] == "demo.apk"
    assert seen["content_status"] == 200
    assert seen["content_bytes"] == body
    assert seen["content_hash_header"] == digest
    assert seen["x_content_hash_header"] == digest
    assert seen["session_meta_status"] == 200
    assert seen["session_content_bytes"] == body
    assert seen["cross_worker_status"] == 404
    assert seen["cross_session_status"] == 404
    assert seen["cross_meta_status"] == 404
    assert seen["cross_list"] == {"items": []}
    assert seen["foreign_scope_status"] == 404
    assert seen["anon_status"] == 401
    assert seen["bad_token_status"] == 401

    # Direct store read from a fresh connection (other process view) returns the same bytes.
    store = restarted.state.open_store()
    migrate_store(store)
    with store.transaction() as connection:
        loaded = load_app_build_bytes(connection, store.config.artifacts_dir, UUID(project_id), UUID(build_id))
        assert loaded == (body, digest)
        assert load_app_build_bytes(connection, store.config.artifacts_dir, UUID(other_project), UUID(build_id)) is None
        view = get_app_build(UUID(project_id), UUID(build_id), connection=connection)
    store.close()
    assert view is not None and view.content_hash == digest and view.ready is True


def test_rx_74_incomplete_corrupt_and_heal(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    app = _make_app(root)
    project_id = _project(app, "rx74-c")
    body = _apk_bytes(b"corrupt-case")
    digest = _digest(body)
    app_builds_module._known.clear()

    async def flow() -> dict[str, object]:
        transport = httpx.ASGITransport(app=app)
        seen: dict[str, object] = {}
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            headers = await session(client, project_id)
            token = await _enroll(client, project_id, headers, "rx74-c-enroll")
            bearer = {"Authorization": f"Bearer {token}"}
            created = await _upload(client, project_id, headers, body, "rx74-c-1")
            assert created.status_code == 201, created.text
            build_id = created.json()["build_id"]
            database = root / "db" / "aiqa.sqlite"
            with sqlite3.connect(database) as connection:
                object_key = connection.execute(
                    "SELECT object_key FROM app_builds WHERE project_id = ? AND build_id = ?",
                    (project_id, build_id),
                ).fetchone()[0]
                # Incomplete upload: a pinned row exists but nothing was published.
                incomplete = str(uuid4())
                connection.execute(
                    "INSERT INTO app_builds (project_id, build_id, content_hash) VALUES (?, ?, ?)",
                    (project_id, incomplete, "sha256:" + "0" * 64),
                )
            seen["incomplete_meta"] = (
                await client.get(f"/api/v1/projects/{project_id}/app-builds/{incomplete}", headers=bearer)
            ).status_code
            seen["incomplete_content"] = (
                await client.get(f"/api/v1/projects/{project_id}/app-builds/{incomplete}/content", headers=bearer)
            ).status_code
            seen["missing_row"] = (
                await client.get(f"/api/v1/projects/{project_id}/app-builds/{uuid4()}/content", headers=bearer)
            ).status_code
            seen["bad_id"] = (
                await client.get(f"/api/v1/projects/{project_id}/app-builds/not-a-uuid/content", headers=bearer)
            ).status_code
            listed = await client.get(f"/api/v1/projects/{project_id}/app-builds", headers=bearer)
            seen["listed_ids"] = [item["build_id"] for item in listed.json()["items"]]

            path = app.state.open_store().config.artifacts_dir / object_key
            path.write_bytes(b"tampered")
            tampered = await client.get(
                f"/api/v1/projects/{project_id}/app-builds/{build_id}/content", headers=bearer
            )
            seen["corrupt_status"] = tampered.status_code
            seen["corrupt_leaked"] = tampered.content == b"tampered"
            reupload_corrupt = await _upload(client, project_id, headers, body, "rx74-c-2")
            seen["reupload_corrupt_status"] = reupload_corrupt.status_code

            path.unlink()
            missing = await client.get(
                f"/api/v1/projects/{project_id}/app-builds/{build_id}/content", headers=bearer
            )
            seen["missing_file_status"] = missing.status_code
            healed = await _upload(client, project_id, headers, body, "rx74-c-3")
            seen["heal_status"] = healed.status_code
            seen["heal_build"] = healed.json()["build_id"]
            again = await client.get(
                f"/api/v1/projects/{project_id}/app-builds/{build_id}/content", headers=bearer
            )
            seen["heal_content"] = again.content
            seen["build_id"] = build_id
        return seen

    seen = asyncio.run(flow())
    assert seen["incomplete_meta"] == 404
    assert seen["incomplete_content"] == 404
    assert seen["missing_row"] == 404
    assert seen["bad_id"] == 404
    assert seen["listed_ids"] == [seen["build_id"]]
    assert seen["corrupt_status"] == 409
    assert seen["corrupt_leaked"] is False
    assert seen["reupload_corrupt_status"] == 409
    assert seen["missing_file_status"] == 409
    assert seen["heal_status"] == 201
    assert seen["heal_build"] == seen["build_id"]
    assert seen["heal_content"] == body
    assert digest.startswith("sha256:")


def test_rx_74_install_enqueue_does_not_wipe_published_build(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    app = _make_app(root)
    project_id = _project(app, "rx74-d")
    body = _apk_bytes(b"pin-case")
    digest = _digest(body)
    app_builds_module._known.clear()
    store = app.state.open_store()
    migrate_store(store)
    with store.transaction() as connection:
        _, view = register_app_build(
            ApkInspectionSpec(UUID(project_id), "demo.apk", body, len(body)),
            tool_path="fixture-meta",
            connection=connection,
            artifacts_dir=store.config.artifacts_dir,
        )
    with store.transaction() as connection:
        # Install enqueue with a wrong client hash must not wipe the hash or object key.
        pin_build_hash(connection, UUID(project_id), view.build_id, "sha256:" + "f" * 64)
        row = connection.execute(
            "SELECT content_hash, object_key FROM app_builds WHERE project_id = ? AND build_id = ?",
            (project_id, str(view.build_id)),
        ).fetchone()
        assert row[0] == digest and row[1] is not None
        assert load_app_build_bytes(
            connection, store.config.artifacts_dir, UUID(project_id), view.build_id
        ) == (body, digest)
        # A pin row for an unpublished build id stays invisible as a build.
        ghost = uuid4()
        pin_build_hash(connection, UUID(project_id), ghost, "sha256:" + "e" * 64)
        assert get_app_build(UUID(project_id), ghost, connection=connection) is None
        assert load_app_build_bytes(connection, store.config.artifacts_dir, UUID(project_id), ghost) is None
        (store.config.artifacts_dir / row[1]).write_bytes(b"x")
        with pytest.raises(ArtifactRejected):
            load_app_build_bytes(connection, store.config.artifacts_dir, UUID(project_id), view.build_id)
    store.close()


def _claim(project_id: str, build_id: str, digest: str, *, serial: str, build_hash: str | None = None) -> dict:
    limits = {
        "kind": "app_install",
        "build_id": build_id,
        "build_hash": digest if build_hash is None else build_hash,
        "content_hash": digest,
        "policy": "force_reinstall",
        "serial": serial,
        "confirmed": True,
        "resource_id": str(uuid4()),
    }
    return {
        "project_id": project_id,
        "snapshot": {"purpose": "app_install", "limits": json.dumps(limits), "serial": serial},
    }


def test_rx_74_worker_fetches_build_over_authenticated_http(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    app = _make_app(root)
    project_id = _project(app, "rx74-e")
    other_project = _project(app, "rx74-f")
    body = _apk_bytes(b"worker-case")
    digest = _digest(body)
    app_builds_module._known.clear()

    uploaded = asyncio.run(_phase_upload(app, project_id, body))
    build_id = uploaded["first"]["build_id"]
    token = uploaded["token"]

    # The worker is a separate process: no API memory object is shared with it.
    app_builds_module._known.clear()
    settings = WorkerClientSettings(base_url="https://127.0.0.1", token=token)
    with WorkerHttpClient(settings, transport=SyncASGITransport(_make_app(root))) as client:
        meta = client.get_app_build(project_id, build_id)
        assert meta["content_hash"] == digest
        fetched, fetched_hash = client.fetch_app_build_content(project_id, build_id, expected_hash=digest)
        assert fetched == body and fetched_hash == digest
        with pytest.raises(WorkerHttpError):
            client.fetch_app_build_content(project_id, build_id, expected_hash="sha256:" + "1" * 64)
        with pytest.raises(WorkerHttpError) as cross:
            client.fetch_app_build_content(other_project, build_id)
        assert cross.value.status_code == 404

        serial = "emulator-5580"
        driver = FixtureInstallDriver(installed=set())
        _, handler = build_android_support_handlers(
            adb_path=Path(r"C:\sdk\adb.exe"),
            serial=serial,
            install_driver=driver,
            build_fetcher=http_app_build_fetcher(client),
        )
        ok = handler.handle(_claim(project_id, build_id, digest, serial=serial))
        assert ok.outcome == "completed"
        assert driver.install_calls == 1
        assert driver.unapproved_mutations == 0

        wrong = "sha256:" + "2" * 64
        mismatch = handler.handle(_claim(project_id, build_id, wrong, serial=serial))
        assert mismatch.outcome == "error"
        assert driver.install_calls == 1

        split = handler.handle(_claim(project_id, build_id, digest, serial=serial, build_hash=wrong))
        assert split.outcome == "error"
        assert driver.install_calls == 1

        unknown = handler.handle(_claim(project_id, str(uuid4()), digest, serial=serial))
        assert unknown.outcome == "error"
        assert driver.install_calls == 1

    # Without any fetcher a process that has no memory object fails closed.
    bare = AppInstallHandler(expected_serial="emulator-5580", driver=FixtureInstallDriver(installed=set()))
    result = bare.handle(_claim(project_id, build_id, digest, serial="emulator-5580"))
    assert result.outcome == "error"
    assert bare.driver.install_calls == 0
