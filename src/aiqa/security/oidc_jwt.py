"""Bounded standard OIDC code exchange with pinned RS256/JWKS verification."""
from __future__ import annotations

import json
import math
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx

_MAX_JSON = 262144
_CACHE_SECONDS = 300
_REFRESH_COOLDOWN = 10


def https_url(value):
    try:
        parsed = urlsplit(value)
        return (type(value) is str and parsed.scheme == 'https' and bool(parsed.hostname)
                and not parsed.username and not parsed.password and not parsed.fragment)
    except (ValueError, TypeError):
        return False


def _json(client, method, url, **kwargs):
    from aiqa.security.oidc import OidcRejected
    try:
        with client.stream(method, url, **kwargs) as response:
            if response.status_code != 200:
                raise OidcRejected('OIDC endpoint response was rejected')
            data = bytearray()
            for chunk in response.iter_bytes():
                if len(data) + len(chunk) > _MAX_JSON:
                    raise OidcRejected('OIDC endpoint response was rejected')
                data.extend(chunk)
        value = json.loads(data)
        if type(value) is not dict:
            raise ValueError
        return value
    except (httpx.HTTPError, ValueError, TypeError, RecursionError):
        raise OidcRejected('OIDC endpoint response was rejected') from None


class VerifiedOidcExchange:
    """One issuer's bounded, locked cache. URLs come from approved discovery only."""
    def __init__(self, config, token_endpoint, client_secret, transport, timeout):
        self.config = config
        self.token_endpoint = token_endpoint
        self.client_secret = client_secret
        self.transport = transport
        self.timeout = timeout
        self._lock = threading.RLock()
        self._keys = {}
        self._jwks_uri = None
        self._expires = 0.0
        self._last_unknown_refresh = None

    def _refresh(self, client):
        from aiqa.security.oidc import OidcRejected
        metadata = _json(client, 'GET', self.config.issuer.rstrip('/') + '/.well-known/openid-configuration')
        if metadata.get('issuer') != self.config.issuer:
            raise OidcRejected('OIDC issuer was rejected')
        if metadata.get('token_endpoint') != self.token_endpoint:
            raise OidcRejected('OIDC token endpoint was rejected')
        uri = metadata.get('jwks_uri')
        if not https_url(uri):
            raise OidcRejected('OIDC JWKS endpoint was rejected')
        algorithms = metadata.get('id_token_signing_alg_values_supported', ['RS256'])
        methods = metadata.get('token_endpoint_auth_methods_supported', ['client_secret_basic'])
        if type(algorithms) is not list or 'RS256' not in algorithms:
            raise OidcRejected('OIDC signing algorithm was rejected')
        # This implementation explicitly supports client_secret_post. Register
        # that method at the IdP; never infer it from the incoming token.
        if type(methods) is not list or 'client_secret_post' not in methods:
            raise OidcRejected('OIDC client authentication method was rejected')
        body = _json(client, 'GET', uri)
        keys = body.get('keys')
        if type(keys) is not list or not 1 <= len(keys) <= 32:
            raise OidcRejected('OIDC JWKS was rejected')
        selected = {}
        for key in keys:
            if type(key) is not dict:
                raise OidcRejected('OIDC JWKS was rejected')
            kid = key.get('kid')
            if (key.get('kty') != 'RSA' or key.get('use', 'sig') != 'sig'
                    or key.get('alg', 'RS256') != 'RS256'
                    or key.get('key_ops', ['verify']) != ['verify']):
                continue
            if type(kid) is not str or not 1 <= len(kid) <= 256 or kid in selected:
                raise OidcRejected('OIDC JWKS was rejected')
            selected[kid] = key
        self._keys, self._jwks_uri = selected, uri
        self._expires = time.monotonic() + _CACHE_SECONDS

    def exchange(self, *, code, code_verifier, redirect_uri, state, now):
        from aiqa.security.oidc import IdTokenClaims, OidcRejected
        try:
            import jwt
        except ImportError:
            raise OidcRejected('OIDC JWT runtime is unavailable') from None
        with httpx.Client(transport=self.transport, timeout=self.timeout,
                          follow_redirects=False, verify=True, trust_env=False) as client:
            with self._lock:
                if time.monotonic() >= self._expires:
                    self._refresh(client)
            payload = _json(client, 'POST', self.token_endpoint,
                            data={'grant_type': 'authorization_code', 'code': code,
                                  'redirect_uri': redirect_uri, 'client_id': self.config.client_id,
                                  'client_secret': self.client_secret, 'code_verifier': code_verifier},
                            headers={'Accept': 'application/json'})
            token = payload.get('id_token')
            if type(token) is not str or not 1 <= len(token) <= 65536:
                raise OidcRejected('OIDC ID token was rejected')
            try:
                header = jwt.get_unverified_header(token)
            except (jwt.PyJWTError, ValueError, TypeError):
                raise OidcRejected('OIDC token header was rejected') from None
            kid = header.get('kid')
            if (header.get('alg') != 'RS256' or type(kid) is not str or not 1 <= len(kid) <= 256
                    or any(name in header for name in ('jku', 'jwk', 'x5u', 'crit'))):
                raise OidcRejected('OIDC token header was rejected')
            with self._lock:
                if kid not in self._keys:
                    instant = time.monotonic()
                    if self._last_unknown_refresh is None or instant - self._last_unknown_refresh >= _REFRESH_COOLDOWN:
                        self._last_unknown_refresh = instant
                        self._refresh(client)
                jwk = self._keys.get(kid)
            if jwk is None:
                raise OidcRejected('OIDC signing key was rejected')
            try:
                key = jwt.PyJWK.from_dict(jwk, algorithm='RS256').key
                if key.key_size < 2048:
                    raise ValueError
                claims = jwt.decode(token, key, algorithms=['RS256'],
                    issuer=self.config.issuer, audience=self.config.audience,
                    options={'require': ['iss', 'sub', 'aud', 'exp', 'iat', 'nonce'],
                             'verify_exp': False, 'verify_iat': False, 'verify_nbf': False})
            except (jwt.PyJWTError, ValueError, TypeError, AttributeError):
                raise OidcRejected('OIDC token signature or claims were rejected') from None
            stamp = now.timestamp()
            for name in ('exp', 'iat', 'nbf'):
                if name not in claims and name == 'nbf':
                    continue
                value = claims.get(name)
                if type(value) not in (int, float) or not math.isfinite(value):
                    raise OidcRejected('OIDC token time was rejected')
                if (name == 'exp' and value <= stamp) or (name != 'exp' and value > stamp):
                    raise OidcRejected('OIDC token time was rejected')
            audience = claims.get('aud')
            audience = [audience] if type(audience) is str else audience
            if (type(audience) is not list or self.config.client_id not in audience
                    or any(value not in {self.config.client_id, self.config.audience} for value in audience)
                    or (len(audience) > 1 and claims.get('azp') != self.config.client_id)
                    or ('azp' in claims and claims['azp'] != self.config.client_id)):
                raise OidcRejected('OIDC token audience was rejected')
            if any(type(claims.get(name)) is not str or not claims[name].strip() for name in ('sub', 'nonce')):
                raise OidcRejected('OIDC token subject or nonce was rejected')
            try:
                expiry = datetime.fromtimestamp(claims['exp'], timezone.utc).isoformat()
            except (ValueError, OverflowError, OSError):
                raise OidcRejected('OIDC token time was rejected') from None
            return IdTokenClaims(claims['iss'], claims['sub'], self.config.audience, claims['nonce'], expiry)
