"""Retention windows. Expiry removes payload and leaves the hash with a tombstone."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

DETAIL_WINDOW = timedelta(days=90)
FILE_WINDOW = timedelta(days=30)
SPOOL_WINDOW = timedelta(days=7)
DEBUG_WINDOW = timedelta(hours=24)

_CORE = frozenset({"core_fact", "approval", "manifest", "lineage", "content_hash", "ledger"})
_WINDOWS = {
    "detail": DETAIL_WINDOW,
    "png": FILE_WINDOW,
    "log": FILE_WINDOW,
    "acked_spool": SPOOL_WINDOW,
    "debug": DEBUG_WINDOW,
}


class RetentionRejected(ValueError):
    """The retention input cannot be planned."""


@dataclass(frozen=True, slots=True)
class UtcInstant:
    value: datetime


@dataclass(frozen=True, slots=True)
class RetentionSubject:
    kind: str
    subject_id: str
    stored_at: datetime
    content_hash: str
    path: str = ""
    acked: bool = False
    protected: bool = False


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    subjects: tuple[RetentionSubject, ...]


@dataclass(frozen=True, slots=True)
class RetentionAction:
    subject_id: str
    kind: str
    content_hash: str
    path: str
    expire_payload: bool
    tombstone: bool


@dataclass(frozen=True, slots=True)
class RetentionPlan:
    actions: tuple[RetentionAction, ...]
    core_facts_deleted: int
    expired_has_tombstone: bool
    unacked_spool_deleted: int
    old_stats_available: bool


def plan_retention(policy: RetentionPolicy, now: UtcInstant) -> RetentionPlan:
    """Choose payload expiry. Core facts and an unacked spool stay."""

    clock = _instant(now.value)
    actions: list[RetentionAction] = []
    core_deleted = 0
    for subject in policy.subjects:
        stored = _instant(subject.stored_at)
        if subject.kind in _CORE:
            continue
        if subject.kind == "unacked_spool":
            continue
        if subject.protected:
            continue
        window = _WINDOWS.get(subject.kind)
        if window is None:
            raise RetentionRejected("retention kind is unknown")
        if clock - stored < window:
            continue
        actions.append(
            RetentionAction(subject.subject_id, subject.kind, subject.content_hash, subject.path, True, True)
        )
    expired = tuple(actions)
    return RetentionPlan(expired, core_deleted, all(item.tombstone for item in expired), 0, core_deleted == 0)


def apply_retention(
    connection: sqlite3.Connection,
    project_id: UUID,
    plan: RetentionPlan,
    artifacts_dir: Path,
    spool_dir: Path,
    now: datetime,
) -> None:
    """Delete expired payload and write the tombstone. Rows that hold identity stay."""

    clock = _instant(now)
    for action in plan.actions:
        if not action.expire_payload or not action.tombstone:
            raise RetentionRejected("expiry requires a tombstone")
        if action.kind in _CORE or action.kind == "unacked_spool":
            raise RetentionRejected("core facts stay")
        if _protected(connection, project_id, action.subject_id):
            continue
        if action.kind == "detail":
            updated = connection.execute(
                """
                UPDATE attempt_events
                SET detail_payload = NULL
                WHERE project_id = ? AND event_id = ? AND sealed = 0
                """,
                (str(project_id), action.subject_id),
            )
            if updated.rowcount != 1:
                raise RetentionRejected("detail payload was not expired")
        else:
            root = artifacts_dir if action.kind in {"png", "log"} else spool_dir
            path = _inside(root, action.path)
            if path is None:
                raise RetentionRejected("retention path leaves its root")
            if path.is_file():
                path.unlink()
            if action.kind in {"png", "log"}:
                connection.execute(
                    """
                    UPDATE artifact_objects
                    SET custody = 'expired'
                    WHERE project_id = ? AND artifact_id = ?
                    """,
                    (str(project_id), action.subject_id),
                )
        connection.execute(
            """
            INSERT INTO retention_tombstones (
                project_id, tombstone_id, subject_kind, subject_id, content_hash, expired_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (str(project_id), str(uuid4()), action.kind, action.subject_id, action.content_hash, clock.isoformat()),
        )
        connection.execute(
            """
            INSERT INTO payload_retention_events (
                project_id, event_id, subject_kind, subject_id, content_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (str(project_id), str(uuid4()), action.kind, action.subject_id, action.content_hash, clock.isoformat()),
        )


def _protected(connection: sqlite3.Connection, project_id: UUID, subject_id: str) -> bool:
    row = connection.execute(
        """
        SELECT 1 FROM artifact_protections AS pins
        WHERE pins.project_id = ? AND pins.artifact_id = ?
          AND NOT EXISTS (
              SELECT 1 FROM protection_releases AS released
              WHERE released.project_id = pins.project_id AND released.protection_id = pins.protection_id
          )
        """,
        (str(project_id), subject_id),
    ).fetchone()
    return row is not None


def _instant(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise RetentionRejected("retention time needs a timezone")
    return value.astimezone(timezone.utc)


def _inside(root: Path, relative: str) -> Path | None:
    if type(relative) is not str or relative.strip() == "" or ".." in relative:
        return None
    if relative.startswith(("/", "\\")) or "\\" in relative or ":" in relative:
        return None
    base = root.resolve()
    path = (base / relative).resolve()
    if path != base and base not in path.parents:
        return None
    return path
