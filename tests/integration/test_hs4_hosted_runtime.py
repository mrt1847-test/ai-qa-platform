"""Hosted entry contracts; synthetic configuration and temporary SQLite only."""
import asyncio
import base64
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest


def hosted_env(root):
    return {
        'AIQA_PROFILE': 'hosted', 'AIQA_RUNTIME_ROOT': str(root),
        'AIQA_PUBLIC_ORIGIN': 'https://manage.example.test',
        'AIQA_TRUSTED_PROXIES': '127.0.0.1/32',
        'AIQA_DATABASE_URL': 'postgresql://operator:synthetic-password@db.example.test/app?sslmode=verify-full',
        'AIQA_ARTIFACT_BACKEND': 'supabase',
        'AIQA_SUPABASE_URL': 'https://storage.example.test',
        'AIQA_SUPABASE_SERVICE_KEY': 'synthetic-storage-key',
        'AIQA_SUPABASE_BUCKET': 'private-evidence',
        'AIQA_OIDC_ISSUER': 'https://idp.example.test',
        'AIQA_OIDC_CLIENT_ID': 'client', 'AIQA_OIDC_AUDIENCE': 'client',
        'AIQA_OIDC_AUTHORIZE_ENDPOINT': 'https://idp.example.test/authorize',
        'AIQA_OIDC_TOKEN_ENDPOINT': 'https://idp.example.test/token',
        'AIQA_HOSTED_SECRETS_JSON': json.dumps({'AIQA/aiqa-server/oidc/client_secret': 'synthetic-oidc-secret'}),
        'AIQA_RECEIPT_HMAC_KEY': base64.b64encode(bytes(range(32))).decode(),
    }


def test_preflight_accepts_complete_config_without_exposing_secrets(tmp_path):
    from aiqa.hosted.preflight import validate_hosted_environment
    settings = validate_hosted_environment(hosted_env(tmp_path))
    assert settings.profile == 'hosted'
    assert settings.oidc.client_id == 'client'


@pytest.mark.parametrize('name', [
    'AIQA_DATABASE_URL', 'AIQA_ARTIFACT_BACKEND', 'AIQA_SUPABASE_URL',
    'AIQA_SUPABASE_SERVICE_KEY', 'AIQA_SUPABASE_BUCKET', 'AIQA_OIDC_ISSUER',
    'AIQA_OIDC_CLIENT_ID', 'AIQA_OIDC_AUDIENCE', 'AIQA_OIDC_TOKEN_ENDPOINT',
    'AIQA_HOSTED_SECRETS_JSON', 'AIQA_RECEIPT_HMAC_KEY', 'AIQA_PUBLIC_ORIGIN',
])
def test_preflight_refuses_missing_required_config_with_names_only(tmp_path, name):
    from aiqa.hosted.preflight import HostedConfigurationError, validate_hosted_environment
    env = hosted_env(tmp_path)
    del env[name]
    with pytest.raises(HostedConfigurationError) as caught:
        validate_hosted_environment(env)
    assert name in caught.value.fields
    assert 'synthetic-' not in str(caught.value)


@pytest.mark.parametrize(('name', 'value'), [
    ('AIQA_PROFILE', 'local'), ('AIQA_DATABASE_URL', 'sqlite:///runtime.db'),
    ('AIQA_DATABASE_BACKEND', 'sqlite'),
    ('AIQA_DATABASE_URL', 'postgresql://user:secret@db.test/app?sslmode=disable'),
    ('AIQA_ARTIFACT_BACKEND', 'local'), ('AIQA_SUPABASE_URL', 'http://storage.test'),
    ('AIQA_SUPABASE_BUCKET', 'invalid.bucket'), ('AIQA_SUPABASE_SERVICE_KEY', 'invalid\nkey'),
    ('AIQA_PUBLIC_ORIGIN', 'https://user:password@public.test'),
    ('AIQA_OIDC_TOKEN_ENDPOINT', 'https://user:password@idp.test/token'),
    ('AIQA_TRUSTED_PROXIES', '0.0.0.0/0'), ('AIQA_TRUSTED_PROXIES', '::/0'),
    ('AIQA_TRUSTED_PROXIES', '*'), ('AIQA_RECEIPT_HMAC_KEY', 'invalid-secret'),
])
def test_preflight_refuses_unsafe_config_without_echo(tmp_path, name, value):
    from aiqa.hosted.preflight import HostedConfigurationError, validate_hosted_environment
    env = hosted_env(tmp_path)
    env[name] = value
    with pytest.raises(HostedConfigurationError) as caught:
        validate_hosted_environment(env)
    assert name in caught.value.fields
    assert value not in str(caught.value)


def test_preflight_cli_reports_only_setting_names(tmp_path, monkeypatch, capsys):
    from aiqa.hosted.preflight import main
    monkeypatch.setenv('AIQA_DATABASE_URL', 'postgresql://secret:never-print@invalid')
    assert main() == 1
    result = capsys.readouterr()
    assert 'AIQA_DATABASE_URL' in result.err
    assert 'never-print' not in result.err


def test_worker_environment_excludes_all_server_and_unrecognized_keys():
    from aiqa.hosted.worker import build_worker_environment
    env = build_worker_environment({
        'PATH': 'path', 'SystemRoot': 'windows',
        'AIQA_MANAGEMENT_BASE_URL': 'https://manage.example.test',
        'AIQA_WORKER_TOKEN': 'synthetic-worker-token',
        'AIQA_WORKER_PROJECT_ID': str(uuid4()), 'AIQA_WORKER_MODEL_MODE': 'operational',
        'AIQA_DATABASE_URL': 'do-not-forward', 'AIQA_HOSTED_SECRETS_JSON': 'do-not-forward',
        'AIQA_RECEIPT_HMAC_KEY': 'do-not-forward', 'AIQA_SUPABASE_SERVICE_KEY': 'do-not-forward',
        'OPENAI_API_KEY': 'do-not-forward', 'AIQA_WORKER_FUTURE_SECRET': 'do-not-forward',
    })
    assert env['AIQA_WORKER_TOKEN'] == 'synthetic-worker-token'
    assert env['AIQA_WORKER_MODEL_MODE'] == 'operational'
    assert 'do-not-forward' not in env.values()
    assert env['SystemRoot'] == 'windows'


def test_worker_refuses_tls_disable_before_start():
    from aiqa.hosted.worker import build_worker_environment
    with pytest.raises(ValueError, match='AIQA_WORKER_VERIFY_TLS'):
        build_worker_environment({'AIQA_MANAGEMENT_BASE_URL': 'https://public.test',
                                  'AIQA_WORKER_TOKEN': 'token', 'AIQA_WORKER_VERIFY_TLS': '0'})


def test_hosted_entry_binds_container_and_preserves_peer_address(monkeypatch):
    from aiqa.hosted import entry
    captured = {}
    monkeypatch.setattr(entry, 'validate_hosted_environment', lambda: object())
    monkeypatch.setattr(entry.uvicorn, 'run', lambda *args, **kwargs: captured.update(kwargs))
    assert entry.main() == 0
    assert captured['host'] == '0.0.0.0'
    assert captured['port'] == 8000
    assert captured['proxy_headers'] is False
    assert captured['workers'] == 1


def test_runtime_migrates_and_reconciles_without_windows_boot(tmp_path, monkeypatch):
    from aiqa.hosted import entry
    from aiqa.config import load_settings
    from aiqa.store.database import StorageConfig, open_store
    import ctypes
    monkeypatch.setattr(ctypes, 'WinDLL', lambda *args, **kwargs: pytest.fail('Windows DLL used'), raising=False)
    env = hosted_env(tmp_path)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    app = entry.create_hosted_app()
    # External managed services are replaced at the physical store boundary only.
    config = StorageConfig.from_settings(load_settings({'AIQA_RUNTIME_ROOT': str(tmp_path / 'fixture')}))
    app.state.open_store = lambda: open_store(config)
    async def start():
        async with app.router.lifespan_context(app):
            assert app.state.hosted_schema_revision
            assert app.state.hosted_reconciliation.queued_preserved is True
    asyncio.run(start())
    store = open_store(config)
    try:
        assert store._connection.execute('SELECT COUNT(*) FROM schema_migrations').fetchone()[0] > 0
    finally:
        store.close()


def test_bootstrap_is_atomic_and_idempotent_and_refuses_foreign_identity(tmp_path):
    from aiqa.hosted.bootstrap import bootstrap_first_admin, BootstrapRefused
    from aiqa.config import load_settings
    from aiqa.store.database import StorageConfig, open_store, migrate_store
    from aiqa.store.models import ProjectCreate
    config = StorageConfig.from_settings(load_settings({'AIQA_RUNTIME_ROOT': str(tmp_path)}))
    store = open_store(config)
    migrate_store(store)
    project = ProjectCreate('Android QA', 'android', '', 'android')
    try:
        first = bootstrap_first_admin(store, issuer='https://idp.test', subject='operator-subject', project=project)
        repeated = bootstrap_first_admin(store, issuer='https://idp.test', subject='operator-subject', project=project)
        assert repeated == first
        with pytest.raises(BootstrapRefused):
            bootstrap_first_admin(store, issuer='https://idp.test', subject='stranger', project=project)
        assert store._connection.execute('SELECT COUNT(*) FROM projects').fetchone()[0] == 1
        assert store._connection.execute('SELECT COUNT(*) FROM oidc_identities').fetchone()[0] == 1
        assert store._connection.execute('SELECT role FROM project_memberships').fetchone()[0] == 'admin'
        assert store._connection.execute('SELECT actor_is_local_owner FROM projects').fetchone()[0] == 0
    finally:
        store.close()


def test_bootstrap_rolls_back_project_when_membership_write_fails(tmp_path, monkeypatch):
    from aiqa.hosted import bootstrap
    from aiqa.config import load_settings
    from aiqa.store.database import StorageConfig, open_store, migrate_store
    from aiqa.store.models import ProjectCreate
    store = open_store(StorageConfig.from_settings(load_settings({'AIQA_RUNTIME_ROOT': str(tmp_path)})))
    migrate_store(store)
    def fail(*args, **kwargs):
        raise RuntimeError('fixture write failure')
    monkeypatch.setattr(bootstrap, 'grant_membership', fail)
    try:
        with pytest.raises(RuntimeError):
            bootstrap.bootstrap_first_admin(store, issuer='https://idp.test', subject='operator',
                                            project=ProjectCreate('QA', 'qa', '', 'android'))
        assert store._connection.execute('SELECT COUNT(*) FROM projects').fetchone()[0] == 0
        assert store._connection.execute('SELECT COUNT(*) FROM oidc_identities').fetchone()[0] == 0
    finally:
        store.close()


def test_preflight_refuses_short_oidc_secret(tmp_path):
    from aiqa.hosted.preflight import HostedConfigurationError, validate_hosted_environment
    env = hosted_env(tmp_path)
    env['AIQA_HOSTED_SECRETS_JSON'] = '{"AIQA/aiqa-server/oidc/client_secret":"x"}'
    with pytest.raises(HostedConfigurationError) as caught:
        validate_hosted_environment(env)
    assert 'AIQA_HOSTED_SECRETS_JSON' in caught.value.fields


def test_preflight_refuses_operational_model_tls_disable(tmp_path):
    from aiqa.hosted.preflight import HostedConfigurationError, validate_hosted_environment
    env = hosted_env(tmp_path)
    env.update(AIQA_MODEL_PROVIDER_MODE='operational', AIQA_MODEL_PROVIDER_BASE_URL='https://model.example.test',
               AIQA_MODEL_PROVIDER_VERIFY_TLS='false')
    with pytest.raises(HostedConfigurationError) as caught:
        validate_hosted_environment(env)
    assert 'AIQA_MODEL_PROVIDER_VERIFY_TLS' in caught.value.fields


def test_container_copies_pinned_server_protocol_and_packaged_load_works(tmp_path, monkeypatch):
    import shutil
    from aiqa.adapters import mobile_agent_upstream
    root = Path(__file__).resolve().parents[2]
    dockerfile = (root / 'Dockerfile').read_text()
    ignore = (root / '.dockerignore').read_text().splitlines()
    packaged = tmp_path / 'app'
    files = ['manifest.json', *['upstream/' + name for name in (
        'run_gui_owl_1_5_for_mobile.py', 'utils.py', 'packages.py', 'LICENSE')]]
    for name in files:
        relative = 'third_party/mobile_agent/' + name
        assert '!' + relative in ignore
        target_dir = str(Path(relative).parent).replace('\\', '/') + '/'
        assert f'COPY {relative} ./{target_dir}' in dockerfile
        target = packaged / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / relative, target)
    # Exercise the default image-relative lookup, not a source-tree override.
    monkeypatch.setattr(mobile_agent_upstream, '__file__',
                        str(packaged / 'src/aiqa/adapters/mobile_agent_upstream.py'))
    protocol = mobile_agent_upstream.load_protocol()
    assert protocol.SYSTEM_PROMPT
    assert callable(protocol.build_messages)
    assert protocol.parse_action('Action: wait\n<tool_call>\n{"name":"mobile_use","arguments":{"action":"wait","time":1}}\n</tool_call>')['name'] == 'mobile_use'


def test_worker_preserves_real_android_and_optional_web_runtime_inputs():
    from aiqa.hosted.worker import build_worker_environment
    from aiqa.worker.runtime import load_android_inventory_binding
    from aiqa.worker.web_vm_transport import load_web_guest_entry_binding
    source = {
        'AIQA_MANAGEMENT_BASE_URL': 'https://manage.example.test', 'AIQA_WORKER_TOKEN': 'token',
        'AIQA_WORKER_PROJECT_ID': str(uuid4()), 'AIQA_WORKER_MODEL_MODE': 'operational',
        'AIQA_ADB_PATH': 'C:/Android/adb.exe', 'AIQA_ANDROID_SERIAL': 'emulator-5554',
        'AIQA_ANDROID_AVD': 'qa-avd', 'AIQA_ANDROID_VIDEO': '1',
        'AIQA_WORKER_APPROVED_DIGEST': 'sha256:approved', 'AIQA_WORKER_APPROVED_PLAN': 'approved.json',
        'AIQA_WEB_GUEST_ENDPOINT': 'https://guest.example.test', 'AIQA_WEB_GUEST_PEER_TOKEN': 'guest-only-token',
        'AIQA_WEB_APPROVED_ORIGIN': 'https://test.example.test',
        'AIQA_WEB_GUEST_PROOF_SECRET': 'worker-guest-only-proof', 'AIQA_WORKER_APPROVED_REVISION': 'lock-2',
        'AIQA_HOSTED_SECRETS_JSON': 'server-secret', 'AIQA_DATABASE_URL': 'server-secret',
    }
    child = build_worker_environment(source)
    assert load_android_inventory_binding(child).expected_avd == 'qa-avd'
    assert load_web_guest_entry_binding(child) is not None
    for name in source:
        if name not in {'AIQA_HOSTED_SECRETS_JSON', 'AIQA_DATABASE_URL'}:
            assert child[name] == source[name]
    assert 'server-secret' not in child.values()


def test_proxy_probe_records_only_socket_peer_without_reading_http(tmp_path):
    from aiqa.hosted.proxy_probe import record_connection
    class Connection:
        def recv(self, *args):
            pytest.fail('Probe must not read credentials, headers, or routes')
        def sendall(self, value):
            self.reply = value
        def settimeout(self, value):
            pass
    connection = Connection()
    output = tmp_path / 'peers.json'
    record_connection(connection, ('192.0.2.5', 43210), output)
    assert json.loads(output.read_text()) == ['192.0.2.5']
    assert b'503 Service Unavailable' in connection.reply
    assert b'192.0.2.5' not in connection.reply
    for _ in range(80):
        record_connection(connection, ('192.0.2.6', 43210), output)
    assert len(json.loads(output.read_text())) == 64


def test_proxy_probe_refuses_any_server_secret_without_echo(monkeypatch, capsys):
    from aiqa.hosted import proxy_probe
    monkeypatch.setenv('AIQA_DATABASE_URL', 'never-print')
    assert proxy_probe.main() == 1
    assert 'never-print' not in capsys.readouterr().err


def test_proxy_probe_uses_real_socket_peer_and_never_persists_http(tmp_path):
    import socket
    from aiqa.hosted.proxy_probe import record_connection
    output = tmp_path / 'real-peers.json'
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        with socket.create_connection(listener.getsockname(), timeout=2) as client:
            client.sendall(b'GET /private-route HTTP/1.1\r\nAuthorization: Bearer never-store\r\n\r\n')
            connection, peer = listener.accept()
            with connection:
                record_connection(connection, peer, output)
    assert output.read_text() == '["127.0.0.1"]'


def test_fly_probe_and_normal_manifest_keep_same_service_without_secrets():
    import tomllib
    root = Path(__file__).resolve().parents[2]
    probe = tomllib.loads((root / 'deploy/fly-proxy-probe.toml.example').read_text())
    normal = tomllib.loads((root / 'fly.toml.example').read_text())
    assert probe['processes'] == {'app': 'python -B -m aiqa.hosted.proxy_probe'}
    assert 'env' not in probe
    assert 'processes' not in normal
    assert probe['services'][0]['internal_port'] == normal['services'][0]['internal_port'] == 8000
    assert probe['services'][0]['ports'] == normal['services'][0]['ports']
    assert 'tcp_checks' not in probe['services'][0]
