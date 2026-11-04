"""RX-32: worker start wires dedicated Android serial inventory after heartbeat."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from aiqa.config import WorkerClientSettings
from aiqa.contracts.actions import CaptureGeometry, Observation
from aiqa.environments.android_observation import AndroidObservationResult
from aiqa.worker.http_client import WorkerHttpClient
from aiqa.worker.resources import assemble_android_inventory_payload, inventory_from_observation
from aiqa.worker.runtime import (
    InertHandler,
    WorkerRuntime,
    WorkerRuntimeConfig,
    load_android_inventory_binding,
    make_android_inventory_provider,
    run_worker_process,
)


class _FixtureAndroid:
    def __init__(
        self,
        *,
        serial: str = "emulator-5580",
        state: str = "ready",
        observation: Observation | None = None,
        raise_exc: bool = False,
    ) -> None:
        self.serial = serial
        self.state = state
        self.observation = observation
        self.raise_exc = raise_exc
        self.observe_calls = 0
        self.capture_flags: list[bool] = []

    def observe(self, *, capture: bool = True) -> AndroidObservationResult:
        self.observe_calls += 1
        self.capture_flags.append(capture)
        if self.raise_exc:
            raise RuntimeError("adb unavailable")
        geometry = None
        if self.state == "ready":
            geometry = CaptureGeometry(720, 1600, 720, 1600, "identity", 90, (0, 0, 720, 1600))
        return AndroidObservationResult(
            serial=self.serial,
            state=self.state,
            reason="metadata_only" if self.state == "ready" else self.state,
            observed_at="2026-11-04T06:00:00+00:00",
            device_kind="android_emulator",
            avd_name="AIQA_API36",
            android_release="16",
            api_level=36,
            model="sdk_gphone64_x86_64",
            density=280 if self.state == "ready" else None,
            geometry=geometry,
            observation=self.observation,
            sanitized=False,
        )


def test_rx_32_binding_missing_skips_ready_and_fixture_reports_serial_only(tmp_path: Path) -> None:
    assert load_android_inventory_binding({}) is None
    assert load_android_inventory_binding({"AIQA_ANDROID_SERIAL": "emulator-5580"}) is None

    adb = tmp_path / "adb.exe"
    adb.write_text("", encoding="utf-8")
    binding = load_android_inventory_binding(
        {
            "AIQA_WORKER_PROJECT_ID": "proj-1",
            "AIQA_ANDROID_SERIAL": "emulator-5580",
            "AIQA_ADB_PATH": str(adb),
            "AIQA_ANDROID_AVD": "AIQA_API36",
        }
    )
    assert binding is not None
    assert binding.serial == "emulator-5580"

    provider = _FixtureAndroid()
    payload = assemble_android_inventory_payload(
        provider,  # type: ignore[arg-type]
        project_id="proj-1",
        expected_serial="emulator-5580",
    )
    assert payload is not None
    assert payload["native_id"] == "emulator-5580"
    assert payload["state"] == "ready"
    assert payload["geometry"] == "720x1600@90"
    assert payload.get("raw_handle") is None
    assert "png" not in payload and "pixels" not in payload
    assert provider.capture_flags == [False]
    assert json.loads(str(payload["permissions"]))["raw_upload"] == 0

    offline = assemble_android_inventory_payload(
        _FixtureAndroid(state="offline"),  # type: ignore[arg-type]
        project_id="proj-1",
        expected_serial="emulator-5580",
    )
    assert offline is not None and offline["state"] == "offline"

    mismatched = assemble_android_inventory_payload(
        _FixtureAndroid(serial="emulator-5554"),  # type: ignore[arg-type]
        project_id="proj-1",
        expected_serial="emulator-5580",
    )
    assert mismatched is not None and mismatched["state"] == "offline"
    assert mismatched["native_id"] == "emulator-5580"

    pixels = Observation(
        "obs",
        "2026-11-04T06:00:00+00:00",
        CaptureGeometry(1, 1, 1, 1, "identity", 0, (0, 0, 1, 1)),
        b"\x89PNG",
        "",
        "",
        (),
        "",
        True,
        "android",
    )
    assert (
        assemble_android_inventory_payload(
            _FixtureAndroid(observation=pixels),  # type: ignore[arg-type]
            project_id="proj-1",
            expected_serial="emulator-5580",
        )
        is None
    )
    assert (
        assemble_android_inventory_payload(
            _FixtureAndroid(raise_exc=True),  # type: ignore[arg-type]
            project_id="proj-1",
            expected_serial="emulator-5580",
        )
        is None
    )


def test_rx_32_runtime_inventory_after_heartbeat_no_arbitrary_select() -> None:
    settings = WorkerClientSettings(base_url="https://manage.example", token="tok")
    inventory_bodies: list[dict] = []
    fixture = _FixtureAndroid()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/heartbeats"):
            return httpx.Response(200, json={"state": "online"})
        if request.url.path.endswith("/inventory"):
            inventory_bodies.append(json.loads(request.content.decode("utf-8")))
            return httpx.Response(200, json={"state": "ready"})
        if request.url.path.endswith("/claims"):
            return httpx.Response(204)
        return httpx.Response(404)

    binding = load_android_inventory_binding(
        {
            "AIQA_WORKER_PROJECT_ID": str(uuid4()),
            "AIQA_ANDROID_SERIAL": "emulator-5580",
            "AIQA_ADB_PATH": r"C:\tools\adb.exe",
            "AIQA_ANDROID_AVD": "AIQA_API36",
        }
    )
    assert binding is not None
    provide = make_android_inventory_provider(binding, provider=fixture)

    with WorkerHttpClient(settings, transport=httpx.MockTransport(handler)) as client:
        runtime = WorkerRuntime(
            client,
            WorkerRuntimeConfig(
                boot_id="boot-rx32",
                prepared_adapters=frozenset({"resource_probe"}),
                max_cycles=1,
            ),
            InertHandler(),
            inventory_provider=provide,
        )
        report = runtime.run_once()
    assert report.reason == "empty"
    assert fixture.observe_calls == 1
    assert fixture.capture_flags == [False]
    assert len(inventory_bodies) == 1
    body = inventory_bodies[0]
    assert body["native_id"] == "emulator-5580"
    assert body["state"] == "ready"
    assert body["geometry"] == "720x1600@90"
    assert "png" not in body

    # Probe failure → no inventory POST (no ready).
    fail_bodies: list[dict] = []

    def fail_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/heartbeats"):
            return httpx.Response(200, json={"state": "online"})
        if request.url.path.endswith("/inventory"):
            fail_bodies.append(json.loads(request.content.decode("utf-8")))
            return httpx.Response(200, json={"state": "ready"})
        if request.url.path.endswith("/claims"):
            return httpx.Response(204)
        return httpx.Response(404)

    broken = make_android_inventory_provider(binding, provider=_FixtureAndroid(raise_exc=True))
    with WorkerHttpClient(settings, transport=httpx.MockTransport(fail_handler)) as client:
        runtime = WorkerRuntime(
            client,
            WorkerRuntimeConfig(boot_id="boot-fail", prepared_adapters=frozenset({"resource_probe"})),
            InertHandler(),
            inventory_provider=broken,
        )
        runtime.run_once()
    assert fail_bodies == []


def test_rx_32_run_worker_process_wires_binding(monkeypatch, tmp_path: Path) -> None:
    adb = tmp_path / "adb.exe"
    adb.write_bytes(b"")
    project = str(uuid4())
    env = {
        "AIQA_MANAGEMENT_BASE_URL": "https://manage.example",
        "AIQA_WORKER_TOKEN": "tok",
        "AIQA_WORKER_BOOT_ID": "boot-proc",
        "AIQA_WORKER_PROJECT_ID": project,
        "AIQA_ANDROID_SERIAL": "emulator-5580",
        "AIQA_ADB_PATH": str(adb),
        "AIQA_ANDROID_AVD": "AIQA_API36",
    }
    seen: list[dict] = []
    fixture = _FixtureAndroid()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/heartbeats"):
            return httpx.Response(200, json={"state": "online"})
        if request.url.path.endswith("/inventory"):
            seen.append(json.loads(request.content.decode("utf-8")))
            return httpx.Response(200, json={"state": "ready"})
        if request.url.path.endswith("/claims"):
            return httpx.Response(204)
        return httpx.Response(404)

    original = WorkerHttpClient.__init__

    def patched(self, settings, *, transport=None, **kwargs):
        return original(self, settings, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(WorkerHttpClient, "__init__", patched)
    provide = make_android_inventory_provider(
        load_android_inventory_binding(env),  # type: ignore[arg-type]
        provider=fixture,
    )
    code = run_worker_process(env, inventory_provider=provide, max_cycles=1)
    assert code == 0
    assert seen and seen[0]["project_id"] == project
    assert seen[0]["native_id"] == "emulator-5580"
    assert fixture.observe_calls == 1


def test_rx_32_inventory_from_observation_rejects_other_serial_ready() -> None:
    stamp = datetime(2026, 11, 4, tzinfo=timezone.utc).isoformat()
    other = inventory_from_observation(
        AndroidObservationResult(
            "other-device",
            "ready",
            "metadata_only",
            stamp,
            "android_usb",
            geometry=CaptureGeometry(100, 200, 100, 200, "identity", 0, (0, 0, 100, 200)),
        ),
        expected_serial="emulator-5580",
    )
    assert other.state == "offline"


def test_rx_32_process_env_reports_inventory_without_claiming_unwired_jobs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project = str(uuid4())
    adb = tmp_path / "adb.exe"
    settings = {
        "AIQA_MANAGEMENT_BASE_URL": "https://manage.example",
        "AIQA_WORKER_TOKEN": "fixture-token",
        "AIQA_WORKER_BOOT_ID": "process-boot",
        "AIQA_WORKER_PROJECT_ID": project,
        "AIQA_ANDROID_SERIAL": "emulator-5580",
        "AIQA_ANDROID_AVD": "AIQA_API36",
        "AIQA_ADB_PATH": str(adb),
    }
    for key, value in settings.items():
        monkeypatch.setenv(key, value)

    requests = []
    fixture = _FixtureAndroid()

    def create_observer(path, serial, *, expected_avd):
        assert (path, serial, expected_avd) == (adb, "emulator-5580", "AIQA_API36")
        return fixture

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append((request.url.path.rsplit("/", 1)[-1], json.loads(request.content)))
        return httpx.Response(200, json={})

    monkeypatch.setattr("aiqa.environments.android_observation.AndroidObservationProvider", create_observer)
    monkeypatch.setattr(
        "aiqa.worker.runtime.WorkerHttpClient",
        lambda settings: WorkerHttpClient(settings, transport=httpx.MockTransport(respond)),
    )

    assert run_worker_process(max_cycles=1) == 0
    assert [route for route, _ in requests] == ["heartbeats", "inventory"]
    assert requests[0][1]["boot_id"] == "process-boot"
    body = requests[1][1]
    assert (body["project_id"], body["native_id"], body["state"]) == (
        project, "emulator-5580", "unavailable"
    )
    assert body["geometry"] == "720x1600@90"
    assert fixture.capture_flags == [False]
