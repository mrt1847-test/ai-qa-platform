"""Hosted OIDC login against a configured or fixture IdP. Import opens no sockets."""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from aiqa.config import AppSettings, PROFILE_HOSTED
from aiqa.domain.projects import MembershipDenied, require_project_capability
from aiqa.security.oidc import (
    DEFAULT_STATE_TTL,
    FixtureIdP,
    OidcClientConfig,
    OidcExchangePort,
    OidcRejected,
    OperationalOidcClient,
    begin_authorization,
    validate_id_token_claims,
)
from aiqa.security.secrets import SecretUnavailable, ServerSecretResolver
from aiqa.store.models import Actor, BrowserSession, Transaction

_SESSION_TTL = timedelta(hours=8)


@dataclass(frozen=True, slots=True)
class HostedOidcRuntime:
    """Assembled hosted OIDC path: approved settings + resolved client secret + exchange port."""

    config: OidcClientConfig
    idp: OidcExchangePort
    authorize_endpoint: str
    client_secret_present: bool
    token_endpoint: str = ""


def assemble_hosted_oidc_runtime(
    settings: AppSettings,
    resolver: ServerSecretResolver,
    *,
    idp: FixtureIdP | OidcExchangePort | None = None,
    token_transport=None,
) -> HostedOidcRuntime | None:
    """Build the hosted IdP client at app start. Missing secret fails closed (no runtime).

    Production uses OperationalOidcClient against the registered token endpoint.
    MockHttpsIdP is injected only in tests via idp=.
    """

    if settings.profile != PROFILE_HOSTED or settings.public_origin is None or settings.oidc is None:
        return None
    try:
        client_secret = resolver.resolve_oidc_client_secret()
    except SecretUnavailable:
        return None
    oidc = settings.oidc
    config = OidcClientConfig(
        issuer=oidc.issuer,
        audience=oidc.audience,
        redirect_uri=f"{settings.public_origin}/api/v1/auth/oidc/callback",
        client_id=oidc.client_id,
    )
    if idp is None:
        runtime_idp: OidcExchangePort = OperationalOidcClient(
            config=config,
            token_endpoint=oidc.token_endpoint,
            client_secret=client_secret,
            transport=token_transport,
        )
    else:
        runtime_idp = idp
    return HostedOidcRuntime(
        config=config,
        idp=runtime_idp,
        authorize_endpoint=oidc.authorize_endpoint,
        client_secret_present=True,
        token_endpoint=oidc.token_endpoint,
    )


def start_oidc_login(
    connection: sqlite3.Connection,
    config: OidcClientConfig,
    *,
    authorize_endpoint: str,
    project_id: UUID | None = None,
    now: datetime | None = None,
) -> dict[str, str]:
    instant = _utc(now)
    started = begin_authorization(config, authorize_endpoint=authorize_endpoint)
    connection.execute(
        """
        INSERT INTO oidc_login_states (
            state, nonce, code_challenge, code_verifier, redirect_uri, expires_at, used_at, project_id
        ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?)
        """,
        (
            started.state,
            started.nonce,
            started.pkce.challenge,
            started.pkce.verifier,
            config.redirect_uri,
            (instant + DEFAULT_STATE_TTL).isoformat(),
            None if project_id is None else str(project_id),
        ),
    )
    return {
        "state": started.state,
        "authorize_url": started.authorize_url,
        "code_verifier": started.pkce.verifier,
    }


def complete_oidc_login(
    connection: sqlite3.Connection,
    config: OidcClientConfig,
    idp: OidcExchangePort,
    *,
    code: str,
    state: str,
    code_verifier: str | None,
    project_id: UUID | None,
    origin: str,
    now: datetime | None = None,
) -> BrowserSession:
    instant = _utc(now)
    row = connection.execute(
        """
        SELECT nonce, code_challenge, code_verifier, redirect_uri, expires_at, used_at, project_id
        FROM oidc_login_states WHERE state = ?
        """,
        (state,),
    ).fetchone()
    if row is None or row[5] is not None:
        raise OidcRejected("state was rejected")
    if datetime.fromisoformat(str(row[4])) <= instant:
        raise OidcRejected("state expired")
    if str(row[3]) != config.redirect_uri:
        raise OidcRejected("redirect_uri was rejected")
    stored_verifier = str(row[2])
    if code_verifier is None or str(code_verifier).strip() == "":
        presented_verifier = stored_verifier
    else:
        presented_verifier = str(code_verifier)
        if presented_verifier != stored_verifier:
            raise OidcRejected("pkce was rejected")
    if project_id is None:
        if row[6] is None or str(row[6]).strip() == "":
            raise OidcRejected("project was rejected")
        try:
            bound_project = UUID(str(row[6]))
        except (TypeError, ValueError) as exc:
            raise OidcRejected("project was rejected") from exc
    else:
        bound_project = project_id
        if row[6] is not None and str(row[6]).strip() != "" and str(row[6]) != str(bound_project):
            raise OidcRejected("project was rejected")
    updated = connection.execute(
        "UPDATE oidc_login_states SET used_at = ? WHERE state = ? AND used_at IS NULL",
        (instant.isoformat(), state),
    )
    if updated.rowcount != 1:
        raise OidcRejected("state was rejected")

    claims = idp.exchange(
        code=code,
        code_verifier=presented_verifier,
        redirect_uri=config.redirect_uri,
        state=state,
        now=instant,
    )
    validate_id_token_claims(
        claims,
        config=config,
        expected_nonce=str(row[0]),
        now=instant,
    )

    identity = connection.execute(
        "SELECT actor_id FROM oidc_identities WHERE issuer = ? AND subject = ?",
        (claims.issuer, claims.subject),
    ).fetchone()
    if identity is None:
        actor_id = uuid4()
        connection.execute(
            """
            INSERT INTO oidc_identities (identity_id, issuer, subject, actor_id, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (str(uuid4()), claims.issuer, claims.subject, str(actor_id), instant.isoformat()),
        )
    else:
        actor_id = UUID(str(identity[0]))

    actor = Actor(actor_id=actor_id, project_scope=bound_project, is_local_owner=False)
    require_project_capability(Transaction(connection), actor, bound_project, "project_view")

    session_id = uuid4()
    csrf = secrets.token_urlsafe(32)
    expires = instant + _SESSION_TTL
    connection.execute(
        """
        INSERT INTO browser_sessions (
            session_id, origin, csrf_hash, actor_id, project_scope, is_local_owner, expires_at
        ) VALUES (?, ?, ?, ?, ?, 0, ?)
        """,
        (
            str(session_id),
            origin,
            hashlib.sha256(csrf.encode("utf-8")).hexdigest(),
            str(actor_id),
            str(bound_project),
            expires.isoformat(),
        ),
    )
    return BrowserSession(
        session_id=session_id,
        origin=origin,
        csrf_token=csrf,
        actor=actor,
        expires_at=expires.isoformat(),
    )


def assert_route_capability(
    connection: sqlite3.Connection,
    actor: Actor,
    project_id: UUID,
    capability: str,
) -> str:
    try:
        return require_project_capability(Transaction(connection), actor, project_id, capability)
    except MembershipDenied as exc:
        raise MembershipDenied(str(exc)) from exc


def _utc(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise OidcRejected("now must be timezone-aware")
    return now.astimezone(timezone.utc)
