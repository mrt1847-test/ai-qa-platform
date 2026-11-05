"""RX-63: resource_aliases schema compatibility — named columns + legacy null alias_id."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from aiqa.api.app import create_app
from aiqa.api.auth import bound_auth_store, enroll_worker
from aiqa.config import load_settings
from aiqa.contracts.resources import new_resource_alias_id
from aiqa.domain.projects import bind_store, create_project
from aiqa.store.database import migrate_store
from aiqa.store.models import Actor, ProjectCreate
from aiqa.worker.resources import bind_inventory_store, list_resources
from worker_presence_support import seed_inventory, seed_presence, seed_resource_alias


def test_rx_63_named_insert_and_legacy_null_alias_backfill(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    settings = load_settings(
        {"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}
    )
    app = create_app(settings)
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("Compat63", "rx63", "rx", "web"))
    actor = Actor(owner.actor_id, project.project_id, True)
    worker_id = f"worker-rx63-{uuid4()}"
    with bound_auth_store(store):
        enroll_worker(actor, worker_id, "resource_probe")

    physical_named = str(uuid4())
    physical_legacy = str(uuid4())
    now = datetime(2026, 11, 5, 22, 0, tzinfo=timezone.utc)
    fixed_alias = new_resource_alias_id()

    with store.transaction() as connection:
        for physical, native in (
            (physical_named, "named-device"),
            (physical_legacy, "legacy-device"),
        ):
            connection.execute(
                "INSERT INTO physical_resource_keys (physical_key_id, worker_id, native_id) VALUES (?, ?, ?)",
                (physical, worker_id, native),
            )
            seed_inventory(connection, physical)
        seed_resource_alias(
            connection,
            project.project_id,
            physical_named,
            display_name="Named",
            target_kind="web",
            alias_id=fixed_alias,
        )
        # Pre-alias_id fixture shape: named columns, omit alias_id (NULL).
        connection.execute(
            """
            INSERT INTO resource_aliases (
                project_id, physical_key_id, display_name, target_kind
            ) VALUES (?, ?, ?, ?)
            """,
            (str(project.project_id), physical_legacy, "Legacy", "web"),
        )
        seed_presence(connection, project.project_id, worker_id, now)

    with bind_inventory_store(store):
        listed = list_resources(project.project_id)
    by_physical = {item["physical_key_id"]: item for item in listed}
    assert by_physical[physical_named]["alias_id"] == fixed_alias
    assert by_physical[physical_named]["alias_id"] != physical_named
    legacy_alias = by_physical[physical_legacy]["alias_id"]
    assert legacy_alias
    assert legacy_alias != physical_legacy

    with store.transaction() as connection:
        stored = connection.execute(
            "SELECT alias_id FROM resource_aliases WHERE physical_key_id = ?",
            (physical_legacy,),
        ).fetchone()
    assert stored is not None and stored[0] == legacy_alias
    store.close()
