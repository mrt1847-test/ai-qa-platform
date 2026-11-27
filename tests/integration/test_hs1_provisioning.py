"""Register deployment references; values never enter SQL or operator argv."""
import json
import sqlite3
from uuid import uuid4

import pytest

from aiqa.domain.projects import bind_store, create_project, grant_membership
from aiqa.security.secrets import (
    SecretScopeDenied, SecretUnavailable, SecretValidationError, bind_secret_store,
    build_server_secret_resolver,
)
from aiqa.store.database import StorageConfig, Store, migrate_store
from aiqa.store.models import Actor, ProjectCreate, RuntimeScope, SecretRef, Transaction
from tests.integration.test_hs1_hosted_secrets import hosted_settings


@pytest.fixture
def deployment(tmp_path, monkeypatch):
    from aiqa.security.environment_secrets import EnvironmentSecretBackend
    settings = hosted_settings(tmp_path)
    con = sqlite3.connect(':memory:', isolation_level=None)
    con.execute('PRAGMA foreign_keys=ON')
    store = Store(StorageConfig.from_settings(settings), con)
    migrate_store(store)
    actor_id = uuid4()
    with bind_store(store):
        project = create_project(Actor(actor_id, None, True), ProjectCreate('Hosted', 'hosted', '', 'android'))
    actor = Actor(actor_id, project.project_id, False)
    with store.transaction() as tx:
        grant_membership(Transaction(tx), project.project_id, actor_id, 'admin')
    ref = SecretRef(project.project_id, uuid4(), 1)
    targets = {f'AIQA/aiqa-server/secret/{ref.project_id}/{ref.ref_id}/{rev}': f'fixture-key-revision-{rev}' for rev in (1, 2, 4)}
    monkeypatch.setenv('AIQA_HOSTED_SECRETS_JSON', json.dumps(targets))
    resolver = build_server_secret_resolver(settings)
    assert isinstance(resolver.backend, EnvironmentSecretBackend)
    yield store, settings, actor, ref, resolver
    store.close()


def test_provision_resolve_rotate_and_restart_metadata_only(deployment):
    store, settings, actor, ref, resolver = deployment
    with bind_secret_store(store):
        view = resolver.register_deployment_ref(actor, ref, 'Recording')
        assert view.ref_id == ref.ref_id and view.revision == 1
        assert resolver.register_deployment_ref(actor, ref, 'Recording') == view
        assert resolver.resolve_for_server(ref, RuntimeScope(ref.project_id, actor.actor_id)).value == 'fixture-key-revision-1'
        next_ref = SecretRef(ref.project_id, ref.ref_id, 2)
        resolver.register_deployment_ref(actor, next_ref, 'Recording')
        restarted = build_server_secret_resolver(settings)
        assert restarted.resolve_for_server(ref, RuntimeScope(ref.project_id, actor.actor_id)).value == 'fixture-key-revision-1'
        assert restarted.resolve_for_server(next_ref, RuntimeScope(ref.project_id, actor.actor_id)).value == 'fixture-key-revision-2'
        assert restarted.register_deployment_ref(actor, ref, 'Recording') == view
    rows = store._connection.execute('SELECT revision,action FROM secret_ref_audits ORDER BY revision').fetchall()
    assert rows == [(1, 'create'), (2, 'rotate')]
    assert store._connection.execute('SELECT count(*) FROM secret_ref_snapshots').fetchone()[0] == 2
    assert 'fixture-key-revision' not in '\n'.join(store._connection.iterdump())


@pytest.mark.parametrize('role', ['viewer', 'operator', None, 'revoked'])
def test_provision_requires_active_admin_even_if_local_owner_flag_is_set(deployment, role):
    store, _, actor, ref, resolver = deployment
    with store.transaction() as con:
        if role is None:
            con.execute('DELETE FROM project_memberships')
        elif role == 'revoked':
            con.execute("UPDATE project_memberships SET revoked_at='2026-11-25'")
        else:
            con.execute('UPDATE project_memberships SET role=?', (role,))
    with bind_secret_store(store), pytest.raises(SecretScopeDenied):
        resolver.register_deployment_ref(Actor(actor.actor_id, actor.project_scope, True), ref, 'Recording')
    assert store._connection.execute('SELECT count(*) FROM secret_refs').fetchone()[0] == 0


def test_bad_refs_never_publish_metadata(deployment):
    store, _, actor, ref, resolver = deployment
    with bind_secret_store(store):
        for bad in (SecretRef(ref.project_id, ref.ref_id, 2),
                    SecretRef(ref.project_id, ref.ref_id, 3),
                    SecretRef(ref.project_id, uuid4(), 1)):
            with pytest.raises((SecretValidationError, SecretUnavailable)):
                resolver.register_deployment_ref(actor, bad, 'Recording')
        assert store._connection.execute('SELECT count(*) FROM secret_refs').fetchone()[0] == 0
        resolver.register_deployment_ref(actor, ref, 'Recording')
        for bad, name in ((ref, 'Renamed'), (SecretRef(ref.project_id, ref.ref_id, 4), 'Recording')):
            with pytest.raises(SecretValidationError):
                resolver.register_deployment_ref(actor, bad, name)
        with pytest.raises(SecretScopeDenied):
            resolver.register_deployment_ref(Actor(actor.actor_id, uuid4(), False), ref, 'Recording')
    assert store._connection.execute('SELECT count(*) FROM secret_refs').fetchone()[0] == 1


def test_cli_has_no_secret_argument_and_prints_metadata_only(deployment, monkeypatch, capsys):
    from aiqa.security import provision_hosted_secret as cli
    store, settings, actor, ref, _ = deployment
    monkeypatch.setattr(cli, 'load_settings', lambda: settings)
    monkeypatch.setattr(cli, 'open_store', lambda config: store)
    monkeypatch.setattr(store, 'close', lambda: None)
    assert cli.main(['--project-id', str(ref.project_id), '--actor-id', str(actor.actor_id),
                     '--ref-id', str(ref.ref_id), '--revision', '1', '--name', 'Recording']) == 0
    printed = capsys.readouterr()
    assert str(ref.ref_id) in printed.out
    assert 'fixture-key' not in printed.out + printed.err


def test_hosted_oidc_browser_mutations_and_restart_use_deployment_secrets(deployment, monkeypatch):
    import asyncio
    import base64
    from dataclasses import replace
    from datetime import datetime, timezone
    import httpx
    from aiqa.api.app import create_app
    from aiqa.api.mutations import current_mutation_store
    from aiqa.config import OidcHostedSettings
    from aiqa.security.oidc import MockHttpsIdP
    from aiqa.security.secrets import WindowsCredentialBackend
    store, settings, actor, ref, resolver = deployment
    secret = 'fixture-deployed-oidc-secret'
    env = json.loads(__import__('os').environ['AIQA_HOSTED_SECRETS_JSON'])
    env['AIQA/aiqa-server/oidc/client_secret'] = secret
    monkeypatch.setenv('AIQA_HOSTED_SECRETS_JSON', json.dumps(env))
    monkeypatch.setenv('AIQA_RECEIPT_HMAC_KEY', base64.b64encode(b'K' * 32).decode())
    # Make any accidental Windows fallback an explicit test failure.
    def no_windows(*args, **kwargs):
        pytest.fail('hosted browser request called Windows credentials')
    monkeypatch.setattr(WindowsCredentialBackend, 'write', no_windows)
    monkeypatch.setattr(store, 'close', lambda: None)
    settings = replace(settings, oidc=OidcHostedSettings('https://idp.example.test', 'aiqa', 'aiqa',
        'https://idp.example.test/authorize', 'https://idp.example.test/token'))
    store.config = StorageConfig.from_settings(settings)
    idp = MockHttpsIdP(issuer=settings.oidc.issuer, audience='aiqa', signing_key=secret, require_signature=True)
    now = datetime.now(timezone.utc)
    store._connection.execute('INSERT INTO oidc_identities VALUES(?,?,?,?,?)',
        (str(uuid4()), idp.issuer, 'hosted-admin', str(actor.actor_id), now.isoformat()))
    with bind_secret_store(store):
        resolver.register_deployment_ref(actor, ref, 'Recording')
    def app_instance():
        app = create_app(settings, oidc_idp=idp)
        app.state.open_store = lambda: current_mutation_store() or store
        return app
    async def flow():
        app = app_instance()
        headers = {'Origin': settings.public_origin, 'X-Forwarded-Proto': 'https', 'X-Forwarded-For': '203.0.113.8', 'Idempotency-Key': 'start'}
        transport = httpx.ASGITransport(app=app, client=('127.0.0.1', 45555))
        async with httpx.AsyncClient(transport=transport, base_url=settings.public_origin) as client:
            start = await client.post('/api/v1/auth/oidc/start', json={'project_id': str(ref.project_id)}, headers=headers)
            assert start.status_code == 201, start.text
            state = start.json()['state']
            row = store._connection.execute('SELECT nonce,code_challenge FROM oidc_login_states WHERE state=?', (state,)).fetchone()
            code = idp.issue_code(subject='hosted-admin', redirect_uri=settings.public_origin+'/api/v1/auth/oidc/callback',
                                  state=state, nonce=row[0], code_challenge=row[1], now=now)
            callback = await client.get('/api/v1/auth/oidc/callback', params={'code': code, 'state': state}, headers=headers)
            assert callback.status_code == 303, callback.text
            headers.update({'X-CSRF-Token': client.cookies['aiqa_csrf'], 'Idempotency-Key': 'dataset'})
            binding = await client.post('/api/v1/model-bindings', headers={**headers, 'Idempotency-Key': 'deployed-binding'},
                json={'project_id': str(ref.project_id), 'name': 'Recording', 'role': 'authoring',
                      'provider': 'fixture', 'endpoint_kind': 'https', 'endpoint': 'https://model.example',
                      'model': 'fixture-model', 'prompt_hash': 'sha256:' + 'ab' * 32, 'tariff_id': 't1',
                      'compatibility_status': 'unchecked', 'key_ref': {'project_id': str(ref.project_id),
                      'ref_id': str(ref.ref_id), 'revision': 1}})
            assert binding.status_code == 201, binding.text
            url = f'/api/v1/projects/{ref.project_id}/datasets'
            body = {'name': 'Orders', 'row_schema': {'columns': [{'name': 'amount', 'type': 'int'}]},
                    'rows': [{'id': 'r1', 'values': {'amount': 10000}}]}
            saved = await client.post(url, json=body, headers=headers)
            assert saved.status_code == 201, saved.text
            restarted = app_instance()
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=restarted, client=('127.0.0.1', 45556)),
                    base_url=settings.public_origin, cookies=client.cookies) as new_client:
                again = await new_client.post(url, json=body, headers=headers)
                assert again.status_code == 200, again.text
                assert again.json()['id'] == saved.json()['id']
                conflict = await new_client.post(url, json={**body, 'name': 'Changed'}, headers=headers)
                assert conflict.status_code == 409
            headers['Idempotency-Key'] = 'secret-write'
            denied = await client.post(f'/api/v1/projects/{ref.project_id}/secret-refs',
                    json={'name': 'No', 'value': 'fixture-browser-key'}, headers=headers)
            assert denied.status_code == 503, denied.text
            assert denied.json()['error']['code'] == 'deployment_managed_secret'
            headers['Idempotency-Key'] = 'settings-write'
            denied_settings = await client.post(f'/ui/projects/{ref.project_id}/settings',
                    json={'roles': [{'role': 'authoring', 'mode': 'replace', 'endpoint': 'https://model.example',
                                     'model': 'fixture-model', 'key': 'fixture-browser-key'}]}, headers=headers)
            assert denied_settings.status_code == 503, denied_settings.text
            assert 'fixture-browser-key' not in denied.text + denied_settings.text
            ref_body = {'project_id': str(ref.project_id), 'ref_id': str(ref.ref_id), 'revision': 1}
            for wrong_ref in ({**ref_body, 'project_id': str(uuid4())}, {**ref_body, 'revision': 999}):
                bad = await client.post(f'/ui/projects/{ref.project_id}/settings',
                    headers={**headers, 'Idempotency-Key': str(uuid4())},
                    json={'expected_lock': 0, 'roles': [{'role': 'authoring', 'mode': 'bind_ref',
                        'endpoint': 'https://api.openai.com', 'model': 'fixture-model', 'key_ref': wrong_ref}]})
                assert bad.status_code in {404, 422}, bad.text
            linked = await client.post(f'/ui/projects/{ref.project_id}/settings',
                headers={**headers, 'Idempotency-Key': 'settings-link-ref'},
                json={'expected_lock': 0, 'roles': [{'role': 'authoring', 'mode': 'bind_ref',
                    'endpoint': 'https://api.openai.com', 'model': 'fixture-model', 'key_ref': ref_body}]})
            assert linked.status_code == 201, linked.text
            again_linked = await client.post(f'/ui/projects/{ref.project_id}/settings',
                headers={**headers, 'Idempotency-Key': 'settings-link-ref'},
                json={'expected_lock': 0, 'roles': [{'role': 'authoring', 'mode': 'bind_ref',
                    'endpoint': 'https://api.openai.com', 'model': 'fixture-model', 'key_ref': ref_body}]})
            assert again_linked.status_code == 200 and again_linked.json() == linked.json()
            page = await client.get(f'/ui/projects/{ref.project_id}/settings', headers=headers)
            assert page.status_code == 200
            assert '키는 서버 배포 설정에서 관리합니다' in page.text
            assert '<option value="replace"' not in page.text
            assert '<option value="bind_ref"' in page.text
            assert 'data-secret-picker' in page.text
    asyncio.run(flow())
    assert 'fixture-browser-key' not in '\n'.join(store._connection.iterdump())
    assert store._connection.execute('SELECT count(*) FROM secret_refs').fetchone()[0] == 1
