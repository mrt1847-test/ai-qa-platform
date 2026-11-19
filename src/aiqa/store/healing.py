"""Durable healing episode reservation. One item keeps one episode."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from uuid import UUID, uuid4

_REASONS = frozenset({"target_not_found", "ambiguous", "layout_shift"})


class HealingRejected(Exception):
    """The lookup cannot reserve an episode."""


_UNSENT = frozenset({"planned", "lookup_failed"})


def unsent_action(connection: sqlite3.Connection, project_id: UUID, attempt_id: UUID, action_id: UUID) -> str | None:
    """None when this action is pinned and unsent. Other actions do not count."""

    row = connection.execute(
        """
        SELECT action_seq, dispatch_state FROM actions
        WHERE project_id = ? AND attempt_id = ? AND action_id = ?
        """,
        (str(project_id), str(attempt_id), str(action_id)),
    ).fetchone()
    if row is None or str(row[1]) not in _UNSENT:
        return "missing" if row is None else "sent"
    sent = connection.execute(
        """
        SELECT 1 FROM dispatch_journal
        WHERE project_id = ? AND attempt_id = ? AND action_seq = ?
          AND dispatch_state IN ('dispatch_started', 'acknowledged', 'observed', 'unknown')
        """,
        (str(project_id), str(attempt_id), int(row[0])),
    ).fetchone()
    return "sent" if sent is not None else None


def dispatch_started(connection: sqlite3.Connection, project_id: UUID, attempt_id: UUID) -> bool:
    row = connection.execute(
        """
        SELECT 1 FROM dispatch_journal
        WHERE project_id = ? AND attempt_id = ? AND dispatch_state = 'dispatch_started'
        """,
        (str(project_id), str(attempt_id)),
    ).fetchone()
    return row is not None


def lease_remaining_seconds(connection: sqlite3.Connection, project_id: UUID, job_id: UUID, now: datetime) -> int:
    row = connection.execute(
        """
        SELECT expires_at FROM leases
        WHERE project_id = ? AND job_id = ?
        ORDER BY generation DESC LIMIT 1
        """,
        (str(project_id), str(job_id)),
    ).fetchone()
    if row is None:
        return 0
    expires = datetime.fromisoformat(str(row[0]))
    if expires.tzinfo is None:
        return 0
    return int((expires - now).total_seconds())


def read_reservation(connection: sqlite3.Connection, project_id: UUID, case_run_id: UUID) -> tuple[UUID, int, int] | None:
    row = connection.execute(
        """
        SELECT episode_id, reserved_calls, reserved_seconds
        FROM healing_reservations
        WHERE project_id = ? AND case_run_id = ?
        """,
        (str(project_id), str(case_run_id)),
    ).fetchone()
    if row is None:
        return None
    return UUID(str(row[0])), int(row[1]), int(row[2])


def insert_reservation(
    connection: sqlite3.Connection,
    project_id: UUID,
    case_run_id: UUID,
    attempt_id: UUID,
    package_id: UUID,
    request_key: str,
    reason: str,
    reserved_calls: int,
    reserved_seconds: int,
    now: datetime,
    action_id: UUID | None = None,
) -> UUID:
    if reason not in _REASONS:
        raise HealingRejected("lookup reason is invalid")
    if request_key.strip() == "":
        raise HealingRejected("request key is missing")
    episode_id = uuid4()
    connection.execute(
        """
        INSERT INTO healing_episodes (
            project_id, episode_id, case_run_id, attempt_id, package_id, request_key
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (str(project_id), str(episode_id), str(case_run_id), str(attempt_id), str(package_id), request_key),
    )
    connection.execute(
        """
        INSERT INTO healing_reservations (
            project_id, reservation_id, episode_id, case_run_id, request_key, reason,
            reserved_calls, reserved_seconds, created_at, action_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(project_id),
            str(uuid4()),
            str(episode_id),
            str(case_run_id),
            request_key,
            reason,
            reserved_calls,
            reserved_seconds,
            now.isoformat(),
            None if action_id is None else str(action_id),
        ),
    )
    return episode_id
