"""RX-16: hosted server profile, trusted proxy, and HTTPS cookie boundary."""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from aiqa.api.app import create_app
from aiqa.api.auth import session_cookie_secure
from aiqa.config import PROFILE_HOSTED, PROFILE_LOCAL, SettingsError, load_settings
from aiqa.domain.projects import bind_store, create_project
from aiqa.launcher import HostedServerConfig, build_hosted_env, start_hosted_server, worker_database_grant
from aiqa.store.database import migrate_store
from aiqa.store.models import Actor, ProjectCreate


def _local_env(root: Path) -> dict[str, str]:
    return {
        "AIQA_HOST": "127.0.0.1",
        "AIQA_PORT": "8000",
        "AIQA_RUNTIME_ROOT": str(root),
    }


def _hosted_env(root: Path) -> dict[str, str]:
    return {
        **_local_env(root),
        "AIQA_PROFILE": "hosted",
        "AIQA_PUBLIC_ORIGIN": "https://manage.example.test",
        "AIQA_TRUSTED_PROXIES": "127.0.0.1,10.0.0.5",
    }


def test_hosted_settings_require_https_origin_and_trusted_proxies(tmp_path: Path) -> None:
    settings = load_settings(_hosted_env(tmp_path))
    assert settings.profile == PROFILE_HOSTED
    assert settings.public_origin == "https://manage.example.test"
    assert settings.trusted_proxies == ("127.0.0.1", "10.0.0.5")
    assert settings.host == "127.0.0.1"
    assert worker_database_grant(settings) is None
    assert session_cookie_secure(settings) is True

    with pytest.raises(SettingsError):
        load_settings({**_hosted_env(tmp_path), "AIQA_PUBLIC_ORIGIN": "http://manage.example.test"})
    with pytest.raises(SettingsError):
        load_settings({**_hosted_env(tmp_path), "AIQA_TRUSTED_PROXIES": ""})
    with pytest.raises(SettingsError):
        load_settings({**_local_env(tmp_path), "AIQA_PROFILE": "hosted"})
    local = load_settings(_local_env(tmp_path))
    assert local.profile == PROFILE_LOCAL
    assert local.public_origin is None
    assert session_cookie_secure(local) is False


def test_hosted_rejects_public_http_forged_forwarded_nonce_and_keeps_secure_csrf(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    settings = load_settings(_hosted_env(root))
    app = create_app(settings)
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("rx16", "rx16", "ex", "android"))
    store.close()
    asyncio.run(_exercise_hosted(app, project.project_id))

    hosted = HostedServerConfig(
        host="127.0.0.1",
        port=8016,
        runtime_root=str(root / "hosted"),
        public_origin="https://manage.example.test",
        trusted_proxies=("127.0.0.1",),
    )
    env = build_hosted_env(hosted)
    assert env["AIQA_PROFILE"] == "hosted"
    assert env["AIQA_PUBLIC_ORIGIN"] == "https://manage.example.test"
    assert worker_database_grant(load_settings(env)) is None
    status = start_hosted_server(hosted, spawn=False)
    assert status.state == "configured"
    assert status.worker_instances == 0
    assert status.publish is False


async def _exercise_hosted(app, project_id) -> None:
    proxy = ASGITransport(app=app, client=("127.0.0.1", 50000))
    async with AsyncClient(transport=proxy, base_url="http://test") as client:
        http_proto = await client.get(
            "/api/v1/health",
            headers={"X-Forwarded-Proto": "http", "X-Forwarded-For": "203.0.113.10"},
        )
        assert http_proto.status_code == 403
        assert http_proto.json()["error"]["message"] == "public HTTP was refused"

    outsider = ASGITransport(app=app, client=("203.0.113.9", 50001))
    async with AsyncClient(transport=outsider, base_url="http://test") as client:
        forged = await client.get(
            "/api/v1/health",
            headers={
                "X-Forwarded-Proto": "https",
                "X-Forwarded-For": "203.0.113.10",
            },
        )
        assert forged.status_code == 403
        assert forged.json()["error"]["message"] == "forwarded headers were refused"

        direct = await client.get("/api/v1/health")
        assert direct.status_code == 403
        assert direct.json()["error"]["message"] == "direct access was refused"

    async with AsyncClient(transport=proxy, base_url="http://test") as client:
        ok = await client.get(
            "/api/v1/health",
            headers={
                "X-Forwarded-Proto": "https",
                "X-Forwarded-For": "203.0.113.10",
                "X-Forwarded-Host": "manage.example.test",
            },
        )
        assert ok.status_code == 200

        nonce = await client.post(
            "/api/v1/session/nonces",
            json={"origin": "https://manage.example.test", "project_id": str(project_id)},
            headers={
                "Idempotency-Key": "rx16-nonce",
                "Origin": "https://manage.example.test",
                "X-Forwarded-Proto": "https",
                "X-Forwarded-For": "203.0.113.10",
            },
        )
        assert nonce.status_code == 403
        assert "nonce" in nonce.json()["error"]["message"]

        bootstrap = await client.post(
            "/api/v1/session/bootstrap",
            json={"nonce": "not-a-real-nonce"},
            headers={
                "Idempotency-Key": "rx16-boot",
                "Origin": "https://manage.example.test",
                "X-Forwarded-Proto": "https",
                "X-Forwarded-For": "203.0.113.10",
            },
        )
        assert bootstrap.status_code == 403
        assert "nonce" in bootstrap.json()["error"]["message"]

        csrf = await client.get(
            "/api/v1/session/csrf",
            headers={
                "Origin": "https://evil.example.test",
                "X-Forwarded-Proto": "https",
                "X-Forwarded-For": "203.0.113.10",
            },
        )
        assert csrf.status_code == 403
