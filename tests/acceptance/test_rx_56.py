"""RX-56: read-only Android installed_apps probe, lease gate, wizard selection."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from aiqa.api.app import create_app
from aiqa.config import load_settings
from aiqa.domain.projects import bind_store, create_project
from aiqa.environments import android_observation
from aiqa.environments.usb_android import list_installed_apps
from aiqa.store.database import migrate_store
from aiqa.store.models import Actor, ProjectCreate
from aiqa.worker.android_jobs import InstalledAppsProbeHandler
from ux_support import session

_BROWSERS = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
)

_SERIAL = "emulator-5580"
_ADB = Path(r"C:\sdk\adb.exe")


class AppsAdbBoundary:
    """Fixture ADB: two packages, offline/unauthorized/permission, no install/reset."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.state = "device"
        self.list_error = b""
        self.list_code = 0
        self.packages = (
            "package:/data/app/com.example.one-1/base.apk=com.example.one",
            "package:/data/app/com.example.two-2/base.apk=com.example.two",
        )
        self.versions = {
            "com.example.one": "versionName=1.0.0\n",
            "com.example.two": "versionName=2.0.0\n",
        }

    def __call__(self, argv, **kwargs):
        assert isinstance(argv, list)
        assert argv[0].lower().endswith("adb.exe") or argv[0].lower().endswith("adb")
        assert kwargs.get("shell", False) is False
        serial = argv[2] if len(argv) > 2 and argv[1] == "-s" else ""
        command = tuple(argv[3:] if serial else argv[1:])
        self.calls.append(command)
        joined = " ".join(command).lower()
        assert "install" not in joined
        assert "uninstall" not in joined
        assert "pm clear" not in joined
        assert "reboot" not in joined
        if command == ("get-state",):
            if self.state != "device":
                return subprocess.CompletedProcess(
                    argv, 1, b"", f"error: device {self.state}\n".encode()
                )
            return subprocess.CompletedProcess(argv, 0, b"device\n", b"")
        if command == ("shell", "pm", "list", "packages", "-f"):
            return subprocess.CompletedProcess(
                argv, self.list_code, ("\n".join(self.packages) + "\n").encode(), self.list_error
            )
        if command == ("shell", "getprop", "ro.build.version.sdk"):
            return subprocess.CompletedProcess(argv, 0, b"36\n", b"")
        if command == ("shell", "getprop", "ro.product.cpu.abi"):
            return subprocess.CompletedProcess(argv, 0, b"x86_64\n", b"")
        if command[:3] == ("shell", "dumpsys", "package") and len(command) == 4:
            body = self.versions.get(command[3], "versionName=0\n")
            return subprocess.CompletedProcess(argv, 0, body.encode(), b"")
        raise AssertionError(f"Unexpected ADB command: {command}")


def test_list_installed_apps_read_only_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    boundary = AppsAdbBoundary()
    monkeypatch.setattr(android_observation, "_run_bounded", boundary)
    ready = list_installed_apps(_ADB, _SERIAL, expected_serial=_SERIAL)
    assert ready.state == "ready"
    assert ready.install_calls == 0 and ready.reset_calls == 0
    assert [app.package for app in ready.apps] == ["com.example.one", "com.example.two"]
    assert ready.apps[0].content_hash == "unknown"
    assert ready.apps[0].api_level == 36 and ready.apps[0].abi == "x86_64"
    assert not any("install" in " ".join(call) for call in boundary.calls)

    mismatch = list_installed_apps(_ADB, "other-serial", expected_serial=_SERIAL)
    assert mismatch.state == "unavailable" and mismatch.reason == "serial_mismatch"
    assert mismatch.apps == () and mismatch.install_calls == 0

    boundary.state = "offline"
    offline = list_installed_apps(_ADB, _SERIAL, expected_serial=_SERIAL)
    assert offline.state == "offline" and offline.install_calls == 0

    boundary.state = "unauthorized"
    denied = list_installed_apps(_ADB, _SERIAL, expected_serial=_SERIAL)
    assert denied.state == "unauthorized"

    boundary.state = "device"
    boundary.list_code = 1
    boundary.list_error = b"Permission denied PRIVATE"
    permission = list_installed_apps(_ADB, _SERIAL, expected_serial=_SERIAL)
    assert permission.state == "unauthorized" and permission.reason == "permission_denied"
    assert "PRIVATE" not in permission.reason


def test_rx_56_installed_apps_probe_and_wizard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    boundary = AppsAdbBoundary()
    monkeypatch.setattr(android_observation, "_run_bounded", boundary)
    monkeypatch.setenv("AIQA_ADB_PATH", str(_ADB))

    root = tmp_path / "runtime"
    app = create_app(
        load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)})
    )
    owner = Actor(uuid4(), None, True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("앱조회", "rx56", "installed", "android"))
    store.close()
    project_id = str(project.project_id)
    database = root / "db" / "aiqa.sqlite"

    observed = asyncio.run(_flow(app, project_id, database, boundary))
    browser_ok = _browser_shot(tmp_path, observed["page_html"])

    assert observed["lease_blocked"] == 422
    assert observed["probe_status"] == 201
    assert observed["probe_kind"] == "installed_apps"
    assert observed["packages"] == ["com.example.one", "com.example.two"]
    assert observed["install_calls"] == 0 and observed["reset_calls"] == 0
    assert observed["content_hash"] == "unknown"
    assert observed["observed_at"]
    assert observed["offline_state"] == "offline"
    assert observed["unauthorized_state"] == "unauthorized"
    assert observed["wizard_has_select"] is True
    assert observed["wizard_has_refresh"] is True
    assert observed["handler_install_calls"] == 0
    assert browser_ok is True
    assert not any("install" in " ".join(call) for call in boundary.calls)


async def _flow(app: object, project_id: str, database: Path, boundary: AppsAdbBoundary) -> dict[str, object]:
    transport = httpx.ASGITransport(app=app)
    origin = "http://127.0.0.1"
    async with httpx.AsyncClient(transport=transport, base_url=origin) as client:
        headers = await session(client, project_id)
        worker_id = str(uuid4())
        headers["Idempotency-Key"] = "rx56-enroll"
        enrolled = await client.post(
            f"/api/v1/projects/{project_id}/worker-enrollments",
            json={"worker_id": worker_id, "purpose": "resource_probe"},
            headers=headers,
        )
        assert enrolled.status_code == 201, enrolled.text
        token = enrolled.json()["credential"]
        worker_headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": "rx56-inv"}
        inventory = await client.post(
            "/api/v1/worker/inventory",
            headers=worker_headers,
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
                "display_name": "RX56 에뮬레이터",
                "raw_handle": None,
            },
        )
        assert inventory.status_code == 200, inventory.text
        resource_id = inventory.json()["physical_key_id"]
        heartbeat = await client.post(
            "/api/v1/worker/heartbeats",
            headers={"Authorization": f"Bearer {token}"},
            json={"boot_id": "rx56-boot"},
        )
        assert heartbeat.status_code == 200, heartbeat.text

        headers["Idempotency-Key"] = "rx56-no-lease"
        blocked = await client.post(
            f"/api/v1/resources/{resource_id}/probes",
            params={"project_id": project_id},
            json={"provider": "fixture", "kind": "installed_apps", "proof": None},
            headers=headers,
        )

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

        headers["Idempotency-Key"] = "rx56-apps"
        probed = await client.post(
            f"/api/v1/resources/{resource_id}/probes",
            params={"project_id": project_id},
            json={"provider": "fixture", "kind": "installed_apps", "proof": None},
            headers=headers,
        )
        body = probed.json()
        assert probed.status_code == 201, probed.text
        observation = body["observation"]
        listed = await client.get(
            f"/api/v1/resources/{resource_id}/installed-apps",
            params={"project_id": project_id},
            headers=headers,
        )
        listed_body = listed.json()
        assert listed.status_code == 200, listed.text

        boundary.state = "offline"
        headers["Idempotency-Key"] = "rx56-offline"
        offline = await client.post(
            f"/api/v1/resources/{resource_id}/probes",
            params={"project_id": project_id},
            json={"provider": "fixture", "kind": "installed_apps", "proof": None},
            headers=headers,
        )
        offline_state = offline.json()["observation"]["state"]

        boundary.state = "unauthorized"
        headers["Idempotency-Key"] = "rx56-unauth"
        unauth = await client.post(
            f"/api/v1/resources/{resource_id}/probes",
            params={"project_id": project_id},
            json={"provider": "fixture", "kind": "installed_apps", "proof": None},
            headers=headers,
        )
        unauthorized_state = unauth.json()["observation"]["state"]
        boundary.state = "device"

        handler = InstalledAppsProbeHandler(_ADB, _SERIAL, run=boundary)
        handled = handler.handle(
            {
                "snapshot": {
                    "purpose": "resource_probe",
                    "serial": _SERIAL,
                    "limits": {"kind": "installed_apps"},
                }
            }
        )
        handler_event = json.loads(handled.action_mapping)

        page = await client.get(
            f"/ui/projects/{project_id}/recordings/wizard",
            params={"resource_id": resource_id, "target": "android", "step": "2"},
        )
        assert page.status_code == 200, page.text
        return {
            "lease_blocked": blocked.status_code,
            "probe_status": probed.status_code,
            "probe_kind": body.get("kind"),
            "packages": [app["package"] for app in observation["apps"]],
            "install_calls": observation["install_calls"],
            "reset_calls": observation["reset_calls"],
            "content_hash": observation["apps"][0]["content_hash"],
            "observed_at": listed_body.get("observed_at") or observation.get("observed_at"),
            "offline_state": offline_state,
            "unauthorized_state": unauthorized_state,
            "wizard_has_select": 'id="android-package-select"' in page.text or "android-package-select" in page.text,
            "wizard_has_refresh": "설치 앱 조회" in page.text,
            "handler_install_calls": handler_event["install_calls"],
            "page_html": page.text,
        }


def _browser_shot(tmp_path: Path, html: str) -> bool:
    browser = next((path for path in _BROWSERS if path.exists()), None)
    if browser is None:
        return False
    page = tmp_path / "rx56.html"
    shot = tmp_path / "rx56.png"
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
