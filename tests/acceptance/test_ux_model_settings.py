import asyncio
import sqlite3
import httpx
from ux_support import ux_app, session


def test_settings_explicit_keep_and_incomplete_replacement_are_atomic(ux_app):
    app, p, db = ux_app
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1') as c:
            h=await session(c,p)
            url=f'/ui/projects/{p}/settings'
            body={'expected_lock':0,'timeout_seconds':600,'roles':[{'role':'authoring','mode':'replace','endpoint':'https://model.example','model':'m','key':''}]}
            bad=await c.post(url,json=body,headers=h)
            assert bad.status_code==422
            assert 'key-authoring' in bad.json()['error']['fields']
            body['roles']=[{'role':'authoring','mode':'keep'}]
            kept=await c.post(url,json=body,headers={**h,'Idempotency-Key':'keep'})
            assert kept.status_code==201,kept.text
            assert kept.json()['lock_version']==1
            assert kept.json()['bindings']==[]
            page=await c.get(url)
            assert 'type="password"' in page.text and '녹화 AI' in page.text
            assert '일반 재생은 저장된 동작·코드' in page.text
    asyncio.run(run())
    with sqlite3.connect(db) as c:
        assert c.execute('SELECT count(*) FROM secret_refs').fetchone()[0]==0
        assert c.execute('SELECT count(*) FROM binding_revisions').fetchone()[0]==0


def test_stale_project_settings_roll_back_new_key_and_binding(ux_app, monkeypatch):
    import aiqa.security.secrets as secrets
    app,p,db=ux_app
    writes=[];discarded=[]
    monkeypatch.setattr(secrets,'_write_os',lambda ref,value:writes.append(ref))
    monkeypatch.setattr(secrets,'discard_os_secret',lambda ref:discarded.append(ref))
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1') as c:
            h=await session(c,p);url=f'/ui/projects/{p}/settings'
            first=await c.post(url,json={'expected_lock':0,'timeout_seconds':600,'roles':[]},headers=h)
            assert first.status_code==201
            stale=await c.post(url,json={'expected_lock':0,'timeout_seconds':500,'roles':[{'role':'authoring','mode':'replace','endpoint':'https://model.example','model':'test-model','key':'synthetic-only'}]},headers={**h,'Idempotency-Key':'stale-binding'})
            assert stale.status_code==409,stale.text
            assert 'synthetic-only' not in stale.text
    asyncio.run(run())
    with sqlite3.connect(db) as c:
        assert c.execute('SELECT count(*) FROM binding_revisions').fetchone()[0]==0
        assert c.execute('SELECT count(*) FROM secret_refs').fetchone()[0]==0
        assert c.execute('SELECT lock_version FROM project_settings').fetchone()[0]==1
    assert discarded==writes
