import asyncio
import json
import sqlite3
from uuid import uuid4
import httpx
from ux_support import ux_app,session
from test_w16 import _resource,_binding,_draft


def test_rerecord_wizard_keeps_base_and_stores_separate_candidate(ux_app):
    app,p,db=ux_app
    _resource(db,p);_binding(db,p,str(uuid4()))
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1') as c:
            h=await session(c,p)
            created=await c.post(f'/api/v1/projects/{p}/cases',json={'name':'재녹화 주문'},headers=h);cid=created.json()['case_id']
            payload=_draft('web','https://shop.example','')
            base=await c.post(f'/api/v1/projects/{p}/cases/{cid}/versions',json=payload,headers={**h,'Idempotency-Key':'base'})
            bid=base.json()['id']
            page=await c.get(f'/ui/projects/{p}/recordings/wizard',params={'case':cid,'base':bid})
            assert page.status_code==200 and 'name="rerecord_reason"' in page.text
            wrong=await c.get(f'/ui/projects/{p}/recordings/wizard',params={'case':cid,'base':str(uuid4())})
            assert wrong.status_code==404
            with sqlite3.connect(db) as con: original=con.execute('SELECT definition_json,settings_json FROM case_versions WHERE version_id=?',(bid,)).fetchone()
            payload.update(parent_version_id=bid,base_version_id=bid,expected_head=bid)
            payload['settings'].update(rerecord_base_version_id=bid,rerecord_reason='로그인 경로 갱신',rerecord_confirmed=True)
            candidate=await c.post(f'/api/v1/projects/{p}/cases/{cid}/versions',json=payload,headers={**h,'Idempotency-Key':'candidate'})
            assert candidate.status_code==201,candidate.text
            v=candidate.json()
            with sqlite3.connect(db) as con: assert con.execute('SELECT base_version_id FROM case_versions WHERE version_id=?',(v['id'],)).fetchone()[0]==bid
            request={'case_id':cid,'input_case_version_id':v['id'],'input_version_hash':v['content_hash'],'resource_id':'key-w1605'}
            started=await c.post(f'/api/v1/projects/{p}/recordings',json=request,headers={**h,'Idempotency-Key':'rerecord-start'})
            assert started.status_code==201,started.text
            with sqlite3.connect(db) as con:
                assert con.execute('SELECT base_case_version_id FROM recordings WHERE recording_id=?',(started.json()['recording_id'],)).fetchone()[0]==bid
                assert con.execute('SELECT definition_json,settings_json FROM case_versions WHERE version_id=?',(bid,)).fetchone()==original
                assert con.execute('SELECT count(*) FROM reviews').fetchone()[0]==0
    asyncio.run(run())
