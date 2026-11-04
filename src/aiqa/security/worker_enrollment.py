"""Admin enrollment codes and revocable worker bearers. Raw secrets are not stored."""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from aiqa.store.models import Actor

DEFAULT_CODE_TTL = timedelta(minutes=15)
DEFAULT_TOKEN_TTL = timedelta(hours=24)


class EnrollmentDenied(Exception):
    """The actor or code cannot complete enrollment."""


class EnrollmentCodeRejected(Exception):
    """The enrollment code is unknown, reused, or expired."""


@dataclass(frozen=True, slots=True)
class EnrollmentCodeIssue:
    code: str
    worker_id: str
    purpose: str
    expires_at: str


@dataclass(frozen=True, slots=True)
class EnrollmentExchange:
    token: str
    worker_id: str
    project_id: UUID
    purpose: str
    expires_at: str


def actor_can_manage_workers(connection: sqlite3.Connection, actor: Actor) -> bool:
    """Local owners and project admins may issue, cancel, or revoke workers."""

    if actor.project_scope is None:
        return False
    if actor.is_local_owner:
        return True
    row = connection.execute(
        """
        SELECT role FROM project_memberships
        WHERE project_id = ? AND actor_id = ? AND revoked_at IS NULL
        """,
        (str(actor.project_scope), str(actor.actor_id)),
    ).fetchone()
    return row is not None and str(row[0]) == "admin"


def issue_enrollment_code(
    connection: sqlite3.Connection,
    actor: Actor,
    worker_id: str,
    purpose: str,
    *,
    now: datetime | None = None,
    ttl: timedelta = DEFAULT_CODE_TTL,
) -> EnrollmentCodeIssue:
    """Issue one admin enrollment code bound to worker_id and expiry."""

    moment = _utc(now or datetime.now(timezone.utc))
    if actor.project_scope is None:
        raise EnrollmentDenied("project was not found")
    if not actor_can_manage_workers(connection, actor):
        raise EnrollmentDenied("worker manage was denied")
    if type(worker_id) is not str or worker_id.strip() == "":
        raise EnrollmentDenied("worker id is missing")
    if type(purpose) is not str or purpose.strip() == "" or purpose == "approval":
        raise EnrollmentDenied("purpose is not enrollable")
    if ttl <= timedelta(0):
        raise EnrollmentDenied("enrollment code ttl is invalid")
    raw = secrets.token_urlsafe(32)
    expires_at = (moment + ttl).isoformat()
    created_at = moment.isoformat()
    enrollment_id = str(uuid4())
    connection.execute(
        """
        INSERT INTO worker_enrollments (enrollment_id, worker_id, project_id, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (enrollment_id, worker_id, str(actor.project_scope), created_at),
    )
    connection.execute(
        """
        INSERT INTO worker_enrollment_codes (
            code_id, code_hash, enrollment_id, purpose, expires_at, consumed_at, created_at
        ) VALUES (?, ?, ?, ?, ?, NULL, ?)
        """,
        (str(uuid4()), _hash(raw), enrollment_id, purpose, expires_at, created_at),
    )
    return EnrollmentCodeIssue(raw, worker_id, purpose, expires_at)


def exchange_enrollment_code(
    connection: sqlite3.Connection,
    code: str,
    worker_id: str,
    *,
    now: datetime | None = None,
    token_ttl: timedelta = DEFAULT_TOKEN_TTL,
) -> EnrollmentExchange:
    """Consume a one-time code and return a project-scoped revocable bearer."""

    moment = _utc(now or datetime.now(timezone.utc))
    if type(code) is not str or code.strip() == "":
        raise EnrollmentCodeRejected("enrollment code was rejected")
    if type(worker_id) is not str or worker_id.strip() == "":
        raise EnrollmentCodeRejected("enrollment code was rejected")
    if token_ttl <= timedelta(0):
        raise EnrollmentCodeRejected("enrollment code was rejected")
    row = connection.execute(
        """
        SELECT codes.code_id, codes.enrollment_id, codes.purpose, codes.expires_at, codes.consumed_at,
               enrollments.worker_id, enrollments.project_id
        FROM worker_enrollment_codes AS codes
        JOIN worker_enrollments AS enrollments
          ON enrollments.enrollment_id = codes.enrollment_id
        WHERE codes.code_hash = ?
        """,
        (_hash(code),),
    ).fetchone()
    if row is None:
        raise EnrollmentCodeRejected("enrollment code was rejected")
    code_id, enrollment_id, purpose, expires_at, consumed_at, bound_worker, project_id = row
    if consumed_at is not None:
        raise EnrollmentCodeRejected("enrollment code was rejected")
    if datetime.fromisoformat(str(expires_at)) <= moment:
        raise EnrollmentCodeRejected("enrollment code was rejected")
    if str(bound_worker) != worker_id:
        raise EnrollmentCodeRejected("enrollment code was rejected")
    updated = connection.execute(
        """
        UPDATE worker_enrollment_codes
        SET consumed_at = ?
        WHERE code_id = ? AND consumed_at IS NULL
        """,
        (moment.isoformat(), str(code_id)),
    )
    if updated.rowcount != 1:
        raise EnrollmentCodeRejected("enrollment code was rejected")
    raw = secrets.token_urlsafe(32)
    token_expires = (moment + token_ttl).isoformat()
    connection.execute(
        """
        INSERT INTO worker_tokens (token_id, enrollment_id, token_hash, purpose, created_at, expires_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (str(uuid4()), str(enrollment_id), _hash(raw), str(purpose), moment.isoformat(), token_expires),
    )
    return EnrollmentExchange(raw, worker_id, UUID(str(project_id)), str(purpose), token_expires)


def cancel_pending_enrollment_codes(
    connection: sqlite3.Connection,
    actor: Actor,
    worker_id: str,
    *,
    now: datetime | None = None,
) -> int:
    """Consume unexchanged codes for one worker without issuing a bearer."""

    moment = _utc(now or datetime.now(timezone.utc))
    if actor.project_scope is None:
        raise EnrollmentDenied("project was not found")
    if not actor_can_manage_workers(connection, actor):
        raise EnrollmentDenied("worker manage was denied")
    if type(worker_id) is not str or worker_id.strip() == "":
        raise EnrollmentDenied("worker id is missing")
    updated = connection.execute(
        """
        UPDATE worker_enrollment_codes
        SET consumed_at = ?
        WHERE consumed_at IS NULL
          AND enrollment_id IN (
              SELECT enrollment_id FROM worker_enrollments
              WHERE project_id = ? AND worker_id = ?
          )
        """,
        (moment.isoformat(), str(actor.project_scope), worker_id),
    )
    return int(updated.rowcount)


def revoke_worker_credentials(
    connection: sqlite3.Connection, project_id: UUID, worker_id: str, *, now: datetime | None = None
) -> bool:
    """Drop bearers and send the worker's active jobs to cleanup wait."""

    moment = _utc(now or datetime.now(timezone.utc))
    if type(worker_id) is not str or worker_id.strip() == "":
        return False
    connection.execute(
        """
        DELETE FROM worker_tokens
        WHERE enrollment_id IN (
            SELECT enrollment_id FROM worker_enrollments
            WHERE project_id = ? AND worker_id = ?
        )
        """,
        (str(project_id), worker_id),
    )
    connection.execute(
        """
        UPDATE worker_enrollment_codes
        SET consumed_at = COALESCE(consumed_at, ?)
        WHERE enrollment_id IN (
            SELECT enrollment_id FROM worker_enrollments
            WHERE project_id = ? AND worker_id = ?
        )
          AND consumed_at IS NULL
        """,
        (moment.isoformat(), str(project_id), worker_id),
    )
    connection.execute(
        """
        DELETE FROM worker_presence
        WHERE project_id = ? AND worker_id = ?
        """,
        (str(project_id), worker_id),
    )
    connection.execute(
        """
        UPDATE jobs
        SET status = 'cancel_requested'
        WHERE project_id = ?
          AND status IN ('preparing', 'running')
          AND job_id IN (
              SELECT job_id FROM leases
              WHERE project_id = ? AND worker_id = ?
          )
        """,
        (str(project_id), str(project_id), worker_id),
    )
    return True


def token_is_active(connection: sqlite3.Connection, token_hash: str, now: datetime) -> bool:
    row = connection.execute(
        """
        SELECT expires_at FROM worker_tokens WHERE token_hash = ?
        """,
        (token_hash,),
    ).fetchone()
    if row is None:
        return False
    if row[0] is None:
        return True
    return datetime.fromisoformat(str(row[0])) > _utc(now)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("enrollment time requires a timezone")
    return value.astimezone(timezone.utc)
