"""Server-clock presence for registered execution hosts."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import sqlite3
from uuid import UUID, uuid4

from aiqa.store.models import WorkerIncarnation, WorkerScope

HEARTBEAT_SECONDS = 10
OFFLINE_AFTER = timedelta(seconds=45)


class PresenceDenied(Exception):
    """The worker credential no longer authorizes this report."""


@dataclass(frozen=True, slots=True)
class WorkerPresence:
    state: str
    last_seen: datetime | None = None
    boot_id: str | None = None
    session_id: str | None = None


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("presence time requires a timezone")
    return value.astimezone(timezone.utc)


def get_presence(
    connection: sqlite3.Connection, worker_id: str, now: datetime, *, project_id: UUID | str | None = None
) -> WorkerPresence:
    now = _utc(now)
    project = None if project_id is None else str(project_id)
    rows = connection.execute(
        """SELECT presence.last_seen, presence.boot_id, presence.session_id
           FROM worker_presence AS presence
           JOIN worker_tokens AS token ON token.token_id = presence.token_id
           WHERE presence.worker_id = ? AND (? IS NULL OR presence.project_id = ?)""",
        (worker_id, project, project),
    ).fetchall()
    if len(rows) != 1:
        return WorkerPresence("unknown")
    last_seen, boot_id, session_id = rows[0]
    received = _utc(datetime.fromisoformat(last_seen))
    state = "online" if timedelta(0) <= now - received < OFFLINE_AFTER else "offline"
    return WorkerPresence(state, received, boot_id, session_id)


def report_presence(
    connection: sqlite3.Connection, worker: WorkerScope, boot_id: str, now: datetime
) -> WorkerPresence:
    now = _utc(now)
    if type(boot_id) is not str or not 1 <= len(boot_id) <= 128 or not boot_id.isascii() or not boot_id.isprintable() or not boot_id.strip():
        raise ValueError("boot id is invalid")
    if len(worker.permitted_projects) != 1 or len(worker.permitted_purposes) != 1:
        raise PresenceDenied
    project_id = worker.permitted_projects[0]
    credential = connection.execute(
        """SELECT token.expires_at FROM worker_tokens AS token
           JOIN worker_enrollments AS enrollment USING (enrollment_id)
           WHERE token.token_id = ? AND enrollment.project_id = ?
             AND enrollment.worker_id = ? AND token.purpose = ?""",
        (worker.token_id, str(project_id), worker.worker_id, worker.permitted_purposes[0]),
    ).fetchone()
    if credential is None:
        raise PresenceDenied
    if credential[0] is not None and datetime.fromisoformat(str(credential[0])) <= now:
        raise PresenceDenied
    if connection.execute(
        "SELECT 1 FROM worker_retired_boots WHERE project_id = ? AND worker_id = ? AND boot_id = ?",
        (str(project_id), worker.worker_id, boot_id),
    ).fetchone():
        raise PresenceDenied
    previous = get_presence(connection, worker.worker_id, now, project_id=project_id)
    if previous.boot_id is not None and previous.boot_id != boot_id:
        connection.execute(
            "INSERT INTO worker_retired_boots VALUES (?, ?, ?, ?)",
            (str(project_id), worker.worker_id, previous.boot_id, worker.token_id),
        )
    session_id = previous.session_id if previous.state == "online" and previous.boot_id == boot_id else str(uuid4())
    connection.execute(
        """INSERT INTO worker_presence VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(project_id, worker_id) DO UPDATE SET
           token_id=excluded.token_id, boot_id=excluded.boot_id,
           last_seen=excluded.last_seen, session_id=excluded.session_id""",
        (str(project_id), worker.worker_id, worker.token_id, boot_id, now.isoformat(), session_id),
    )
    return WorkerPresence("online", now, boot_id, session_id)


def incarnation_of(worker_id: str, presence: WorkerPresence) -> WorkerIncarnation | None:
    """Build the registered generation, or nothing when the worker is not online."""

    if presence.state != "online" or presence.session_id is None or presence.boot_id is None:
        return None
    return WorkerIncarnation(worker_id, presence.session_id, presence.boot_id)
