"""RX-17: OIDC PKCE login, membership roles, and capability gates."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from aiqa.api.app import create_app
from aiqa.api.oidc_login import assert_route_capability, complete_oidc_login, start_oidc_login
from aiqa.config import load_settings
from aiqa.domain.projects import (
    MembershipDenied,
    bind_store,
    create_project,
    grant_membership,
    revoke_membership,
)
from aiqa.security.oidc import (
    FixtureIdP,
    IdTokenClaims,
    OidcClientConfig,
    OidcRejected,
    generate_pkce,
    validate_id_token_claims,
)
from aiqa.store.database import migrate_store
from aiqa.store.models import Actor, ProjectCreate, Transaction
from aiqa.web.routes import hosted_login_path


def _hosted_env(root: Path) -> dict[str, str]:
    return {
        "AIQA_HOST": "127.0.0.1",
        "AIQA_PORT": "8000",
        "AIQA_RUNTIME_ROOT": str(root),
        "AIQA_PROFILE": "hosted",
        "AIQA_PUBLIC_ORIGIN": "https://manage.example.test",
        "AIQA_TRUSTED_PROXIES": "127.0.0.1",
    }


def test_oidc_rejects_bad_claims_and_reused_code() -> None:
    idp = FixtureIdP()
    config = OidcClientConfig(
        issuer=idp.issuer,
        audience=idp.audience,
        redirect_uri="https://manage.example.test/api/v1/auth/oidc/callback",
    )
    pkce = generate_pkce()
    now = datetime(2026, 11, 3, 14, 0, tzinfo=timezone.utc)
    code = idp.issue_code(
        subject="user-1",
        redirect_uri=config.redirect_uri,
        state="state-1",
        nonce="nonce-1",
        code_challenge=pkce.challenge,
        now=now,
    )
    claims = idp.exchange(
        code=code,
        code_verifier=pkce.verifier,
        redirect_uri=config.redirect_uri,
        state="state-1",
        now=now,
    )
    validate_id_token_claims(claims, config=config, expected_nonce="nonce-1")
    with pytest.raises(OidcRejected, match="issuer"):
        validate_id_token_claims(
            IdTokenClaims("https://evil.test", "user-1", idp.audience, "nonce-1"),
            config=config,
            expected_nonce="nonce-1",
        )
    with pytest.raises(OidcRejected, match="audience"):
        validate_id_token_claims(
            IdTokenClaims(idp.issuer, "user-1", "other-aud", "nonce-1"),
            config=config,
            expected_nonce="nonce-1",
        )
    with pytest.raises(OidcRejected, match="nonce"):
        validate_id_token_claims(claims, config=config, expected_nonce="other")
    with pytest.raises(OidcRejected, match="reused"):
        idp.exchange(
            code=code,
            code_verifier=pkce.verifier,
            redirect_uri=config.redirect_uri,
            state="state-1",
            now=now,
        )


def test_membership_roles_and_oidc_session_gates(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    settings = load_settings(_hosted_env(root))
    app = create_app(settings)
    idp = FixtureIdP()
    app.state.oidc_idp = idp
    store = app.state.open_store()
    migrate_store(store)
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("Alpha", "alpha", "", "web"))
        other = create_project(owner, ProjectCreate("Beta", "beta", "", "web"))
    config = OidcClientConfig(
        issuer=idp.issuer,
        audience=idp.audience,
        redirect_uri="https://manage.example.test/api/v1/auth/oidc/callback",
    )
    now = datetime(2026, 11, 3, 14, 0, tzinfo=timezone.utc)
    origin = "https://manage.example.test"
    actor_id = uuid4()

    with store.transaction() as connection:
        connection.execute(
            """
            INSERT INTO oidc_identities (identity_id, issuer, subject, actor_id, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (str(uuid4()), idp.issuer, "alice", str(actor_id), now.isoformat()),
        )
        with pytest.raises(MembershipDenied):
            assert_route_capability(
                connection,
                Actor(actor_id, project.project_id, False),
                project.project_id,
                "project_view",
            )
        grant_membership(Transaction(connection), project.project_id, actor_id, "viewer", now=now)
        started = start_oidc_login(
            connection, config, authorize_endpoint=f"{idp.issuer}/authorize", now=now
        )
        nonce = connection.execute(
            "SELECT nonce FROM oidc_login_states WHERE state=?", (started["state"],)
        ).fetchone()[0]
        challenge = connection.execute(
            "SELECT code_challenge FROM oidc_login_states WHERE state=?",
            (started["state"],),
        ).fetchone()[0]
        code = idp.issue_code(
            subject="alice",
            redirect_uri=config.redirect_uri,
            state=started["state"],
            nonce=nonce,
            code_challenge=challenge,
            now=now,
        )
        session = complete_oidc_login(
            connection,
            config,
            idp,
            code=code,
            state=started["state"],
            code_verifier=started["code_verifier"],
            project_id=project.project_id,
            origin=origin,
            now=now,
        )
        assert session.actor.is_local_owner is False
        assert session.actor.actor_id == actor_id
        assert_route_capability(connection, session.actor, project.project_id, "project_view")
        assert_route_capability(connection, session.actor, project.project_id, "evidence_download")
        with pytest.raises(MembershipDenied):
            assert_route_capability(connection, session.actor, project.project_id, "approve")
        with pytest.raises(MembershipDenied):
            assert_route_capability(connection, session.actor, project.project_id, "worker_manage")
        with pytest.raises(MembershipDenied):
            assert_route_capability(connection, session.actor, other.project_id, "project_view")

        grant_membership(Transaction(connection), project.project_id, actor_id, "admin", now=now)
        assert_route_capability(connection, session.actor, project.project_id, "approve")
        assert_route_capability(connection, session.actor, project.project_id, "worker_manage")

        revoke_membership(Transaction(connection), project.project_id, actor_id, now=now)
        with pytest.raises(MembershipDenied):
            assert_route_capability(connection, session.actor, project.project_id, "project_view")
        with pytest.raises(MembershipDenied):
            assert_route_capability(connection, session.actor, project.project_id, "approve")

    assert hosted_login_path() == "/ui/login"
    store.close()


def test_hosted_login_page_and_http_oidc_callback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime(2026, 11, 3, 15, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("aiqa.api.oidc_login._utc", lambda value: now if value is None else value)
    asyncio.run(_http_flow(tmp_path, now))


async def _http_flow(tmp_path: Path, now: datetime) -> None:
    root = tmp_path / "http"
    settings = load_settings(_hosted_env(root))
    app = create_app(settings)
    idp = FixtureIdP()
    app.state.oidc_idp = idp
    store = app.state.open_store()
    migrate_store(store)
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("Http", "http", "", "web"))
    actor_id = uuid4()
    with store.transaction() as connection:
        connection.execute(
            """
            INSERT INTO oidc_identities (identity_id, issuer, subject, actor_id, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (str(uuid4()), idp.issuer, "bob", str(actor_id), now.isoformat()),
        )
        grant_membership(Transaction(connection), project.project_id, actor_id, "admin", now=now)
    store.close()

    transport = ASGITransport(app=app, client=("127.0.0.1", 50000))
    headers_base = {
        "X-Forwarded-Proto": "https",
        "X-Forwarded-For": "203.0.113.10",
        "Origin": "https://manage.example.test",
    }
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        page = await client.get("/ui/login", headers=headers_base)
        assert page.status_code == 200
        assert "/api/v1/auth/oidc/start" in page.text

        started = await client.post(
            "/api/v1/auth/oidc/start",
            headers={**headers_base, "Idempotency-Key": "rx17-start"},
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
            subject="bob",
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
            headers={**headers_base, "Idempotency-Key": "rx17-callback"},
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
            headers={**headers_base, "Idempotency-Key": "rx17-reuse"},
        )
        assert reused.status_code == 401
