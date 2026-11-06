"""RX-68: installed_apps / app_install handlers registered on the Android worker entry."""

from __future__ import annotations

import asyncio
import io
import json
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx

from aiqa.api.app import create_app
from aiqa.api.auth import bound_auth_store, enroll_worker
from aiqa.config import WorkerClientSettings, load_settings
from aiqa.domain.projects import bind_store, create_project
from aiqa.environments.app_builds import (
    ApkInspectionSpec,
    FixtureInstallDriver,
    register_app_build,
)
from aiqa.store.database import migrate_store
from aiqa.store.models import Actor, ProjectCreate
from aiqa.worker.android_jobs import (
    assemble_android_worker_handlers,
    build_android_support_handlers,
    build_fixture_android_recording_handler,
)
from aiqa.worker.http_client import SyncASGITransport, WorkerHttpClient
from aiqa.worker.runtime import WorkerRuntime, WorkerRuntimeConfig, android_worker_prepared_adapters
from ux_support import session

_SERIAL = "emulator-5580"
_ADB = Path(r"C:\sdk\adb.exe")


class AppsAdbBoundary:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.packages = (
            "package:/data/app/com.example.one-1/base.apk=com.example.one",
            "package:/data/app/com.example.two-2/base.apk=com.example.two",
        )

    def __call__(self, argv, **kwargs):
        serial = argv[2] if len(argv) > 2 and argv[1] == "-s" else ""
        command = tuple(argv[3:] if serial else argv[1:])
        self.calls.append(command)
        joined = " ".join(command).lower()
        assert "install" not in joined
        assert "pm clear" not in joined
        if command == ("get-state",):
            return subprocess.CompletedProcess(argv, 0, b"device\n", b"")
        if command == ("shell", "pm", "list", "packages", "-f"):
            return subprocess.CompletedProcess(
                argv, 0, ("\n".join(self.packages) + "\n").encode(), b""
            )
        if command == ("shell", "getprop", "ro.build.version.sdk"):
            return subprocess.CompletedProcess(argv, 0, b"36\n", b"")
        if command == ("shell", "getprop", "ro.product.cpu.abi"):
            return subprocess.CompletedProcess(argv, 0, b"x86_64\n", b"")
        if command[:3] == ("shell", "dumpsys", "package") and len(command) == 4:
            return subprocess.CompletedProcess(argv, 0, b"versionName=1.0.0\n", b"")
        return subprocess.CompletedProcess(argv, 0, b"", b"")


def _apk_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("AndroidManifest.xml", b"<manifest/>")
        archive.writestr("classes.dex", b"dex")
    return buffer.getvalue()


def _seed_android_resource(store, *, project_id, worker_id: str, physical: str, now: datetime) -> None:
    with store.transaction() as connection:
        connection.execute(
            "INSERT INTO physical_resource_keys (physical_key_id, worker_id, native_id) VALUES (?, ?, ?)",
            (physical, worker_id, _SERIAL),
        )
        connection.execute(
            """
            INSERT INTO resource_aliases (
                project_id, physical_key_id, display_name, target_kind, alias_id
            ) VALUES (?, ?, ?, 'android', ?)
            """,
            (str(project_id), physical, "AVD", str(uuid4())),
        )
        connection.execute(
            """
            INSERT INTO resource_inventory (
                physical_key_id, state, os_build, geometry, permissions, ime, observed_at
            ) VALUES (?, 'ready', '', '100x200@0', '[]', '', ?)
            """,
            (physical, now.isoformat()),
        )


def _release_physical_lease(app, *, token: str, physical: str, now: datetime, key: str) -> None:
    """Confirm cleanup so the next worker job can claim the same physical scope."""

    store = app.state.open_store()
    try:
        with store.transaction() as connection:
            row = connection.execute(
                """
                SELECT leases.project_id, leases.job_id, leases.generation, attempts.attempt_id
                FROM leases
                JOIN attempts
                  ON attempts.project_id = leases.project_id
                 AND attempts.job_id = leases.job_id
                 AND attempts.generation = leases.generation
                WHERE leases.physical_key_id = ?
                """,
                (physical,),
            ).fetchone()
    finally:
        store.close()
    if row is None:
        return
    transport = SyncASGITransport(app)
    with httpx.Client(transport=transport, base_url="https://127.0.0.1") as http:
        response = http.post(
            "/api/v1/worker/cleanup-confirmations",
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": key},
            json={
                "project_id": str(row[0]),
                "job_id": str(row[1]),
                "generation": int(row[2]),
                "attempt_id": str(row[3]),
                "physical_key_id": physical,
                "proof_refs": ["adb:released"],
                "now": now.isoformat(),
            },
        )
    assert response.status_code == 200, response.text


def test_rx_68_worker_entry_probe_and_install(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "runtime"
    root.mkdir()
    settings = load_settings(
        {"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}
    )
    app = create_app(settings)
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("앱관리", "rx68", "rx", "android"))
    actor = Actor(owner.actor_id, project.project_id, True)
    project_id = str(project.project_id)
    probe_worker = "worker-rx68-probe"
    install_worker = "worker-rx68-install"
    with bound_auth_store(store):
        probe_token = enroll_worker(actor, probe_worker, "resource_probe")
        install_token = enroll_worker(actor, install_worker, "app_install")

    physical = str(uuid4())
    # Keep server/presence clock on wall time so enqueue online checks stay valid.
    monkeypatch.setattr("aiqa.api.worker._server_now", lambda: datetime.now(timezone.utc))
    now = lambda: datetime.now(timezone.utc)
    _seed_android_resource(
        store,
        project_id=project.project_id,
        worker_id=probe_worker,
        physical=physical,
        now=now(),
    )
    store.close()

    adb = AppsAdbBoundary()
    driver = FixtureInstallDriver(installed=set())
    app.state.fixture_install_driver = driver
    probe, install = build_android_support_handlers(
        adb_path=_ADB,
        serial=_SERIAL,
        run=adb,
        install_driver=driver,
    )
    recording = build_fixture_android_recording_handler(
        adb_path=_ADB,
        serial=_SERIAL,
        expected_avd="rx68-avd",
        runtime_root=tmp_path / "rec",
        fixture_response="finish()",
    )
    handler = assemble_android_worker_handlers(
        recording=recording,
        installed_apps=probe,
        app_install=install,
    )
    assert "app_install" in android_worker_prepared_adapters()
    assert "resource_probe" in android_worker_prepared_adapters()

    transport = SyncASGITransport(app)
    probe_settings = WorkerClientSettings(
        base_url="https://127.0.0.1",
        token=probe_token,
        timeout_seconds=10,
        verify_tls=False,
        ca_bundle=None,
    )
    # Physical enqueue requires the owning execution PC to be online.
    with WorkerHttpClient(probe_settings, transport=transport) as client:
        client.heartbeat("boot-rx68-probe")

    async def _api_enqueue_probe() -> str:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
        ) as http:
            headers = await session(http, project_id)
            response = await http.post(
                f"/api/v1/resources/{physical}/probes",
                params={"project_id": project_id},
                json={"provider": "worker", "kind": "installed_apps"},
                headers={**headers, "Idempotency-Key": "rx68-probe"},
            )
            assert response.status_code == 201, response.text
            body = response.json()
            assert body["status"] == "queued"
            assert body.get("ready") is False
            return str(body["job_id"])

    probe_job = asyncio.run(_api_enqueue_probe())

    with WorkerHttpClient(probe_settings, transport=transport) as client:
        client.heartbeat("boot-rx68-probe")
        runtime = WorkerRuntime(
            client,
            WorkerRuntimeConfig(
                boot_id="boot-rx68-probe",
                prepared_adapters=android_worker_prepared_adapters(),
                max_cycles=1,
            ),
            handler,
            registered_serial=_SERIAL,
            now=now,
            mono=lambda: 100.0,
        )
        runtime._registered_physical_key_id = physical
        report = runtime.run_once()
    assert report.claimed is True
    assert report.finished is True
    assert adb.calls
    assert not any("install" in " ".join(call).lower() for call in adb.calls)
    _release_physical_lease(
        app, token=probe_token, physical=physical, now=now(), key="rx68-probe-cleanup"
    )

    store = app.state.open_store()
    try:
        with store.transaction() as connection:
            row = connection.execute(
                "SELECT status, limits FROM jobs WHERE job_id = ?",
                (probe_job,),
            ).fetchone()
    finally:
        store.close()
    assert row is not None
    assert str(row[0]) == "completed"
    limits = json.loads(str(row[1]))
    assert limits.get("kind") == "installed_apps"
    assert limits.get("ready") is True
    assert len(limits.get("apps") or []) == 2
    assert limits.get("install_calls") == 0

    async def _read_apps() -> dict:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
        ) as http:
            headers = await session(http, project_id)
            response = await http.get(
                f"/api/v1/resources/{physical}/installed-apps",
                params={"project_id": project_id},
                headers=headers,
            )
            assert response.status_code == 200, response.text
            return response.json()

    observation = asyncio.run(_read_apps())
    assert observation.get("state") == "ready"
    assert len(observation.get("apps") or []) == 2

    body = _apk_bytes()
    _, build = register_app_build(
        ApkInspectionSpec(project.project_id, "demo.apk", body, len(body)),
        tool_path="fixture-meta",
    )

    async def _api_install(*, serial: str, key: str) -> dict:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
        ) as http:
            headers = await session(http, project_id)
            response = await http.post(
                f"/api/v1/resources/{physical}/app-installs",
                params={"project_id": project_id},
                json={
                    "provider": "worker",
                    "build_id": str(build.build_id),
                    "content_hash": build.content_hash,
                    "policy": "force_reinstall",
                    "serial": serial,
                    "confirmed": True,
                },
                headers={**headers, "Idempotency-Key": key},
            )
            assert response.status_code == 201, response.text
            return response.json()

    # Keep the physical-key owner online for enqueue; claim can use a different purpose worker.
    with WorkerHttpClient(probe_settings, transport=transport) as client:
        client.heartbeat("boot-rx68-probe")

    forged = asyncio.run(_api_install(serial="forged-serial", key="rx68-forged"))
    assert forged.get("ready") is False
    assert forged.get("status") == "queued"
    install_job = str(forged["job_id"])

    install_settings = WorkerClientSettings(
        base_url="https://127.0.0.1",
        token=install_token,
        timeout_seconds=10,
        verify_tls=False,
        ca_bundle=None,
    )
    before_mutations = driver.unapproved_mutations
    before_installs = driver.install_calls
    with WorkerHttpClient(install_settings, transport=transport) as client:
        client.heartbeat("boot-rx68-install")
        runtime = WorkerRuntime(
            client,
            WorkerRuntimeConfig(
                boot_id="boot-rx68-install",
                prepared_adapters=android_worker_prepared_adapters(),
                max_cycles=1,
            ),
            handler,
            registered_serial=_SERIAL,
            now=now,
            mono=lambda: 100.0,
        )
        runtime._registered_physical_key_id = physical
        forged_report = runtime.run_once()
    assert forged_report.claimed is True
    assert forged_report.finished is True
    assert driver.install_calls == before_installs
    assert driver.unapproved_mutations == before_mutations
    _release_physical_lease(
        app, token=install_token, physical=physical, now=now(), key="rx68-forged-cleanup"
    )

    store = app.state.open_store()
    try:
        with store.transaction() as connection:
            row = connection.execute(
                "SELECT status, limits FROM jobs WHERE job_id = ?",
                (install_job,),
            ).fetchone()
    finally:
        store.close()
    forged_limits = json.loads(str(row[1]))
    assert forged_limits.get("ready") is False
    assert int(forged_limits.get("install_calls") or 0) == 0
    assert int(forged_limits.get("unapproved_mutations") or 0) == 0

    with WorkerHttpClient(probe_settings, transport=transport) as client:
        client.heartbeat("boot-rx68-probe")
    ok = asyncio.run(_api_install(serial=_SERIAL, key="rx68-ok"))
    ok_job = str(ok["job_id"])
    with WorkerHttpClient(install_settings, transport=transport) as client:
        client.heartbeat("boot-rx68-install-2")
        runtime = WorkerRuntime(
            client,
            WorkerRuntimeConfig(
                boot_id="boot-rx68-install-2",
                prepared_adapters=android_worker_prepared_adapters(),
                max_cycles=1,
            ),
            handler,
            registered_serial=_SERIAL,
            now=now,
            mono=lambda: 100.0,
        )
        runtime._registered_physical_key_id = physical
        ok_report = runtime.run_once()
    assert ok_report.claimed is True and ok_report.finished is True
    assert driver.install_calls == before_installs + 1
    assert driver.unapproved_mutations == before_mutations
    _release_physical_lease(
        app, token=install_token, physical=physical, now=now(), key="rx68-ok-cleanup"
    )

    store = app.state.open_store()
    try:
        with store.transaction() as connection:
            row = connection.execute(
                "SELECT status, limits FROM jobs WHERE job_id = ?",
                (ok_job,),
            ).fetchone()
    finally:
        store.close()
    assert str(row[0]) == "completed"
    ok_limits = json.loads(str(row[1]))
    assert ok_limits.get("ready") is True
    assert int(ok_limits.get("install_calls") or 0) == 1

