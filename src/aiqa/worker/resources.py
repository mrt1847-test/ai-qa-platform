"""Inventory reports share one physical key per worker serial. No device is opened."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from aiqa.contracts.resources import (
    INVENTORY_STATES,
    InventoryReceipt,
    InventoryReport,
    ResourcePreviewView,
    require_target_kind,
    resource_key,
)
from aiqa.contracts.jobs import IdempotencyKey, JobSubmission
from aiqa.store.database import Store
from aiqa.store.models import Actor, Transaction, WorkerScope
from aiqa.store.queue import enqueue_job
from aiqa.worker.presence import get_presence

_store: ContextVar[Store] = ContextVar("aiqa_inventory_store")


class InventoryDenied(Exception):
    """The worker cannot report this project."""


class PreviewDenied(Exception):
    """This session cannot see the resource preview."""


class DiagnosticBlocked(Exception):
    """A diagnostic provider or recovery proof is missing."""


_OBSERVATION_RETENTION = timedelta(days=30)
_KIND_LABELS = {"web": "Web", "android": "Android"}
_STATE_LABELS = {
    "ready": "준비",
    "busy": "사용 중",
    "cleanup_pending": "정리 확인 필요",
    "offline": "오프라인",
    "unauthorized": "권한 없음",
    "quarantine": "격리",
    "unavailable": "사용할 수 없음",
}
_CONNECTION_LABELS = {"online": "연결됨", "offline": "오프라인", "unknown": "연결 보고 없음"}
_DEVICE_BLOCKS = {
    "busy": "기기가 사용 중입니다. 점유 작업이 끝난 뒤 다시 확인하세요.",
    "cleanup_pending": "이전 작업의 기기 정리를 확인해야 새 작업을 시작할 수 있습니다.",
    "offline": "기기가 오프라인입니다. 실행 PC에서 기기 연결을 확인하세요.",
    "unauthorized": "기기 제어 권한을 확인하세요.",
    "quarantine": "기기가 격리되었습니다. 진단에서 복구 조건을 확인하세요.",
    "unavailable": "기기 상태를 확인할 수 없습니다.",
}


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


def list_resources(project_id: UUID) -> tuple[dict[str, object], ...]:
    """List project aliases. This does not open a device."""

    store = _bound_store()
    with store.transaction() as connection:
        rows = connection.execute(
            """
            SELECT aliases.physical_key_id, aliases.display_name, aliases.target_kind,
                   inventory.state, inventory.os_build, inventory.geometry, inventory.observed_at,
                   quarantine.physical_key_id, physical.worker_id
            FROM resource_aliases AS aliases
            JOIN physical_resource_keys AS physical USING (physical_key_id)
            LEFT JOIN resource_inventory AS inventory
              ON inventory.physical_key_id = aliases.physical_key_id
            LEFT JOIN resource_quarantine AS quarantine
              ON quarantine.physical_key_id = aliases.physical_key_id
            WHERE aliases.project_id = ?
            ORDER BY aliases.display_name
            """,
            (str(project_id),),
        ).fetchall()
        listed = []
        now = datetime.now(timezone.utc)
        connections = {}
        for row in rows:
            resource_id = str(row[0])
            inventory_state = None if row[3] is None else str(row[3])
            state = "quarantine" if row[7] is not None else (inventory_state or "unavailable")
            worker_id = str(row[8])
            if worker_id not in connections:
                connections[worker_id] = get_presence(connection, worker_id, now, project_id=project_id)
            presence = connections[worker_id]
            online = presence.state == "online"
            observed = "" if row[6] is None else str(row[6])
            observation = connection.execute(
                """
                SELECT artifact_id, captured_at FROM resource_observations
                WHERE project_id = ? AND resource_id = ?
                ORDER BY captured_at DESC LIMIT 1
                """,
                (str(project_id), resource_id),
            ).fetchone()
            lease = connection.execute(
                """
                SELECT leases.project_id, leases.job_id, jobs.status
                FROM leases JOIN jobs USING (project_id, job_id)
                WHERE leases.physical_key_id = ?
                LIMIT 1
                """,
                (resource_id,),
            ).fetchone()
            if state in {"ready", "busy"} and lease is not None:
                state = "cleanup_pending" if lease[2] in {"completed", "error", "cancelled", "lost"} else "busy"
            if online:
                block_reason = _DEVICE_BLOCKS.get(state, "")
            elif presence.state == "offline":
                block_reason = "실행 PC가 오프라인입니다. 연결이 복구되면 다시 확인하세요."
            else:
                block_reason = "실행 PC의 연결 보고가 없습니다. 워커를 실행한 뒤 다시 확인하세요."
            reason = _preview_reason(state, observed, observation is not None)
            listed.append(
                {
                    "resource_id": resource_id,
                    "display_name": str(row[1]),
                    "target_kind": str(row[2]),
                    "kind_label": _KIND_LABELS.get(str(row[2]), str(row[2])),
                    "state": state,
                    "state_label": _STATE_LABELS.get(state, state),
                    "worker_id": worker_id,
                    "connection_state": presence.state,
                    "connection_label": _CONNECTION_LABELS[presence.state],
                    "last_seen": None if presence.last_seen is None else presence.last_seen.isoformat(),
                    "can_execute": online and state == "ready",
                    "can_diagnose": online,
                    "block_reason": block_reason,
                    "os_build": "" if row[4] is None else str(row[4]),
                    "geometry": "" if row[5] is None else str(row[5]),
                    "observed_at": observed,
                    "availability": "unavailable" if observation is None else "observed",
                    "reason": reason,
                    "run_href": None
                    if lease is None or lease[0] != str(project_id)
                    else f"/ui/projects/{project_id}/environments?run={lease[1]}",
                }
            )
    return tuple(listed)


def preview_resource(project_id: UUID, resource_id: UUID) -> ResourcePreviewView:
    """Return the latest redacted observation. A preview is not device control."""

    store = _bound_store()
    with store.transaction() as connection:
        row = connection.execute(
            """
            SELECT inventory.state, inventory.geometry, inventory.observed_at, quarantine.physical_key_id
            FROM resource_aliases AS aliases
            LEFT JOIN resource_inventory AS inventory
              ON inventory.physical_key_id = aliases.physical_key_id
            LEFT JOIN resource_quarantine AS quarantine
              ON quarantine.physical_key_id = aliases.physical_key_id
            WHERE aliases.project_id = ? AND aliases.physical_key_id = ?
            """,
            (str(project_id), str(resource_id)),
        ).fetchone()
        if row is None:
            raise PreviewDenied("resource was not found")
        state = "quarantine" if row[3] is not None else (None if row[0] is None else str(row[0]))
        if state == "unauthorized":
            raise PreviewDenied("preview is not allowed")
        if state == "busy":
            lease = connection.execute(
                """
                SELECT 1 FROM leases
                WHERE project_id = ? AND physical_key_id = ?
                LIMIT 1
                """,
                (str(project_id), str(resource_id)),
            ).fetchone()
            if lease is None:
                raise PreviewDenied("preview is not allowed")
        observation = connection.execute(
            """
            SELECT artifact_id, captured_at, geometry FROM resource_observations
            WHERE project_id = ? AND resource_id = ?
            ORDER BY captured_at DESC LIMIT 1
            """,
            (str(project_id), str(resource_id)),
        ).fetchone()
    observed = None if row[2] is None else str(row[2])
    captured = None if observation is None else str(observation[1])
    stamp = captured or observed
    reason = _preview_reason(state or "unavailable", stamp or "", observation is not None)
    artifact = None if observation is None or reason != "observed" else str(observation[0])
    geometry = "" if row[1] is None else str(row[1])
    if observation is not None and reason == "observed":
        geometry = str(observation[2])
    return ResourcePreviewView(resource_id, state or "unavailable", stamp, geometry, artifact, reason, False)


def _preview_reason(state: str, observed_at: str, has_observation: bool) -> str:
    if state == "unauthorized":
        return "unauthorized"
    if _stale(observed_at):
        return "expired"
    if not has_observation:
        return "unobserved"
    return "observed"


def _stale(observed_at: str) -> bool:
    if observed_at.strip() == "":
        return False
    parsed = datetime.fromisoformat(observed_at)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return True
    return datetime.now(timezone.utc) - parsed.astimezone(timezone.utc) > _OBSERVATION_RETENTION


def submit_diagnostic(
    actor: Actor,
    project_id: UUID,
    resource_id: UUID,
    kind: str,
    provider: str,
    proof: str | None,
    request_key: str,
) -> tuple[object, bool]:
    """Queue a management probe or recovery. Ready waits for VM proof."""

    if provider != "fixture":
        raise DiagnosticBlocked("provider is not configured")
    if kind not in {"probe", "recovery"}:
        raise DiagnosticBlocked("diagnostic kind is invalid")
    if kind == "recovery" and (proof is None or proof.strip() == ""):
        raise DiagnosticBlocked("recovery requires proof")
    ready = kind == "probe" and proof == "vm-present"
    store = _bound_store()
    with store.transaction() as connection:
        alias = connection.execute(
            """
            SELECT target_kind FROM resource_aliases
            WHERE project_id = ? AND physical_key_id = ?
            """,
            (str(project_id), str(resource_id)),
        ).fetchone()
        if alias is None:
            raise PreviewDenied("resource was not found")
        if str(alias[0]) == "web" and proof != "vm-present":
            ready = False
        receipt = enqueue_job(
            Transaction(connection),
            JobSubmission(
                project_id,
                "resource_probe",
                None,
                None,
                (str(resource_id),),
                json.dumps({"kind": kind, "qa": None, "ready": ready}, sort_keys=True),
            ),
            IdempotencyKey(actor.actor_id, project_id, "enqueue_job", request_key),
        )
    return receipt, ready


def list_diagnostic_jobs(project_id: UUID) -> tuple[dict[str, object], ...]:
    """List probe jobs for the environment page. This does not open a device."""

    with _bound_store().transaction() as connection:
        rows = connection.execute(
            """
            SELECT job_id, status, limits FROM jobs
            WHERE project_id = ? AND purpose = 'resource_probe'
            ORDER BY job_id
            """,
            (str(project_id),),
        ).fetchall()
    listed = []
    for row in rows:
        limits = json.loads(str(row[2]))
        listed.append(
            {
                "job_id": str(row[0]),
                "status": str(row[1]),
                "kind": str(limits.get("kind", "probe")),
                "ready": bool(limits.get("ready")),
            }
        )
    return tuple(listed)


def _bound_store() -> Store:
    try:
        return _store.get()
    except LookupError as exc:
        raise RuntimeError("inventory store is not bound") from exc
