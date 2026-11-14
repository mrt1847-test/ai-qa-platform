"""Request-serialized durable staging; SQL writers never wait for artifact bytes."""
import hashlib
import json
import logging
import sqlite3
from dataclasses import replace
from datetime import datetime, timezone
from uuid import UUID, uuid4

from aiqa.store.artifacts import ArtifactRejected, DurableObject, open_durable, suffix_for
from aiqa.store.queue import LeaseDenied
from aiqa.worker.files import file_lock


def commit_staged_evidence(binding, lease, *, events, artifacts, request_key, body_fingerprint, authority_clock):
    # Import lazily: evidence owns the public types and publishing seam.
    from aiqa.store import evidence
    identity = (str(lease.project_id), str(lease.job_id), lease.generation,
                binding.worker.worker_id, request_key)
    lock_key = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
    kwargs = dict(events=events, artifacts=artifacts, request_key=request_key,
                  body_fingerprint=body_fingerprint, authority_clock=authority_clock)
    with file_lock(binding.store.config.spool_dir / 'evidence-locks' / (lock_key + '.lock')):
        stages = []
        finalize_only = False
        with binding.store.transaction() as connection:
            evidence._require_evidence_purpose(connection, binding.worker, lease)
            current = evidence.artifact_authority_now(replace(binding, authority_clock=authority_clock))
            row = connection.execute("""SELECT body_hash,response_body FROM evidence_commit_requests
                WHERE project_id=? AND job_id=? AND generation=? AND worker_id=? AND request_key=?""", identity).fetchone()
            if row is not None and row[0] != body_fingerprint:
                raise evidence.EventConflict('commit key already has another body')
            # Cached receipts and already-late work require no file I/O. The metadata
            # commit still rechecks scope and current lease before handling either.
            lease_row = connection.execute("""SELECT l.worker_id,l.expires_at,j.status
                FROM leases l JOIN jobs j USING(project_id,job_id)
                WHERE l.project_id=? AND l.job_id=? AND l.generation=?""", identity[:3]).fetchone()
            cached = row is not None and bool(row[1])
            if not cached and lease_row is not None and lease_row[0] != binding.worker.worker_id:
                raise LeaseDenied('worker cannot use this lease')
            finalize_only = (row is not None and bool(row[1])) or lease_row is None
            if lease_row is not None:
                expires = datetime.fromisoformat(lease_row[1])
                finalize_only = finalize_only or (lease_row[2] in evidence._TERMINAL or expires.tzinfo is None
                    or current >= expires.astimezone(timezone.utc))
            if not finalize_only:
                if row is None:
                    connection.execute("""INSERT INTO evidence_commit_requests
                        (project_id,job_id,generation,worker_id,request_key,body_hash,created_at)
                        VALUES(?,?,?,?,?,?,?)""", (*identity, body_fingerprint, current.isoformat()))
                owner = connection.execute('SELECT recording_id,case_run_id FROM jobs WHERE project_id=? AND job_id=?',identity[:2]).fetchone()
                attempt = connection.execute('SELECT attempt_id FROM attempts WHERE project_id=? AND job_id=? AND generation=?',identity[:3]).fetchone()
                for index, part in enumerate(artifacts):
                    suffix = suffix_for(part.filename, part.media_type)
                    expected_owner = owner[0] if part.owner_kind == 'REC' else owner[1] if part.owner_kind == 'ITEM' else None
                    if (suffix is None or expected_owner is None or part.role not in {'before','after','log','source'}
                        or part.owner_id is not None and str(part.owner_id) != expected_owner
                        or attempt is None or part.attempt_id is not None and str(part.attempt_id) != attempt[0]
                        or part.role in {'before','after'} and not part.action_id
                        or part.owner_kind == 'ITEM' and not part.action_id):
                        raise ValueError('invalid evidence owner or target')
                    existing = connection.execute("""SELECT artifact_id,object_key,content_hash,byte_length
                        FROM artifact_objects WHERE project_id=? AND attempt_id=? AND content_hash=? AND role=?
                        AND status='ready' AND acked=1 LIMIT 1""",
                        (identity[0],attempt[0],part.declared_hash,part.role)).fetchone()
                    if existing is not None:
                        stages.append((existing, suffix, part, False))
                        continue
                    stage_identity = json.dumps(['evidence-commit', *identity, body_fingerprint, index], separators=(',',':'))
                    stage = connection.execute('SELECT artifact_id,object_key,content_hash,byte_length FROM artifact_staging WHERE project_id=? AND identity=? AND content_hash=?',
                        (identity[0],stage_identity,part.declared_hash)).fetchone()
                    if stage is None:
                        artifact_id = uuid4()
                        key = f'{lease.project_id}/{artifact_id}{suffix}'
                        stage = (str(artifact_id), key, part.declared_hash, part.declared_length)
                        connection.execute('INSERT INTO artifact_staging(project_id,artifact_id,object_key,identity,content_hash,byte_length) VALUES(?,?,?,?,?,?)',
                            (identity[0],str(artifact_id),key,stage_identity,part.declared_hash,part.declared_length))
                    stages.append((stage, suffix, part, True))
        prepared = []
        for stage, suffix, part, owned_stage in stages:
            artifact_id, key, digest, length = stage
            # Reuse durable staged bytes after an interrupted metadata commit. Never
            # delete a stage/ready file as compensation for an uncertain SQL outcome.
            path = evidence.resolve_stored(binding.store.config.artifacts_dir, key)
            if path is None:
                raise ValueError('invalid staged object path')
            try:
                if path.exists():
                    body = open_durable(binding.store.config.artifacts_dir, key, digest)
                    if len(body) != length:
                        raise ArtifactRejected('staged object size mismatch')
                    durable = DurableObject(UUID(artifact_id), key, digest, length)
                elif not owned_stage:
                    raise ArtifactRejected("ready artifact is unavailable")
                else:
                    durable = evidence.publish_durable(binding.store.config.artifacts_dir, lease.project_id,
                        UUID(artifact_id), suffix, part.body, declared_hash=digest)
            except ArtifactRejected as exc:
                raise ValueError(str(exc)) from exc
            prepared.append(durable)
        ack = evidence._commit_evidence_metadata(binding, lease, prepared=tuple(prepared), **kwargs)
        if not ack.late:
            used_ids = set(ack.artifact_ids)
            for (stage, _, _, owned_stage), durable in zip(stages, prepared):
                if owned_stage and str(durable.artifact_id) not in used_ids:
                    _discard_redundant_stage(binding, durable)
        return ack


def _discard_redundant_stage(binding, durable):
    """A successful racing commit may use another ready object. Discard only ours.

    The request-key lock is still held. Other request keys cannot own this unique
    staging identity, and ready/refs checks protect against deleting published bytes.
    Cleanup failure retains an observable stage; it cannot revoke a committed ACK.
    """
    from aiqa.store.artifacts import resolve_stored
    # Project is encoded in the server-created key, not inferred from scope order.
    identity = (durable.object_key.split('/')[0], str(durable.artifact_id))
    try:
        with binding.store.transaction() as connection:
            stage = connection.execute('SELECT object_key FROM artifact_staging WHERE project_id=? AND artifact_id=?', identity).fetchone()
            referenced = connection.execute('SELECT 1 FROM artifact_objects WHERE project_id=? AND artifact_id=? UNION ALL SELECT 1 FROM artifact_refs WHERE project_id=? AND artifact_id=?', (*identity,*identity)).fetchone()
        if stage is None or stage[0] != durable.object_key or referenced is not None:
            return
        path = resolve_stored(binding.store.config.artifacts_dir, durable.object_key)
        if path is None:
            return
        path.unlink(missing_ok=True)
        with binding.store.transaction() as connection:
            connection.execute('DELETE FROM artifact_staging WHERE project_id=? AND artifact_id=?', identity)
    except (OSError, sqlite3.Error):
        logging.getLogger(__name__).warning('Redundant evidence stage cleanup deferred')

