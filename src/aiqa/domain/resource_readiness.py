"""Read execution admission state without requiring a live device connection."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from aiqa.worker.presence import get_presence


@dataclass(frozen=True, slots=True)
class ResourceReadiness:
    ready: bool
    code: str = ""
    message: str = ""
    job_id: str = ""


def resource_readiness(
    connection: sqlite3.Connection, project_id: UUID, resource_id: str, target_kind: str,
    *, now: datetime | None = None,
) -> ResourceReadiness:
    """Check admission without reserving a resource."""
    row = connection.execute(
        """
        SELECT aliases.target_kind, inventory.state, quarantine.physical_key_id, resource.worker_id
        FROM resource_aliases AS aliases
        JOIN physical_resource_keys AS resource USING (physical_key_id)
        LEFT JOIN resource_inventory AS inventory
          ON inventory.physical_key_id = aliases.physical_key_id
        LEFT JOIN resource_quarantine AS quarantine
          ON quarantine.physical_key_id = aliases.physical_key_id
        WHERE aliases.project_id = ? AND aliases.physical_key_id = ?
        """,
        (str(project_id), resource_id),
    ).fetchone()
    if row is None:
        return ResourceReadiness(False, "RESOURCE_UNAVAILABLE", "resource is missing")
    if target_kind not in {"web", "android"} or row[0] != target_kind:
        return ResourceReadiness(False, "RESOURCE_UNAVAILABLE", "resource target does not match")
    if row[2] is not None:
        return ResourceReadiness(False, "RESOURCE_UNAVAILABLE", "resource is quarantined")
    if row[1] == "busy":
        lease = connection.execute(
            """SELECT job_id FROM leases WHERE project_id = ? AND physical_key_id = ?
               ORDER BY generation DESC LIMIT 1""",
            (str(project_id), resource_id),
        ).fetchone()
        return ResourceReadiness(False, "RESOURCE_BUSY", "resource is busy", "" if lease is None else str(lease[0]))
    if row[1] == "unauthorized":
        return ResourceReadiness(False, "RESOURCE_UNAVAILABLE", "resource permission is missing")
    if row[1] != "ready":
        return ResourceReadiness(False, "RESOURCE_UNAVAILABLE", "resource is not ready")
    if get_presence(connection, row[3], now or datetime.now(timezone.utc), project_id=project_id).state != "online":
        return ResourceReadiness(False, "RESOURCE_UNAVAILABLE", "execution PC is offline or has not checked in")
    return ResourceReadiness(True)
