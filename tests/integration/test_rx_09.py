"""RX-09: Android worker inventory readiness, serial gate, and no raw upload."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from aiqa.api.app import create_app
from aiqa.api.auth import bound_auth_store, enroll_worker
from aiqa.config import WorkerClientSettings, load_settings
from aiqa.contracts.actions import CaptureGeometry
from aiqa.domain.projects import bind_store, create_project
from aiqa.environments.android_observation import AndroidObservationResult
from aiqa.environments.usb_android import require_dedicated_serial
from aiqa.store.database import migrate_store
from aiqa.store.models import Actor, ProjectCreate, WorkerScope
from aiqa.worker.http_client import RetryClass, SyncASGITransport, WorkerHttpClient, WorkerHttpError
from aiqa.worker.resources import (
    android_inventory_payload,
    bind_inventory_store,
    inventory_from_observation,
    list_resources,
    report_android_observation,
)


def _result(state: str, *, serial: str = "emulator-5580", observed_at: str, rotation: int = 0) -> AndroidObservationResult:
    geometry = None
    if state == "ready":
        geometry = CaptureGeometry(720, 1600, 720, 1600, "identity", rotation, (0, 0, 720, 1600))
    return AndroidObservationResult(
        serial=serial,
        state=state,
        reason="metadata_only" if state == "ready" else state,
        observed_at=observed_at,
        device_kind="android_emulator",
        avd_name="AIQA_API36",
        android_release="16",
        api_level=36,
        model="sdk_gphone64_x86_64",
        density=280 if state == "ready" else None,
        geometry=geometry,
        observation=None,
        sanitized=False,
    )


def test_readiness_gates_geometry_and_no_raw_upload() -> None:
    assert require_dedicated_serial("emulator-5580", "emulator-5580") is True
    assert require_dedicated_serial("emulator-5580", "emulator-5554") is False
    stamp = "2026-11-03T10:00:00+00:00"
    ready = inventory_from_observation(_result("ready", observed_at=stamp, rotation=90))
    assert ready.state == "ready"
    assert ready.geometry == "720x1600@90"
    assert json.loads(ready.permissions)["raw_upload"] == 0
    assert inventory_from_observation(_result("unauthorized", observed_at=stamp)).state == "unauthorized"
    assert inventory_from_observation(_result("offline", observed_at=stamp)).state == "offline"
    mismatched = inventory_from_observation(
        _result("ready", serial="emulator-5554", observed_at=stamp),
        expected_serial="emulator-5580",
    )
    assert mismatched.state == "offline"
    assert mismatched.native_id == "emulator-5580"

    settings = WorkerClientSettings(base_url="https://manage.example", token="tok")
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(200, json={"state": "ready"})

    with WorkerHttpClient(settings, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(WorkerHttpError) as blocked:
            client.report_inventory(
                {"native_id": "x", "png": b"raw", "state": "ready"},
                idempotency_key="bad",
            )
        assert blocked.value.retry_class is RetryClass.fatal
        client.report_inventory(
            android_inventory_payload(ready, project_id=str(uuid4())),
            idempotency_key="ok",
        )
    assert calls and "png" not in calls[0] and calls[0].get("raw_handle") is None


def test_stale_not_ready_and_selector_fields(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "runtime"
    app = create_app(
        load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)})
    )
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("안드", "rx09", "rx", "android"))
    actor = Actor(owner.actor_id, project.project_id, True)
    worker_id = str(uuid4())
    with bound_auth_store(store):
        token = enroll_worker(actor, worker_id, "resource_probe")
    now = datetime.now(timezone.utc)
    fresh = (now - timedelta(minutes=1)).isoformat()
    stale = (now - timedelta(minutes=30)).isoformat()
    worker = WorkerScope(worker_id, (project.project_id,), ("resource_probe",))

    class _Provider:
        def __init__(self, result):
            self.serial = result.serial
            self._result = result

        def observe(self, *, capture: bool = True):
            assert capture is False
            return self._result

    transport = SyncASGITransport(app)
    settings = WorkerClientSettings(
        base_url="https://127.0.0.1", token=token, timeout_seconds=10, verify_tls=False
    )
    with WorkerHttpClient(settings, transport=transport) as client:
        client.heartbeat("boot-rx09")

    with bind_inventory_store(store):
        report_android_observation(worker, _Provider(_result("ready", observed_at=fresh, rotation=0)))
        listed = list_resources(project.project_id)
        assert len(listed) == 1
        item = listed[0]
        assert item["state"] == "ready"
        assert item["can_execute"] is True
        assert item["geometry"] == "720x1600@0"
        assert item["rotation"] == 0
        assert item["observed_at"] == fresh
        assert item["last_seen"] is not None
        assert "observed_at" in item and "last_seen" in item

        with store.transaction() as connection:
            connection.execute(
                "UPDATE resource_inventory SET observed_at = ? WHERE physical_key_id = ?",
                (stale, item["resource_id"]),
            )
        aged = list_resources(project.project_id)[0]
        assert aged["state"] == "offline"
        assert aged["can_execute"] is False
        assert aged["observed_at"] == stale
        assert aged["connection_state"] == "online"
        assert aged["last_seen"] is not None

    template = (Path("src/aiqa/web/templates/recording_setup.html")).read_text(encoding="utf-8")
    assert "data-observed-at" in template and "data-last-seen" in template and "data-geometry" in template
    assert "heartbeat" in template

    payload = android_inventory_payload(
        inventory_from_observation(_result("unauthorized", observed_at=now.isoformat())),
        project_id=str(project.project_id),
    )
    with WorkerHttpClient(settings, transport=transport) as client:
        body = client.report_inventory(payload, idempotency_key="rx09-unauth")
    assert body["state"] == "unauthorized"
    store.close()
