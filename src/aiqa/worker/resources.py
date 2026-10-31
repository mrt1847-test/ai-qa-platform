"""Inventory reports share one physical key per worker serial. No device is opened."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import UUID, uuid4

from aiqa.contracts.resources import (
    INVENTORY_STATES,
    InventoryReceipt,
    InventoryReport,
    require_target_kind,
    resource_key,
)
from aiqa.store.database import Store
from aiqa.store.models import WorkerScope

_store: ContextVar[Store] = ContextVar("aiqa_inventory_store")


class InventoryDenied(Exception):
    """The worker cannot report this project."""


@contextmanager
def bind_inventory_store(store: Store) -> Iterator[None]:
    token = _store.set(store)
    try:
        yield
    finally:
        _store.reset(token)


def report_inventory(worker: WorkerScope, report: InventoryReport) -> InventoryReceipt:
    if report.state not in INVENTORY_STATES:
        raise ValueError("inventory state is invalid")
    target_kind = require_target_kind(report.target_kind)
    if len(worker.permitted_projects) != 1:
        raise InventoryDenied("worker project is missing")
    project_id = worker.permitted_projects[0]
    identity = resource_key(UUID(worker.worker_id), report.native_id)
    store = _bound_store()
    with store.transaction() as connection:
        row = connection.execute(
            """
            SELECT physical_key_id FROM physical_resource_keys
            WHERE worker_id = ? AND native_id = ?
            """,
            (worker.worker_id, report.native_id),
        ).fetchone()
        if row is None:
            physical_key_id = str(uuid4())
            connection.execute(
                """
                INSERT INTO physical_resource_keys (physical_key_id, worker_id, native_id)
                VALUES (?, ?, ?)
                """,
                (physical_key_id, worker.worker_id, report.native_id),
            )
        else:
            physical_key_id = str(row[0])
        connection.execute(
            """
            INSERT INTO resource_aliases (project_id, physical_key_id, display_name, target_kind)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (project_id, physical_key_id) DO UPDATE SET display_name = excluded.display_name
            """,
            (str(project_id), physical_key_id, report.display_name, target_kind),
        )
        connection.execute(
            """
            INSERT INTO resource_inventory (
                physical_key_id, state, os_build, geometry, permissions, ime, observed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (physical_key_id) DO UPDATE SET
                state = excluded.state,
                os_build = excluded.os_build,
                geometry = excluded.geometry,
                permissions = excluded.permissions,
                ime = excluded.ime,
                observed_at = excluded.observed_at
            """,
            (
                physical_key_id,
                report.state,
                report.os_build,
                report.geometry,
                report.permissions,
                report.ime,
                report.observed_at,
            ),
        )
        if report.state == "busy":
            held = connection.execute(
                "SELECT COUNT(*) FROM leases WHERE physical_key_id = ?",
                (physical_key_id,),
            ).fetchone()
            if held is not None and int(held[0]) == 0:
                job_id = str(uuid4())
                connection.execute(
                    """
                    INSERT INTO jobs (
                        project_id, job_id, purpose, recording_id, case_run_id,
                        payload_hash, source_refs, limits, status
                    ) VALUES (?, ?, 'resource_probe', NULL, NULL, 'inventory', ?, '{}', 'queued')
                    """,
                    (str(project_id), job_id, json.dumps([physical_key_id])),
                )
                connection.execute(
                    """
                    INSERT INTO leases (
                        project_id, job_id, generation, worker_id, physical_key_id, expires_at
                    ) VALUES (?, ?, 1, ?, ?, '2026-11-01T01:00:00+00:00')
                    """,
                    (str(project_id), job_id, worker.worker_id, physical_key_id),
                )
    return InventoryReceipt(
        physical_key_id=UUID(physical_key_id),
        resource_key=identity,
        state=report.state,
        project_id=project_id,
    )


def _bound_store() -> Store:
    try:
        return _store.get()
    except LookupError as exc:
        raise RuntimeError("inventory store is not bound") from exc
