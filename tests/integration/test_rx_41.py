"""RX-41: operational OIDC client — HTTPS token exchange + mock IdP test injection."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from aiqa.api.app import create_app
from aiqa.api.oidc_login import assemble_hosted_oidc_runtime
from aiqa.config import load_settings
from aiqa.domain.projects import bind_store, create_project, grant_membership
from aiqa.security.oidc import (
    MockHttpsIdP,
    OidcRejected,
    OperationalOidcClient,
    generate_pkce,
    mock_https_token_handler,
)
from aiqa.security.secrets import MemorySecretBackend, build_server_secret_resolver
from aiqa.store.database import migrate_store
from aiqa.store.models import Actor, ProjectCreate, Transaction


def _hosted_env(root: Path) -> dict[str, str]:
    return {
        "AIQA_HOST": "127.0.0.1",
        "AIQA_PORT": "8000",
        "AIQA_RUNTIME_ROOT": str(root),
        "AIQA_PROFILE": "hosted",
        "AIQA_PUBLIC_ORIGIN": "https://manage.example.test",
        "AIQA_TRUSTED_PROXIES": "127.0.0.1",
        "AIQA_OIDC_ISSUER": "https://idp.example.test",
        "AIQA_OIDC_AUDIENCE": "aiqa-management",
        "AIQA_OIDC_CLIENT_ID": "aiqa-management",
        "AIQA_OIDC_AUTHORIZE_ENDPOINT": "https://idp.example.test/authorize",
        "AIQA_OIDC_TOKEN_ENDPOINT": "https://idp.example.test/token",
    }


def test_rx_41_operational_client_exchanges_and_rejects(tmp_path: Path) -> None:
    settings = load_settings(_hosted_env(tmp_path / "op"))
    assert settings.oidc is not None
    assert settings.oidc.token_endpoint == "https://idp.example.test/token"

    secret = "operational-oidc-client-secret"
    backend = MemorySecretBackend()
    resolver = build_server_secret_resolver(settings, backend=backend)
    resolver.store_oidc_client_secret(secret)

    mock = MockHttpsIdP(
        issuer="https://idp.example.test",
        audience="aiqa-management",
        signing_key=secret,
        require_signature=True,
    )
    now = datetime(2026, 11, 4, 18, 0, tzinfo=timezone.utc)
    transport = httpx.MockTransport(mock_https_token_handler(mock, clock=now))
    runtime = assemble_hosted_oidc_runtime(settings, resolver, token_transport=transport)
    assert runtime is not None
    assert isinstance(runtime.idp, OperationalOidcClient)
    assert runtime.token_endpoint == "https://idp.example.test/token"

    pkce = generate_pkce()
    state = "state-rx41"
    nonce = "nonce-rx41"
    redirect = runtime.config.redirect_uri
    code = mock.issue_code(
        subject="dana",
        redirect_uri=redirect,
        state=state,
        nonce=nonce,
        code_challenge=pkce.challenge,
        now=now,
    )
    claims = runtime.idp.exchange(
        code=code,
        code_verifier=pkce.verifier,
        redirect_uri=redirect,
        state=state,
        now=now,
    )
    assert claims.subject == "dana"
    assert claims.nonce == nonce

    # Code reuse at IdP.
    with pytest.raises(OidcRejected):
        runtime.idp.exchange(
            code=code,
            code_verifier=pkce.verifier,
            redirect_uri=redirect,
            state=state,
            now=now,
        )

    # Bad signature after a successful token HTTP body (client-side verify).
    code2 = mock.issue_code(
        subject="dana",
        redirect_uri=redirect,
        state="state-sig",
        nonce=nonce,
        code_challenge=pkce.challenge,
        now=now,
    )
    with pytest.raises(OidcRejected, match="signature"):
        runtime.idp.exchange(
            code=code2,
            code_verifier=pkce.verifier,
            redirect_uri=redirect,
            state="state-sig",
            now=now,
            presented_signature="sha256:" + ("0" * 64),
        )

    # Expired authorization code against the handler clock.
    expired_mock = MockHttpsIdP(
        issuer="https://idp.example.test",
        audience="aiqa-management",
        signing_key=secret,
        require_signature=True,
    )
    expired_client = OperationalOidcClient(
        config=runtime.config,
        token_endpoint="https://idp.example.test/token",
        client_secret=secret,
        transport=httpx.MockTransport(mock_https_token_handler(expired_mock, clock=now)),
    )
    code3 = expired_mock.issue_code(
        subject="dana",
        redirect_uri=redirect,
        state="state-exp",
        nonce=nonce,
        code_challenge=pkce.challenge,
        now=now - timedelta(minutes=5),
        ttl=timedelta(seconds=30),
    )
    with pytest.raises(OidcRejected):
        expired_client.exchange(
            code=code3,
            code_verifier=pkce.verifier,
            redirect_uri=redirect,
            state="state-exp",
            now=now,
        )

    # Forged issuer in token body.
    forged = MockHttpsIdP(
        issuer="https://evil.example.test",
        audience="aiqa-management",
        signing_key=secret,
        require_signature=True,
    )
    forged_transport = httpx.MockTransport(mock_https_token_handler(forged))
    forged_client = OperationalOidcClient(
        config=runtime.config,
        token_endpoint="https://idp.example.test/token",
        client_secret=secret,
        transport=forged_transport,
    )
    bad_code = forged.issue_code(
        subject="dana",
        redirect_uri=redirect,
        state="state-iss",
        nonce=nonce,
        code_challenge=pkce.challenge,
        now=now,
    )
    with pytest.raises(OidcRejected, match="issuer"):
        forged_client.exchange(
            code=bad_code,
            code_verifier=pkce.verifier,
            redirect_uri=redirect,
            state="state-iss",
            now=now,
        )


def test_rx_41_mock_idp_injection_keeps_browser_login_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime(2026, 11, 4, 18, 30, tzinfo=timezone.utc)
    monkeypatch.setattr("aiqa.api.oidc_login._utc", lambda value: now if value is None else value)
    asyncio.run(_browser_flow(tmp_path, now))


async def _browser_flow(tmp_path: Path, now: datetime) -> None:
    root = tmp_path / "browser"
    settings = load_settings(_hosted_env(root))
    secret = "browser-oidc-client-secret"
    backend = MemorySecretBackend()
    resolver = build_server_secret_resolver(settings, backend=backend)
    resolver.store_oidc_client_secret(secret)
    idp = MockHttpsIdP(
        issuer="https://idp.example.test",
        audience="aiqa-management",
        signing_key=secret,
        require_signature=True,
    )
    app = create_app(settings, secret_backend=backend, oidc_idp=idp)
    assert app.state.oidc_runtime is not None
    assert app.state.oidc_idp is idp
    assert not isinstance(app.state.oidc_runtime.idp, OperationalOidcClient)

    store = app.state.open_store()
    migrate_store(store)
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("Oidc41", "oidc41", "", "web"))
    actor_id = uuid4()
    with store.transaction() as connection:
        connection.execute(
            """
            INSERT INTO oidc_identities (identity_id, issuer, subject, actor_id, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (str(uuid4()), idp.issuer, "erin", str(actor_id), now.isoformat()),
        )
        grant_membership(Transaction(connection), project.project_id, actor_id, "admin", now=now)
    store.close()

    headers = {
        "X-Forwarded-Proto": "https",
        "X-Forwarded-For": "203.0.113.41",
        "Origin": "https://manage.example.test",
    }
    transport = ASGITransport(app=app, client=("127.0.0.1", 50041))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        page = await client.get("/ui/login", headers=headers)
        assert page.status_code == 200

        started = await client.post(
            "/api/v1/auth/oidc/start",
            headers={**headers, "Idempotency-Key": "rx41-start"},
        )
        assert started.status_code == 201, started.text
        body = started.json()
        assert "authorize_url" in body and body["authorize_url"].startswith(
            "https://idp.example.test/authorize?"
        )

        store = app.state.open_store()
        with store.transaction() as connection:
            row = connection.execute(
                "SELECT nonce, code_challenge FROM oidc_login_states WHERE state=?",
                (body["state"],),
            ).fetchone()
        store.close()
        code = idp.issue_code(
            subject="erin",
            redirect_uri="https://manage.example.test/api/v1/auth/oidc/callback",
            state=body["state"],
            nonce=str(row[0]),
            code_challenge=str(row[1]),
            now=now,
        )
        booted = await client.post(
            "/api/v1/auth/oidc/callback",
            json={
                "code": code,
                "state": body["state"],
                "code_verifier": body["code_verifier"],
                "project_id": str(project.project_id),
            },
            headers={**headers, "Idempotency-Key": "rx41-callback"},
        )
        assert booted.status_code == 201, booted.text
        assert "aiqa_session" in booted.cookies

        reused = await client.post(
            "/api/v1/auth/oidc/callback",
            json={
                "code": code,
                "state": body["state"],
                "code_verifier": body["code_verifier"],
                "project_id": str(project.project_id),
            },
            headers={**headers, "Idempotency-Key": "rx41-reuse"},
        )
        assert reused.status_code == 401

        started2 = await client.post(
            "/api/v1/auth/oidc/start",
            headers={**headers, "Idempotency-Key": "rx41-start2"},
        )
        body2 = started2.json()
        store = app.state.open_store()
        with store.transaction() as connection:
            row2 = connection.execute(
                "SELECT nonce, code_challenge FROM oidc_login_states WHERE state=?",
                (body2["state"],),
            ).fetchone()
        store.close()
        code2 = idp.issue_code(
            subject="stranger",
            redirect_uri="https://manage.example.test/api/v1/auth/oidc/callback",
            state=body2["state"],
            nonce=str(row2[0]),
            code_challenge=str(row2[1]),
            now=now,
        )
        denied = await client.post(
            "/api/v1/auth/oidc/callback",
            json={
                "code": code2,
                "state": body2["state"],
                "code_verifier": body2["code_verifier"],
                "project_id": str(project.project_id),
            },
            headers={**headers, "Idempotency-Key": "rx41-nomember"},
        )
        assert denied.status_code == 403


def test_rx_41_create_app_default_wires_operational_client(tmp_path: Path) -> None:
    settings = load_settings(_hosted_env(tmp_path / "default"))
    backend = MemorySecretBackend()
    resolver = build_server_secret_resolver(settings, backend=backend)
    resolver.store_oidc_client_secret("default-oidc-client-secret")
    app = create_app(settings, secret_backend=backend)
    assert app.state.oidc_runtime is not None
    assert isinstance(app.state.oidc_runtime.idp, OperationalOidcClient)
    assert app.state.oidc_runtime.token_endpoint == "https://idp.example.test/token"
