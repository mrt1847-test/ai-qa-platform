"""Normal queued recording/worker ACK path on PostgreSQL + private Storage."""
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from tests.integration.test_hs2_postgres import pg_store
from tests.unit.test_hs3_object_storage import Remote, make_root


@pytest.fixture
def pg_recording(pg_store, tmp_path):
    from aiqa.api.auth import bound_auth_store, enroll_worker
    from aiqa.contracts.cases import CaseDefinition, CaseRevisionInput, CaseSettings, PathPolicy
    from aiqa.contracts.jobs import IdempotencyKey, JobSubmission, LeaseToken
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.domain.versions import bind_case_store, create_case, save_case_revision
    from aiqa.security.receipt_digest import EnvironmentReceiptKey
    from aiqa.store.database import open_store
    from aiqa.store.models import Actor, ProjectCreate, Transaction, WorkerScope
    from aiqa.store.queue import enqueue_job
    from aiqa.worker.service import bind_claim_store, claim_job
    from worker_presence_support import seed_presence, seed_inventory, seed_resource_alias
    import base64

    store = pg_store
    remote = Remote()
    root = make_root(tmp_path, remote)
    store.config = replace(store.config, artifacts_dir=root, receipt_key_provider=EnvironmentReceiptKey(
        environ={'AIQA_RECEIPT_HMAC_KEY': base64.b64encode(b'K' * 32).decode()}))
    owner = Actor(uuid4(), None, True)
    with bind_store(store):
        project = create_project(owner, ProjectCreate('Worker PG', 'worker-pg', '', 'web'))
    actor = Actor(owner.actor_id, project.project_id, True)
    with bind_case_store(store):
        case = create_case(actor, 'Recording', None)
        version = save_case_revision(actor, case.case_id, CaseRevisionInput(
            CaseDefinition('pay', 'pay', (), {}, {}, (), (), PathPolicy()), CaseSettings('web')), None)
    with bound_auth_store(store):
        worker_token = enroll_worker(actor, 'pg-worker', 'recording')
    physical = uuid4()
    con = store._connection
    con.execute('INSERT INTO physical_resource_keys(physical_key_id,worker_id,native_id) VALUES(?,?,?)',
                (str(physical), 'pg-worker', 'fixture-device'))
    seed_resource_alias(con, project.project_id, physical, display_name='Fixture', target_kind='web')
    now = datetime.now(timezone.utc)
    seed_presence(con, project.project_id, 'pg-worker', now)
    seed_inventory(con, physical)
    with store.transaction() as tx:
        receipt = enqueue_job(Transaction(tx), JobSubmission(project.project_id, 'recording', case.case_id,
            version.id, (str(physical),), '{}'), IdempotencyKey(actor.actor_id, project.project_id, 'enqueue_job', 'pg-record'), now=now)
    worker = WorkerScope('pg-worker', (project.project_id,), ('recording',))
    with bind_claim_store(store):
        job = claim_job(worker, now)
    assert job is not None
    yield SimpleNamespace(store=store, open_store=lambda: open_store(store.config), con=con, project=project,
        actor=actor, case=case, version=version, recording_id=receipt.recording_id, job=job,
        lease=LeaseToken(job.project_id, job.job_id, job.generation), worker=worker,
        worker_token=worker_token, now=now, remote=remote, root=root)
    root.close()


def test_queued_recording_claim_and_private_upload_receipt(pg_recording):
    from tests.integration.test_review_evidence import test_worker_upload_http_key_replays_and_rejects_changed_body
    f = pg_recording
    test_worker_upload_http_key_replays_and_rejects_changed_body(f)
    assert f.remote.objects
    assert f.con.execute('SELECT count(*) FROM artifact_upload_requests WHERE response_body IS NOT NULL').fetchone()[0] == 1
    assert f.con.execute("SELECT count(*) FROM artifact_objects WHERE status='ready' AND acked=1").fetchone()[0] == 1


def test_postgres_artifact_reconciliation_supports_batch_updates(pg_store):
    from aiqa.store.evidence import ArtifactBinding, bind_artifact_ingest, reconcile_artifacts, reset_artifact_ingest
    token = bind_artifact_ingest(ArtifactBinding(pg_store, None, datetime.now(timezone.utc)))
    try:
        report = reconcile_artifacts()
        assert report.missing == 0
    finally:
        reset_artifact_ingest(token)


def test_postgres_migration_rejects_disabled_guard(pg_store):
    from aiqa.store.database import StorageError, migrate_store
    pg_store._connection.raw.execute('ALTER TABLE case_versions DISABLE TRIGGER case_versions_no_update')
    with pytest.raises(StorageError):
        migrate_store(pg_store)


def test_postgres_migration_rejects_changed_function_and_rendered_snapshot(pg_store, monkeypatch):
    from aiqa.store.database import StorageError, migrate_store
    from aiqa.store import postgres_schema
    original = postgres_schema.load_manifest
    with monkeypatch.context() as changed:
        changed.setattr(postgres_schema, 'load_manifest', lambda: {**original(), 'rendered_sha256': '00' * 32})
        with pytest.raises(StorageError):
            migrate_store(pg_store)
    pg_store._connection.raw.execute('''CREATE OR REPLACE FUNCTION aiqa_guard_case_versions_no_update()
        RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END $$''')
    with pytest.raises(StorageError):
        migrate_store(pg_store)


def test_video_restart_reads_explicit_publisher_columns_on_postgres(pg_store):
    from aiqa.api.app import create_app
    from aiqa.api.video import manager
    from aiqa.config import load_settings
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.store.database import open_store
    from aiqa.store.models import Actor, ProjectCreate
    with bind_store(pg_store):
        project = create_project(Actor(uuid4(), None, True), ProjectCreate('Video', 'video', '', 'android'))
    pg_store._connection.execute('INSERT INTO live_video_publishers VALUES(?,?,?,?,?,?,?,?)',
        ('session', str(project.project_id), 'resource', 'actor', 'worker', 'native', 'producer', 0))
    app = create_app(load_settings({'AIQA_RUNTIME_ROOT': str(pg_store.config.runtime_root)}))
    app.state.open_store = lambda: open_store(pg_store.config)
    assert manager(app).sessions['session'].status == 'blocked'


def test_first_admin_oidc_and_browser_receipt_survive_restart_on_postgres(pg_store):
    """Exercise the hosted operator/login/mutation seam on the actual DB adapter."""
    import asyncio
    import base64
    import httpx
    from aiqa.api.app import create_app
    from aiqa.config import load_settings
    from aiqa.hosted.bootstrap import bootstrap_first_admin
    from aiqa.security.oidc import FixtureIdP
    from aiqa.security.receipt_digest import EnvironmentReceiptKey
    from aiqa.security.secrets import MemorySecretBackend, build_server_secret_resolver
    from aiqa.store.database import StorageConfig
    from unittest.mock import patch
    from aiqa.store.models import ProjectCreate

    settings = load_settings({'AIQA_PROFILE': 'hosted',
        'AIQA_RUNTIME_ROOT': str(pg_store.config.runtime_root),
        'AIQA_DATABASE_BACKEND': 'postgres', 'AIQA_DATABASE_URL': pg_store.config.database_url,
        'AIQA_PUBLIC_ORIGIN': 'https://manage.test', 'AIQA_TRUSTED_PROXIES': '127.0.0.1',
        'AIQA_OIDC_ISSUER': 'https://idp.example.test', 'AIQA_OIDC_CLIENT_ID': 'client',
        'AIQA_OIDC_AUDIENCE': 'client'})
    backend = MemorySecretBackend()
    build_server_secret_resolver(settings, backend=backend).store_oidc_client_secret('synthetic-client-secret')
    pg_store.config = replace(pg_store.config, receipt_key_provider=EnvironmentReceiptKey(
        environ={'AIQA_RECEIPT_HMAC_KEY': base64.b64encode(b'K' * 32).decode()}))
    idp = FixtureIdP(audience='client')
    identity = bootstrap_first_admin(pg_store, issuer=idp.issuer, subject='operator',
        project=ProjectCreate('Hosted PG', 'hosted-pg', '', 'android'))
    assert bootstrap_first_admin(pg_store, issuer=idp.issuer, subject='operator',
        project=ProjectCreate('Hosted PG', 'hosted-pg', '', 'android')) == identity

    def application():
        # Substitute only the test schema, keeping the real factory's borrowed
        # mutation-store behavior and connection lifetime intact.
        with patch.object(StorageConfig, 'from_settings', return_value=pg_store.config):
            return create_app(settings, secret_backend=backend, oidc_idp=idp)

    async def journey():
        headers = {'Origin': settings.public_origin, 'X-Forwarded-Proto': 'https',
                   'Idempotency-Key': 'pg-login'}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application()),
                                     base_url=settings.public_origin) as browser:
            started = await browser.post('/api/v1/auth/oidc/start', headers=headers,
                                         json={'project_id': identity['project_id']})
            assert started.status_code == 201, started.text
            state = started.json()['state']
            nonce, challenge = pg_store._connection.execute(
                'SELECT nonce,code_challenge FROM oidc_login_states WHERE state=?', (state,)).fetchone()
            code = idp.issue_code(subject='operator', redirect_uri=settings.public_origin + '/api/v1/auth/oidc/callback',
                                 state=state, nonce=nonce, code_challenge=challenge)
            logged_in = await browser.get('/api/v1/auth/oidc/callback', headers=headers,
                                          params={'state': state, 'code': code})
            assert logged_in.status_code == 303, logged_in.text
            headers.update({'X-CSRF-Token': browser.cookies['aiqa_csrf'], 'Idempotency-Key': 'pg-dataset'})
            path = f"/api/v1/projects/{identity['project_id']}/datasets"
            body = {'name': 'Orders', 'row_schema': {'columns': [{'name': 'amount', 'type': 'int'}]},
                    'rows': [{'id': 'r1', 'values': {'amount': 10000}}]}
            saved = await browser.post(path, headers=headers, json=body)
            assert saved.status_code == 201, saved.text
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application()),
                    base_url=settings.public_origin, cookies=browser.cookies) as restarted:
                repeated = await restarted.post(path, headers=headers, json=body)
                assert repeated.status_code == 200 and repeated.json()['id'] == saved.json()['id'], repeated.text
                conflict = await restarted.post(path, headers=headers, json={**body, 'name': 'Changed'})
                assert conflict.status_code == 409, conflict.text
    asyncio.run(journey())
