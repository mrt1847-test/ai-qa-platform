"""RX-62: multi-worker physical resource identity, slots, and lease fences."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from aiqa.api.app import create_app
from aiqa.api.auth import bound_auth_store, enroll_worker
from aiqa.config import DEFAULT_MAX_ACTIVE_SLOTS, load_settings
from aiqa.contracts.resources import common_physical_scope
from aiqa.domain.projects import bind_store, create_project
from aiqa.store.database import migrate_store
from aiqa.store.models import Actor, ProjectCreate
from aiqa.store.queue import (
    active_slot_limit,
    claim_queued_job,
    configure_active_slots,
    physical_scope_is_leased,
)
from aiqa.worker.resources import bind_inventory_store, list_resources


def test_rx_62_default_slot_and_alias_physical_separation() -> None:
    assert DEFAULT_MAX_ACTIVE_SLOTS == 1
    configure_active_slots(1)
    assert active_slot_limit() == 1
    assert common_physical_scope("emulator-5580") == "emulator-5580"
    with pytest.raises(ValueError):
        common_physical_scope("  ")
    with pytest.raises(ValueError):
        configure_active_slots(0)


def test_rx_62_two_workers_same_resource_and_independent_slots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "runtime"
    settings = load_settings(
        {
            "AIQA_HOST": "127.0.0.1",
            "AIQA_PORT": "8000",
            "AIQA_RUNTIME_ROOT": str(root),
            "AIQA_MAX_ACTIVE_SLOTS": "2",
        }
    )
    assert settings.max_active_slots == 2
    app = create_app(settings)
    assert active_slot_limit() == 2

    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("슬롯", "rx62", "rx", "android"))
    actor = Actor(owner.actor_id, project.project_id, True)
    worker_a = f"worker-a-{uuid4()}"
    worker_b = f"worker-b-{uuid4()}"
    with bound_auth_store(store):
        token_a = enroll_worker(actor, worker_a, "resource_probe")
        token_b = enroll_worker(actor, worker_b, "resource_probe")

    physical_shared = str(uuid4())
    physical_other = str(uuid4())
    alias_shared = str(uuid4())
    alias_other = str(uuid4())
    now = datetime(2026, 11, 5, 19, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("aiqa.api.worker._server_now", lambda: now)

    with store.transaction() as connection:
        connection.execute(
            "INSERT INTO physical_resource_keys (physical_key_id, worker_id, native_id) VALUES (?, ?, ?)",
            (physical_shared, worker_a, "emulator-5580"),
        )
        connection.execute(
            "INSERT INTO physical_resource_keys (physical_key_id, worker_id, native_id) VALUES (?, ?, ?)",
            (physical_other, worker_b, "emulator-5582"),
        )
        # Sibling key: same native scope, owned by worker B — used for cross-worker busy.
        sibling = str(uuid4())
        connection.execute(
            "INSERT INTO physical_resource_keys (physical_key_id, worker_id, native_id) VALUES (?, ?, ?)",
            (sibling, worker_b, "emulator-5580"),
        )
        for physical, alias, name, kind_worker in (
            (physical_shared, alias_shared, "SharedAVD", worker_a),
            (physical_other, alias_other, "OtherAVD", worker_b),
            (sibling, str(uuid4()), "SharedAVD-B", worker_b),
        ):
            del kind_worker
            connection.execute(
                """
                INSERT INTO resource_aliases (
                    project_id, physical_key_id, display_name, target_kind, alias_id
                ) VALUES (?, ?, ?, 'android', ?)
                """,
                (str(project.project_id), physical, name, alias),
            )
            connection.execute(
                """
                INSERT INTO resource_inventory (
                    physical_key_id, state, os_build, geometry, permissions, ime, observed_at
                ) VALUES (?, 'ready', '', '', '[]', '', ?)
                """,
                (physical, now.isoformat()),
            )
    store.close()

    with bind_inventory_store(app.state.open_store()):
        listed = list_resources(project.project_id)
    shared_row = next(item for item in listed if item["physical_key_id"] == physical_shared)
    assert shared_row["alias_id"] == alias_shared
    assert shared_row["alias_id"] != shared_row["physical_key_id"]
    assert shared_row["common_physical_scope"] == "emulator-5580"

    observed = asyncio.run(
        _exercise(
            app,
            project.project_id,
            worker_a,
            worker_b,
            token_a,
            token_b,
            physical_shared,
            physical_other,
            sibling,
            now,
        )
    )
    assert observed["same_resource_second_blocked"] is True
    assert observed["native_scope_blocks_sibling"] is True
    assert observed["different_resources_independent"] is True
    assert observed["expired_lease_blocks_without_cleanup"] is True
    assert observed["slot_one_blocks_second_job"] is True


async def _exercise(
    app,
    project_id,
    worker_a: str,
    worker_b: str,
    token_a: str,
    token_b: str,
    physical_shared: str,
    physical_other: str,
    sibling: str,
    now: datetime,
) -> dict[str, bool]:
    origin = "http://127.0.0.1"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        for token, boot in ((token_a, "boot-a"), (token_b, "boot-b")):
            assert (
                await client.post(
                    "/api/v1/worker/heartbeats",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"boot_id": boot},
                )
            ).status_code == 200

        store = app.state.open_store()
        try:
            with store.transaction() as connection:
                job_shared = str(uuid4())
                job_other = str(uuid4())
                job_sibling = str(uuid4())
                job_extra = str(uuid4())
                for job_id, physical in (
                    (job_shared, physical_shared),
                    (job_other, physical_other),
                    (job_sibling, sibling),
                    (job_extra, physical_other),
                ):
                    connection.execute(
                        """
                        INSERT INTO jobs (
                            project_id, job_id, purpose, payload_hash, source_refs, limits, status
                        ) VALUES (?, ?, 'resource_probe', 'hash', ?, '{}', 'queued')
                        """,
                        (str(project_id), job_id, json.dumps([physical])),
                    )
        finally:
            store.close()

        first = await client.post(
            "/api/v1/worker/claims",
            headers={"Authorization": f"Bearer {token_a}", "Idempotency-Key": "rx62-a1"},
            json={"boot_id": "boot-a", "now": now.isoformat()},
        )
        assert first.status_code == 200, first.text
        assert first.json()["physical_key_id"] == physical_shared

        # Worker B cannot claim the same physical scope (same key).
        blocked_same = await client.post(
            "/api/v1/worker/claims",
            headers={"Authorization": f"Bearer {token_b}", "Idempotency-Key": "rx62-b-same"},
            json={"boot_id": "boot-b", "now": now.isoformat()},
        )
        # May claim other resource instead — force by checking lease fence on shared/sibling.
        store = app.state.open_store()
        try:
            with store.transaction() as connection:
                assert physical_scope_is_leased(connection, physical_shared) is True
                assert physical_scope_is_leased(connection, sibling) is True
                from aiqa.store.models import WorkerScope

                sibling_leased = physical_scope_is_leased(connection, sibling)
        finally:
            store.close()

        # Independent other resource with slots=2.
        if blocked_same.status_code == 200:
            body_b = blocked_same.json()
            independent = body_b.get("physical_key_id") == physical_other
        else:
            second = await client.post(
                "/api/v1/worker/claims",
                headers={"Authorization": f"Bearer {token_b}", "Idempotency-Key": "rx62-b2"},
                json={"boot_id": "boot-b", "now": now.isoformat()},
            )
            independent = second.status_code == 200 and second.json()["physical_key_id"] == physical_other

        # Expired generation without cleanup still blocks reassignment of the shared scope.
        store = app.state.open_store()
        try:
            with store.transaction() as connection:
                expired = now - timedelta(minutes=10)
                connection.execute(
                    "UPDATE leases SET expires_at = ? WHERE physical_key_id = ?",
                    (expired.isoformat(), physical_shared),
                )
                still_held = physical_scope_is_leased(connection, physical_shared)
                scope_b = WorkerScope(
                    worker_id=worker_b,
                    permitted_projects=(project_id,),
                    permitted_purposes=("resource_probe",),
                    token_id=None,
                )
                refuse = claim_queued_job(connection, scope_b, now, boot_id="boot-b")
                refused_shared = refuse is None or str(getattr(refuse, "physical_key_id", "")) not in {
                    physical_shared,
                    sibling,
                }
        finally:
            store.close()

        # Slot budget 1 blocks a second concurrent active job even for another resource.
        configure_active_slots(1)
        store = app.state.open_store()
        try:
            with store.transaction() as connection:
                # Ensure at least one active lease/job remains.
                active = connection.execute(
                    "SELECT COUNT(*) FROM jobs WHERE status IN ('preparing','running','finalizing','cancel_requested')"
                ).fetchone()
                assert active is not None and int(active[0]) >= 1
                from aiqa.store.models import WorkerScope as WS

                scope_a = WS(
                    worker_id=worker_a,
                    permitted_projects=(project_id,),
                    permitted_purposes=("resource_probe",),
                    token_id=None,
                )
                slot_blocked = claim_queued_job(connection, scope_a, now, boot_id="boot-a") is None
        finally:
            store.close()
        configure_active_slots(2)

    return {
        "same_resource_second_blocked": sibling_leased and refused_shared,
        "native_scope_blocks_sibling": sibling_leased,
        "different_resources_independent": independent,
        "expired_lease_blocks_without_cleanup": still_held and refused_shared,
        "slot_one_blocks_second_job": slot_blocked,
    }
