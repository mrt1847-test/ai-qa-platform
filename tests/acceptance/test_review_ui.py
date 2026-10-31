"""Adversarial product-entry and browser-mutation contract regressions."""
import asyncio
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from aiqa.api.app import create_app
from aiqa.config import load_settings
from aiqa.domain.projects import bind_store, create_project
from aiqa.store.database import StorageConfig, migrate_store, open_store
from aiqa.store.models import Actor, ProjectCreate


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def ui(tmp_path):
    app = create_app(load_settings({'AIQA_RUNTIME_ROOT': str(tmp_path / 'runtime')}))
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(Actor(uuid4(), None, True), ProjectCreate('Review', 'review', '', 'web'))
    cookie, csrf, actor_id = str(uuid4()), 'fixture-csrf', str(uuid4())
    with store.transaction() as con:
        con.execute('INSERT INTO browser_sessions(session_id,origin,csrf_hash,actor_id,project_scope,is_local_owner,expires_at) VALUES (?,?,?,?,?,1,?)', (cookie, 'http://127.0.0.1', hashlib.sha256(csrf.encode()).hexdigest(), actor_id, str(project.project_id), (datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()))
    store.close()
    return SimpleNamespace(app=app, project=str(project.project_id), cookie=cookie, headers={'Origin':'http://127.0.0.1','X-CSRF-Token':csrf,'Idempotency-Key':'fixture'}, database=tmp_path/'runtime'/'db'/'aiqa.sqlite')


def client(ui):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=ui.app), base_url='http://127.0.0.1', cookies={'aiqa_session':ui.cookie})


async def seed(ui, c):
    result = await c.post(f'/api/v1/projects/{ui.project}/cases', json={'name':'Review', 'tc_reference':None}, headers=ui.headers)
    assert result.status_code == 201, result.text
    case = result.json()['case_id']
    definition = {'raw_text':'Pay', 'objective':'Pay', 'preconditions':['signed in','cart'], 'variables':{'amount':100}, 'secret_refs':{'login':{'project_id':ui.project,'ref_id':str(uuid4()),'revision':2}}, 'steps':[{'id':'s1','instruction':'pay','point':[12,34],'expected':[{'id':'c1','kind':'text','expected':'paid'},{'id':'c2','kind':'text','expected':'receipt'}]},{'id':'s2','instruction':'return','expected':[],'point':None}], 'final_expected':[{'id':'f1','kind':'text','expected':'done'}], 'path_policy':{'must_use':['checkout'],'forbidden':['delete']}}
    body={'definition':definition,'settings':{'target_kind':'android','android_package':'com.example.review'},'recorded_steps':[{'action_id':'a1','kind':'tap','point':[12,34]}],'expected_head':None,'reason':'draft'}
    saved=await c.post(f'/api/v1/projects/{ui.project}/cases/{case}/versions',json=body,headers={**ui.headers,'Idempotency-Key':'version'})
    assert saved.status_code == 201, saved.text
    return case,saved.json(),body


def test_real_factory_registers_catalog_without_opening_store(tmp_path):
    app=create_app(load_settings({'AIQA_RUNTIME_ROOT':str(tmp_path/'lazy')}))
    assert not (tmp_path/'lazy').exists()
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1') as c:
            assert (await c.get('/api/v1/health')).status_code==200
            assert not (tmp_path/'lazy').exists()
            assert (await c.get('/api/v1/projects')).status_code==200
            assert (await c.get('/ui/projects')).status_code==200
    run(exercise())


def test_definition_roundtrip_rehydrates_complete_snapshot(ui):
    async def exercise():
        async with client(ui) as c:
            case,version,body=await seed(ui,c)
            response=await c.get(f'/ui/projects/{ui.project}/cases/{case}/definition')
            match=re.search(r'<script id="definition-snapshot" type="application/json">(.*?)</script>',response.text,re.S)
            assert match, 'editor must rehydrate complete execution snapshot'
            snapshot=json.loads(match[1])
            assert snapshot['definition']==body['definition']
            assert snapshot['settings']['android_package']=='com.example.review'
            assert snapshot['recorded_steps']==body['recorded_steps']
            snapshot['definition']['objective']='Updated only'
            snapshot['expected_head']=version['id']
            saved=await c.post(f'/ui/projects/{ui.project}/cases/{case}/definition',json=snapshot,headers={**ui.headers,'Idempotency-Key':'roundtrip'})
            assert saved.status_code==201,saved.text
            with sqlite3.connect(ui.database) as con:
                row=con.execute('SELECT definition_json,settings_json,recorded_steps_json FROM case_versions WHERE version_id=?',(saved.json()['id'],)).fetchone()
            expected={**body['definition'],'objective':'Updated only'}
            assert json.loads(row[0])==expected
            assert json.loads(row[1])==snapshot['settings']
            assert json.loads(row[2])==body['recorded_steps']
    run(exercise())


def test_browser_mutations_reject_foreign_origin_and_missing_csrf(ui):
    async def exercise():
        async with client(ui) as c:
            case,version,body=await seed(ui,c)
            mutations=[(f'/ui/projects/{ui.project}/cases/{case}/definition',{**body,'expected_head':version['id']}),(f'/ui/projects/{ui.project}/cases/{case}/steps',{'action':'add','instruction':'x','expected_head':version['id']}),(f'/ui/projects/{ui.project}/cases/{case}/settings',{'expected_head':version['id'],'target_kind':'web'}),(f'/ui/projects/{ui.project}/cases/bulk',{'items':[{'case_id':case,'action':'clone','name':'Copy','expected_revision':1}]}),(f'/ui/projects/{ui.project}/settings',{'timeout_seconds':12})]
            for index,(path,body) in enumerate(mutations):
                for headers in ({'Origin':'https://foreign.example'},{'Origin':'http://127.0.0.1'}):
                    response=await c.post(path,json=body,headers={**headers,'Idempotency-Key':str(index)})
                    assert response.status_code==403,(path,response.text)
    run(exercise())


@pytest.mark.parametrize('timeout',[0,-123,601,'bad',1.5,True])
def test_ui_settings_reject_invalid_timeout_and_preserve_input(ui,timeout):
    async def exercise():
        async with client(ui) as c:
            response=await c.post(f'/ui/projects/{ui.project}/settings',json={'expected_lock':0,'timeout_seconds':timeout},headers=ui.headers)
            assert response.status_code==422,response.text
            assert response.json()['submitted']['timeout_seconds']==timeout
    run(exercise())


def test_mutation_receipt_survives_reconnect_and_detects_changed_body(ui):
    async def exercise():
        async with client(ui) as c:
            case,_,_=await seed(ui,c)
            body={'items':[{'case_id':case,'action':'clone','name':'Copy','expected_revision':1}]}
            path=f'/ui/projects/{ui.project}/cases/bulk'
            first=await c.post(path,json=body,headers={**ui.headers,'Idempotency-Key':'clone-once'})
            assert first.status_code==200,first.text
        # A new app instance and a new connection must read the durable receipt.
        ui.app=create_app(ui.app.state.settings)
        async with client(ui) as c:
            repeated=await c.post(path,json=body,headers={**ui.headers,'Idempotency-Key':'clone-once'})
            assert repeated.json()==first.json()
            changed=await c.post(path,json={'items':[]},headers={**ui.headers,'Idempotency-Key':'clone-once'})
            assert changed.status_code==409,changed.text
        with sqlite3.connect(ui.database) as con:
            assert con.execute('SELECT count(*) FROM automation_cases WHERE name=?',('Copy',)).fetchone()[0]==1
    run(exercise())


def test_tc_buttons_have_explicit_operation_targets(ui):
    async def exercise():
        async with client(ui) as c:
            case,version,_=await seed(ui,c)
            created=await c.post(f'/api/v1/projects/{ui.project}/tcs',json={'name':'TC','body':{'raw_text':'TC','steps':[]},'reason':'draft'},headers={**ui.headers,'Idempotency-Key':'tc'})
            assert created.status_code==201,created.text
            response=await c.get(f'/ui/projects/{ui.project}/tcs?case_id={case}')
            assert f'data-tc="{created.json()["tc_id"]}"' in response.text
            assert 'data-action="clone"' in response.text
            assert 'data-action="archive"' in response.text
            assert 'data-action="link"' in response.text
            assert 'data-action="unlink"' in response.text
            assert '/static/tcs.js' in response.text
    run(exercise())


def test_receipt_failure_rolls_back_business_write(ui):
    async def prepare():
        async with client(ui) as c:
            case,_,_=await seed(ui,c)
            return case
    case=run(prepare())
    with sqlite3.connect(ui.database) as con:
        con.execute("CREATE TRIGGER fixture_receipt_failure BEFORE INSERT ON browser_mutation_receipts BEGIN SELECT RAISE(ABORT,'fixture receipt failure'); END")
    async def fail():
        async with client(ui) as c:
            with pytest.raises(sqlite3.IntegrityError,match='fixture receipt failure'):
                await c.post(f'/ui/projects/{ui.project}/cases/bulk',json={'items':[{'case_id':case,'action':'clone','name':'Atomic copy','expected_revision':1}]},headers={**ui.headers,'Idempotency-Key':'atomic-copy'})
    run(fail())
    with sqlite3.connect(ui.database) as con:
        assert con.execute('SELECT count(*) FROM automation_cases WHERE name=?',('Atomic copy',)).fetchone()[0]==0
        assert con.execute('SELECT count(*) FROM browser_mutation_receipts WHERE request_key=?',('atomic-copy',)).fetchone()[0]==0


def test_concurrent_same_key_requests_share_one_committed_receipt(ui):
    from concurrent.futures import ThreadPoolExecutor
    async def prepare():
        async with client(ui) as c:
            case,_,_=await seed(ui,c)
            return case
    case=run(prepare())
    body={'items':[{'case_id':case,'action':'clone','name':'Concurrent copy','expected_revision':1}]}
    def send():
        async def request():
            async with client(ui) as c:
                response=await c.post(f'/ui/projects/{ui.project}/cases/bulk',json=body,headers={**ui.headers,'Idempotency-Key':'concurrent-copy'})
                assert response.status_code==200,response.text
                return response.json()
        return run(request())
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses=list(executor.map(lambda _:send(),range(2)))
    assert responses[0]==responses[1]
    with sqlite3.connect(ui.database) as con:
        assert con.execute('SELECT count(*) FROM automation_cases WHERE name=?',('Concurrent copy',)).fetchone()[0]==1
        assert con.execute('SELECT count(*) FROM browser_mutation_receipts WHERE request_key=?',('concurrent-copy',)).fetchone()[0]==1


def test_only_first_project_can_use_initial_local_owner_bootstrap(tmp_path):
    app=create_app(load_settings({'AIQA_RUNTIME_ROOT':str(tmp_path/'runtime')}))
    body={'name':'First','key':'first','description':'','target':'web','actor':{'actor_id':str(uuid4()),'project_scope':None,'is_local_owner':True}}
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1') as c:
            missing=await c.post('/api/v1/projects',json=body,headers={'Idempotency-Key':'first'})
            foreign=await c.post('/api/v1/projects',json=body,headers={'Origin':'https://foreign.example','Idempotency-Key':'first'})
            assert missing.status_code==foreign.status_code==403
            headers={'Origin':'http://127.0.0.1','Idempotency-Key':'first'}
            first=await c.post('/api/v1/projects',json=body,headers=headers)
            assert first.status_code==201,first.text
            retry=await c.post('/api/v1/projects',json=body,headers=headers)
            assert retry.json()==first.json()
            changed=await c.post('/api/v1/projects',json={**body,'key':'second'},headers=headers)
            assert changed.status_code==409
            later=await c.post('/api/v1/projects',json={**body,'key':'second'},headers={**headers,'Idempotency-Key':'second'})
            assert later.status_code==401
    run(exercise())


def test_tc_operations_detect_stale_ui_revision(ui):
    async def exercise():
        async with client(ui) as c:
            case,_,_=await seed(ui,c)
            created=await c.post(f'/api/v1/projects/{ui.project}/tcs',json={'name':'TC','body':{'raw_text':'TC','steps':[]},'reason':'draft'},headers={**ui.headers,'Idempotency-Key':'tc'})
            tc=created.json()
            for action in ('clone','archive'):
                response=await c.post(f'/api/v1/projects/{ui.project}/tcs/{tc["tc_id"]}/{action}',json={'expected_revision':999},headers={**ui.headers,'Idempotency-Key':action})
                assert response.status_code==409,response.text
            response=await c.put(f'/api/v1/projects/{ui.project}/cases/{case}/tc-reference',json={'tc_version_id':tc['id'],'expected_revision':999},headers={**ui.headers,'Idempotency-Key':'link-stale'})
            assert response.status_code==409,response.text
        with sqlite3.connect(ui.database) as con:
            assert con.execute('SELECT count(*) FROM test_cases').fetchone()[0]==1
            assert con.execute('SELECT archived_at FROM test_cases').fetchone()[0] is None
            assert con.execute('SELECT tc_reference FROM automation_cases WHERE case_id=?',(case,)).fetchone()[0] is None
    run(exercise())


def test_csrf_read_is_read_only_and_preserves_other_tabs(ui):
    async def exercise():
        async with client(ui) as c:
            c.cookies.set('aiqa_csrf', ui.headers['X-CSRF-Token'])
            with sqlite3.connect(ui.database) as con:
                before = con.execute('SELECT csrf_hash FROM browser_sessions WHERE session_id=?', (ui.cookie,)).fetchone()[0]
            response = await c.get('/api/v1/session/csrf', headers={'Origin':'http://127.0.0.1'})
            assert response.status_code == 200
            assert response.json()['csrf_token'] == ui.headers['X-CSRF-Token']
            with sqlite3.connect(ui.database) as con:
                assert con.execute('SELECT csrf_hash FROM browser_sessions WHERE session_id=?', (ui.cookie,)).fetchone()[0] == before
    run(exercise())


def test_local_owner_actor_is_stable_across_session_bootstrap(ui):
    async def exercise():
        actors = []
        async with client(ui) as c:
            for index in range(2):
                headers = {'Origin':'http://127.0.0.1','Idempotency-Key':f'nonce-{index}'}
                nonce = await c.post('/api/v1/session/nonces', json={'origin':'http://127.0.0.1','project_id':ui.project}, headers=headers)
                created = await c.post('/api/v1/session/bootstrap',json={'nonce':nonce.json()['nonce']},headers=headers)
                assert created.status_code == 201
                with sqlite3.connect(ui.database) as con:
                    actors.append(con.execute('SELECT actor_id FROM browser_sessions WHERE session_id=?',(created.json()['session_id'],)).fetchone()[0])
        assert actors[0] == actors[1]
    run(exercise())


def test_receipt_key_expires_after_seven_days(ui):
    async def exercise():
        async with client(ui) as c:
            case, _, _ = await seed(ui, c)
            body = {'items':[{'case_id':case,'action':'clone','name':'Expired-key copy','expected_revision':1}]}
            headers = {**ui.headers,'Idempotency-Key':'expired-copy'}
            first = await c.post(f'/ui/projects/{ui.project}/cases/bulk',json=body,headers=headers)
            assert first.status_code == 200
            with sqlite3.connect(ui.database) as con:
                con.execute('UPDATE browser_mutation_receipts SET created_at=? WHERE request_key=?',((datetime.now(timezone.utc)-timedelta(days=8)).isoformat(),'expired-copy'))
            second = await c.post(f'/ui/projects/{ui.project}/cases/bulk',json=body,headers=headers)
            assert second.status_code == 200
            assert first.json() != second.json()
    run(exercise())


def test_receipt_fingerprint_is_keyed_and_key_is_user_protected(ui):
    from aiqa.security.receipt_digest import protected_body_digest
    marker = b'synthetic-sensitive-request'
    with sqlite3.connect(ui.database) as con:
        first = protected_body_digest(con, marker)
        envelope = con.execute('SELECT protected_key FROM browser_receipt_key').fetchone()[0]
        assert first.startswith('hmac-sha256:')
        assert first != 'hmac-sha256:' + hashlib.sha256(marker).hexdigest()
        assert marker not in envelope
        assert len(envelope) > 32
    with sqlite3.connect(ui.database) as con:
        assert protected_body_digest(con, marker) == first
        assert protected_body_digest(con, marker + b'-changed') != first


def test_secret_creation_replay_and_rollback_do_not_duplicate_external_writes(ui, monkeypatch):
    import aiqa.security.secrets as secrets_store
    writes, discarded = [], []
    monkeypatch.setattr(secrets_store, '_write_os', lambda ref, value: writes.append(ref))
    monkeypatch.setattr(secrets_store, 'discard_os_secret', lambda ref: discarded.append(ref))
    async def exercise():
        async with client(ui) as c:
            path = f'/api/v1/projects/{ui.project}/secret-refs'
            body = {'name':'Review key','value':'synthetic-only-key'}
            headers = {**ui.headers, 'Idempotency-Key':'secret-create'}
            first = await c.post(path, json=body, headers=headers)
            repeated = await c.post(path, json=body, headers=headers)
            changed = await c.post(path, json={**body,'value':'synthetic-other-key'}, headers=headers)
            assert first.status_code == 201 and repeated.status_code == 200
            assert first.json() == repeated.json()
            assert changed.status_code == 409
            assert len(writes) == 1
            with sqlite3.connect(ui.database) as con:
                assert con.execute('SELECT count(*) FROM secret_refs').fetchone()[0] == 1
                assert con.execute('SELECT body_hash FROM browser_mutation_receipts WHERE request_key=?', ('secret-create',)).fetchone()[0].startswith('hmac-sha256:')
                con.execute("CREATE TRIGGER fixture_receipt_failure BEFORE INSERT ON browser_mutation_receipts BEGIN SELECT RAISE(ABORT,'fixture failure'); END")
            with pytest.raises(sqlite3.IntegrityError):
                await c.post(path, json=body, headers={**headers,'Idempotency-Key':'secret-failure'})
            assert len(writes) == 2 and discarded == [writes[1]]
            with sqlite3.connect(ui.database) as con:
                assert con.execute('SELECT count(*) FROM secret_refs').fetchone()[0] == 1
    run(exercise())
