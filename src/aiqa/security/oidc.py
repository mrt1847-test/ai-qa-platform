"""OIDC authorization-code + PKCE helpers, operational HTTP client, and test IdP."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol
from urllib.parse import parse_qs, urlencode

import httpx

DEFAULT_CODE_TTL = timedelta(seconds=120)
DEFAULT_STATE_TTL = timedelta(seconds=600)


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
) -> None:
    if claims.issuer != config.issuer:
        raise OidcRejected("issuer was rejected")
    if claims.audience != config.audience:
        raise OidcRejected("audience was rejected")
    if claims.nonce != expected_nonce:
        raise OidcRejected("nonce was rejected")
    if type(claims.subject) is not str or claims.subject.strip() == "":
        raise OidcRejected("subject was rejected")


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
    ) -> str:
        instant = _utc(now)
        code = secrets.token_urlsafe(24)
        claims = IdTokenClaims(self.issuer, subject, self.audience, nonce)
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
    """HTTPS token-endpoint client for a registered hosted IdP. Mock IdP stays test-only."""

    config: OidcClientConfig
    token_endpoint: str
    client_secret: str
    transport: httpx.BaseTransport | None = None
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if type(self.token_endpoint) is not str or not self.token_endpoint.startswith("https://"):
            raise OidcRejected("token endpoint must be https")
        if type(self.client_secret) is not str or len(self.client_secret) < 8:
            raise OidcRejected("signing key is missing")

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
        del now  # Token expiry is enforced by the IdP response and claim checks.
        if type(code) is not str or code.strip() == "":
            raise OidcRejected("authorization code was rejected")
        if type(code_verifier) is not str or code_verifier.strip() == "":
            raise OidcRejected("pkce was rejected")
        if type(redirect_uri) is not str or redirect_uri.strip() == "":
            raise OidcRejected("redirect_uri was rejected")
        if type(state) is not str or state.strip() == "":
            raise OidcRejected("state was rejected")
        body = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": self.config.client_id,
            "code_verifier": code_verifier,
            "state": state,
        }
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        try:
            with httpx.Client(
                transport=self.transport,
                timeout=self.timeout_seconds,
                follow_redirects=False,
                verify=True if self.transport is None else False,
            ) as client:
                response = client.post(self.token_endpoint, data=body, headers=headers)
        except httpx.HTTPError as exc:
            raise OidcRejected("token endpoint is unreachable") from exc
        if response.status_code >= 400:
            raise OidcRejected("authorization code was rejected")
        try:
            payload = response.json()
        except Exception as exc:
            raise OidcRejected("token response was rejected") from exc
        if type(payload) is not dict:
            raise OidcRejected("token response was rejected")
        claims_raw = payload.get("id_token_claims")
        signature = payload.get("id_token_signature")
        if presented_signature is not None:
            signature = presented_signature
        if type(claims_raw) is not dict or type(signature) is not str:
            raise OidcRejected("token response was rejected")
        try:
            claims = IdTokenClaims(
                issuer=str(claims_raw["issuer"]),
                subject=str(claims_raw["subject"]),
                audience=str(claims_raw["audience"]),
                nonce=str(claims_raw["nonce"]),
            )
        except (KeyError, TypeError) as exc:
            raise OidcRejected("token response was rejected") from exc
        if claims.issuer != self.config.issuer:
            raise OidcRejected("issuer was rejected")
        if claims.audience != self.config.audience:
            raise OidcRejected("audience was rejected")
        if type(claims.subject) is not str or claims.subject.strip() == "":
            raise OidcRejected("subject was rejected")
        if type(claims.nonce) is not str or claims.nonce.strip() == "":
            raise OidcRejected("nonce was rejected")
        verify_id_token_signature(claims, signature, self.client_secret)
        return claims


def mock_https_token_handler(
    idp: MockHttpsIdP,
    *,
    clock: datetime | None = None,
) -> Any:
    """httpx MockTransport handler that fronts MockHttpsIdP over the token endpoint."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method.upper() != "POST":
            return httpx.Response(405, json={"error": "method_not_allowed"})
        form = {key: values[-1] for key, values in parse_qs(request.content.decode("utf-8")).items()}
        try:
            claims = idp.exchange(
                code=str(form.get("code", "")),
                code_verifier=str(form.get("code_verifier", "")),
                redirect_uri=str(form.get("redirect_uri", "")),
                state=str(form.get("state", "")),
                now=clock,
            )
        except OidcRejected as exc:
            return httpx.Response(400, json={"error": str(exc)})
        signature = sign_id_token_claims(claims, idp.signing_key)
        return httpx.Response(
            200,
            json={
                "id_token_claims": {
                    "issuer": claims.issuer,
                    "subject": claims.subject,
                    "audience": claims.audience,
                    "nonce": claims.nonce,
                },
                "id_token_signature": signature,
            },
        )

    return handler


def _utc(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise OidcRejected("now must be timezone-aware")
    return now.astimezone(timezone.utc)
