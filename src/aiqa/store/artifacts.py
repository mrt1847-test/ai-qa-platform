"""Artifact files. The object key is generated and stays inside the artifact root."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID
from aiqa.worker.files import file_lock

_MEDIA = {".png": "image/png", ".log": "text/plain"}
_MAX_BYTES = 5_000_000
ARTIFACT_RETENTION = timedelta(days=30)


class ArtifactRejected(ValueError):
    """The upload cannot become a ready file."""


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
