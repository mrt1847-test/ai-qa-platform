"""Real management upload/ACK/read flow against synthetic private Storage."""
import asyncio
from dataclasses import replace
from datetime import datetime, timezone
import shutil
import sqlite3

import httpx
import pytest

from tests.unit.test_hs3_object_storage import Remote, make_root
from test_rx98_model_requests import model_job, recording, ux_app, ack
from test_rx87_evidence_authority import payload, upload
from test_rx87_check_bindings import recorded


@pytest.fixture
def remote_job(model_job, tmp_path, monkeypatch):
    f = model_job
    remote = Remote()
    root = make_root(tmp_path, remote)
    original = f['app'].state.open_store
    def open_store():
        store = original()
        store.config = replace(store.config, artifacts_dir=root)
        return store
    monkeypatch.setattr(f['app'].state, 'open_store', open_store)
    f.update(remote=remote, remote_root=root)
    ack(f)
    return f


def test_committed_worker_evidence_survives_cache_loss_and_worker_offline(remote_job):
    f = remote_job
    result = upload(f, payload(f, datetime.now(timezone.utc)))
    assert result.status_code == 200, result.text
    artifact = result.json()['artifact_ids'][0]
    assert f['remote'].objects
    shutil.rmtree(f['remote_root'].cache_dir)
    with sqlite3.connect(f['database']) as c:
        c.execute("UPDATE worker_presence SET last_seen='2000-01-01T00:00:00+00:00'")
    # No worker calls occur after the ACK; the read is served by API + Storage.
    async def read():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=f['app']), base_url='http://127.0.0.1') as client:
            return await client.get('/api/v1/artifacts/' + artifact, headers={'Authorization': 'Bearer ' + f['token']})
    loaded = asyncio.run(read())
    assert loaded.status_code == 200, loaded.text
    assert loaded.content in f['remote'].objects.values()
    assert f['provider'].sent == 0


def test_retention_refuses_unauthenticated_read_before_private_download(remote_job):
    f = remote_job
    uploaded = upload(f, payload(f, datetime.now(timezone.utc)))
    assert uploaded.status_code == 200, uploaded.text
    artifact = uploaded.json()['artifact_ids'][0]
    before = len(f['remote'].requests)
    async def read():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=f['app']), base_url='http://127.0.0.1') as client:
            return await client.get('/api/v1/artifacts/' + artifact + '/retention')
    refused = asyncio.run(read())
    assert refused.status_code in {401, 403}
    assert len(f['remote'].requests) == before


def test_remote_reconcile_uses_durable_objects_after_cache_loss(remote_job):
    from aiqa.store.evidence import bind_artifact_ingest, reset_artifact_ingest, ArtifactBinding, reconcile_artifacts
    f = remote_job
    result = upload(f, payload(f, datetime.now(timezone.utc)))
    assert result.status_code == 200, result.text
    shutil.rmtree(f['remote_root'].cache_dir)
    store = f['app'].state.open_store()
    try:
        token = bind_artifact_ingest(ArtifactBinding(store, None, datetime.now(timezone.utc)))
        try:
            report = reconcile_artifacts()
        finally:
            reset_artifact_ingest(token)
        assert report.stored == 1 and report.missing == 0
    finally:
        store.close()


def test_storage_timeout_cannot_commit_ready_evidence(remote_job):
    f = remote_job
    f['remote'].failure = 'timeout'
    result = upload(f, payload(f, datetime.now(timezone.utc)))
    assert result.status_code == 422, result.text
    with sqlite3.connect(f['database']) as c:
        assert c.execute("SELECT COUNT(*) FROM artifact_objects WHERE status='ready' AND acked=1").fetchone()[0] == 0
    assert f['provider'].sent == 0


def test_cache_failure_cannot_commit_ack_and_retry_reuses_remote_object(remote_job, monkeypatch):
    f = remote_job
    root = f['remote_root']
    original = root._cache_locked
    def disk_full(*args):
        raise OSError('synthetic filesystem failure')
    body = payload(f, datetime.now(timezone.utc))
    monkeypatch.setattr(root, '_cache_locked', disk_full)
    result = upload(f, body)
    assert result.status_code == 422, result.text
    with sqlite3.connect(f['database']) as c:
        assert c.execute("SELECT COUNT(*) FROM artifact_objects WHERE status='ready' AND acked=1").fetchone()[0] == 0
    assert len(f['remote'].objects) == 1
    monkeypatch.setattr(root, '_cache_locked', original)
    result = upload(f, body)
    assert result.status_code == 200, result.text
    assert len(result.json()['artifact_ids']) == 1
    assert sum(r.method == 'POST' for r in f['remote'].requests) == 1
    assert f['provider'].sent == 0


def _export_input():
    return {'format': 'csv', 'as_of': 15, 'criteria_version': 'criteria-1',
            'filters': {'purpose': 'regression'}, 'cohort': 'strict',
            'expires_at': '2099-01-01T00:00:00+00:00'}


@pytest.mark.parametrize('operation', ['recovery', 'export', 'apk'])
def test_remote_publish_does_not_block_loop_or_heartbeat_writer(remote_job, monkeypatch, operation):
    import base64
    import threading
    from ux_support import session
    from test_w25 import _export_graph
    f = remote_job
    if operation == 'export':
        graph = _export_graph(f['database'], f['project'], str(f['actor'].actor_id))
        path = f"/api/v1/executions/{graph['execution']}/exports?project_id={f['project']}"
        body = _export_input()
    elif operation == 'apk':
        from test_rx_74 import _apk_bytes
        apk = _apk_bytes(b'private-remote-apk-upload')
        path = f"/api/v1/projects/{f['project']}/app-builds"
        body = {'filename': 'remote.apk', 'body_base64': base64.b64encode(apk).decode(),
                'declared_length': len(apk), 'tool_path': 'fixture-meta'}
    else:
        with sqlite3.connect(f['database']) as c:
            recording_id = c.execute('SELECT recording_id FROM jobs WHERE job_id=?', (f['job']['job_id'],)).fetchone()[0]
            c.execute("UPDATE recordings SET stop_status='stopped',completion_status='interrupted' WHERE recording_id=?", (recording_id,))
        path = f'/api/v1/recordings/{recording_id}/evidence-recoveries'
        body = {'project_id': f['project'], 'captures': [{'action_id': 'act1', 'timing': 'immediate',
                'png_b64': base64.b64encode(b'PNG').decode()}]}
    root = f['remote_root']
    original = root.put
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    def slow(*args, **kwargs):
        started.set()
        try:
            assert release.wait(2), 'remote publish stalled other requests'
            return original(*args, **kwargs)
        finally:
            finished.set()
    monkeypatch.setattr(root, 'put', slow)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=f['app']), base_url='http://127.0.0.1') as client:
            headers = await session(client, f['project'])
            pending = asyncio.create_task(client.post(path, json=body, headers=headers))
            try:
                for _ in range(60):
                    await asyncio.sleep(.005)
                    if started.is_set():
                        break
                assert started.is_set() and not finished.is_set(), 'remote publish blocked event loop'
                heartbeat = await asyncio.wait_for(client.post('/api/v1/worker/heartbeats',
                    json={'boot_id': 'fixture-boot'}, headers={'Authorization': 'Bearer ' + f['token']}), .5)
                assert heartbeat.status_code == 200 and not finished.is_set()
            finally:
                release.set()
                response = await pending
            assert response.status_code in (200, 201), response.text
    asyncio.run(run())


def test_export_lost_response_keeps_unready_identity_and_retries_frozen_snapshot(remote_job):
    import json
    from ux_support import session
    from test_w25 import _export_graph, _late_facts
    f = remote_job
    graph = _export_graph(f['database'], f['project'], str(f['actor'].actor_id))
    remote = f['remote']
    def lose_response(request):
        response = remote(request)
        if request.method == 'POST':
            raise httpx.ReadTimeout('lost response', request=request)
        return response
    root = f['remote_root']
    root._client.close()
    root._client = httpx.Client(transport=httpx.MockTransport(lose_response))
    path = f"/api/v1/executions/{graph['execution']}/exports?project_id={f['project']}"
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=f['app']), base_url='http://127.0.0.1') as client:
            headers = await session(client, f['project'])
            first = await client.post(path, json=_export_input(), headers=headers)
            assert first.status_code == 422, first.text
            with sqlite3.connect(f['database']) as c:
                jobs = c.execute("SELECT job_id,limits,status FROM jobs WHERE purpose='export'").fetchall()
            assert len(jobs) == 1 and jobs[0][2] == 'queued'
            job_id, frozen, _ = jobs[0]
            unready = await client.get(f"/api/v1/exports/{job_id}?project_id={f['project']}", headers=headers)
            assert unready.status_code == 200 and unready.json()['artifact_ready'] is False
            _late_facts(f['database'], f['project'], graph['run'])
            root._client.close()
            root._client = httpx.Client(transport=httpx.MockTransport(remote))
            retried = await client.post(path, json=_export_input(), headers=headers)
            assert retried.status_code == 200, retried.text
            assert retried.json()['job_id'] == job_id and retried.json()['artifact_ready'] is True
            assert retried.json()['cost'] is None and retried.json()['as_of'] == 15
            with sqlite3.connect(f['database']) as c:
                assert c.execute("SELECT limits,status FROM jobs WHERE job_id=?", (job_id,)).fetchone() == (frozen, 'completed')
                assert c.execute("SELECT COUNT(*) FROM jobs WHERE purpose='export'").fetchone()[0] == 1
            assert json.loads(frozen)['created_at'] == retried.json()['created_at']
    asyncio.run(run())
    assert sum(r.method == 'POST' for r in remote.requests) == 1


def test_apk_lost_response_keeps_stage_without_ready_build_and_retry_reuses_object(remote_job):
    import base64
    from ux_support import session
    from test_rx_74 import _apk_bytes
    f = remote_job
    apk = _apk_bytes(b'private-remote-retried-apk')
    remote, root = f['remote'], f['remote_root']
    def lose_response(request):
        response = remote(request)
        if request.method == 'POST':
            raise httpx.ReadTimeout('lost upload response', request=request)
        return response
    root._client.close()
    root._client = httpx.Client(transport=httpx.MockTransport(lose_response))
    body = {'filename': 'remote.apk', 'body_base64': base64.b64encode(apk).decode(),
            'declared_length': len(apk), 'tool_path': 'fixture-meta'}
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=f['app']), base_url='http://127.0.0.1') as client:
            headers = await session(client, f['project'])
            path = f"/api/v1/projects/{f['project']}/app-builds"
            first = await client.post(path, json=body, headers=headers)
            assert first.status_code == 409, first.text
            with sqlite3.connect(f['database']) as c:
                assert c.execute('SELECT COUNT(*) FROM app_builds').fetchone()[0] == 0
                staged_key = c.execute('SELECT object_key FROM artifact_staging').fetchone()[0]
            assert list(remote.objects) == [staged_key]
            root._client.close()
            root._client = httpx.Client(transport=httpx.MockTransport(remote))
            retried = await client.post(path, json=body, headers=headers)
            assert retried.status_code == 201 and retried.json()['ready'] is True, retried.text
            with sqlite3.connect(f['database']) as c:
                assert c.execute('SELECT object_key FROM app_builds').fetchone()[0] == staged_key
                assert c.execute('SELECT COUNT(*) FROM artifact_staging').fetchone()[0] == 0
            again = await client.post(path, json=body, headers=headers)
            assert again.status_code == 201 and again.json()['replayed'] is True
            assert again.json()['build_id'] == retried.json()['build_id']
    asyncio.run(run())
    assert sum(r.method == 'POST' for r in remote.requests) == 1


@pytest.mark.parametrize('suffix', ['', '/retention'])
def test_slow_remote_download_does_not_block_worker_heartbeat(remote_job, monkeypatch, suffix):
    import threading
    import time
    f = remote_job
    result = upload(f, payload(f, datetime.now(timezone.utc)))
    artifact = result.json()['artifact_ids'][0]
    root = f['remote_root']
    original = root.read
    started, finished = threading.Event(), threading.Event()
    def slow(*args, **kwargs):
        started.set()
        time.sleep(.3)
        try:
            return original(*args, **kwargs)
        finally:
            finished.set()
    monkeypatch.setattr(root, 'read', slow)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=f['app']), base_url='http://127.0.0.1') as client:
            headers = {'Authorization': 'Bearer ' + f['token']}
            download = asyncio.create_task(client.get('/api/v1/artifacts/' + artifact + suffix, headers=headers))
            try:
                for _ in range(30):
                    await asyncio.sleep(.005)
                    if started.is_set():
                        break
                assert started.is_set() and not finished.is_set(), 'remote read blocked event loop'
                heartbeat = await client.post('/api/v1/worker/heartbeats', json={'boot_id': 'fixture-boot'}, headers=headers)
                assert heartbeat.status_code == 200 and not finished.is_set()
            finally:
                loaded = await download
            assert loaded.status_code == 200
    asyncio.run(run())


def test_registered_apk_download_survives_cache_loss(remote_job):
    from uuid import UUID
    from aiqa.environments.app_builds import ApkInspectionSpec, register_app_build
    from test_rx_74 import _apk_bytes
    f = remote_job
    body = _apk_bytes(b'private-remote-apk')
    store = f['app'].state.open_store()
    try:
        with store.transaction() as c:
            _, view = register_app_build(ApkInspectionSpec(UUID(f['project']), 'remote.apk', body, len(body)),
                                         tool_path='fixture-meta', connection=c, artifacts_dir=f['remote_root'])
    finally:
        store.close()
    shutil.rmtree(f['remote_root'].cache_dir)
    async def read():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=f['app']), base_url='http://127.0.0.1') as client:
            return await client.get(f"/api/v1/projects/{f['project']}/app-builds/{view.build_id}/content",
                                    headers={'Authorization': 'Bearer ' + f['token']})
    result = asyncio.run(read())
    assert result.status_code == 200 and result.content == body


def test_private_evidence_review_approval_and_same_package_ai0_replay(recorded, tmp_path, monkeypatch):
    from uuid import UUID, uuid4
    from aiqa.store.artifacts import publish_durable, open_durable
    import test_ma05b2_same_package as journey
    remote = Remote()
    root = make_root(tmp_path, remote)
    r = recorded
    r['store'].config = replace(r['store'].config, artifacts_dir=root)

    def stored_artifact(c, project, owner_kind, owner, attempt, action, role, job):
        artifact = uuid4()
        durable = publish_durable(root, project, artifact, '.png', b'private-review-PNG')
        c.execute('INSERT INTO artifact_refs(project_id,artifact_id,attempt_id,action_id) VALUES(?,?,?,?)',
                  (str(project), str(artifact), attempt, action))
        c.execute('''INSERT INTO artifact_objects(project_id,artifact_id,object_key,content_hash,byte_length,media_type,
            owner_id,status,acked,custody,stored_at,owner_kind,attempt_id,action_id,role,job_id,generation)
            VALUES(?,?,?,?,?,'image/png',?,'ready',1,'stored',?,?,?,?,?,?,1)''',
                  (str(project), str(artifact), durable.object_key, durable.content_hash, durable.byte_length,
                   owner, datetime.now(timezone.utc).isoformat(), owner_kind, attempt, action, role, job))
        return str(artifact), durable.content_hash

    original_approve = journey.approve_case
    def approve_after_cache_loss(*args, **kwargs):
        shutil.rmtree(root.cache_dir)
        # Server-only authenticated reads work while the worker is absent.
        for key, body in remote.objects.items():
            from aiqa.store.artifacts import content_hash
            assert open_durable(root, key, content_hash(body)) == body
        return original_approve(*args, **kwargs)
    monkeypatch.setattr(journey, '_artifact', stored_artifact)
    monkeypatch.setattr(journey, 'approve_case', approve_after_cache_loss)
    journey.test_saved_source_is_approved_then_the_same_package_replays_without_actor_ai(r, tmp_path)
    assert len(remote.objects) == 2
