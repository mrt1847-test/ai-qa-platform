"""Artifact files. The object key is generated and stays inside the artifact root."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID, uuid4
from aiqa.worker.files import file_lock

_MEDIA = {".png": "image/png", ".log": "text/plain"}
_MAX_BYTES = 5_000_000
APK_BYTE_LIMIT = 500 * 1024 * 1024
PROJECT_BYTE_LIMIT = 20 * 1024 * 1024 * 1024
ARTIFACT_RETENTION = timedelta(days=30)


class ArtifactRejected(ValueError):
    """The upload cannot become a ready file."""


@dataclass(frozen=True, slots=True)
class ProtectionReceipt:
    protection_id: UUID
    review_id: UUID
    artifact_id: UUID
    reason: str
    expires_at: str
    prior_expires_at: str
    event_count: int
    approve_allowed: bool
    temporary: bool


def extend_review_retention(
    connection: object,
    project_id: UUID,
    review_id: UUID,
    artifact_id: UUID,
    reason: str,
) -> ProtectionReceipt:
    """Append one 30-day protection event. Earlier expiry rows stay as written."""

    if reason.strip() == "":
        raise ArtifactRejected("protection reason is missing")
    review = connection.execute(  # type: ignore[attr-defined]
        "SELECT 1 FROM reviews WHERE project_id = ? AND review_id = ?",
        (str(project_id), str(review_id)),
    ).fetchone()
    if review is None:
        raise ArtifactRejected("review is missing")
    member = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT 1 FROM review_evidence_entries
        WHERE project_id = ? AND review_id = ? AND artifact_ref_id = ?
        """,
        (str(project_id), str(review_id), str(artifact_id)),
    ).fetchone()
    if member is None:
        raise ArtifactRejected("artifact is outside the review")
    prior = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT expires_at FROM review_retention_events
        WHERE project_id = ? AND review_id = ? AND artifact_id = ?
        ORDER BY created_at, rowid
        """,
        (str(project_id), str(review_id), str(artifact_id)),
    ).fetchall()
    now = datetime.now(timezone.utc)
    expires_at = (now + ARTIFACT_RETENTION).isoformat()
    protection_id = uuid4()
    event_id = uuid4()
    connection.execute(  # type: ignore[attr-defined]
        """
        INSERT INTO artifact_protections (
            project_id, protection_id, artifact_id, kind, backup_receipt_id, build_id, manual_request_id
        ) VALUES (?, ?, ?, 'review', NULL, NULL, NULL)
        """,
        (str(project_id), str(protection_id), str(artifact_id)),
    )
    connection.execute(  # type: ignore[attr-defined]
        """
        INSERT INTO review_retention_events (
            project_id, event_id, review_id, protection_id, artifact_id, reason, expires_at, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (str(project_id), str(event_id), str(review_id), str(protection_id), str(artifact_id), reason, expires_at, now.isoformat()),
    )
    return ProtectionReceipt(
        protection_id,
        review_id,
        artifact_id,
        reason,
        expires_at,
        "" if not prior else str(prior[-1][0]),
        len(prior) + 1,
        not _review_evidence_expired(connection, project_id, review_id, now),
        True,
    )


def review_protection(connection: object, project_id: UUID, case_id: UUID) -> dict[str, object] | None:
    """Show the latest temporary deadline. A rejected decision and an old expiry stay."""

    review = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT review_id FROM reviews
        WHERE project_id = ? AND case_id = ?
        ORDER BY created_commit_seq DESC
        LIMIT 1
        """,
        (str(project_id), str(case_id)),
    ).fetchone()
    if review is None:
        return None
    review_id = str(review[0])
    rows = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT expires_at, reason FROM review_retention_events
        WHERE project_id = ? AND review_id = ?
        ORDER BY created_at, rowid
        """,
        (str(project_id), review_id),
    ).fetchall()
    rejected = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT 1 FROM review_decisions
        WHERE project_id = ? AND review_id = ? AND state = 'rejected'
        """,
        (str(project_id), review_id),
    ).fetchone()
    now = datetime.now(timezone.utc)
    latest = rows[-1] if rows else None
    prior = rows[-2] if len(rows) >= 2 else None
    return {
        "expires_at": "" if latest is None else str(latest[0]),
        "reason": "" if latest is None else str(latest[1]),
        "prior_expires_at": "" if prior is None else str(prior[0]),
        "event_count": len(rows),
        "temporary": True,
        "expired": _review_evidence_expired(connection, project_id, UUID(review_id), now),
        "rejected_retained": rejected is not None,
    }


def _review_evidence_expired(connection: object, project_id: UUID, review_id: UUID, now: datetime) -> bool:
    rows = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT artifact_objects.status, artifact_objects.custody, artifact_objects.stored_at
        FROM review_evidence_entries
        LEFT JOIN artifact_objects
          ON artifact_objects.project_id = review_evidence_entries.project_id
         AND artifact_objects.artifact_id = review_evidence_entries.artifact_ref_id
        WHERE review_evidence_entries.project_id = ? AND review_evidence_entries.review_id = ?
        """,
        (str(project_id), str(review_id)),
    ).fetchall()
    if not rows:
        return True
    for row in rows:
        if row[0] is None or str(row[0]) != "ready" or str(row[1]) == "expired" or expired_at(str(row[2] or ""), now):
            return True
    return False


def pin_approval(connection: object, project_id: UUID, artifact_id: UUID, protection_id: UUID) -> None:
    """Register one approval pin. An expired file cannot become protected here."""

    row = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT custody, stored_at FROM artifact_objects
        WHERE project_id = ? AND artifact_id = ? AND status = 'ready' AND acked = 1
        """,
        (str(project_id), str(artifact_id)),
    ).fetchone()
    if row is None or str(row[0]) == "expired" or expired_at(str(row[1] or ""), datetime.now(timezone.utc)):
        raise ArtifactRejected("artifact is not ready")
    connection.execute(  # type: ignore[attr-defined]
        """
        INSERT INTO artifact_protections (
            project_id, protection_id, artifact_id, kind, backup_receipt_id, build_id, manual_request_id
        ) VALUES (?, ?, ?, 'approval', NULL, NULL, NULL)
        """,
        (str(project_id), str(protection_id), str(artifact_id)),
    )


def pin_review(connection: object, project_id: UUID, artifact_id: UUID, protection_id: UUID) -> None:
    """Register one review pin. The retention horizon is 30 days."""

    row = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT 1 FROM artifact_objects
        WHERE project_id = ? AND artifact_id = ? AND status = 'ready' AND acked = 1
        """,
        (str(project_id), str(artifact_id)),
    ).fetchone()
    if row is None:
        raise ArtifactRejected("artifact is not ready")
    connection.execute(  # type: ignore[attr-defined]
        """
        INSERT INTO artifact_protections (
            project_id, protection_id, artifact_id, kind, backup_receipt_id, build_id, manual_request_id
        ) VALUES (?, ?, ?, 'review', NULL, NULL, NULL)
        """,
        (str(project_id), str(protection_id), str(artifact_id)),
    )


def require_ready_artifacts(connection: object, project_id: UUID, artifact_ids: tuple[str, ...]) -> None:
    """Refuse a package commit until every listed artifact is already ready."""

    if artifact_ids == ():
        raise ArtifactRejected("artifact is not ready")
    for artifact_id in artifact_ids:
        row = connection.execute(  # type: ignore[attr-defined]
            """
            SELECT 1 FROM artifact_objects
            WHERE project_id = ? AND artifact_id = ? AND status = 'ready' AND acked = 1
            """,
            (str(project_id), artifact_id),
        ).fetchone()
        if row is None:
            raise ArtifactRejected("artifact is not ready")


@dataclass(frozen=True, slots=True)
class ArtifactUpload:
    project_id: UUID
    owner_id: UUID
    filename: str
    media_type: str
    declared_hash: str
    declared_length: int
    body: bytes
    owner_kind: str = 'REC'
    attempt_id: UUID | None = None
    action_id: str | None = None
    check_id: str | None = None
    role: str = 'source'


@dataclass(frozen=True, slots=True)
class ArtifactReconcileReport:
    missing: int
    corruption: int
    expired: int
    spooling: int
    stored: int


@dataclass(frozen=True, slots=True)
class ArtifactStream:
    body: bytes
    media_type: str


@dataclass(frozen=True, slots=True)
class EvidenceUnavailable:
    state: str


@dataclass(frozen=True, slots=True)
class ArtifactReceipt:
    artifact_id: UUID
    object_key: str
    content_hash: str
    byte_length: int
    ready: bool
    acked: bool
    status: str


def content_hash(body: bytes) -> str:
    return "sha256:" + hashlib.sha256(body).hexdigest()


def suffix_for(filename: str, media_type: str) -> str | None:
    if _hostile(filename):
        return None
    suffix = Path(filename).suffix.lower()
    if _MEDIA.get(suffix) != media_type:
        return None
    return suffix


def within_apk_budget(declared_length: int, project_total: int) -> bool:
    """One APK stays within 500MB and the project stays within 20GB."""

    if type(declared_length) is not int or type(project_total) is not int:
        return False
    if declared_length < 1 or declared_length > APK_BYTE_LIMIT:
        return False
    return project_total + declared_length <= PROJECT_BYTE_LIMIT


def acceptable_size(declared_length: int, body: bytes) -> bool:
    return type(declared_length) is int and 1 <= declared_length <= _MAX_BYTES and declared_length == len(body)


def place_ready(root: Path, project_id: UUID, artifact_id: UUID, suffix: str, body: bytes) -> str:
    """Flush a temp file and rename it inside the same artifact directory."""

    folder = (root / str(project_id)).resolve()
    destination = (folder / f"{artifact_id}{suffix}").resolve()
    if destination.parent != folder:
        raise ArtifactRejected("object key leaves the artifact root")
    staging = folder / 'tmp'
    staging.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(dir=staging, prefix=f'{artifact_id}.', suffix=suffix+'.partial', delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        # Windows readers cannot share a replace operation. Serialize by object
        # identity and reuse equal bytes instead of replacing an existing file.
        with file_lock(root.parent / 'artifact-locks' / str(project_id) / f'{artifact_id}.lock'):
            if destination.exists():
                if content_hash(destination.read_bytes()) != content_hash(body):
                    raise ArtifactRejected('immutable object already contains different bytes')
            else:
                os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return f"{project_id}/{artifact_id}{suffix}"


def resolve_stored(root: Path, object_key: str) -> Path | None:
    """Return a file inside the artifact root. A client key cannot leave it."""

    if type(object_key) is not str or object_key.strip() == "" or ".." in object_key:
        return None
    if object_key.startswith(("/", "\\")) or "\\" in object_key or ":" in object_key:
        return None
    base = root.resolve()
    path = (base / object_key).resolve()
    if path != base and base not in path.parents:
        return None
    return path


def expired_at(stored_at: str, now: datetime) -> bool:
    if stored_at.strip() == "":
        return False
    parsed = datetime.fromisoformat(stored_at)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return False
    return now.astimezone(timezone.utc) - parsed.astimezone(timezone.utc) >= ARTIFACT_RETENTION


def _hostile(filename: str) -> bool:
    if type(filename) is not str or filename.strip() == "":
        return True
    if ".." in filename or filename.startswith(("/", "\\")) or "\\" in filename or ":" in filename:
        return True
    return False
