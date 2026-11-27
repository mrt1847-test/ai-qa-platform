"""OIDC authorization-code + PKCE helpers, operational HTTP client, and test IdP."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol
from urllib.parse import parse_qs, urlencode

import httpx

DEFAULT_CODE_TTL = timedelta(seconds=120)
DEFAULT_STATE_TTL = timedelta(seconds=600)
DEFAULT_ID_TOKEN_TTL = timedelta(minutes=10)


class OidcRejected(Exception):
    """OIDC state, nonce, issuer, audience, or PKCE was refused."""


@dataclass(frozen=True, slots=True)
class OidcClientConfig:
    issuer: str
    audience: str
    redirect_uri: str
    client_id: str = "aiqa-management"


@dataclass(frozen=True, slots=True)
class PkcePair:
    verifier: str
    challenge: str


@dataclass(frozen=True, slots=True)
class LoginStart:
    state: str
    nonce: str
    pkce: PkcePair
    authorize_url: str


@dataclass(frozen=True, slots=True)
class IdTokenClaims:
    issuer: str
    subject: str
    audience: str
    nonce: str
    expires_at: str | None = None


def generate_pkce() -> PkcePair:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return PkcePair(verifier=verifier, challenge=challenge)


def verify_pkce(verifier: str, challenge: str) -> None:
    if type(verifier) is not str or type(challenge) is not str:
        raise OidcRejected("pkce was rejected")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    if not hmac.compare_digest(expected, challenge):
        raise OidcRejected("pkce was rejected")


def begin_authorization(config: OidcClientConfig, *, authorize_endpoint: str) -> LoginStart:
    pkce = generate_pkce()
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    query = urlencode(
        {
            "response_type": "code",
            "client_id": config.client_id,
            "redirect_uri": config.redirect_uri,
            "scope": "openid",
            "state": state,
            "nonce": nonce,
            "code_challenge": pkce.challenge,
            "code_challenge_method": "S256",
        }
    )
    return LoginStart(
        state=state,
        nonce=nonce,
        pkce=pkce,
        authorize_url=f"{authorize_endpoint}?{query}",
    )


def validate_id_token_claims(
    claims: IdTokenClaims,
    *,
    config: OidcClientConfig,
    expected_nonce: str,
    now: datetime | None = None,
) -> None:
    if claims.issuer != config.issuer:
        raise OidcRejected("issuer was rejected")
    if claims.audience != config.audience:
        raise OidcRejected("audience was rejected")
    if claims.nonce != expected_nonce:
        raise OidcRejected("nonce was rejected")
    if type(claims.subject) is not str or claims.subject.strip() == "":
        raise OidcRejected("subject was rejected")
    if claims.expires_at is not None:
        try:
            expires = datetime.fromisoformat(claims.expires_at)
        except ValueError as exc:
            raise OidcRejected("id_token expiry was rejected") from exc
        if expires.tzinfo is None:
            raise OidcRejected("id_token expiry was rejected")
        if _utc(now) >= expires.astimezone(timezone.utc):
            raise OidcRejected("id_token expired")


def sign_id_token_claims(claims: IdTokenClaims, signing_key: str) -> str:
    if type(signing_key) is not str or len(signing_key) < 8:
        raise OidcRejected("signing key is missing")
    material = "|".join([claims.issuer, claims.subject, claims.audience, claims.nonce])
    digest = hmac.new(signing_key.encode("utf-8"), material.encode("utf-8"), hashlib.sha256).hexdigest()
    return "sha256:" + digest


def verify_id_token_signature(claims: IdTokenClaims, signature: str, signing_key: str) -> None:
    expected = sign_id_token_claims(claims, signing_key)
    if type(signature) is not str or not hmac.compare_digest(expected, signature):
        raise OidcRejected("signature was rejected")


@dataclass
class FixtureIdP:
    """In-process IdP for tests. Does not open network sockets."""

    issuer: str = "https://idp.example.test"
    audience: str = "aiqa-management"
    signing_key: str = ""
    require_signature: bool = False
    _codes: dict[str, dict[str, object]] | None = None

    def __post_init__(self) -> None:
        self._codes = {}
        if self.require_signature and (type(self.signing_key) is not str or len(self.signing_key) < 8):
            raise OidcRejected("signing key is missing")

    def issue_code(
        self,
        *,
        subject: str,
        redirect_uri: str,
        state: str,
        nonce: str,
        code_challenge: str,
        now: datetime | None = None,
        ttl: timedelta | None = None,
        id_token_ttl: timedelta | None = None,
    ) -> str:
        instant = _utc(now)
        code = secrets.token_urlsafe(24)
        token_ttl = id_token_ttl if id_token_ttl is not None else DEFAULT_ID_TOKEN_TTL
        claims = IdTokenClaims(
            self.issuer,
            subject,
            self.audience,
            nonce,
            (instant + token_ttl).isoformat(),
        )
        signature = ""
        if self.require_signature or self.signing_key:
            signature = sign_id_token_claims(claims, self.signing_key)
        assert self._codes is not None
        self._codes[code] = {
            "subject": subject,
            "redirect_uri": redirect_uri,
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "expires_at": instant + (ttl if ttl is not None else DEFAULT_CODE_TTL),
            "id_token_expires_at": claims.expires_at,
            "used": False,
            "signature": signature,
        }
        return code

    def exchange(
        self,
        *,
        code: str,
        code_verifier: str,
        redirect_uri: str,
        state: str,
        now: datetime | None = None,
        presented_signature: str | None = None,
    ) -> IdTokenClaims:
        assert self._codes is not None
        row = self._codes.get(code)
        if row is None:
            raise OidcRejected("authorization code was rejected")
        if bool(row["used"]):
            raise OidcRejected("authorization code was reused")
        if str(row["state"]) != state:
            raise OidcRejected("state was rejected")
        if str(row["redirect_uri"]) != redirect_uri:
            raise OidcRejected("redirect_uri was rejected")
        expires_at = row["expires_at"]
        if not isinstance(expires_at, datetime) or _utc(now) >= expires_at:
            raise OidcRejected("authorization code expired")
        verify_pkce(code_verifier, str(row["code_challenge"]))
        claims = IdTokenClaims(
            issuer=self.issuer,
            subject=str(row["subject"]),
            audience=self.audience,
            nonce=str(row["nonce"]),
            expires_at=str(row["id_token_expires_at"]) if row.get("id_token_expires_at") else None,
        )
        if self.require_signature:
            signature = presented_signature if presented_signature is not None else str(row["signature"])
            verify_id_token_signature(claims, signature, self.signing_key)
        row["used"] = True
        return claims


@dataclass
class MockHttpsIdP(FixtureIdP):
    """Mock HTTPS IdP for test injection only. Opens no sockets."""

    issuer: str = "https://idp.example.test"
    audience: str = "aiqa-management"
    signing_key: str = "fixture-oidc-signing-key"
    require_signature: bool = True


class OidcExchangePort(Protocol):
    """Code→claims exchange used by hosted login. Mock or operational HTTP client."""

    def exchange(
        self,
        *,
        code: str,
        code_verifier: str,
        redirect_uri: str,
        state: str,
        now: datetime | None = None,
        presented_signature: str | None = None,
    ) -> IdTokenClaims:
        """Exchange one authorization code. Must not open the management SQLite."""


@dataclass(frozen=True, slots=True)
class OperationalOidcClient:
    """Standard OIDC confidential client: RS256 ID tokens and client_secret_post."""

    config: OidcClientConfig
    token_endpoint: str
    client_secret: str = field(repr=False)
    transport: httpx.BaseTransport | None = field(default=None, repr=False)
    timeout_seconds: float = 10.0
    _verified_exchange: Any = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        from aiqa.security.oidc_jwt import VerifiedOidcExchange, https_url
        import math
        if not https_url(self.token_endpoint) or not https_url(self.config.issuer):
            raise OidcRejected("OIDC HTTPS endpoint is invalid")
        if type(self.client_secret) is not str or len(self.client_secret) < 8:
            raise OidcRejected("OIDC client secret is unavailable")
        if type(self.timeout_seconds) not in (int,float) or not math.isfinite(self.timeout_seconds) or not 0 < self.timeout_seconds <= 30:
            raise OidcRejected("OIDC timeout is invalid")
        object.__setattr__(self, '_verified_exchange', VerifiedOidcExchange(
            self.config, self.token_endpoint, self.client_secret, self.transport, self.timeout_seconds))

    def exchange(self, *, code: str, code_verifier: str, redirect_uri: str, state: str,
                 now: datetime | None = None, presented_signature: str | None = None) -> IdTokenClaims:
        if presented_signature is not None:
            raise OidcRejected("signature override was rejected")
        for value in (code, code_verifier, state):
            if type(value) is not str or not value.strip():
                raise OidcRejected("authorization exchange was rejected")
        if redirect_uri != self.config.redirect_uri:
            raise OidcRejected("redirect_uri was rejected")
        return self._verified_exchange.exchange(code=code, code_verifier=code_verifier,
            redirect_uri=redirect_uri, state=state, now=_utc(now))


def mock_https_token_handler(
    idp: MockHttpsIdP,
    *,
    clock: datetime | None = None,
) -> Any:
    """Test-only HTTPS discovery/JWKS/token fixture with real synthetic RSA signatures."""

    import json
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = {**json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key())),
                  'kid': 'fixture-one', 'alg': 'RS256', 'use': 'sig'}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == 'GET' and request.url.path.endswith('/.well-known/openid-configuration'):
            return httpx.Response(200, json={
                'issuer': idp.issuer, 'token_endpoint': idp.issuer.rstrip('/') + '/token',
                'jwks_uri': idp.issuer.rstrip('/') + '/keys',
                'token_endpoint_auth_methods_supported': ['client_secret_post'],
                'id_token_signing_alg_values_supported': ['RS256']})
        if request.method == 'GET' and request.url.path.endswith('/keys'):
            return httpx.Response(200, json={'keys': [public_jwk]})
        if request.method.upper() != "POST":
            return httpx.Response(405, json={"error": "method_not_allowed"})
        form = {key: values[-1] for key, values in parse_qs(request.content.decode("utf-8")).items()}
        if form.get('client_secret') != idp.signing_key:
            return httpx.Response(401, json={'error': 'invalid_client'})
        try:
            claims = idp.exchange(
                code=str(form.get("code", "")),
                code_verifier=str(form.get("code_verifier", "")),
                redirect_uri=str(form.get("redirect_uri", "")),
                state=str(form.get('state') or (idp._codes or {}).get(str(form.get('code', '')), {}).get('state', '')),
                now=clock,
            )
        except OidcRejected as exc:
            return httpx.Response(400, json={"error": str(exc)})
        instant = _utc(clock)
        claims_body = {
            "iss": claims.issuer,
            "sub": claims.subject,
            "aud": claims.audience,
            "nonce": claims.nonce,
            'iat': int(instant.timestamp()) - 1,
            'exp': int((instant + DEFAULT_ID_TOKEN_TTL).timestamp()),
        }
        if claims.expires_at is not None:
            claims_body['exp'] = int(datetime.fromisoformat(claims.expires_at).timestamp())
        return httpx.Response(
            200,
            json={
                "id_token": jwt.encode(claims_body, private_key, algorithm='RS256', headers={'kid': 'fixture-one'}),
                'token_type': 'Bearer',
            },
        )

    return handler


def _utc(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise OidcRejected("now must be timezone-aware")
    return now.astimezone(timezone.utc)
