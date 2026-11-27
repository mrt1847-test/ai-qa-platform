"""Private remote durability, with no accounts or cloud calls."""
import shutil
from uuid import uuid4

import httpx
import pytest

from aiqa.store.artifacts import ArtifactRejected, content_hash, open_durable, publish_durable, resolve_stored


class Remote:
    def __init__(self):
        self.objects = {}
        self.requests = []
        self.failure = None
        self.public = False
        self.corrupt_read = False
        self.missing_status = 400

    def __call__(self, request):
        self.requests.append(request)
        assert request.headers['apikey'] == 'synthetic-server-key'
        assert request.headers['authorization'] == 'Bearer synthetic-server-key'
        if self.failure:
            if self.failure == 'timeout':
                raise httpx.ReadTimeout('synthetic secret upstream failure', request=request)
            return httpx.Response(self.failure, headers={'location': 'https://attacker.invalid/key'}, json={'message': 'synthetic-server-key'})
        path = request.url.path
        if path == '/storage/v1/bucket/private-evidence':
            return httpx.Response(200, json={'id': 'private-evidence', 'public': self.public})
        prefix = '/storage/v1/object/'
        assert path.startswith(prefix)
        key = path.removeprefix(prefix).removeprefix('authenticated/').removeprefix('private-evidence/')
        if request.method == 'POST':
            assert request.headers['x-upsert'] == 'false'
            if key in self.objects:
                return httpx.Response(409, json={'error': 'Duplicate'})
            self.objects[key] = request.content
            return httpx.Response(200, json={'Key': key})
        if request.method == 'DELETE':
            import json
            for item in json.loads(request.content)['prefixes']:
                self.objects.pop(item, None)
            return httpx.Response(200, json=[])
        if key not in self.objects:
            return httpx.Response(self.missing_status, json={
                'statusCode': '404', 'code': 'NoSuchKey', 'error': 'not_found', 'message': 'Object not found'})
        return httpx.Response(200, content=b'corrupt' if self.corrupt_read else self.objects[key])


def make_root(tmp_path, remote, **kwargs):
    from aiqa.store.object_storage import artifact_root
    return artifact_root(tmp_path / 'cache', backend='supabase', supabase_url='https://example.supabase.co',
                         service_key='synthetic-server-key', bucket='private-evidence',
                         client=httpx.Client(transport=httpx.MockTransport(remote)), **kwargs)


def test_recovery_retry_reuses_manifest_and_remote_objects_after_lost_response(tmp_path):
    from aiqa.recording.recovery import EvidenceRecoverySpec, RecoveryCapture, RecoveryRejected, prepare_recovery
    remote = Remote()
    root = make_root(tmp_path, remote)
    lost = {'once': True}
    def uncertain(request):
        response = remote(request)
        if request.method == 'POST' and lost['once']:
            lost['once'] = False
            raise httpx.ReadTimeout('response lost', request=request)
        return response
    root._client.close()
    root._client = httpx.Client(transport=httpx.MockTransport(uncertain))
    spec = EvidenceRecoverySpec(uuid4(), uuid4(), 'recovery-request', (
        RecoveryCapture('A1', 'immediate', b'first'), RecoveryCapture('A2', 'delayed', b'second')))
    with pytest.raises(RecoveryRejected):
        prepare_recovery(root, spec)
    prior_key = next(iter(remote.objects))
    prepared = prepare_recovery(root, spec)
    again = prepare_recovery(root, spec)
    assert prepared.manifest_id == again.manifest_id
    assert prior_key in remote.objects and len(remote.objects) == 2
    assert sum(r.method == 'POST' for r in remote.requests) == 2
    assert str(prepared.manifest_id) in prior_key


@pytest.mark.parametrize('status', [400, 404])
def test_storage_missing_wire_response_allows_first_upload(tmp_path, status):
    remote = Remote()
    remote.missing_status = status
    root = make_root(tmp_path, remote)
    receipt = publish_durable(root, uuid4(), uuid4(), '.png', b'PNG')
    assert open_durable(root, receipt.object_key, receipt.content_hash) == b'PNG'
    assert sum(r.method == 'POST' for r in remote.requests) == 1


@pytest.mark.parametrize('status', [400, 404])
def test_storage_missing_wire_response_removes_stale_cache_and_materializes_absent_path(tmp_path, status):
    remote = Remote()
    remote.missing_status = status
    root = make_root(tmp_path, remote)
    key = 'project/absent.png'
    root._cache(key, b'stale')
    with pytest.raises(ArtifactRejected, match='artifact is missing'):
        open_durable(root, key, content_hash(b'stale'))
    assert not root.path(key).exists()
    assert root.materialize(key) == root.path(key)


@pytest.mark.parametrize('status', [400, 404])
def test_storage_missing_wire_response_verifies_deletion(tmp_path, status):
    remote = Remote()
    remote.missing_status = status
    root = make_root(tmp_path, remote)
    key = 'project/deleted.png'
    remote.objects[key] = b'PNG'
    root._cache(key, b'PNG')
    root.delete(key)
    assert key not in remote.objects and not root.path(key).exists()


@pytest.mark.parametrize('status,body', [
    (400, b'{"statusCode":"404","code":"NoSuchBucket","error":"Bucket not found"}'),
    (400, b'{"statusCode":"403","code":"AccessDenied","error":"Unauthorized"}'),
    (400, b'{"statusCode":"400","code":"InvalidJWT"}'),
    (400, b'{"statusCode":"403","code":"NoSuchKey","error":"not_found"}'),
    (400, b'{"statusCode":"404","error":"not_found"}'),
    (400, b'{"code":"NoSuchKey","error":"not_found"}'),
    (400, b'{"statusCode":404,"code":"NoSuchKey","error":"not_found"}'),
    (400, b'[]'), (400, b'null'), (400, b'not JSON'),
    (401, b'{"statusCode":"404","code":"NoSuchKey","error":"not_found"}'),
    (403, b'{"statusCode":"404","code":"NoSuchKey","error":"not_found"}'),
    (500, b'{"statusCode":"404","code":"NoSuchKey","error":"not_found"}'),
])
def test_storage_other_errors_cannot_be_treated_as_absent_objects(tmp_path, status, body):
    remote = Remote()
    def reject_object_read(request):
        if '/object/authenticated/' in request.url.path:
            remote.requests.append(request)
            return httpx.Response(status, content=body)
        return remote(request)
    root = make_root(tmp_path, reject_object_read)
    with pytest.raises(ArtifactRejected, match='read failed'):
        publish_durable(root, uuid4(), uuid4(), '.png', b'PNG')
    assert not any(r.method == 'POST' for r in remote.requests)


@pytest.mark.parametrize('key,bearer', [
    ('sb_secret_synthetic_server_key', False),
    ('eyJ.synthetic.service_role', True),
    ('synthetic-server-key', True),
])
def test_server_key_headers_cover_all_storage_operations(tmp_path, key, bearer):
    from aiqa.store.object_storage import artifact_root
    remote = Remote()
    def authenticated(request):
        assert request.headers['apikey'] == key
        assert request.headers.get('authorization') == ('Bearer ' + key if bearer else None)
        # Reuse the fake object's protocol assertions independently of credentials.
        request.headers['apikey'] = 'synthetic-server-key'
        request.headers['authorization'] = 'Bearer synthetic-server-key'
        return remote(request)
    root = artifact_root(tmp_path / 'cache', backend='supabase', supabase_url='https://example.supabase.co',
                         service_key=key, bucket='private-evidence',
                         client=httpx.Client(transport=httpx.MockTransport(authenticated)))
    receipt = publish_durable(root, uuid4(), uuid4(), '.png', b'PNG')
    assert open_durable(root, receipt.object_key, receipt.content_hash) == b'PNG'
    root.delete(receipt.object_key)
    assert {r.method for r in remote.requests} == {'GET', 'POST', 'DELETE'}


def test_publishable_key_is_rejected_before_private_storage_requests(tmp_path):
    from aiqa.store.object_storage import artifact_root
    with pytest.raises(ValueError, match='server') as error:
        artifact_root(tmp_path / 'cache', backend='supabase', supabase_url='https://example.supabase.co',
                      service_key='sb_publishable_synthetic_browser_key', bucket='private-evidence')
    assert 'sb_publishable_synthetic_browser_key' not in str(error.value)


def test_upload_readback_retry_conflict_and_cache_loss(tmp_path):
    remote = Remote()
    root = make_root(tmp_path, remote)
    project, artifact = uuid4(), uuid4()
    receipt = publish_durable(root, project, artifact, '.png', b'PNG')
    assert receipt.content_hash == content_hash(b'PNG')
    assert publish_durable(root, project, artifact, '.png', b'PNG') == receipt
    with pytest.raises(ArtifactRejected, match='different bytes'):
        publish_durable(root, project, artifact, '.png', b'OTHER')
    shutil.rmtree(root.cache_dir)
    assert open_durable(root, receipt.object_key, receipt.content_hash) == b'PNG'
    assert resolve_stored(root, receipt.object_key).read_bytes() == b'PNG'
    assert 'synthetic-server-key' not in repr(root)
    assert all('/public/' not in str(r.url) and '/sign/' not in str(r.url) for r in remote.requests)


@pytest.mark.parametrize('failure', ['timeout', 301, 401, 403, 500])
def test_uncertain_or_refused_upload_never_publishes_cache(tmp_path, failure):
    remote = Remote()
    root = make_root(tmp_path, remote)
    remote.failure = failure
    with pytest.raises(ArtifactRejected) as error:
        publish_durable(root, uuid4(), uuid4(), '.png', b'PNG')
    assert 'synthetic-server-key' not in str(error.value)
    assert not list(root.cache_dir.rglob('*.png'))
    assert all(r.url.host == 'example.supabase.co' for r in remote.requests)


def test_readback_required_even_after_successful_upload(tmp_path):
    remote = Remote()
    root = make_root(tmp_path, remote)
    remote.corrupt_read = True
    with pytest.raises(ArtifactRejected, match='hash'):
        publish_durable(root, uuid4(), uuid4(), '.log', b'log')
    assert not list(root.cache_dir.rglob('*.log'))


def test_public_bucket_is_refused(tmp_path):
    remote = Remote()
    root = make_root(tmp_path, remote)
    remote.public = True
    with pytest.raises(ArtifactRejected, match='private'):
        publish_durable(root, uuid4(), uuid4(), '.png', b'PNG')


def test_cache_cannot_ack_or_hide_remote_missing(tmp_path):
    remote = Remote()
    root = make_root(tmp_path, remote)
    project, artifact = uuid4(), uuid4()
    receipt = publish_durable(root, project, artifact, '.png', b'PNG')
    remote.objects.clear()
    with pytest.raises(ArtifactRejected, match='missing'):
        open_durable(root, receipt.object_key, receipt.content_hash)
    assert not resolve_stored(root, receipt.object_key).exists()


def test_remote_delete_verified_before_local_deletion(tmp_path):
    from aiqa.store.artifacts import delete_durable
    remote = Remote()
    root = make_root(tmp_path, remote)
    receipt = publish_durable(root, uuid4(), uuid4(), '.png', b'PNG')
    delete_durable(root, receipt.object_key)
    assert not remote.objects
    assert not resolve_stored(root, receipt.object_key).exists()


def test_local_factory_preserves_path_and_unsafe_remote_config_fails(tmp_path):
    from aiqa.store.object_storage import artifact_root
    assert artifact_root(tmp_path) == tmp_path
    for url in ('http://example.supabase.co', 'https://user:pass@example.supabase.co', 'https://example.supabase.co/path'):
        with pytest.raises(ValueError):
            artifact_root(tmp_path, backend='supabase', supabase_url=url, service_key='x', bucket='private')


def test_remote_limit_refuses_large_read(tmp_path):
    remote = Remote()
    root = make_root(tmp_path, remote, max_bytes=3)
    remote.objects['p/a.png'] = b'four'
    with pytest.raises(ArtifactRejected, match='limit'):
        open_durable(root, 'p/a.png', content_hash(b'four'))


def test_recovery_captures_remain_remote_after_cache_loss(tmp_path):
    import json
    from aiqa.recording.recovery import prepare_recovery, EvidenceRecoverySpec, RecoveryCapture
    remote = Remote()
    root = make_root(tmp_path, remote)
    prepared = prepare_recovery(root, EvidenceRecoverySpec(uuid4(), uuid4(), 'recover',
                                (RecoveryCapture('act1', 'immediate', b'PNG'),)))
    entry = json.loads(prepared.mapping_json)['act1']
    shutil.rmtree(root.cache_dir)
    assert open_durable(root, entry['object_key'], entry['hash']) == b'PNG'


def test_recovery_storage_outage_uses_domain_rejection(tmp_path):
    from aiqa.recording.recovery import prepare_recovery, EvidenceRecoverySpec, RecoveryCapture, RecoveryRejected
    remote = Remote()
    root = make_root(tmp_path, remote)
    remote.failure = 'timeout'
    with pytest.raises(RecoveryRejected, match='stored') as error:
        prepare_recovery(root, EvidenceRecoverySpec(uuid4(), uuid4(), 'recover',
                         (RecoveryCapture('act1', 'immediate', b'PNG'),)))
    assert 'synthetic-server-key' not in str(error.value)


def test_export_manifest_uses_remote_durability(tmp_path, monkeypatch):
    from aiqa.domain import exports
    from aiqa.domain.hashing import canonical_json
    remote = Remote()
    root = make_root(tmp_path, remote)
    project, job = uuid4(), uuid4()
    manifest = {'format': 'csv', 'as_of': 1}
    monkeypatch.setattr(exports, '_stored_manifest', lambda *_: manifest)
    exports._write_artifact(root, project, job, None)
    shutil.rmtree(root.cache_dir)
    body = canonical_json(manifest).encode()
    assert open_durable(root, f'{project}/exports/{job}.json', content_hash(body)) == body


def test_retention_deletes_remote_payload_after_pin_check(tmp_path):
    import sqlite3
    from datetime import datetime, timezone
    from aiqa.store.retention import RetentionPlan, RetentionAction, apply_retention
    remote = Remote()
    root = make_root(tmp_path, remote)
    project, artifact = uuid4(), uuid4()
    receipt = publish_durable(root, project, artifact, '.png', b'PNG')
    c = sqlite3.connect(':memory:')
    c.executescript('''CREATE TABLE artifact_protections(project_id,artifact_id,protection_id);
        CREATE TABLE protection_releases(project_id,protection_id);
        CREATE TABLE artifact_objects(project_id,artifact_id,custody);
        CREATE TABLE retention_tombstones(project_id,tombstone_id,subject_kind,subject_id,content_hash,expired_at);
        CREATE TABLE payload_retention_events(project_id,event_id,subject_kind,subject_id,content_hash,created_at);''')
    c.execute('INSERT INTO artifact_objects VALUES(?,?,?)', (str(project), str(artifact), 'stored'))
    c.execute('INSERT INTO artifact_protections VALUES(?,?,?)', (str(project), str(artifact), 'pin'))
    plan = RetentionPlan((RetentionAction(str(artifact), 'png', receipt.content_hash, receipt.object_key, True, True),), 0, True, 0, True)
    now = datetime.now(timezone.utc)
    apply_retention(c, project, plan, root, tmp_path / 'spool', now)
    assert receipt.object_key in remote.objects
    c.execute('DELETE FROM artifact_protections')
    apply_retention(c, project, plan, root, tmp_path / 'spool', now)
    assert receipt.object_key not in remote.objects
    assert c.execute('SELECT COUNT(*) FROM retention_tombstones').fetchone()[0] == 1


def test_hosted_backup_refuses_before_sqlite_snapshot(tmp_path):
    from types import SimpleNamespace
    from datetime import datetime, timezone
    from aiqa.store.backup import create_backup, BackupSpec, BackupRejected
    from aiqa.store.models import Actor
    project = uuid4()
    root = make_root(tmp_path, Remote())
    store = SimpleNamespace(config=SimpleNamespace(artifacts_dir=root))
    with pytest.raises(BackupRejected, match='hosted'):
        create_backup(store, BackupSpec(project, Actor(uuid4(), project, True)), datetime.now(timezone.utc))


def test_hosted_restore_refuses_sqlite_validation_and_activation(tmp_path):
    from types import SimpleNamespace
    from datetime import datetime, timezone
    from aiqa.store.backup import validate_restore, activate_restore, RestoreSpec, RestoreActivation, RestoreRejected
    from aiqa.store.models import Actor
    project = uuid4()
    actor = Actor(uuid4(), project, True)
    store = SimpleNamespace(config=SimpleNamespace(artifacts_dir=make_root(tmp_path, Remote())))
    now = datetime.now(timezone.utc)
    with pytest.raises(RestoreRejected, match='hosted'):
        validate_restore(store, RestoreSpec(project, uuid4(), actor), now)
    with pytest.raises(RestoreRejected, match='hosted'):
        activate_restore(store, RestoreActivation(project, uuid4(), actor, True), now)


def test_timeout_after_remote_write_is_unacked_and_retry_reuses_same_object(tmp_path):
    remote = Remote()
    def lose_upload_response(request):
        result = remote(request)
        if request.method == 'POST':
            raise httpx.ReadTimeout('lost ACK', request=request)
        return result
    from aiqa.store.object_storage import artifact_root
    root = artifact_root(tmp_path / 'cache', backend='supabase', supabase_url='https://example.supabase.co',
                         service_key='synthetic-server-key', bucket='private-evidence',
                         client=httpx.Client(transport=httpx.MockTransport(lose_upload_response)))
    project, artifact = uuid4(), uuid4()
    with pytest.raises(ArtifactRejected):
        publish_durable(root, project, artifact, '.png', b'PNG')
    assert len(remote.objects) == 1 and not root.cache_dir.exists()
    receipt = publish_durable(root, project, artifact, '.png', b'PNG')
    assert receipt.content_hash == content_hash(b'PNG')
    assert sum(r.method == 'POST' for r in remote.requests) == 1


def test_remote_cache_corruption_is_repaired_from_verified_remote(tmp_path):
    remote = Remote()
    root = make_root(tmp_path, remote)
    receipt = publish_durable(root, uuid4(), uuid4(), '.apk', b'APK')
    root.path(receipt.object_key).write_bytes(b'corrupt')
    assert open_durable(root, receipt.object_key, receipt.content_hash) == b'APK'


def test_hosted_suffix_cannot_create_nested_object(tmp_path):
    root = make_root(tmp_path, Remote())
    with pytest.raises(ArtifactRejected):
        publish_durable(root, uuid4(), uuid4(), '/nested.png', b'PNG')


def test_retention_failure_leaves_payload_metadata_untombstoned(tmp_path):
    # The provider must reject a successful delete response while GET still sees
    # the object; the caller cannot treat that response as a durable deletion.
    remote = Remote()
    def ignore_delete(request):
        if request.method == 'DELETE':
            return httpx.Response(200, json=[])
        return remote(request)
    from aiqa.store.object_storage import artifact_root
    root = artifact_root(tmp_path / 'cache', backend='supabase', supabase_url='https://example.supabase.co',
                         service_key='synthetic-server-key', bucket='private-evidence',
                         client=httpx.Client(transport=httpx.MockTransport(ignore_delete)))
    receipt = publish_durable(root, uuid4(), uuid4(), '.png', b'PNG')
    with pytest.raises(ArtifactRejected, match='deletion'):
        root.delete(receipt.object_key)
    assert root.path(receipt.object_key).is_file()


def test_review_viewer_remote_outage_shows_unavailable_without_cache_success(tmp_path):
    from datetime import datetime, timezone
    from aiqa.api.artifacts import _state
    remote = Remote()
    root = make_root(tmp_path, remote)
    receipt = publish_durable(root, uuid4(), uuid4(), '.png', b'PNG')
    remote.failure = 'timeout'
    now = datetime.now(timezone.utc)
    assert _state(root, (None, receipt.object_key, receipt.content_hash, 'ready', 'stored', now.isoformat()), now) == 'missing'


def test_concurrent_cache_reader_does_not_require_replacing_identical_bytes(tmp_path, monkeypatch):
    remote = Remote()
    root = make_root(tmp_path, remote)
    receipt = publish_durable(root, uuid4(), uuid4(), '.png', b'PNG')
    def windows_reader_holds_destination(*args):
        raise PermissionError('destination open by another reader')
    monkeypatch.setattr('aiqa.store.object_storage.os.replace', windows_reader_holds_destination)
    assert open_durable(root, receipt.object_key, receipt.content_hash) == b'PNG'


def test_export_outage_is_unavailable_and_failed_publish_is_rejected(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from aiqa.domain import exports
    remote = Remote()
    root = make_root(tmp_path, remote)
    execution, project, job = uuid4(), uuid4(), uuid4()
    manifest = {'format': 'csv', 'as_of': 1, 'source_ids': [str(execution)],
                'expires_at': '2099-01-01T00:00:00+00:00', 'created_at': '2026-11-25T00:00:00+00:00',
                'criteria_version': 'v1'}
    monkeypatch.setattr(exports, '_stored_manifest', lambda *_: manifest)
    remote.failure = 'timeout'
    tx = SimpleNamespace(connection=SimpleNamespace(execute=lambda *_: SimpleNamespace(fetchone=lambda: (1,))))
    view = exports._view(tx, project, execution, job, False, root, datetime.now(timezone.utc))
    assert view.artifact_ready is False
    with pytest.raises(exports.ExportRejected):
        exports._write_artifact(root, project, job, None)


def test_failed_cache_publish_is_unacked_and_retry_reuses_remote_bytes(tmp_path, monkeypatch):
    remote = Remote()
    root = make_root(tmp_path, remote)
    project, artifact = uuid4(), uuid4()
    original = root._cache_locked
    def disk_full(*args):
        raise OSError('synthetic-server-key disk details')
    monkeypatch.setattr(root, '_cache_locked', disk_full)
    with pytest.raises(ArtifactRejected, match='cache') as error:
        publish_durable(root, project, artifact, '.png', b'PNG')
    assert 'synthetic-server-key' not in str(error.value)
    assert len(remote.objects) == 1 and not root.cache_dir.exists()
    monkeypatch.setattr(root, '_cache_locked', original)
    receipt = publish_durable(root, project, artifact, '.png', b'PNG')
    assert open_durable(root, receipt.object_key, receipt.content_hash) == b'PNG'
    assert sum(r.method == 'POST' for r in remote.requests) == 1


def test_failed_cache_read_reports_unavailable_without_relaying_oserror(tmp_path, monkeypatch):
    remote = Remote()
    root = make_root(tmp_path, remote)
    receipt = publish_durable(root, uuid4(), uuid4(), '.png', b'PNG')
    def permission_denied(*args):
        raise PermissionError('synthetic-server-key filesystem details')
    monkeypatch.setattr(root, '_cache_locked', permission_denied)
    with pytest.raises(ArtifactRejected, match='cache') as error:
        open_durable(root, receipt.object_key, receipt.content_hash)
    assert 'synthetic-server-key' not in str(error.value)


@pytest.mark.parametrize('failure', ['timeout', 'still-present'])
def test_retention_provider_failure_cannot_tombstone_metadata(tmp_path, failure):
    import sqlite3
    from datetime import datetime, timezone
    from aiqa.store.retention import RetentionPlan, RetentionAction, apply_retention
    remote = Remote()
    root = make_root(tmp_path, remote)
    project, artifact = uuid4(), uuid4()
    receipt = publish_durable(root, project, artifact, '.png', b'PNG')
    if failure == 'timeout':
        remote.failure = 'timeout'
    else:
        def ignore_delete(request):
            return httpx.Response(200, json=[]) if request.method == 'DELETE' else remote(request)
        root._client.close()
        root._client = httpx.Client(transport=httpx.MockTransport(ignore_delete))
    c = sqlite3.connect(':memory:')
    c.executescript('''CREATE TABLE artifact_protections(project_id,artifact_id,protection_id);
        CREATE TABLE protection_releases(project_id,protection_id);
        CREATE TABLE artifact_objects(project_id,artifact_id,custody);
        CREATE TABLE retention_tombstones(project_id,tombstone_id,subject_kind,subject_id,content_hash,expired_at);
        CREATE TABLE payload_retention_events(project_id,event_id,subject_kind,subject_id,content_hash,created_at);''')
    c.execute('INSERT INTO artifact_objects VALUES(?,?,?)', (str(project), str(artifact), 'stored'))
    plan = RetentionPlan((RetentionAction(str(artifact), 'png', receipt.content_hash, receipt.object_key, True, True),), 0, True, 0, True)
    with pytest.raises(ArtifactRejected):
        apply_retention(c, project, plan, root, tmp_path / 'spool', datetime.now(timezone.utc))
    assert c.execute('SELECT custody FROM artifact_objects').fetchone()[0] == 'stored'
    assert c.execute('SELECT COUNT(*) FROM retention_tombstones').fetchone()[0] == 0
    assert c.execute('SELECT COUNT(*) FROM payload_retention_events').fetchone()[0] == 0
    assert receipt.object_key in remote.objects
