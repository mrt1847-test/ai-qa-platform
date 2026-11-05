"""RX-59: hosted browser OIDC login via registered redirect URI."""

from __future__ import annotations

import asyncio
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
from urllib.parse import parse_qs, urlparse

import pytest
from httpx import ASGITransport, AsyncClient

from aiqa.api.app import create_app
from aiqa.config import load_settings
from aiqa.domain.projects import bind_store, create_project, grant_membership
from aiqa.security.oidc import MockHttpsIdP
from aiqa.security.secrets import MemorySecretBackend, build_server_secret_resolver
from aiqa.store.database import migrate_store
from aiqa.store.models import Actor, ProjectCreate, Transaction

_BROWSERS = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
)


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


def test_rx_59_browser_oidc_roundtrip_and_rejects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime(2026, 11, 5, 10, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("aiqa.api.oidc_login._utc", lambda value: now if value is None else value)
    observed = asyncio.run(_flow(tmp_path, now, monkeypatch))
    browser_ok = _browser_shot(tmp_path, str(observed["login_html"]))

    assert observed["login_has_start"] is True
    assert observed["login_has_callback"] is True
    assert observed["authorize_host"] == "idp.example.test"
    assert observed["happy_status"] == 303
    assert observed["happy_location"].endswith(f"/ui/projects/{observed['project_id']}")
    assert observed["happy_session"] is True
    assert observed["reuse_status"] == 401
    assert observed["bad_signature_status"] == 401
    assert "signature" in str(observed["bad_signature_body"]).lower()
    assert observed["expired_status"] == 401
    assert "expired" in str(observed["expired_body"]).lower()
    assert observed["non_member_status"] == 403
    assert browser_ok is True


async def _flow(
    tmp_path: Path, now: datetime, monkeypatch: pytest.MonkeyPatch
) -> dict[str, object]:
    root = tmp_path / "runtime"
    settings = load_settings(_hosted_env(root))
    secret = "rx59-oidc-client-secret"
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

    store = app.state.open_store()
    migrate_store(store)
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("Oidc59", "oidc59", "", "web"))
    actor_id = uuid4()
    with store.transaction() as connection:
        connection.execute(
            """
            INSERT INTO oidc_identities (identity_id, issuer, subject, actor_id, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (str(uuid4()), idp.issuer, "frank", str(actor_id), now.isoformat()),
        )
        grant_membership(Transaction(connection), project.project_id, actor_id, "admin", now=now)
    store.close()

    headers = {
        "X-Forwarded-Proto": "https",
        "X-Forwarded-For": "203.0.113.59",
        "Origin": "https://manage.example.test",
    }
    transport = ASGITransport(app=app, client=("127.0.0.1", 50059))
    async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=False) as client:
        login = await client.get(
            f"/ui/login?project_id={project.project_id}",
            headers=headers,
        )
        assert login.status_code == 200, login.text

        started = await client.post(
            "/api/v1/auth/oidc/start",
            json={"project_id": str(project.project_id)},
            headers={**headers, "Idempotency-Key": "rx59-start"},
        )
        assert started.status_code == 201, started.text
        body = started.json()
        authorize = urlparse(body["authorize_url"])
        assert authorize.scheme == "https"
        query = parse_qs(authorize.query)
        assert query["state"][0] == body["state"]
        assert query["redirect_uri"][0].endswith("/api/v1/auth/oidc/callback")

        store = app.state.open_store()
        with store.transaction() as connection:
            row = connection.execute(
                "SELECT nonce, code_challenge, project_id FROM oidc_login_states WHERE state=?",
                (body["state"],),
            ).fetchone()
        store.close()
        assert str(row[2]) == str(project.project_id)

        code = idp.issue_code(
            subject="frank",
            redirect_uri="https://manage.example.test/api/v1/auth/oidc/callback",
            state=body["state"],
            nonce=str(row[0]),
            code_challenge=str(row[1]),
            now=now,
        )
        happy = await client.get(
            f"/api/v1/auth/oidc/callback?code={code}&state={body['state']}",
            headers=headers,
        )
        reuse = await client.get(
            f"/api/v1/auth/oidc/callback?code={code}&state={body['state']}",
            headers=headers,
        )

        # Bad signature on a fresh start → GET callback.
        started_sig = await client.post(
            "/api/v1/auth/oidc/start",
            json={"project_id": str(project.project_id)},
            headers={**headers, "Idempotency-Key": "rx59-sig"},
        )
        body_sig = started_sig.json()
        store = app.state.open_store()
        with store.transaction() as connection:
            row_sig = connection.execute(
                "SELECT nonce, code_challenge FROM oidc_login_states WHERE state=?",
                (body_sig["state"],),
            ).fetchone()
        store.close()
        code_sig = idp.issue_code(
            subject="frank",
            redirect_uri="https://manage.example.test/api/v1/auth/oidc/callback",
            state=body_sig["state"],
            nonce=str(row_sig[0]),
            code_challenge=str(row_sig[1]),
            now=now,
        )
        assert idp._codes is not None
        idp._codes[code_sig]["signature"] = "sha256:" + ("0" * 64)
        bad_sig = await client.get(
            f"/api/v1/auth/oidc/callback?code={code_sig}&state={body_sig['state']}",
            headers=headers,
        )

        # Expired ID token while authorization code is still valid.
        started_exp = await client.post(
            "/api/v1/auth/oidc/start",
            json={"project_id": str(project.project_id)},
            headers={**headers, "Idempotency-Key": "rx59-exp"},
        )
        body_exp = started_exp.json()
        store = app.state.open_store()
        with store.transaction() as connection:
            row_exp = connection.execute(
                "SELECT nonce, code_challenge FROM oidc_login_states WHERE state=?",
                (body_exp["state"],),
            ).fetchone()
        store.close()
        code_exp = idp.issue_code(
            subject="frank",
            redirect_uri="https://manage.example.test/api/v1/auth/oidc/callback",
            state=body_exp["state"],
            nonce=str(row_exp[0]),
            code_challenge=str(row_exp[1]),
            now=now,
            ttl=timedelta(minutes=5),
            id_token_ttl=timedelta(seconds=1),
        )
        later = now + timedelta(seconds=2)
        monkeypatch.setattr(
            "aiqa.api.oidc_login._utc", lambda value: later if value is None else value
        )
        monkeypatch.setattr(
            "aiqa.security.oidc._utc", lambda value: later if value is None else value
        )
        expired = await client.get(
            f"/api/v1/auth/oidc/callback?code={code_exp}&state={body_exp['state']}",
            headers=headers,
        )
        monkeypatch.setattr(
            "aiqa.api.oidc_login._utc", lambda value: now if value is None else value
        )
        monkeypatch.setattr(
            "aiqa.security.oidc._utc", lambda value: now if value is None else value
        )

        # Non-member subject.
        started_nm = await client.post(
            "/api/v1/auth/oidc/start",
            json={"project_id": str(project.project_id)},
            headers={**headers, "Idempotency-Key": "rx59-nm"},
        )
        body_nm = started_nm.json()
        store = app.state.open_store()
        with store.transaction() as connection:
            row_nm = connection.execute(
                "SELECT nonce, code_challenge FROM oidc_login_states WHERE state=?",
                (body_nm["state"],),
            ).fetchone()
        store.close()
        code_nm = idp.issue_code(
            subject="stranger",
            redirect_uri="https://manage.example.test/api/v1/auth/oidc/callback",
            state=body_nm["state"],
            nonce=str(row_nm[0]),
            code_challenge=str(row_nm[1]),
            now=now,
        )
        denied = await client.get(
            f"/api/v1/auth/oidc/callback?code={code_nm}&state={body_nm['state']}",
            headers=headers,
        )

    return {
        "project_id": str(project.project_id),
        "login_html": login.text,
        "login_has_start": "data-oidc-start='/api/v1/auth/oidc/start'" in login.text
        or 'data-oidc-start="/api/v1/auth/oidc/start"' in login.text,
        "login_has_callback": "data-oidc-callback='/api/v1/auth/oidc/callback'" in login.text
        or 'data-oidc-callback="/api/v1/auth/oidc/callback"' in login.text,
        "authorize_host": authorize.hostname,
        "happy_status": happy.status_code,
        "happy_location": happy.headers.get("location", ""),
        "happy_session": "aiqa_session" in happy.cookies,
        "reuse_status": reuse.status_code,
        "bad_signature_status": bad_sig.status_code,
        "bad_signature_body": bad_sig.text,
        "expired_status": expired.status_code,
        "expired_body": expired.text,
        "non_member_status": denied.status_code,
    }


def _browser_shot(tmp_path: Path, html: str) -> bool:
    browser = next((path for path in _BROWSERS if path.exists()), None)
    if browser is None:
        return False
    page = tmp_path / "rx59.html"
    shot = tmp_path / "rx59.png"
    page.write_text(html, encoding="utf-8")
    completed = subprocess.run(
        [
            str(browser),
            "--headless=new",
            "--disable-gpu",
            f"--screenshot={shot}",
            page.resolve().as_uri(),
        ],
        check=False,
        capture_output=True,
        timeout=60,
    )
    return completed.returncode == 0 and shot.exists() and shot.stat().st_size > 1024
