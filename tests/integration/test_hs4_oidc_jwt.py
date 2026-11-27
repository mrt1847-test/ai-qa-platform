"""Real RSA signatures, synthetic IdP HTTP, no external identity services."""
import base64
import json
import time
from datetime import datetime, timezone
from urllib.parse import parse_qs

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from aiqa.security.oidc import OidcClientConfig, OidcRejected, OperationalOidcClient, validate_id_token_claims


@pytest.fixture(scope='module')
def signing_keys():
    return [rsa.generate_private_key(public_exponent=65537, key_size=2048) for _ in range(2)]


def jwk(key, kid):
    return {**json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key())),
            'kid': kid, 'alg': 'RS256', 'use': 'sig'}


def provider(signing_keys, *, changes=None, algorithm='RS256', headers=None, forged_key=False,
             metadata_changes=None, oversized=False, token_endpoint='https://idp.example.test/token'):
    now = int(time.time())
    claims = {'iss': 'https://idp.example.test', 'sub': 'operator', 'aud': 'client',
              'nonce': 'expected-nonce', 'iat': now - 1, 'exp': now + 120}
    claims.update(changes or {})
    key = ('a-long-synthetic-hmac-secret-for-negative-test' if algorithm == 'HS256'
           else signing_keys[1 if forged_key else 0])
    token = jwt.encode(claims, key, algorithm=algorithm, headers={'kid': 'one', **(headers or {})})
    requests = []
    keys = [jwk(signing_keys[0], 'one')]
    def handler(request):
        requests.append(request)
        if request.url.path == '/.well-known/openid-configuration':
            return httpx.Response(200, json={'issuer': 'https://idp.example.test',
                'token_endpoint': token_endpoint, 'jwks_uri': 'https://idp.example.test/keys',
                'token_endpoint_auth_methods_supported': ['client_secret_post'],
                **(metadata_changes or {})})
        if request.url.path == '/keys':
            return httpx.Response(200, json={'keys': keys})
        if str(request.url) == token_endpoint:
            return httpx.Response(200, json={'id_token': token, 'access_token': 'unused',
                                            'padding': 'x' * 300000 if oversized else ''})
        pytest.fail('Unapproved OIDC network URL: ' + str(request.url))
    config = OidcClientConfig('https://idp.example.test', 'client', 'https://manage.test/callback', 'client')
    client = OperationalOidcClient(config, token_endpoint,
                                   'synthetic-client-secret', httpx.MockTransport(handler))
    return client, requests, keys


def exchange(client):
    return client.exchange(code='auth-code', code_verifier='pkce-secret',
                           redirect_uri=client.config.redirect_uri, state='state')


def test_standard_token_exchange_verifies_signature_and_authenticates_client(signing_keys):
    client, requests, _ = provider(signing_keys)
    claims = exchange(client)
    assert (claims.subject, claims.nonce) == ('operator', 'expected-nonce')
    posted = next(request for request in requests if request.method == 'POST')
    body = parse_qs(posted.content.decode())
    assert body['client_secret'] == ['synthetic-client-secret']
    assert body['code_verifier'] == ['pkce-secret']
    assert 'synthetic-client-secret' not in str(posted.url)
    exchange(client)
    assert len([request for request in requests if request.url.path == '/keys']) == 1


def test_operator_supplied_slashed_endpoints_are_preserved_and_exactly_verified(tmp_path, signing_keys):
    from aiqa.config import load_settings
    from aiqa.security.oidc import begin_authorization
    settings = load_settings({'AIQA_PROFILE': 'hosted', 'AIQA_RUNTIME_ROOT': str(tmp_path),
        'AIQA_DATABASE_BACKEND': 'sqlite', 'AIQA_PUBLIC_ORIGIN': 'https://manage.test',
        'AIQA_TRUSTED_PROXIES': '127.0.0.1', 'AIQA_OIDC_ISSUER': 'https://idp.example.test',
        'AIQA_OIDC_CLIENT_ID': 'client', 'AIQA_OIDC_AUDIENCE': 'client',
        'AIQA_OIDC_AUTHORIZE_ENDPOINT': 'https://idp.example.test/authorize/',
        'AIQA_OIDC_TOKEN_ENDPOINT': 'https://idp.example.test/token/'})
    assert settings.oidc.authorize_endpoint == 'https://idp.example.test/authorize/'
    assert settings.oidc.token_endpoint == 'https://idp.example.test/token/'
    client, requests, _ = provider(signing_keys, token_endpoint=settings.oidc.token_endpoint)
    assert begin_authorization(client.config, authorize_endpoint=settings.oidc.authorize_endpoint).authorize_url.startswith('https://idp.example.test/authorize/?')
    assert exchange(client).subject == 'operator'
    assert next(request.url.path for request in requests if request.method == 'POST') == '/token/'
    mismatched, _, _ = provider(signing_keys, token_endpoint=settings.oidc.token_endpoint,
                                metadata_changes={'token_endpoint': 'https://idp.example.test/token'})
    with pytest.raises(OidcRejected, match='token endpoint'):
        exchange(mismatched)


@pytest.mark.parametrize('changes', [
    {'iss': 'https://evil.test'}, {'aud': 'someone-else'}, {'exp': 1}, {'iat': 9999999999},
    {'sub': ''}, {'nonce': ''}, {'exp': None}, {'exp': True},
    {'aud': ['client', 'untrusted'], 'azp': 'client'}, {'azp': 'wrong-client'},
])
def test_invalid_verified_claims_are_refused(signing_keys, changes):
    client, _, _ = provider(signing_keys, changes=changes)
    with pytest.raises(OidcRejected):
        exchange(client)


@pytest.mark.parametrize('options', [
    {'algorithm': 'HS256'}, {'forged_key': True}, {'headers': {'jku': 'https://evil.test/keys'}},
    {'metadata_changes': {'issuer': 'https://evil.test'}},
    {'metadata_changes': {'jwks_uri': 'http://idp.example.test/keys'}},
    {'metadata_changes': {'token_endpoint': 'https://evil.test/token'}}, {'oversized': True},
])
def test_untrusted_algorithms_endpoints_and_large_payloads_are_refused(signing_keys, options):
    client, _, _ = provider(signing_keys, **options)
    with pytest.raises(OidcRejected):
        exchange(client)


def test_nonce_is_checked_against_login_transaction(signing_keys):
    client, _, _ = provider(signing_keys, changes={'nonce': 'attacker-nonce'})
    claims = exchange(client)
    with pytest.raises(OidcRejected, match='nonce'):
        validate_id_token_claims(claims, config=client.config, expected_nonce='expected-nonce')


def test_unknown_kid_refetches_once_then_rate_limits(signing_keys):
    client, requests, keys = provider(signing_keys, headers={'kid': 'unknown'})
    with pytest.raises(OidcRejected):
        exchange(client)
    before = len([r for r in requests if r.url.path == '/keys'])
    with pytest.raises(OidcRejected):
        exchange(client)
    assert len([r for r in requests if r.url.path == '/keys']) == before


def test_rotated_key_is_accepted_after_bounded_refresh(signing_keys, monkeypatch):
    client, requests, keys = provider(signing_keys, headers={'kid': 'rotated'})
    with pytest.raises(OidcRejected):
        exchange(client)
    keys[:] = [jwk(signing_keys[0], 'rotated')]
    clock = time.monotonic()
    monkeypatch.setattr('aiqa.security.oidc_jwt.time.monotonic', lambda: clock + 11)
    assert exchange(client).subject == 'operator'


def test_redirect_is_not_followed_and_error_does_not_echo_secret():
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(302, headers={'Location': 'https://evil.test/'}, text='secret-body')
    config = OidcClientConfig('https://idp.test', 'client', 'https://manage.test/cb', 'client')
    client = OperationalOidcClient(config, 'https://idp.test/token', 'client-secret', httpx.MockTransport(handler))
    with pytest.raises(OidcRejected) as caught:
        exchange(client)
    assert len(calls) == 1
    assert 'secret-body' not in str(caught.value)


@pytest.mark.parametrize('correct_nonce', [True, False])
def test_signed_oidc_http_callback_creates_session_only_for_bound_nonce(tmp_path, correct_nonce):
    import asyncio
    from aiqa.api.app import create_app
    from aiqa.config import load_settings
    from aiqa.hosted.bootstrap import bootstrap_first_admin
    from aiqa.security.oidc import MockHttpsIdP, mock_https_token_handler
    from aiqa.security.secrets import MemorySecretBackend, build_server_secret_resolver
    from aiqa.store.database import migrate_store
    from aiqa.store.models import ProjectCreate
    now = datetime.now(timezone.utc)
    settings = load_settings({'AIQA_PROFILE': 'hosted', 'AIQA_RUNTIME_ROOT': str(tmp_path),
        'AIQA_DATABASE_BACKEND': 'sqlite', 'AIQA_ARTIFACT_BACKEND': 'local',
        'AIQA_PUBLIC_ORIGIN': 'https://manage.test', 'AIQA_TRUSTED_PROXIES': '127.0.0.1',
        'AIQA_OIDC_ISSUER': 'https://idp.example.test', 'AIQA_OIDC_CLIENT_ID': 'client',
        'AIQA_OIDC_AUDIENCE': 'client', 'AIQA_OIDC_TOKEN_ENDPOINT': 'https://idp.example.test/token'})
    backend = MemorySecretBackend()
    build_server_secret_resolver(settings, backend=backend).store_oidc_client_secret('synthetic-client-secret')
    idp = MockHttpsIdP(issuer='https://idp.example.test', audience='client',
                       signing_key='synthetic-client-secret', require_signature=True)
    app = create_app(settings, secret_backend=backend,
                     oidc_token_transport=httpx.MockTransport(mock_https_token_handler(idp, clock=now)))
    store = app.state.open_store()
    migrate_store(store)
    identity = bootstrap_first_admin(store, issuer=idp.issuer, subject='operator',
                                     project=ProjectCreate('OIDC', 'oidc', '', 'android'))
    store.close()
    async def login():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=('127.0.0.1', 5000)),
                                     base_url='https://manage.test') as browser:
            headers = {'Origin': 'https://manage.test', 'X-Forwarded-Proto': 'https', 'Idempotency-Key': 'start'}
            started = await browser.post('/api/v1/auth/oidc/start', headers=headers,
                                          json={'project_id': identity['project_id']})
            assert started.status_code == 201, started.text
            state = started.json()['state']
            store = app.state.open_store()
            with store.transaction() as connection:
                nonce, challenge = connection.execute('SELECT nonce,code_challenge FROM oidc_login_states WHERE state=?', (state,)).fetchone()
            store.close()
            code = idp.issue_code(subject='operator', redirect_uri=app.state.oidc_config.redirect_uri,
                state=state, nonce=nonce if correct_nonce else 'wrong-nonce', code_challenge=challenge, now=now)
            response = await browser.get('/api/v1/auth/oidc/callback', params={'code': code, 'state': state}, headers=headers)
            assert response.status_code == (303 if correct_nonce else 401), response.text
            assert ('aiqa_session' in response.cookies) == correct_nonce
    asyncio.run(login())
