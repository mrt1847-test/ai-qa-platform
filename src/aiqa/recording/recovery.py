"""Read-only recovery of unsent captures. A late photo does not replace the immediate one."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

from aiqa.domain.hashing import SCHEMA_VERSION, canonical_hash
from aiqa.store.artifacts import content_hash
from aiqa.store.database import Store

_store: ContextVar[Store] = ContextVar("aiqa_recovery_store")
_ACTION = re.compile(r"[A-Za-z0-9_-]+")


class RecoveryConflict(Exception):
    """The same recovery key arrived with a different body."""


class RecoveryRejected(ValueError):
    """The recording cannot take a recovery manifest."""


@dataclass(frozen=True, slots=True)
class RecoveryCapture:
    action_id: str
    timing: str
    png: bytes


@dataclass(frozen=True, slots=True)
class EvidenceRecoverySpec:
    project_id: UUID
    recording_id: UUID
    request_key: str
    captures: tuple[RecoveryCapture, ...]


@dataclass(frozen=True, slots=True)
class ManifestReceipt:
    project_id: UUID
    manifest_id: UUID
    recording_id: UUID
    revision: int
    body_hash: str
    replayed: bool


def bind_recovery(store: Store):
    return _store.set(store)


def reset_recovery(token) -> None:
    _store.reset(token)


@dataclass(frozen=True, slots=True)
class PreparedRecovery:
    manifest_id: UUID
    digest: str
    immediate_json: str
    mapping_json: str
    files: tuple[Path, ...]


def _validate_captures(spec: EvidenceRecoverySpec) -> None:
    if spec.request_key.strip() == "" or not spec.captures:
        raise RecoveryRejected("recovery captures are required")
    seen = set()
    for capture in spec.captures:
        if (_ACTION.fullmatch(capture.action_id) is None or capture.timing not in {'immediate', 'delayed'}
                or capture.action_id in seen or not isinstance(capture.png, bytes) or not 1 <= len(capture.png) <= 5_000_000):
            raise RecoveryRejected('capture is invalid')
        seen.add(capture.action_id)


def find_recovery(connection: sqlite3.Connection, spec: EvidenceRecoverySpec) -> ManifestReceipt | None:
    _validate_captures(spec)
    digest = _body_hash(spec)
    row = connection.execute(
        'SELECT manifest_id,revision,body_hash FROM recording_manifests WHERE project_id=? AND recording_id=? AND request_key=?',
        (str(spec.project_id), str(spec.recording_id), spec.request_key),
    ).fetchone()
    if row is None:
        return None
    if str(row[2]) != digest:
        raise RecoveryConflict('recovery body does not match')
    return ManifestReceipt(spec.project_id, UUID(str(row[0])), spec.recording_id, int(row[1]), digest, True)


def validate_recovery_target(connection: sqlite3.Connection, spec: EvidenceRecoverySpec):
    row = connection.execute(
        """SELECT r.case_id,r.input_case_version_id,v.content_hash,r.stop_status,r.completion_status
        FROM recordings r JOIN case_versions v
          ON v.project_id=r.project_id AND v.case_id=r.case_id AND v.version_id=r.input_case_version_id
        WHERE r.project_id=? AND r.recording_id=?""",
        (str(spec.project_id), str(spec.recording_id)),
    ).fetchone()
    if row is None:
        raise RecoveryRejected('recording was not found')
    if row[3] != 'stopped' or row[4] not in {'interrupted', 'error', 'completed'}:
        raise RecoveryRejected('recording is not terminal')
    return row


def prepare_recovery(artifacts: Path, spec: EvidenceRecoverySpec) -> PreparedRecovery:
    """Flush fresh immutable objects outside the writer transaction."""
    _validate_captures(spec)
    digest, manifest_id = _body_hash(spec), uuid4()
    files, immediate, mapping = [], [], {}
    try:
        for capture in spec.captures:
            folder = artifacts / 'recovery' / str(spec.recording_id) / str(manifest_id)
            if capture.timing == 'delayed':
                folder /= 'delayed'
            path = folder / f'{capture.action_id}.png'
            files.append(path)
            _write(path, capture.png)
            key = path.relative_to(artifacts).as_posix()
            mapping[capture.action_id] = {'timing': capture.timing, 'object_key': key, 'hash': content_hash(capture.png)}
            if capture.timing == 'immediate':
                immediate.append({'action_id': capture.action_id, 'hash': content_hash(capture.png), 'object_key': key})
    except BaseException:
        for path in files:
            path.unlink(missing_ok=True)
        raise
    return PreparedRecovery(manifest_id, digest, json.dumps(immediate, sort_keys=True), json.dumps(mapping, sort_keys=True), tuple(files))


def discard_recovery(prepared: PreparedRecovery) -> None:
    """Discard only newly staged, unreferenced files owned by this call."""
    for path in prepared.files:
        path.unlink(missing_ok=True)


def recover_evidence(spec: EvidenceRecoverySpec) -> ManifestReceipt:
    store = _store.get()
    with store.transaction() as connection:
        existing = find_recovery(connection, spec)
        if existing is not None:
            return existing
        validate_recovery_target(connection, spec)
    prepared = prepare_recovery(store.config.artifacts_dir, spec)
    receipt = None
    committed = False
    try:
        with store.transaction() as connection:
            receipt = apply_recovery(connection, store.config.artifacts_dir, spec, prepared=prepared)
        committed = True
        return receipt
    finally:
        if not committed or receipt is None or receipt.manifest_id != prepared.manifest_id:
            discard_recovery(prepared)


def apply_recovery(connection: sqlite3.Connection, artifacts: Path, spec: EvidenceRecoverySpec, *, prepared: PreparedRecovery | None = None) -> ManifestReceipt:
    """Commit only metadata; caller stages bytes before opening this transaction."""
    existing = find_recovery(connection, spec)
    if existing is not None:
        return existing
    row = validate_recovery_target(connection, spec)
    digest = _body_hash(spec)
    if prepared is None or prepared.digest != digest:
        raise RecoveryRejected('recovery bytes must be staged before the database transaction')
    prior = connection.execute(
        'SELECT revision,manifest_id FROM recording_manifests WHERE project_id=? AND recording_id=? ORDER BY revision DESC LIMIT 1',
        (str(spec.project_id), str(spec.recording_id)),
    ).fetchone()
    revision = 1 if prior is None else int(prior[0]) + 1
    connection.execute(
        """INSERT INTO recording_manifests(project_id,case_id,recording_id,manifest_id,revision,kind,prior_manifest_id,
          input_version_hash,source_artifact_hashes,action_mapping,evidence_completeness,request_key,body_hash)
        VALUES(?,?,?,?,?,'recovery',?,?,?,?, 'incomplete',?,?)""",
        (str(spec.project_id), str(row[0]), str(spec.recording_id), str(prepared.manifest_id), revision,
         None if prior is None else str(prior[1]), str(row[2]), prepared.immediate_json, prepared.mapping_json, spec.request_key, digest),
    )
    return ManifestReceipt(spec.project_id, prepared.manifest_id, spec.recording_id, revision, digest, False)


def _body_hash(spec: EvidenceRecoverySpec) -> str:
    captures = [
        {"action_id": capture.action_id, "hash": content_hash(capture.png), "timing": capture.timing}
        for capture in spec.captures
    ]
    return canonical_hash(
        {"captures": captures, "recording_id": str(spec.recording_id), "request_key": spec.request_key},
        SCHEMA_VERSION,
    )


def _write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
