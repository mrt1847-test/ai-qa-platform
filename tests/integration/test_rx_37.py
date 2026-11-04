"""RX-37: hosted OIDC assembly — mock IdP roundtrip, secret missing, bad claims/signature."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from aiqa.api.app import create_app
from aiqa.api.oidc_login import assemble_hosted_oidc_runtime
from aiqa.config import load_settings
from aiqa.domain.projects import bind_store, create_project, grant_membership
from aiqa.security.oidc import (
    IdTokenClaims,
    MockHttpsIdP,
    OidcRejected,
    OperationalOidcClient,
    generate_pkce,
    sign_id_token_claims,
    validate_id_token_claims,
    verify_id_token_signature,
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
    }


def test_rx_37_assemble_requires_secret_and_rejects_bad_claims() -> None:
    settings = load_settings(_hosted_env(Path("unused")))
    assert settings.oidc is not None
    backend = MemorySecretBackend()
    resolver = build_server_secret_resolver(settings, backend=backend)
    assert assemble_hosted_oidc_runtime(settings, resolver) is None

    resolver.store_oidc_client_secret("hosted-oidc-client-secret")
    runtime = assemble_hosted_oidc_runtime(settings, resolver)
    assert runtime is not None
    assert runtime.client_secret_present is True
    assert runtime.config.issuer == "https://idp.example.test"
    assert runtime.config.redirect_uri.endswith("/api/v1/auth/oidc/callback")
    assert isinstance(runtime.idp, OperationalOidcClient)
    assert runtime.token_endpoint.endswith("/token")

    # Claim/signature gates stay on the shared helpers + injected mock IdP.
    mock = MockHttpsIdP(
        issuer=runtime.config.issuer,
        audience=runtime.config.audience,
        signing_key="hosted-oidc-client-secret",
        require_signature=True,
    )
    now = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
    pkce = generate_pkce()
    pkce_state = "state-ok"
    nonce = "nonce-ok"
    code = mock.issue_code(
        subject="alice",
        redirect_uri=runtime.config.redirect_uri,
        state=pkce_state,
        nonce=nonce,
        code_challenge=pkce.challenge,
        now=now,
        ttl=timedelta(seconds=30),
    )
    claims = IdTokenClaims(runtime.config.issuer, "alice", runtime.config.audience, nonce)
    good_sig = sign_id_token_claims(claims, "hosted-oidc-client-secret")
    verify_id_token_signature(claims, good_sig, "hosted-oidc-client-secret")
    with pytest.raises(OidcRejected, match="signature"):
        verify_id_token_signature(claims, "sha256:" + ("0" * 64), "hosted-oidc-client-secret")
    with pytest.raises(OidcRejected, match="issuer"):
        validate_id_token_claims(
            IdTokenClaims("https://evil.test", "alice", runtime.config.audience, nonce),
            config=runtime.config,
            expected_nonce=nonce,
        )
    with pytest.raises(OidcRejected, match="signature"):
        mock.exchange(
            code=code,
            code_verifier=pkce.verifier,
            redirect_uri=runtime.config.redirect_uri,
            state=pkce_state,
            now=now,
            presented_signature="sha256:" + ("f" * 64),
        )
    code2 = mock.issue_code(
        subject="alice",
        redirect_uri=runtime.config.redirect_uri,
        state="state-exp",
        nonce=nonce,
        code_challenge=pkce.challenge,
        now=now,
        ttl=timedelta(seconds=1),
    )
    with pytest.raises(OidcRejected, match="expired"):
        mock.exchange(
            code=code2,
            code_verifier=pkce.verifier,
            redirect_uri=runtime.config.redirect_uri,
            state="state-exp",
            now=now + timedelta(seconds=2),
        )


def test_rx_37_hosted_app_start_wires_oidc_and_http_roundtrip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime(2026, 11, 4, 12, 30, tzinfo=timezone.utc)
    monkeypatch.setattr("aiqa.api.oidc_login._utc", lambda value: now if value is None else value)
    asyncio.run(_http_assembled_flow(tmp_path, now))


async def _http_assembled_flow(tmp_path: Path, now: datetime) -> None:
    root = tmp_path / "http"
    settings = load_settings(_hosted_env(root))
    backend = MemorySecretBackend()
    resolver = build_server_secret_resolver(settings, backend=backend)
    resolver.store_oidc_client_secret("hosted-oidc-client-secret")
    idp = MockHttpsIdP(
        issuer="https://idp.example.test",
        audience="aiqa-management",
        signing_key="hosted-oidc-client-secret",
        require_signature=True,
    )
    app = create_app(settings, secret_backend=backend, oidc_idp=idp)
    assert app.state.oidc_runtime is not None
    assert app.state.oidc_idp is idp

    store = app.state.open_store()
    migrate_store(store)
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("Oidc", "oidc", "", "web"))
    actor_id = uuid4()
    with store.transaction() as connection:
        connection.execute(
            """
            INSERT INTO oidc_identities (identity_id, issuer, subject, actor_id, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (str(uuid4()), idp.issuer, "carol", str(actor_id), now.isoformat()),
        )
        grant_membership(Transaction(connection), project.project_id, actor_id, "admin", now=now)
    store.close()

    headers_base = {
        "X-Forwarded-Proto": "https",
        "X-Forwarded-For": "203.0.113.10",
        "Origin": "https://manage.example.test",
    }
    transport = ASGITransport(app=app, client=("127.0.0.1", 50000))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        page = await client.get("/ui/login", headers=headers_base)
        assert page.status_code == 200

        started = await client.post(
            "/api/v1/auth/oidc/start",
            headers={**headers_base, "Idempotency-Key": "rx37-start"},
        )
        assert started.status_code == 201, started.text
        body = started.json()
        store = app.state.open_store()
        with store.transaction() as connection:
            row = connection.execute(
                "SELECT nonce, code_challenge FROM oidc_login_states WHERE state=?",
                (body["state"],),
            ).fetchone()
        store.close()
        code = idp.issue_code(
            subject="carol",
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
            headers={**headers_base, "Idempotency-Key": "rx37-callback"},
        )
        assert booted.status_code == 201, booted.text
        assert "aiqa_session" in booted.cookies

        # State reuse.
        reused = await client.post(
            "/api/v1/auth/oidc/callback",
            json={
                "code": code,
                "state": body["state"],
                "code_verifier": body["code_verifier"],
                "project_id": str(project.project_id),
            },
            headers={**headers_base, "Idempotency-Key": "rx37-reuse"},
        )
        assert reused.status_code == 401

        # No membership.
        started2 = await client.post(
            "/api/v1/auth/oidc/start",
            headers={**headers_base, "Idempotency-Key": "rx37-start2"},
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
            subject="nobody",
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
            headers={**headers_base, "Idempotency-Key": "rx37-nomember"},
        )
        assert denied.status_code == 403


def test_rx_37_missing_secret_leaves_oidc_unconfigured(tmp_path: Path) -> None:
    settings = load_settings(_hosted_env(tmp_path / "nosec"))
    app = create_app(settings, secret_backend=MemorySecretBackend())
    assert app.state.oidc_runtime is None
    assert app.state.oidc_idp is None
