"""Inventory reports share one physical key per worker serial. No device is opened."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

from aiqa.contracts.resources import (
    INVENTORY_STATES,
    InventoryReceipt,
    InventoryReport,
    ResourcePreviewView,
    new_resource_alias_id,
    require_target_kind,
    resource_key,
)
from aiqa.contracts.jobs import IdempotencyKey, JobReceipt, JobSubmission
from aiqa.environments.android_observation import AndroidObservationProvider, AndroidObservationResult
from aiqa.environments.usb_android import InstalledAppsObservation, list_installed_apps
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
_INVENTORY_READY_AGE = timedelta(minutes=15)
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


def inventory_from_observation(
    result: AndroidObservationResult,
    *,
    expected_serial: str | None = None,
) -> InventoryReport:
    """Map one AD-01 observation to the four inventory states. Raw pixels stay out."""

    mismatched = expected_serial is not None and result.serial != expected_serial
    if mismatched:
        state = "offline"
        reason = "serial_mismatch"
    else:
        state = _inventory_state(result.state)
        reason = result.reason
    geometry = ""
    rotation = None
    if result.geometry is not None and not mismatched:
        rotation = int(result.geometry.rotation)
        geometry = f"{result.geometry.physical_width}x{result.geometry.physical_height}@{rotation}"
    os_build = ""
    if result.android_release is not None and result.api_level is not None:
        os_build = f"Android {result.android_release} API {result.api_level}"
    elif result.model is not None:
        os_build = result.model
    if result.device_kind == "android_emulator":
        label = result.avd_name or result.serial
        display_name = f"{label} 에뮬레이터"
    else:
        display_name = result.model or result.serial
    permissions = {
        "device_kind": result.device_kind,
        "reason": reason,
        "rotation": rotation,
        "raw_upload": 0,
    }
    return InventoryReport(
        native_id=result.serial if not mismatched else (expected_serial or result.serial),
        target_kind="android",
        state=state,
        os_build=os_build or "unknown",
        geometry=geometry or "unknown",
        permissions=json.dumps(permissions, sort_keys=True),
        ime="unknown",
        observed_at=result.observed_at,
        display_name=display_name,
        raw_handle=None,
    )


def report_android_observation(
    worker: WorkerScope,
    provider: AndroidObservationProvider,
    *,
    expected_serial: str | None = None,
) -> InventoryReceipt:
    """Publish metadata-only observation through the authenticated inventory path.

    Capture pixels are not uploaded. Preview stays unobserved until a typed owner exists.
    """

    result = provider.observe(capture=False)
    if result.observation is not None:
        raise ValueError("raw observation bytes cannot enter inventory")
    provider_serial = getattr(provider, "serial", None)
    expected = expected_serial if expected_serial is not None else (
        provider_serial if type(provider_serial) is str else result.serial
    )
    return report_inventory(worker, inventory_from_observation(result, expected_serial=expected))


def android_inventory_payload(report: InventoryReport, *, project_id: str) -> dict[str, object]:
    """HTTP body for WorkerHttpClient.report_inventory. No pixel fields."""

    return {
        "project_id": project_id,
        "native_id": report.native_id,
        "target_kind": report.target_kind,
        "state": report.state,
        "os_build": report.os_build,
        "geometry": report.geometry,
        "permissions": report.permissions,
        "ime": report.ime,
        "observed_at": report.observed_at,
        "display_name": report.display_name,
        "raw_handle": None,
    }


def assemble_android_inventory_payload(
    provider: AndroidObservationProvider,
    *,
    project_id: str,
    expected_serial: str,
) -> dict[str, object] | None:
    """Probe one dedicated serial into an inventory HTTP body. Ready is omitted on failure.

    Raw pixels, arbitrary serial selection, and capture uploads stay closed.
    """

    if type(project_id) is not str or project_id.strip() == "":
        return None
    if type(expected_serial) is not str or expected_serial.strip() == "":
        return None
    try:
        result = provider.observe(capture=False)
    except Exception:
        return None
    if result.observation is not None:
        return None
    report = inventory_from_observation(result, expected_serial=expected_serial)
    payload = android_inventory_payload(report, project_id=project_id)
    # Refuse any accidental pixel-bearing keys before the HTTP client.
    forbidden = {"png", "pixels", "screenshot", "observation", "image"}
    if forbidden.intersection(payload):
        return None
    return payload


def report_inventory(worker: WorkerScope, report: InventoryReport) -> InventoryReceipt:
    if report.state not in INVENTORY_STATES:
        raise ValueError("inventory state is invalid")
    if report.raw_handle is not None:
        raise ValueError("raw device handles are not stored in inventory")
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
        alias_id = new_resource_alias_id()
        connection.execute(
            """
            INSERT INTO resource_aliases (project_id, physical_key_id, display_name, target_kind, alias_id)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (project_id, physical_key_id) DO UPDATE SET
                display_name = excluded.display_name
            """,
            (str(project_id), physical_key_id, report.display_name, target_kind, alias_id),
        )
        # Preserve an existing alias_id on conflict (SQLite keeps prior row values for unset cols).
        existing_alias = connection.execute(
            """
            SELECT alias_id FROM resource_aliases
            WHERE project_id = ? AND physical_key_id = ?
            """,
            (str(project_id), physical_key_id),
        ).fetchone()
        if existing_alias is None or existing_alias[0] in (None, ""):
            connection.execute(
                """
                UPDATE resource_aliases SET alias_id = ?
                WHERE project_id = ? AND physical_key_id = ?
                """,
                (alias_id, str(project_id), physical_key_id),
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
                   quarantine.physical_key_id, physical.worker_id, inventory.permissions,
                   aliases.alias_id, physical.native_id
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
            device_kind = _device_kind("" if row[9] is None else str(row[9]))
            rotation = _rotation_of("" if row[9] is None else str(row[9]), "" if row[5] is None else str(row[5]))
            alias_id = "" if row[10] is None else str(row[10])
            if alias_id == "":
                # Pre-0047 rows or fixtures that omitted alias_id stay readable.
                alias_id = new_resource_alias_id()
                connection.execute(
                    """
                    UPDATE resource_aliases
                    SET alias_id = ?
                    WHERE project_id = ? AND physical_key_id = ?
                      AND (alias_id IS NULL OR alias_id = '')
                    """,
                    (alias_id, str(project_id), resource_id),
                )
            native_id = "" if row[11] is None else str(row[11])
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
            stale_ready = state == "ready" and not _fresh_for_ready(observed, now)
            if stale_ready:
                state = "offline"
            if online:
                block_reason = (
                    "최근 기기 관찰이 오래되었습니다. 워커가 다시 보고할 때까지 대기하세요."
                    if stale_ready
                    else _DEVICE_BLOCKS.get(state, "")
                )
            elif presence.state == "offline":
                block_reason = "실행 PC가 오프라인입니다. 연결이 복구되면 다시 확인하세요."
            else:
                block_reason = "실행 PC의 연결 보고가 없습니다. 워커를 실행한 뒤 다시 확인하세요."
            reason = _preview_reason(state, observed, observation is not None)
            listed.append(
                {
                    "resource_id": resource_id,
                    "alias_id": alias_id,
                    "physical_key_id": resource_id,
                    "common_physical_scope": native_id,
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
                    "rotation": rotation,
                    "observed_at": observed,
                    "availability": "unavailable" if observation is None else "observed",
                    "reason": reason,
                    "device_kind": device_kind,
                    "is_emulator": device_kind == "android_emulator",
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


def _inventory_state(observed: str) -> str:
    if observed == "ready":
        return "ready"
    if observed == "unauthorized":
        return "unauthorized"
    if observed in {"offline", "booting", "unavailable", "capture_unavailable"}:
        return "offline"
    raise ValueError("observation state is invalid")


def _device_kind(permissions: str) -> str:
    if permissions.strip() == "":
        return ""
    try:
        payload = json.loads(permissions)
    except json.JSONDecodeError:
        return ""
    if type(payload) is not dict:
        return ""
    kind = payload.get("device_kind")
    return kind if type(kind) is str else ""


def _rotation_of(permissions: str, geometry: str) -> int | None:
    if permissions.strip() != "":
        try:
            payload = json.loads(permissions)
        except json.JSONDecodeError:
            payload = None
        if type(payload) is dict and type(payload.get("rotation")) is int:
            return int(payload["rotation"])
    if "@" in geometry:
        try:
            return int(geometry.rsplit("@", 1)[1])
        except ValueError:
            return None
    return None


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


def _fresh_for_ready(observed_at: str, now: datetime) -> bool:
    """Inventory ready requires a recent probe. Heartbeat alone is not enough."""

    if observed_at.strip() == "":
        return False
    parsed = datetime.fromisoformat(observed_at)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return False
    return now.astimezone(timezone.utc) - parsed.astimezone(timezone.utc) <= _INVENTORY_READY_AGE


def submit_diagnostic(
    actor: Actor,
    project_id: UUID,
    resource_id: UUID,
    kind: str,
    provider: str,
    proof: str | None,
    request_key: str,
) -> tuple[object, bool]:
    """Queue a management probe or recovery. Ready waits for VM proof.

    kind=installed_apps requires an Android resource with a physical lease and
    completes the fixture listing without install/reset.
    """

    if provider not in {"fixture", "worker"}:
        raise DiagnosticBlocked("provider is not configured")
    if kind not in {"probe", "recovery", "installed_apps"}:
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
        target_kind = str(alias[0])
        if kind == "installed_apps":
            if target_kind != "android":
                raise DiagnosticBlocked("installed_apps requires android")
            # fixture lists in-process under an existing physical lease.
            # provider=worker queues for claim; the claim itself creates the fence.
            if provider == "fixture":
                lease = connection.execute(
                    """
                    SELECT 1 FROM leases
                    WHERE project_id = ? AND physical_key_id = ?
                    """,
                    (str(project_id), str(resource_id)),
                ).fetchone()
                if lease is None:
                    raise DiagnosticBlocked("physical lease is required")
            ready = False
        if target_kind == "web" and proof != "vm-present":
            ready = False
        limits_payload: dict[str, object] = {
            "kind": kind,
            "qa": None,
            "ready": ready,
            "resource_id": str(resource_id),
            "provider": provider,
        }
        receipt = enqueue_job(
            Transaction(connection),
            JobSubmission(
                project_id,
                "resource_probe",
                None,
                None,
                (str(resource_id),),
                json.dumps(limits_payload, sort_keys=True),
            ),
            IdempotencyKey(actor.actor_id, project_id, "enqueue_job", request_key),
        )
        # provider=worker leaves the job queued for a registered Android worker claim.
        if kind == "installed_apps" and provider == "fixture" and not receipt.replayed:
            observation = _run_installed_apps_listing(connection, resource_id)
            limits_payload = _installed_apps_limits(observation, ready=observation.state == "ready")
            limits_payload["resource_id"] = str(resource_id)
            connection.execute(
                "UPDATE jobs SET status = 'completed', limits = ? WHERE project_id = ? AND job_id = ?",
                (json.dumps(limits_payload, sort_keys=True), str(project_id), str(receipt.job_id)),
            )
            connection.execute(
                """
                UPDATE job_receipts SET status = 'completed'
                WHERE project_id = ? AND job_id = ? AND operation = 'enqueue_job' AND request_key = ?
                """,
                (str(project_id), str(receipt.job_id), request_key),
            )
            receipt = JobReceipt(
                job_id=receipt.job_id,
                purpose=receipt.purpose,
                status="completed",
                recording_id=receipt.recording_id,
                execution_id=receipt.execution_id,
                case_run_id=receipt.case_run_id,
                status_href=receipt.status_href,
                replayed=receipt.replayed,
                body_hash=receipt.body_hash,
            )
            ready = observation.state == "ready"
    return receipt, ready


def latest_installed_apps(project_id: UUID, resource_id: UUID) -> dict[str, object] | None:
    """Return the newest completed installed_apps probe for one resource. No ADB call."""

    refs = json.dumps([str(resource_id)], ensure_ascii=False, separators=(",", ":"))
    with _bound_store().transaction() as connection:
        rows = connection.execute(
            """
            SELECT limits FROM jobs
            WHERE project_id = ? AND purpose = 'resource_probe' AND status = 'completed'
              AND source_refs = ?
            ORDER BY rowid DESC
            """,
            (str(project_id), refs),
        ).fetchall()
    for row in rows:
        limits = json.loads(str(row[0]))
        if str(limits.get("kind", "")) != "installed_apps":
            continue
        apps = limits.get("apps")
        if type(apps) is not list:
            apps = []
        return {
            "resource_id": str(resource_id),
            "serial": str(limits.get("serial", "")),
            "state": str(limits.get("state", "unavailable")),
            "reason": str(limits.get("reason", "")),
            "observed_at": str(limits.get("observed_at", "")),
            "apps": apps,
            "install_calls": int(limits.get("install_calls", 0) or 0),
            "reset_calls": int(limits.get("reset_calls", 0) or 0),
            "qa": None,
        }
    return None


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


def _run_installed_apps_listing(connection: object, resource_id: UUID) -> InstalledAppsObservation:
    row = connection.execute(
        """
        SELECT native_id FROM physical_resource_keys
        WHERE physical_key_id = ?
        """,
        (str(resource_id),),
    ).fetchone()
    if row is None:
        return InstalledAppsObservation(
            serial="",
            state="unavailable",
            reason="resource_missing",
            observed_at=datetime.now(timezone.utc).isoformat(),
            apps=(),
            install_calls=0,
            reset_calls=0,
        )
    serial = str(row[0])
    adb = Path(str(os.environ.get("AIQA_ADB_PATH", r"C:\sdk\adb.exe")).strip() or r"C:\sdk\adb.exe")
    return list_installed_apps(adb, serial, expected_serial=serial)


def _installed_apps_limits(observation: InstalledAppsObservation, *, ready: bool) -> dict[str, object]:
    return {
        "kind": "installed_apps",
        "qa": None,
        "ready": ready,
        "serial": observation.serial,
        "state": observation.state,
        "reason": observation.reason,
        "observed_at": observation.observed_at,
        "install_calls": observation.install_calls,
        "reset_calls": observation.reset_calls,
        "apps": [
            {
                "package": app.package,
                "version_name": app.version_name,
                "api_level": app.api_level,
                "abi": app.abi,
                "content_hash": app.content_hash,
            }
            for app in observation.apps
        ],
    }


def _bound_store() -> Store:
    try:
        return _store.get()
    except LookupError as exc:
        raise RuntimeError("inventory store is not bound") from exc
