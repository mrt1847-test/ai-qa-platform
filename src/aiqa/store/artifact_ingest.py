"""Validate typed evidence, stage immutable bytes, then commit provenance + ACK."""
from dataclasses import replace
from datetime import timedelta, timezone
import json
import hashlib
import time
from uuid import UUID, uuid4

from aiqa.store.artifacts import (
    ArtifactReceipt, ArtifactUpload, acceptable_size, content_hash,
    expired_at, open_durable, publish_durable, resolve_stored, suffix_for,
)
from aiqa.store.queue import LeaseDenied
from aiqa.worker.files import file_lock
from aiqa.security.receipt_digest import protected_body_digest


class ArtifactRequestConflict(ValueError):
    pass


def ingest_upload_request(binding, lease, upload, request_key, payload):
    """Reserve key/body before I/O; a crash retries the same staged object."""
    from aiqa.store.evidence import _require_artifact_lease
    canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    identity = (str(lease.project_id), str(lease.job_id), lease.generation, binding.worker.worker_id, request_key)
    lock_key = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
    with file_lock(binding.store.config.spool_dir / 'upload-locks' / (lock_key + '.lock')):
        with binding.store.transaction() as connection:
            job = connection.execute('SELECT purpose FROM jobs WHERE project_id=? AND job_id=?', identity[:2]).fetchone()
            if lease.project_id not in binding.worker.permitted_projects or job is None or job[0] not in binding.worker.permitted_purposes:
                raise LeaseDenied('worker cannot use this upload request')
            digest = protected_body_digest(connection, canonical)
            cutoff = (binding.now - timedelta(days=7)).isoformat()
            connection.execute('DELETE FROM artifact_upload_requests WHERE project_id=? AND job_id=? AND generation=? AND worker_id=? AND request_key=? AND created_at<?', (*identity, cutoff))
            row = connection.execute('SELECT body_hash,response_body FROM artifact_upload_requests WHERE project_id=? AND job_id=? AND generation=? AND worker_id=? AND request_key=?', identity).fetchone()
            if row is not None:
                if row[0] != digest:
                    raise ArtifactRequestConflict('upload key already has another body')
                if row[1] is not None:
                    return json.loads(row[1])
            _require_artifact_lease(connection, binding.worker, lease, binding.now)
            _owner(connection, lease, binding.worker, upload)
            if row is None:
                connection.execute('INSERT INTO artifact_upload_requests(project_id,job_id,generation,worker_id,request_key,body_hash,created_at) VALUES(?,?,?,?,?,?,?)', (*identity, digest, binding.now.isoformat()))
        receipt = ingest_uploaded(binding, lease, upload)
        body = {'artifact_id': str(receipt.artifact_id), 'object_key': receipt.object_key,
                'content_hash': receipt.content_hash, 'ready': receipt.ready, 'acked': receipt.acked, 'status': receipt.status}
        with binding.store.transaction() as connection:
            connection.execute('UPDATE artifact_upload_requests SET response_body=? WHERE project_id=? AND job_id=? AND generation=? AND worker_id=? AND request_key=?', (json.dumps(body, sort_keys=True), *identity))
        return body


def _owner(connection, lease, worker, upload):
    row = connection.execute(
        """SELECT a.attempt_id,j.recording_id,j.case_run_id,j.purpose
        FROM attempts a JOIN jobs j USING(project_id,job_id)
        WHERE a.project_id=? AND a.job_id=? AND a.generation=?""",
        (str(lease.project_id), str(lease.job_id), lease.generation),
    ).fetchone()
    if row is None or row[3] not in worker.permitted_purposes:
        raise LeaseDenied('artifact attempt is unavailable')
    attempt = str(row[0])
    if upload.attempt_id is not None and str(upload.attempt_id) != attempt:
        raise LeaseDenied('artifact attempt is outside the lease')
    if upload.owner_kind == 'REC':
        target = row[1]
        owner = connection.execute('SELECT case_id,input_case_version_id FROM recordings WHERE project_id=? AND recording_id=?', (str(lease.project_id), str(upload.owner_id))).fetchone()
    elif upload.owner_kind == 'ITEM':
        target = row[2]
        owner = connection.execute('SELECT case_id,case_version_id FROM case_runs WHERE project_id=? AND case_run_id=?', (str(lease.project_id), str(upload.owner_id))).fetchone()
    else:
        raise ValueError('unsupported evidence owner kind')
    if owner is None or str(target) != str(upload.owner_id):
        raise LeaseDenied('artifact owner is outside the leased job')
    if upload.role not in {'before', 'after', 'log', 'check', 'source'}:
        raise ValueError('unsupported evidence role')
    if upload.action_id is not None and upload.check_id is not None:
        raise ValueError('exactly one artifact target is required')
    if upload.role in {'before', 'after'} and upload.action_id is None or upload.role == 'check' and upload.check_id is None:
        raise ValueError('evidence target is required')
    action_id = upload.action_id
    if upload.check_id is not None:
        result = connection.execute('SELECT action_id FROM check_results WHERE project_id=? AND attempt_id=? AND check_id=?', (str(lease.project_id), attempt, upload.check_id)).fetchone()
        if result is None:
            raise LeaseDenied('check is outside the leased attempt')
        action_id = str(result[0])
    if action_id is not None:
        action = connection.execute('SELECT case_id,case_version_id FROM actions WHERE project_id=? AND attempt_id=? AND action_id=?', (str(lease.project_id), attempt, action_id)).fetchone()
        if action is None or tuple(action) != tuple(owner):
            raise LeaseDenied('action is outside the source snapshot')
    elif upload.owner_kind == 'ITEM':
        raise ValueError('item evidence requires an action or check')
    return replace(upload, attempt_id=UUID(attempt))


def _identity(upload):
    return json.dumps([upload.owner_kind, str(upload.owner_id), str(upload.attempt_id), upload.action_id, upload.check_id, upload.role, upload.media_type], separators=(',', ':'))


def _existing(connection, upload, digest):
    row = connection.execute(
        """SELECT artifact_id,object_key,content_hash,byte_length,acked,status,custody,stored_at
        FROM artifact_objects WHERE project_id=? AND owner_kind=? AND owner_id=? AND attempt_id=?
        AND COALESCE(action_id,'')=? AND COALESCE(check_id,'')=? AND role=? AND media_type=? AND content_hash=? AND status='ready'""",
        (str(upload.project_id), upload.owner_kind, str(upload.owner_id), str(upload.attempt_id), upload.action_id or '', upload.check_id or '', upload.role, upload.media_type, digest),
    ).fetchone()
    return row


def _receipt(row, *, available=True):
    return ArtifactReceipt(UUID(str(row[0])), str(row[1]), str(row[2]), int(row[3]), available, bool(row[4]) and available, str(row[5]) if available else 'unavailable')


def _quarantine(connection, upload, digest):
    artifact_id = uuid4()
    connection.execute("""INSERT INTO artifact_objects(project_id,artifact_id,object_key,content_hash,byte_length,media_type,owner_id,status,acked)
        VALUES(?,?,?,?,?,?,?,'quarantine',0)""", (str(upload.project_id), str(artifact_id), f'quarantine/{artifact_id}', digest, len(upload.body), upload.media_type, str(upload.owner_id)))
    return ArtifactReceipt(artifact_id, f'quarantine/{artifact_id}', digest, len(upload.body), False, False, 'quarantine')


def ingest_uploaded(binding, lease, upload: ArtifactUpload, *, fail_ready=False):
    # Import after the evidence module has installed its context-bound API.
    from aiqa.store.evidence import _require_artifact_lease
    if upload.project_id != lease.project_id or lease.project_id not in binding.worker.permitted_projects:
        raise LeaseDenied('worker cannot use this lease')
    started = time.monotonic()
    digest = content_hash(upload.body)
    suffix = suffix_for(upload.filename, upload.media_type)
    with binding.store.transaction() as connection:
        _require_artifact_lease(connection, binding.worker, lease, binding.now)
        upload = _owner(connection, lease, binding.worker, upload)
        if suffix is None or not acceptable_size(upload.declared_length, upload.body) or upload.declared_hash != digest:
            return _quarantine(connection, upload, digest)
        existing = _existing(connection, upload, digest)
    if existing is not None:
        path = resolve_stored(binding.store.config.artifacts_dir, str(existing[1]))
        available = (existing[6] == 'stored' and not expired_at(str(existing[7]), binding.now)
                     and path is not None and path.is_file() and path.stat().st_size == len(upload.body)
                     and content_hash(path.read_bytes()) == digest)
        return _receipt(existing, available=available)
    identity = _identity(upload)
    with binding.store.transaction() as connection:
        stage = connection.execute('SELECT artifact_id,object_key FROM artifact_staging WHERE project_id=? AND identity=? AND content_hash=?', (str(lease.project_id), identity, digest)).fetchone()
        if stage is None:
            artifact_id = uuid4()
            object_key = f'{lease.project_id}/{artifact_id}{suffix}'
            connection.execute('INSERT INTO artifact_staging(project_id,artifact_id,object_key,identity,content_hash,byte_length) VALUES(?,?,?,?,?,?)', (str(lease.project_id), str(artifact_id), object_key, identity, digest, len(upload.body)))
        else:
            artifact_id, object_key = UUID(str(stage[0])), str(stage[1])
    path = resolve_stored(binding.store.config.artifacts_dir, object_key)
    if path is None:
        raise ValueError('staged object path is invalid')
    if path.exists():
        try:
            open_durable(binding.store.config.artifacts_dir, object_key, digest)
        except Exception as exc:
            raise ValueError('staged object is corrupt') from exc
        if path.stat().st_size != len(upload.body):
            raise ValueError('staged object is corrupt')
    else:
        publish_durable(
            binding.store.config.artifacts_dir,
            lease.project_id,
            artifact_id,
            suffix,
            upload.body,
            declared_hash=digest,
        )
    if fail_ready:
        return ArtifactReceipt(artifact_id, object_key, digest, len(upload.body), False, False, 'staged')
    now = binding.now + timedelta(seconds=time.monotonic() - started)
    with binding.store.transaction() as connection:
        _require_artifact_lease(connection, binding.worker, lease, now)
        upload = _owner(connection, lease, binding.worker, upload)
        raced = _existing(connection, upload, digest)
        if raced is not None:
            return _receipt(raced)
        target = 'action_id' if upload.action_id is not None else ('check_id' if upload.check_id is not None else 'recording_id')
        target_id = upload.action_id or upload.check_id or str(upload.owner_id)
        connection.execute(f'INSERT INTO artifact_refs(project_id,artifact_id,attempt_id,{target}) VALUES(?,?,?,?)', (str(lease.project_id), str(artifact_id), str(upload.attempt_id) if target != 'recording_id' else None, target_id))
        connection.execute("""INSERT INTO artifact_objects(project_id,artifact_id,object_key,content_hash,byte_length,
            media_type,owner_id,status,acked,custody,stored_at,owner_kind,attempt_id,action_id,check_id,role,job_id,generation)
            VALUES(?,?,?,?,?,?,?,'ready',1,'stored',?,?,?,?,?,?,?,?)""",
            (str(lease.project_id), str(artifact_id), object_key, digest, len(upload.body), upload.media_type, str(upload.owner_id), now.astimezone(timezone.utc).isoformat(), upload.owner_kind, str(upload.attempt_id), upload.action_id, upload.check_id, upload.role, str(lease.job_id), lease.generation))
        connection.execute('DELETE FROM artifact_staging WHERE project_id=? AND artifact_id=?', (str(lease.project_id), str(artifact_id)))
    return ArtifactReceipt(artifact_id, object_key, digest, len(upload.body), True, True, 'ready')
