"""OIDC browser correlation and non-blocking, committed state reservation."""
import asyncio
from datetime import datetime, timezone
import threading
from uuid import UUID, uuid4

import httpx
import pytest

COOKIE = '__Host-aiqa_oidc_state'
HEADERS = {'Origin': 'https://manage.test', 'X-Forwarded-Proto': 'https', 'Idempotency-Key': 'fixture'}


def fixture_app(root):
    from aiqa.api.app import create_app
    from aiqa.api.auth import bound_auth_store, enroll_worker
    from aiqa.config import load_settings
    from aiqa.hosted.bootstrap import bootstrap_first_admin
    from aiqa.security.oidc import FixtureIdP
    from aiqa.security.secrets import MemorySecretBackend, build_server_secret_resolver
    from aiqa.store.database import migrate_store
    from aiqa.store.models import Actor, ProjectCreate
    settings = load_settings({'AIQA_PROFILE': 'hosted', 'AIQA_RUNTIME_ROOT': str(root),
        'AIQA_DATABASE_BACKEND': 'sqlite', 'AIQA_ARTIFACT_BACKEND': 'local',
        'AIQA_PUBLIC_ORIGIN': 'https://manage.test', 'AIQA_TRUSTED_PROXIES': '127.0.0.1',
        'AIQA_OIDC_ISSUER': 'https://idp.example.test', 'AIQA_OIDC_CLIENT_ID': 'client',
        'AIQA_OIDC_AUDIENCE': 'client'})
    backend = MemorySecretBackend()
    build_server_secret_resolver(settings, backend=backend).store_oidc_client_secret('synthetic-client-secret')
    idp = FixtureIdP(audience='client')
    app = create_app(settings, secret_backend=backend, oidc_idp=idp)
    store = app.state.open_store()
    migrate_store(store)
    identity = bootstrap_first_admin(store, issuer=idp.issuer, subject='operator',
                                     project=ProjectCreate('OIDC', 'oidc', '', 'android'))
    with bound_auth_store(store):
        token = enroll_worker(Actor(UUID(identity['actor_id']), UUID(identity['project_id']), False),
                              str(uuid4()), 'recording')
    store.close()
    return app, idp, identity, token


async def start(browser, app, idp, identity):
    response = await browser.post('/api/v1/auth/oidc/start', headers=HEADERS,
                                  json={'project_id': identity['project_id']})
    assert response.status_code == 201, response.text
    state = response.json()['state']
    store = app.state.open_store()
    with store.transaction() as connection:
        nonce, challenge = connection.execute('SELECT nonce,code_challenge FROM oidc_login_states WHERE state=?', (state,)).fetchone()
    store.close()
    code = idp.issue_code(subject='operator', redirect_uri=app.state.oidc_config.redirect_uri,
                         state=state, nonce=nonce, code_challenge=challenge)
    return response, {'code': code, 'state': state}


async def callback(browser, method, data):
    options = {'params' if method == 'GET' else 'json': data}
    return await browser.request(method, '/api/v1/auth/oidc/callback', headers=HEADERS, **options)


@pytest.mark.parametrize('method', ['GET', 'POST'])
def test_oidc_state_code_copy_cannot_log_another_browser_in(tmp_path, method):
    app, idp, identity, _ = fixture_app(tmp_path)
    async def scenario():
        transport = httpx.ASGITransport(app=app, client=('127.0.0.1', 5000))
        async with httpx.AsyncClient(transport=transport, base_url='https://manage.test') as initiator, \
                   httpx.AsyncClient(transport=transport, base_url='https://manage.test') as other:
            began, data = await start(initiator, app, idp, identity)
            missing = await callback(other, method, data)
            assert missing.status_code == 401, missing.text
            await start(other, app, idp, identity)
            copied = await callback(other, method, data)
            assert copied.status_code == 401, copied.text
            assert COOKIE not in other.cookies
            assert 'Max-Age=0' in copied.headers.get('set-cookie', '')
            cookie_header = began.headers['set-cookie']
            assert 'HttpOnly' in cookie_header and 'Secure' in cookie_header and 'SameSite=lax' in cookie_header
            assert 'Max-Age=600' in cookie_header and 'Path=/' in cookie_header
            assert len(initiator.cookies[COOKIE]) >= 32
            success = await callback(initiator, method, data)
            assert success.status_code == (303 if method == 'GET' else 201), success.text
            assert COOKIE not in initiator.cookies
            initiator.cookies.set(COOKIE, data['state'], domain='manage.test', path='/')
            repeated = await callback(initiator, method, data)
            assert repeated.status_code == 401
            assert COOKIE not in initiator.cookies
    asyncio.run(scenario())


def test_slow_oidc_exchange_releases_event_loop_and_writer_for_worker_heartbeat(tmp_path):
    app, idp, identity, token = fixture_app(tmp_path)
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    original_exchange = idp.exchange
    def slow_exchange(**kwargs):
        entered.set()
        release.wait(timeout=1.5)
        try:
            return original_exchange(**kwargs)
        finally:
            finished.set()
    idp.exchange = slow_exchange
    async def scenario():
        transport = httpx.ASGITransport(app=app, client=('127.0.0.1', 5000))
        async with httpx.AsyncClient(transport=transport, base_url='https://manage.test') as browser:
            _, data = await start(browser, app, idp, identity)
            pending = asyncio.create_task(callback(browser, 'GET', data))
            try:
                while not entered.is_set():
                    await asyncio.sleep(0.001)
                assert not finished.is_set(), 'IdP blocked the event loop before heartbeat could run'
                def independent_writer():
                    store = app.state.open_store()
                    try:
                        with store.transaction() as connection:
                            used = connection.execute('SELECT used_at FROM oidc_login_states WHERE state=?', (data['state'],)).fetchone()[0]
                            assert used is not None, 'reservation must commit before exchange'
                            connection.execute('UPDATE projects SET name=? WHERE project_id=?', ('OIDC updated', identity['project_id']))
                    finally:
                        store.close()
                await asyncio.wait_for(asyncio.to_thread(independent_writer), timeout=0.8)
                heartbeat = await asyncio.wait_for(browser.post('/api/v1/worker/heartbeats',
                    headers={**HEADERS, 'Authorization': 'Bearer ' + token}, json={'boot_id': 'oidc-slow-idp'}), timeout=0.8)
                assert heartbeat.status_code == 200, heartbeat.text
                assert not finished.is_set()
                reused = await callback(browser, 'GET', data)
                assert reused.status_code == 401
                assert not finished.is_set()
            finally:
                release.set()
                response = await pending
            assert response.status_code == 303, response.text
    asyncio.run(scenario())


@pytest.mark.parametrize('change', ['nonce', 'project', 'membership', 'bad-exchange'])
def test_oidc_finalization_rechecks_state_and_membership_after_exchange(tmp_path, change):
    from aiqa.domain.projects import revoke_membership
    from aiqa.security.oidc import OidcRejected
    from aiqa.store.models import Transaction
    app, idp, identity, _ = fixture_app(tmp_path)
    original_exchange = idp.exchange
    def changing_exchange(**kwargs):
        if change == 'bad-exchange':
            raise OidcRejected('synthetic exchange failure')
        claims = original_exchange(**kwargs)
        store = app.state.open_store()
        try:
            with store.transaction() as connection:
                if change == 'membership':
                    revoke_membership(Transaction(connection), UUID(identity['project_id']), UUID(identity['actor_id']))
                elif change == 'nonce':
                    connection.execute('UPDATE oidc_login_states SET nonce=? WHERE state=?', ('changed', kwargs['state']))
                else:
                    connection.execute('UPDATE oidc_login_states SET project_id=? WHERE state=?', (str(uuid4()), kwargs['state']))
        finally:
            store.close()
        return claims
    idp.exchange = changing_exchange
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=('127.0.0.1', 5000)),
                                     base_url='https://manage.test') as browser:
            _, data = await start(browser, app, idp, identity)
            response = await callback(browser, 'GET', data)
            assert response.status_code == (403 if change == 'membership' else 401), response.text
            assert COOKIE not in browser.cookies
            store = app.state.open_store()
            try:
                with store.transaction() as connection:
                    assert connection.execute('SELECT used_at FROM oidc_login_states WHERE state=?', (data['state'],)).fetchone()[0] is not None
                    assert connection.execute('SELECT COUNT(*) FROM browser_sessions').fetchone()[0] == 0
                    assert connection.execute('SELECT COUNT(*) FROM oidc_identities').fetchone()[0] == 1
            finally:
                store.close()
    asyncio.run(scenario())
