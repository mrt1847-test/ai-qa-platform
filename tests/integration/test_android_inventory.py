"""AD-02: Android observation becomes authenticated inventory without raw upload."""

from __future__ import annotations

import asyncio
import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from aiqa.api.app import create_app
from aiqa.config import load_settings
from aiqa.contracts.actions import CaptureGeometry
from aiqa.domain.projects import bind_store, create_project
from aiqa.environments.android_observation import AndroidObservationResult
from aiqa.store.database import migrate_store
from aiqa.store.models import Actor, ProjectCreate, WorkerScope
from aiqa.worker.resources import (
    InventoryDenied,
    bind_inventory_store,
    inventory_from_observation,
    list_resources,
    preview_resource,
    report_android_observation,
    report_inventory,
)


def test_inventory_from_observation_maps_states_and_keeps_raw_out() -> None:
    ready = AndroidObservationResult(
        serial="emulator-5580",
        state="ready",
        reason="metadata_only",
        observed_at="2026-11-03T00:00:00+00:00",
        device_kind="android_emulator",
        avd_name="AIQA_API36",
        android_release="16",
        api_level=36,
        model="sdk_gphone64_x86_64",
        density=280,
        geometry=CaptureGeometry(720, 1600, 720, 1600, "identity", 0, (0, 0, 720, 1600)),
        observation=None,
        sanitized=False,
    )
    report = inventory_from_observation(ready)
    assert report.state == "ready"
    assert report.target_kind == "android"
    assert report.native_id == "emulator-5580"
    assert report.display_name == "AIQA_API36 에뮬레이터"
    assert report.geometry == "720x1600@0"
    assert report.os_build == "Android 16 API 36"
    assert report.raw_handle is None
    assert "android_emulator" in report.permissions
    assert inventory_from_observation(
        AndroidObservationResult("emulator-5580", "booting", "boot_incomplete", "2026-11-03T00:00:00+00:00", "android_emulator")
    ).state == "offline"
    assert inventory_from_observation(
        AndroidObservationResult("ABC", "unauthorized", "device_unauthorized", "2026-11-03T00:00:00+00:00", "android_usb")
    ).state == "unauthorized"


def test_report_android_observation_reuses_key_and_blocks_other_project(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    app = create_app(load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}))
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("인벤토리", "ad02", "inventory", "android"))
        other = create_project(owner, ProjectCreate("다른", "ad02b", "other", "android"))
    worker_id = uuid4()
    enroll_id = str(uuid4())
    token = "worker-ad02-token"
    stamp = datetime.now(timezone.utc).isoformat()
    with store.transaction() as connection:
        connection.execute(
            "INSERT INTO worker_enrollments (enrollment_id, worker_id, project_id, created_at) VALUES (?, ?, ?, ?)",
            (enroll_id, str(worker_id), str(project.project_id), stamp),
        )
        connection.execute(
            """
            INSERT INTO worker_tokens (token_id, enrollment_id, token_hash, purpose, created_at)
            VALUES (?, ?, ?, 'resource_probe', ?)
            """,
            (str(uuid4()), enroll_id, hashlib.sha256(token.encode("utf-8")).hexdigest(), stamp),
        )
    worker = WorkerScope(str(worker_id), (project.project_id,), ("resource_probe",))

    class _Provider:
        def observe(self, *, capture: bool = True):
            assert capture is False
            return AndroidObservationResult(
                serial="emulator-5580",
                state="ready",
                reason="metadata_only",
                observed_at=stamp,
                device_kind="android_emulator",
                avd_name="AIQA_API36",
                android_release="16",
                api_level=36,
                model="sdk_gphone64_x86_64",
                density=280,
                geometry=CaptureGeometry(720, 1600, 720, 1600, "identity", 0, (0, 0, 720, 1600)),
            )

    with bind_inventory_store(store):
        first = report_android_observation(worker, _Provider())  # type: ignore[arg-type]
        second = report_android_observation(worker, _Provider())  # type: ignore[arg-type]
        assert first.physical_key_id == second.physical_key_id
        listed = list_resources(project.project_id)
        preview = preview_resource(project.project_id, first.physical_key_id)
        offline = inventory_from_observation(
            AndroidObservationResult(
                "emulator-5580",
                "offline",
                "device_offline",
                stamp,
                "android_emulator",
                avd_name="AIQA_API36",
            )
        )
        ended = report_inventory(worker, offline)
        assert ended.physical_key_id == first.physical_key_id
        other_worker = WorkerScope(str(uuid4()), (other.project_id,), ("resource_probe",))
        try:
            report_inventory(other_worker, offline)
            raised = False
        except InventoryDenied:
            raised = True
        except Exception:
            raised = True
    store.close()
    match = next(item for item in listed if item["resource_id"] == str(first.physical_key_id))
    page = asyncio.run(_page(app, project.project_id))
    with sqlite3.connect(root / "db" / "aiqa.sqlite") as connection:
        keys = connection.execute(
            "SELECT COUNT(*) FROM physical_resource_keys WHERE worker_id = ? AND native_id = ?",
            (str(worker_id), "emulator-5580"),
        ).fetchone()[0]
        observations = connection.execute(
            "SELECT COUNT(*) FROM resource_observations WHERE resource_id = ?",
            (str(first.physical_key_id),),
        ).fetchone()[0]
    observed = {
        "same_physical_key": first.physical_key_id == second.physical_key_id and keys == 1,
        "emulator_listed": match["is_emulator"] is True and "에뮬레이터" in match["display_name"],
        "preview_without_raw_upload": preview.reason == "unobserved" and preview.raw_control is False and observations == 0,
        "offline_after_end": ended.state == "offline",
        "other_project_denied": raised,
        "page_shows_emulator": "AIQA_API36 에뮬레이터" in page and "에뮬레이터" in page,
    }
    assert observed == {
        "same_physical_key": True,
        "emulator_listed": True,
        "preview_without_raw_upload": True,
        "offline_after_end": True,
        "other_project_denied": True,
        "page_shows_emulator": True,
    }


def test_report_inventory_rejects_raw_handle(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    app = create_app(load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}))
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("거부", "ad02c", "reject", "android"))
    worker = WorkerScope(str(uuid4()), (project.project_id,), ("resource_probe",))
    report = inventory_from_observation(
        AndroidObservationResult(
            "emulator-5580",
            "ready",
            "metadata_only",
            "2026-11-03T00:00:00+00:00",
            "android_emulator",
            avd_name="AIQA_API36",
            android_release="16",
            api_level=36,
            geometry=CaptureGeometry(720, 1600, 720, 1600, "identity", 0, (0, 0, 720, 1600)),
        )
    )
    from dataclasses import replace

    dirty = replace(report, raw_handle="adb://emulator-5580")
    with bind_inventory_store(store):
        try:
            report_inventory(worker, dirty)
            ok = True
        except ValueError:
            ok = False
    store.close()
    assert ok is False


async def _page(app: object, project_id: UUID) -> str:
    import httpx

    origin = "http://127.0.0.1"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        issued = await client.post(
            "/api/v1/session/nonces",
            json={"origin": origin, "project_id": str(project_id)},
            headers={"Idempotency-Key": "ad02-nonce", "Origin": origin},
        )
        booted = await client.post(
            "/api/v1/session/bootstrap",
            json={"nonce": issued.json()["nonce"]},
            headers={"Idempotency-Key": "ad02-boot", "Origin": origin},
        )
        client.cookies.set("aiqa_session", booted.cookies["aiqa_session"])
        page = await client.get(f"/ui/projects/{project_id}/environments")
    assert page.status_code == 200, page.text
    return page.text
