"""Adversarial evidence regressions from R10/R11/R12/R16/R17."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from uuid import uuid4
import pytest

from aiqa.contracts.evidence import EvidenceEnvelope, IngestReceipt
from aiqa.recording.recovery import EvidenceRecoverySpec, RecoveryCapture, apply_recovery, RecoveryRejected, recover_evidence, bind_recovery, reset_recovery
from aiqa.store.artifacts import ArtifactUpload, content_hash
from aiqa.store.evidence import ArtifactBinding, bind_artifact_ingest, reset_artifact_ingest, ingest_artifact
from aiqa.store.queue import LeaseDenied
from aiqa.worker.spool import EvidenceSpool, SpoolError


def test_spool_conflicting_body_is_rejected(tmp_path):
    spool = EvidenceSpool(tmp_path)
    env = EvidenceEnvelope(uuid4(), 1, b'original', 'log', datetime.now(timezone.utc).isoformat())
    original = spool.append(env)
    with pytest.raises(SpoolError):
        spool.append(replace(env, png=b'different'))
    assert spool.append(env) == original
    assert (tmp_path / str(env.attempt_id) / '1.png').read_bytes() == b'original'


def test_ack_cursor_survives_file_purge_and_process_restart(tmp_path):
    spool = EvidenceSpool(tmp_path)
    now = datetime.now(timezone.utc)
    attempt = uuid4()
    spool.append(EvidenceEnvelope(attempt, 1, b'first', 'log', (now - timedelta(days=8)).isoformat()))
    spool.append(EvidenceEnvelope(attempt, 2, b'tail', 'log', now.isoformat()))
    h1 = spool.prefix_hash(attempt, 1)
    h2 = spool.prefix_hash(attempt, 2)
    assert spool.acknowledge(IngestReceipt(attempt, 1, h1, 0)).accepted
    spool.purge(now)
    reopened = EvidenceSpool(tmp_path)
    assert not reopened.has_file(attempt, 1)
    assert reopened.has_file(attempt, 2)
    assert reopened.prefix_hash(attempt, 2) == h2
    assert reopened.acknowledge(IngestReceipt(attempt, 2, h2, 0)).accepted


def test_journal_replacement_failure_preserves_previous_receipt(tmp_path, monkeypatch):
    import aiqa.worker.files as files
    spool = EvidenceSpool(tmp_path)
    env = EvidenceEnvelope(uuid4(), 1, b'first', 'log', datetime.now(timezone.utc).isoformat())
    spool.append(env)
    original = (tmp_path / 'journal.jsonl').read_bytes()
    def fail(*args): raise OSError('fixture: replace failed')
    monkeypatch.setattr(files.os, 'replace', fail)
    with pytest.raises(OSError): spool.mark_sent(env.attempt_id, 1)
    assert (tmp_path / 'journal.jsonl').read_bytes() == original
    assert EvidenceSpool(tmp_path).has_file(env.attempt_id, 1)


def _terminal(f):
    f.con.execute("UPDATE recordings SET stop_status='stopped', completion_status='interrupted' WHERE recording_id=?", (str(f.recording_id),))


def test_recovery_revisions_preserve_prior_file_bytes(review_recording):
    f = review_recording
    _terminal(f)
    receipts = []
    for key, body in [('first', b'original'), ('second', b'replacement')]:
        receipts.append(_recover(f, EvidenceRecoverySpec(f.project.project_id, f.recording_id, key, (RecoveryCapture('A1', 'immediate', body),))))
    files = list(f.store.config.artifacts_dir.rglob('*.png'))
    assert sorted(path.read_bytes() for path in files) == [b'original', b'replacement']
    prior = f.con.execute('SELECT prior_manifest_id FROM recording_manifests WHERE manifest_id=?', (str(receipts[1].manifest_id),)).fetchone()[0]
    assert prior == str(receipts[0].manifest_id)


def test_recovery_validates_all_captures_before_writing(review_recording):
    f = review_recording
    _terminal(f)
    with pytest.raises(RecoveryRejected):
        _recover(f, EvidenceRecoverySpec(f.project.project_id, f.recording_id, 'bad', (RecoveryCapture('A1', 'immediate', b'first'), RecoveryCapture('../escape', 'immediate', b'bad'))))
    assert not list(f.store.config.artifacts_dir.rglob('*.png'))


def upload(f, body=b'fixture-png'):
    return ArtifactUpload(f.project.project_id, f.recording_id, 'shot.png', 'image/png', content_hash(body), len(body), body)


def test_ingest_requires_real_same_job_owner_and_atomic_typed_ref(review_recording):
    f = review_recording
    token = bind_artifact_ingest(ArtifactBinding(f.store, f.worker, f.now))
    try:
        with pytest.raises(LeaseDenied): ingest_artifact(f.lease, replace(upload(f), owner_id=uuid4()))
        good = ingest_artifact(f.lease, upload(f))
        assert good.ready and good.acked
        ref = f.con.execute('SELECT recording_id FROM artifact_refs WHERE artifact_id=?', (str(good.artifact_id),)).fetchone()
        assert ref is not None and ref[0] == str(f.recording_id)
    finally: reset_artifact_ingest(token)


@pytest.mark.parametrize('field,value', [('declared_hash', 'sha256:' + '0' * 64), ('declared_length', -1), ('filename', '../escape.png'), ('media_type', 'application/x-msdownload')])
def test_existing_hash_does_not_bypass_upload_validation(review_recording, field, value):
    f = review_recording
    token = bind_artifact_ingest(ArtifactBinding(f.store, f.worker, f.now))
    try:
        ingest_artifact(f.lease, upload(f))
        receipt = ingest_artifact(f.lease, replace(upload(f), **{field: value}))
        assert not receipt.ready and not receipt.acked
    finally: reset_artifact_ingest(token)


def test_staged_file_retry_commits_same_object_and_ref(review_recording):
    f = review_recording
    token = bind_artifact_ingest(ArtifactBinding(f.store, f.worker, f.now))
    try:
        staged = ingest_artifact(f.lease, upload(f), fail_ready=True)
        assert not staged.acked
        assert f.con.execute('SELECT count(*) FROM artifact_refs').fetchone()[0] == 0
        retried = ingest_artifact(f.lease, upload(f))
        assert retried.artifact_id == staged.artifact_id
        assert retried.acked
        assert f.con.execute('SELECT count(*) FROM artifact_refs').fetchone()[0] == 1
    finally: reset_artifact_ingest(token)


def test_quarantine_cannot_be_promoted_without_atomic_owned_creation(review_recording):
    import sqlite3
    f = review_recording
    ident = str(uuid4())
    f.con.execute("INSERT INTO artifact_objects(project_id,artifact_id,object_key,content_hash,byte_length,media_type,owner_id,status,acked) VALUES (?,?,?,?,?,?,?,'quarantine',0)", (str(f.project.project_id), ident, 'quarantine/fixture', 'hash', 1, 'image/png', str(uuid4())))
    with pytest.raises(sqlite3.IntegrityError):
        f.con.execute("UPDATE artifact_objects SET status='ready',acked=1,owner_kind='REC' WHERE artifact_id=?", (ident,))


def test_ready_identity_and_mime_are_preserved(review_recording):
    import sqlite3
    f = review_recording
    token = bind_artifact_ingest(ArtifactBinding(f.store, f.worker, f.now))
    try:
        first = ingest_artifact(f.lease, upload(f))
        with pytest.raises(sqlite3.IntegrityError):
            f.con.execute('UPDATE artifact_objects SET artifact_id=? WHERE artifact_id=?', (str(uuid4()), str(first.artifact_id)))
        other = ingest_artifact(f.lease, replace(upload(f), filename='shot.log', media_type='text/plain'))
        assert other.artifact_id != first.artifact_id
        assert f.con.execute('SELECT media_type FROM artifact_objects WHERE artifact_id=?', (str(other.artifact_id),)).fetchone()[0] == 'text/plain'
    finally: reset_artifact_ingest(token)


def test_committed_recovery_manifest_cannot_be_deleted(review_recording):
    import sqlite3
    f = review_recording
    _terminal(f)
    receipt = _recover(f, EvidenceRecoverySpec(f.project.project_id, f.recording_id, 'first', (RecoveryCapture('A1', 'immediate', b'original'),)))
    with pytest.raises(sqlite3.IntegrityError):
        f.con.execute('DELETE FROM recording_manifests WHERE manifest_id=?', (str(receipt.manifest_id),))


def _recover(f, spec):
    token = bind_recovery(f.store)
    try: return recover_evidence(spec)
    finally: reset_recovery(token)


def test_recovery_files_are_written_outside_writer_transaction(review_recording, monkeypatch):
    import aiqa.recording.recovery as recovery
    f = review_recording
    _terminal(f)
    original = recovery._write
    writes = []
    def checked(path, body):
        writes.append(f.con.in_transaction)
        original(path, body)
    monkeypatch.setattr(recovery, '_write', checked)
    _recover(f, EvidenceRecoverySpec(f.project.project_id, f.recording_id, 'first', (RecoveryCapture('A1', 'immediate', b'original'),)))
    assert writes == [False]


def test_concurrent_same_object_writers_use_independent_partial_files(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    import aiqa.store.artifacts as artifacts
    project, ident = uuid4(), uuid4()
    body = b'concurrent-fixture' * 4096
    barrier = Barrier(2)
    fsync = artifacts.os.fsync
    def sync(fd):
        fsync(fd)
        barrier.wait(timeout=5)
    real_os = artifacts.os
    class ArtifactOS:
        def __getattr__(self, name):
            return sync if name == 'fsync' else getattr(real_os, name)
    monkeypatch.setattr(artifacts, 'os', ArtifactOS())
    # Synchronize only artifact writers: unrelated durability I/O must not join this barrier.
    import os
    with (tmp_path / 'unrelated-durability.bin').open('wb') as unrelated:
        unrelated.write(b'other I/O')
        unrelated.flush()
        os.fsync(unrelated.fileno())
    def write(_): return artifacts.place_ready(tmp_path, project, ident, '.png', body)
    errors = []
    keys = []
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(write, index) for index in range(2)]
        for future in futures:
            try:
                keys.append(future.result())
            except Exception as exc:
                errors.append((type(exc).__name__, str(exc)))
    assert not errors, errors
    assert keys[0] == keys[1]
    assert (tmp_path / keys[0]).read_bytes() == body
    assert not list((tmp_path / str(project) / 'tmp').iterdir())


def test_recovery_db_failure_discards_only_new_uncommitted_files(review_recording):
    import sqlite3
    f = review_recording
    _terminal(f)
    first = _recover(f, EvidenceRecoverySpec(f.project.project_id, f.recording_id, 'first', (RecoveryCapture('A1', 'immediate', b'original'),)))
    f.con.execute("CREATE TRIGGER fixture_manifest_failure BEFORE INSERT ON recording_manifests BEGIN SELECT RAISE(ABORT,'fixture failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        _recover(f, EvidenceRecoverySpec(f.project.project_id, f.recording_id, 'second', (RecoveryCapture('A1', 'immediate', b'replacement'),)))
    assert [path.read_bytes() for path in f.store.config.artifacts_dir.rglob('*.png')] == [b'original']


def test_worker_upload_http_key_replays_and_rejects_changed_body(review_recording):
    import asyncio
    import base64
    import httpx
    from aiqa.api.app import create_app
    from aiqa.api.mutations import _BorrowedStore
    from aiqa.config import load_settings
    f = review_recording
    f.con.execute('UPDATE leases SET expires_at=? WHERE job_id=?', ((datetime.now(timezone.utc)+timedelta(seconds=45)).isoformat(), str(f.job.job_id)))
    app = create_app(load_settings({'AIQA_RUNTIME_ROOT': str(f.store.config.runtime_root)}))
    app.state.open_store = lambda: _BorrowedStore(f.store)
    data = b'http-fixture'
    payload = {'project_id':str(f.project.project_id),'job_id':str(f.job.job_id),'generation':1,
               'owner_id':str(f.recording_id),'filename':'shot.png','media_type':'image/png',
               'body_b64':base64.b64encode(data).decode(),'declared_hash':content_hash(data),'declared_length':len(data)}
    headers = {'Authorization':'Bearer '+f.worker_token,'Idempotency-Key':'upload-http'}
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1') as client:
            first = await client.post('/api/v1/worker/artifacts',json=payload,headers=headers)
            repeated = await client.post('/api/v1/worker/artifacts',json=payload,headers=headers)
            assert first.status_code == repeated.status_code == 200
            assert first.json() == repeated.json() and first.json()['acked']
            other = b'other-fixture'
            changed = await client.post('/api/v1/worker/artifacts',json={**payload,'body_b64':base64.b64encode(other).decode(),'declared_hash':content_hash(other),'declared_length':len(other)},headers=headers)
            assert changed.status_code == 409
            f.con.execute("UPDATE jobs SET status='completed' WHERE job_id=?", (str(f.job.job_id),))
            late = await client.post('/api/v1/worker/artifacts',json=payload,headers=headers)
            assert late.status_code == 200 and late.json() == first.json()
    asyncio.run(exercise())
    assert f.con.execute("SELECT COUNT(*) FROM artifact_objects WHERE status='ready'").fetchone()[0] == 1
