import asyncio
import sqlite3
from uuid import uuid4
import httpx
from ux_support import ux_app,session

def test_saved_recording_draft_has_read_only_preflight_without_job_creation(ux_app):
    app,p,db=ux_app
    store=app.state.open_store();rid=str(uuid4());c=store._connection
    c.execute("INSERT INTO worker_enrollments(enrollment_id,worker_id,project_id,created_at) VALUES(?,?,?,'2026-11-01')",(str(uuid4()),'ux-worker',p))
    c.execute("INSERT INTO physical_resource_keys(physical_key_id,worker_id,native_id) VALUES(?,'ux-worker',?)",(rid,rid))
    c.execute("INSERT INTO resource_aliases(project_id,physical_key_id,display_name,target_kind) VALUES(?,?,'Web','web')",(p,rid))
    c.execute("INSERT INTO resource_inventory(physical_key_id,state,os_build,geometry,permissions,ime,observed_at) VALUES(?,'offline','','','[]','','2026-11-01')",(rid,));store.close()
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1') as c:
            h=await session(c,p)
            created=await c.post(f'/api/v1/projects/{p}/cases',json={'name':'Natural authoring'},headers=h)
            cid=created.json()['case_id']
            definition={'raw_text':'로그인 후 주문번호 확인','objective':'주문 조회','preconditions':[],'variables':{},'secret_refs':{},'steps':[],'final_expected':[],'path_policy':{'must_use':[],'forbidden':[]}}
            payload={'definition':definition,'settings':{'wizard':True,'target_kind':'web','execution_mode':'recorded_replay','resource_id':rid,'web_url':'https://shop.example','limits':{'timeout_seconds':600,'max_actions':50,'budget':'1','currency':'USD'}}}
            version=await c.post(f'/api/v1/projects/{p}/cases/{cid}/versions',json=payload,headers={**h,'Idempotency-Key':'version'})
            assert version.status_code==201,version.text
            v=version.json()
            page=await c.get(f'/ui/projects/{p}/recordings/wizard',params={'case':cid})
            assert page.status_code==200
            preview=await c.post(f'/api/v1/projects/{p}/recording-previews',json={'case_id':cid,'input_case_version_id':v['id'],'input_version_hash':v['content_hash'],'resource_id':rid},headers={**h,'Idempotency-Key':'preview'})
            assert preview.status_code==200,preview.text
            assert preview.json()['ready'] is False
            assert len(preview.json()['reasons'])>=1
    asyncio.run(run())
    with sqlite3.connect(db) as c:
        assert c.execute('SELECT count(*) FROM jobs').fetchone()[0]==0
        assert c.execute('SELECT count(*) FROM recordings').fetchone()[0]==0
