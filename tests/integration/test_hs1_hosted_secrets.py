"""Deployment secrets: synthetic values only; no network or model requests."""
import json
import os
import subprocess
import sys
import traceback
from pathlib import Path
from uuid import uuid4

import pytest
from ux_support import ux_app, session

from aiqa.config import load_settings
from aiqa.security.secrets import (
    MemorySecretBackend, SecretUnavailable, WindowsCredentialBackend,
    build_server_secret_resolver,
)


def hosted_settings(root):
    return load_settings({
        'AIQA_RUNTIME_ROOT': str(root), 'AIQA_PROFILE': 'hosted',
        'AIQA_PUBLIC_ORIGIN': 'https://manage.example.test',
        'AIQA_TRUSTED_PROXIES': '127.0.0.1',
    })


def test_api_import_and_health_without_windows_dlls(tmp_path):
    code = '''
import ctypes
if hasattr(ctypes, 'WinDLL'): del ctypes.WinDLL
from aiqa.api.app import create_app, health
from aiqa.config import load_settings
app = create_app(load_settings({'AIQA_PROFILE':'hosted',
    'AIQA_RUNTIME_ROOT':__import__('sys').argv[1],
    'AIQA_PUBLIC_ORIGIN':'https://manage.example.test',
    'AIQA_TRUSTED_PROXIES':'127.0.0.1'}))
assert health()['status'] == 'ok'
assert app.state.secret_resolver.profile == 'hosted'
'''
    env = {**os.environ, 'PYTHONPATH': str(Path(__file__).parents[2] / 'src')}
    # Do not let real deployment credentials participate in this fixture.
    env.pop('AIQA_HOSTED_SECRETS_JSON', None)
    env.pop('AIQA_RECEIPT_HMAC_KEY', None)
    run = subprocess.run([sys.executable, '-B', '-c', code, str(tmp_path)],
                         env=env, capture_output=True, text=True, timeout=45)
    assert run.returncode == 0, run.stderr


def test_profiles_and_explicit_injection(tmp_path, monkeypatch):
    from aiqa.security.environment_secrets import EnvironmentSecretBackend
    monkeypatch.delenv('AIQA_HOSTED_SECRETS_JSON', raising=False)
    hosted = hosted_settings(tmp_path)
    assert isinstance(build_server_secret_resolver(hosted).backend, EnvironmentSecretBackend)
    local = load_settings({'AIQA_RUNTIME_ROOT': str(tmp_path)})
    assert isinstance(build_server_secret_resolver(local).backend, WindowsCredentialBackend)
    injected = MemorySecretBackend()
    assert build_server_secret_resolver(hosted, backend=injected).backend is injected


def test_environment_backend_reads_exact_scope_is_read_only_and_restarts(monkeypatch):
    from aiqa.security.environment_secrets import EnvironmentSecretBackend
    target = f'AIQA/aiqa-server/secret/{uuid4()}/{uuid4()}/1'
    oidc = 'AIQA/aiqa-server/oidc/client_secret'
    plain = 'synthetic-hosted-key-value'
    env = {'AIQA_HOSTED_SECRETS_JSON': json.dumps({target: plain, oidc: 'fixture-oidc'})}
    monkeypatch.setenv('AIQA_HOSTED_SECRETS_JSON', env['AIQA_HOSTED_SECRETS_JSON'])
    for backend in (EnvironmentSecretBackend('aiqa-server', environ=env),
                    EnvironmentSecretBackend('aiqa-server')):
        assert backend.read(target) == plain
        assert backend.read(oidc) == 'fixture-oidc'
        assert plain not in repr(backend)
        with pytest.raises(OSError):
            backend.read(target.replace('/1', '/2'))
        with pytest.raises(SecretUnavailable):
            backend.write(target, plain, account='aiqa-server')
        with pytest.raises(SecretUnavailable):
            backend.delete(target)
    assert os.environ['AIQA_HOSTED_SECRETS_JSON'] == env['AIQA_HOSTED_SECRETS_JSON']
    assert env == {'AIQA_HOSTED_SECRETS_JSON': os.environ['AIQA_HOSTED_SECRETS_JSON']}


@pytest.mark.parametrize('raw', [
    '{"sensitive-marker":',
    '{"AIQA/aiqa-server/oidc/client_secret":"sensitive-marker",'
    '"AIQA/aiqa-server/oidc/client_secret":"other"}',
    '["sensitive-marker"]',
    '{"AIQA/other/oidc/client_secret":"sensitive-marker"}',
    '{"AIQA/aiqa-server/oidc/client_secret":42}',
    '{"AIQA/aiqa-server/oidc/client_secret":""}',
    '{"AIQA/aiqa-server/secret/not-uuid/ref/1":"sensitive-marker"}',
    json.dumps({'AIQA/aiqa-server/oidc/client_secret': 'sensitive-marker' * 500}),
])
def test_malformed_deployment_config_does_not_echo_secrets(raw):
    from aiqa.security.environment_secrets import EnvironmentSecretBackend
    with pytest.raises(SecretUnavailable) as exc:
        EnvironmentSecretBackend('aiqa-server', environ={'AIQA_HOSTED_SECRETS_JSON': raw})
    assert 'sensitive-marker' not in ''.join(traceback.format_exception(exc.value))
    assert exc.value.__context__ is None


def test_missing_environment_secret_fails_closed():
    from aiqa.security.environment_secrets import EnvironmentSecretBackend
    backend = EnvironmentSecretBackend('aiqa-server', environ={})
    with pytest.raises(OSError):
        backend.read('AIQA/aiqa-server/oidc/client_secret')


def test_stale_settings_rollback_cleans_original_backend_and_account(ux_app, monkeypatch):
    import asyncio
    from dataclasses import replace
    import httpx
    from aiqa.api.app import create_app
    app, project, db = ux_app
    backend = MemorySecretBackend()
    app = create_app(replace(app.state.settings, secret_account='local-custom'), secret_backend=backend)
    def wrong_backend(*args, **kwargs):
        pytest.fail('rollback used Windows backend instead of original injected backend')
    monkeypatch.setattr(WindowsCredentialBackend, 'delete', wrong_backend)
    async def flow():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1') as client:
            headers = await session(client, project)
            response = await client.post(f'/ui/projects/{project}/settings', headers=headers,
                json={'expected_lock': 999, 'timeout_seconds': 600, 'roles': [
                    {'role': 'authoring', 'mode': 'replace', 'endpoint': 'https://model.example',
                     'model': 'fixture-model', 'key': 'synthetic-rollback-key'}]})
            assert response.status_code == 409, response.text
    asyncio.run(flow())
    assert backend._values == {}
    with __import__('sqlite3').connect(db) as con:
        assert con.execute('SELECT count(*) FROM secret_refs').fetchone()[0] == 0
        assert con.execute('SELECT count(*) FROM binding_revisions').fetchone()[0] == 0


def test_worker_child_never_inherits_deployment_secrets(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from aiqa import launcher
    monkeypatch.setenv('AIQA_HOSTED_SECRETS_JSON', 'synthetic-deployment-secret')
    monkeypatch.setenv('AIQA_RECEIPT_HMAC_KEY', 'synthetic-receipt-key')
    monkeypatch.setenv('AIQA_WORKER_VERIFY_TLS', 'false')
    captured = {}
    def spawn(args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(pid=12345)
    monkeypatch.setattr(launcher.subprocess, 'Popen', spawn)
    config = SimpleNamespace(runtime_root=str(tmp_path))
    management = launcher._Management(8443, tmp_path/'ca.pem', tmp_path/'key.pem', 'synthetic-worker-token', True)
    assert launcher._spawn_worker(config, management) == 12345
    child = captured['env']
    assert 'AIQA_HOSTED_SECRETS_JSON' not in child
    assert 'AIQA_RECEIPT_HMAC_KEY' not in child
    assert child['AIQA_WORKER_TOKEN'] == 'synthetic-worker-token'
    assert child['AIQA_MANAGEMENT_BASE_URL'] == 'https://127.0.0.1:8443'
    assert 'AIQA_WORKER_VERIFY_TLS' not in child
    assert os.environ['AIQA_HOSTED_SECRETS_JSON'] == 'synthetic-deployment-secret'
