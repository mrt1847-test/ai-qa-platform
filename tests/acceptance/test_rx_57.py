"""RX-57: explicit Android install/reset with digest, cancel, lease, and idempotency gates."""

from __future__ import annotations

import asyncio
import base64
import io
import json
import sqlite3
import subprocess
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import httpx

from aiqa.api.app import create_app
from aiqa.config import load_settings
from aiqa.domain.projects import bind_store, create_project
from aiqa.environments.app_builds import (
    ApkInspectionSpec,
    AppBuildView,
    AppPreparationSpec,
    FixtureInstallDriver,
    prepare_app,
    register_app_build,
)
from aiqa.store.database import migrate_store
from aiqa.store.models import Actor, ProjectCreate
from aiqa.worker.android_jobs import AppInstallHandler
from ux_support import session

_BROWSERS = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
)

_SERIAL = "emulator-5580"


def _apk_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("AndroidManifest.xml", b"<manifest/>")
        archive.writestr("classes.dex", b"dex")
    return buffer.getvalue()


def test_prepare_app_gates_without_unapproved_mutations() -> None:
    driver = FixtureInstallDriver(installed=set())
    build = AppBuildView(
        uuid4(),
        "app.apk",
        "com.example.app",
        "1.0.0",
        "24",
        "x86_64",
        "ok",
        True,
        "sha256:good",
    )
    resource = uuid4()
    project = uuid4()

    wrong = prepare_app(
        AppPreparationSpec(project, resource, build.build_id, "sha256:bad", _SERIAL, "force_reinstall", True),
        build=build,
        driver=driver,
        enrolled_serial=_SERIAL,
        lease_held=True,
    )
    assert wrong.ready is False and wrong.reason == "digest_mismatch"
    assert wrong.install_calls == 0 and driver.unapproved_mutations == 0

    cancelled = prepare_app(
        AppPreparationSpec(project, resource, build.build_id, "sha256:good", _SERIAL, "force_reinstall", True),
        build=build,
        driver=driver,
        enrolled_serial=_SERIAL,
        lease_held=True,
        cancel_requested=True,
    )
    assert cancelled.ready is False and cancelled.state == "cancelled"
    assert cancelled.install_calls == 0

    driver.fail_install = True
    failed = prepare_app(
        AppPreparationSpec(project, resource, build.build_id, "sha256:good", _SERIAL, "force_reinstall", True),
        build=build,
        driver=driver,
        enrolled_serial=_SERIAL,
        lease_held=True,
    )
    assert failed.ready is False and failed.state == "cleanup_pending"
    assert failed.install_calls == 1 and driver.unapproved_mutations == 0

    driver.fail_install = False
    ok = prepare_app(
        AppPreparationSpec(project, resource, build.build_id, "sha256:good", _SERIAL, "force_reinstall", True),
        build=build,
        driver=driver,
        enrolled_serial=_SERIAL,
        lease_held=True,
    )
    assert ok.ready is True and ok.install_calls == 1

    default = prepare_app(
        AppPreparationSpec(project, resource, build.build_id, "sha256:good", _SERIAL, "use_installed", False),
        build=build,
        driver=driver,
        enrolled_serial=_SERIAL,
        lease_held=True,
    )
    assert default.ready is True and default.install_calls == 0 and default.reset_calls == 0
    assert driver.unapproved_mutations == 0

    handler = AppInstallHandler(_SERIAL, build, driver, lease_held=True)
    handled = handler.handle(
        {
            "project_id": str(project),
            "snapshot": {
                "purpose": "app_install",
                "serial": _SERIAL,
                "limits": {
                    "build_id": str(build.build_id),
                    "resource_id": str(resource),
                    "content_hash": "sha256:good",
                    "policy": "use_installed",
                    "serial": _SERIAL,
                    "confirmed": False,
                },
            },
        }
    )
    assert handled.evidence_events[0]["install_calls"] == 0
    assert handled.evidence_events[0]["unapproved_mutations"] == 0


def test_rx_57_app_install_api_and_ui(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    app = create_app(
        load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)})
    )
    owner = Actor(uuid4(), None, True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("설치", "rx57", "install", "android"))
    store.close()
    project_id = str(project.project_id)
    database = root / "db" / "aiqa.sqlite"
    body = _apk_bytes()
    register_app_build(
        ApkInspectionSpec(project.project_id, "demo.apk", body, len(body)),
        tool_path="fixture-meta",
    )

    observed = asyncio.run(_flow(app, project_id, database, body))
    browser_ok = _browser_shot(tmp_path, observed["page_html"])

    assert observed["wrong_digest_ready"] is False
    assert observed["wrong_digest_installs"] == 0
    assert observed["cancel_ready"] is False
    assert observed["cancel_installs"] == 0
    assert observed["fail_ready"] is False
    assert observed["fail_state"] == "cleanup_pending"
    assert observed["ok_ready"] is True
    assert observed["ok_installs"] == 1
    assert observed["replay_installs"] == 0
    assert observed["replayed"] is True
    assert observed["driver_installs"] == 2  # fail attempt + success
    assert observed["unapproved"] == 0
    assert observed["lease_blocked_ready"] is False
    assert observed["page_has_confirm"] is True
    assert observed["page_has_installs"] is True
    assert browser_ok is True


async def _flow(app: object, project_id: str, database: Path, apk: bytes) -> dict[str, object]:
    transport = httpx.ASGITransport(app=app)
    origin = "http://127.0.0.1"
    async with httpx.AsyncClient(transport=transport, base_url=origin) as client:
        headers = await session(client, project_id)
        worker_id = str(uuid4())
        headers["Idempotency-Key"] = "rx57-enroll"
        enrolled = await client.post(
            f"/api/v1/projects/{project_id}/worker-enrollments",
            json={"worker_id": worker_id, "purpose": "resource_probe"},
            headers=headers,
        )
        assert enrolled.status_code == 201, enrolled.text
        token = enrolled.json()["credential"]
        inventory = await client.post(
            "/api/v1/worker/inventory",
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "rx57-inv"},
            json={
                "project_id": project_id,
                "native_id": _SERIAL,
                "target_kind": "android",
                "state": "ready",
                "os_build": "Android 16 API 36",
                "geometry": "720x1600@0",
                "permissions": json.dumps(["android_emulator"]),
                "ime": "none",
                "observed_at": datetime.now(timezone.utc).isoformat(),
                "display_name": "RX57 에뮬레이터",
                "raw_handle": None,
            },
        )
        assert inventory.status_code == 200, inventory.text
        resource_id = inventory.json()["physical_key_id"]
        heartbeat = await client.post(
            "/api/v1/worker/heartbeats",
            headers={"Authorization": f"Bearer {token}"},
            json={"boot_id": "rx57-boot"},
        )
        assert heartbeat.status_code == 200, heartbeat.text

        headers["Idempotency-Key"] = "rx57-register"
        registered = await client.post(
            f"/api/v1/projects/{project_id}/app-builds",
            json={
                "filename": "demo.apk",
                "body_base64": base64.b64encode(apk).decode("ascii"),
                "declared_length": len(apk),
                "tool_path": "fixture-meta",
            },
            headers=headers,
        )
        # Same bytes already registered in-process; API may create another entry with same hash key → replay
        assert registered.status_code == 201, registered.text
        build_id = registered.json()["build_id"]
        digest = registered.json()["body_hash"]

        headers["Idempotency-Key"] = "rx57-nolease"
        no_lease = await client.post(
            f"/api/v1/resources/{resource_id}/app-installs",
            params={"project_id": project_id},
            json={
                "provider": "fixture",
                "build_id": build_id,
                "content_hash": digest,
                "policy": "force_reinstall",
                "serial": _SERIAL,
                "confirmed": True,
            },
            headers=headers,
        )
        assert no_lease.status_code == 201, no_lease.text
        lease_blocked = no_lease.json()

        expires = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        lease_job = str(uuid4())
        with sqlite3.connect(database) as connection:
            connection.execute(
                """
                INSERT INTO jobs (
                    project_id, job_id, purpose, recording_id, case_run_id,
                    payload_hash, source_refs, limits, status
                ) VALUES (?, ?, 'resource_probe', NULL, NULL, 'lease', ?, '{}', 'running')
                """,
                (project_id, lease_job, json.dumps([resource_id])),
            )
            connection.execute(
                """
                INSERT INTO leases (
                    project_id, job_id, generation, worker_id, physical_key_id, expires_at
                ) VALUES (?, ?, 1, ?, ?, ?)
                """,
                (project_id, lease_job, worker_id, resource_id, expires),
            )
            connection.commit()

        driver: FixtureInstallDriver = app.state.fixture_install_driver
        headers["Idempotency-Key"] = "rx57-bad-digest"
        bad = await client.post(
            f"/api/v1/resources/{resource_id}/app-installs",
            params={"project_id": project_id},
            json={
                "provider": "fixture",
                "build_id": build_id,
                "content_hash": "sha256:wrong",
                "policy": "force_reinstall",
                "serial": _SERIAL,
                "confirmed": True,
            },
            headers=headers,
        )
        bad_body = bad.json()
        assert bad.status_code == 201, bad.text

        headers["Idempotency-Key"] = "rx57-cancel"
        cancelled = await client.post(
            f"/api/v1/resources/{resource_id}/app-installs",
            params={"project_id": project_id},
            json={
                "provider": "fixture",
                "build_id": build_id,
                "content_hash": digest,
                "policy": "force_reinstall",
                "serial": _SERIAL,
                "confirmed": True,
                "cancel_requested": True,
            },
            headers=headers,
        )
        cancel_body = cancelled.json()
        assert cancelled.status_code == 201, cancelled.text

        driver.fail_install = True
        headers["Idempotency-Key"] = "rx57-fail"
        failed = await client.post(
            f"/api/v1/resources/{resource_id}/app-installs",
            params={"project_id": project_id},
            json={
                "provider": "fixture",
                "build_id": build_id,
                "content_hash": digest,
                "policy": "force_reinstall",
                "serial": _SERIAL,
                "confirmed": True,
            },
            headers=headers,
        )
        fail_body = failed.json()
        assert failed.status_code == 201, failed.text
        driver.fail_install = False

        headers["Idempotency-Key"] = "rx57-ok"
        ok = await client.post(
            f"/api/v1/resources/{resource_id}/app-installs",
            params={"project_id": project_id},
            json={
                "provider": "fixture",
                "build_id": build_id,
                "content_hash": digest,
                "policy": "force_reinstall",
                "serial": _SERIAL,
                "confirmed": True,
            },
            headers=headers,
        )
        ok_body = ok.json()
        assert ok.status_code == 201, ok.text

        headers["Idempotency-Key"] = "rx57-ok"
        again = await client.post(
            f"/api/v1/resources/{resource_id}/app-installs",
            params={"project_id": project_id},
            json={
                "provider": "fixture",
                "build_id": build_id,
                "content_hash": digest,
                "policy": "force_reinstall",
                "serial": _SERIAL,
                "confirmed": True,
            },
            headers=headers,
        )
        again_body = again.json()
        assert again.status_code == 201, again.text

        page = await client.get(f"/ui/projects/{project_id}/app-builds")
        assert page.status_code == 200, page.text
        return {
            "wrong_digest_ready": bad_body["ready"],
            "wrong_digest_installs": bad_body["install_calls"],
            "cancel_ready": cancel_body["ready"],
            "cancel_installs": cancel_body["install_calls"],
            "fail_ready": fail_body["ready"],
            "fail_state": fail_body["state"],
            "ok_ready": ok_body["ready"],
            "ok_installs": ok_body["install_calls"],
            "replay_installs": again_body["install_calls"],
            "replayed": again_body["replayed"],
            "driver_installs": driver.install_calls,
            "unapproved": driver.unapproved_mutations,
            "lease_blocked_ready": lease_blocked["ready"],
            "page_has_confirm": "확인했습니다" in page.text and "force_reinstall" in page.text,
            "page_has_installs": "설치 작업" in page.text and "cleanup_pending" in page.text,
            "page_html": page.text,
        }


def _browser_shot(tmp_path: Path, html: str) -> bool:
    browser = next((path for path in _BROWSERS if path.exists()), None)
    if browser is None:
        return False
    page = tmp_path / "rx57.html"
    shot = tmp_path / "rx57.png"
    page.write_text(html, encoding="utf-8")
    completed = subprocess.run(
        [
            str(browser),
            "--headless=new",
            "--disable-gpu",
            f"--screenshot={shot}",
            page.resolve().as_uri(),
        ],
        check=False,
        capture_output=True,
        timeout=60,
    )
    return completed.returncode == 0 and shot.exists() and shot.stat().st_size > 1024
