import asyncio
import json
import sqlite3
from uuid import uuid4
import httpx
from ux_support import ux_app,session,DATA
from acceptance.test_w17 import _case,_packages,_selection


def test_trial_pins_data_and_replays_receipt_after_resource_changes(ux_app):
    app,p,db=ux_app
    bare,cid=asyncio.run(_case(app,p));environment,resource=str(uuid4()),str(uuid4())
    version,_,_=_packages(db,p,cid,bare,environment,resource)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1') as c:
            h=await session(c,p)
            first=await c.post(f'/api/v1/projects/{p}/datasets',json=DATA,headers={**h,'Idempotency-Key':'data1'})
            second=await c.post(f'/api/v1/projects/{p}/datasets',json={**DATA,'name':'Other'},headers={**h,'Idempotency-Key':'data2'})
            one,two=first.json()['id'],second.json()['id']
            payload=_selection(version,environment,resource,False)
            payload['selection']['items'][0]['dataset_version_id']=one
            a=await c.post(f'/api/v1/projects/{p}/execution-previews',json=payload,headers=h)
            payload['selection']['items'][0]['dataset_version_id']=two
            b=await c.post(f'/api/v1/projects/{p}/execution-previews',json=payload,headers=h)
            assert a.json()['preview_hash']!=b.json()['preview_hash']
            prepared=a.json();item={**prepared['resolved_items'][0],'dataset_version_id':one}
            request={'name':'UI trial','purpose':'trial','source':'single','failure_policy':'stop_on_non_pass','preview_hash':prepared['preview_hash'],'self_healing_enabled':False,'items':[item]}
            receipt=await c.post(f'/api/v1/projects/{p}/executions',json=request,headers={**h,'Idempotency-Key':'trial'})
            assert receipt.status_code==201,receipt.text
            with sqlite3.connect(db) as con:
                limits=json.loads(con.execute('SELECT limits FROM jobs WHERE job_id=?',(receipt.json()['job_ids'][0],)).fetchone()[0])
                assert limits['execution_snapshot']['dataset_version_id']==one
                assert limits['execution_snapshot']['resource_id']==resource
                con.execute("UPDATE resource_inventory SET state='offline' WHERE physical_key_id=?",(resource,))
            repeat=await c.post(f'/api/v1/projects/{p}/executions',json=request,headers={**h,'Idempotency-Key':'trial'})
            assert repeat.status_code==200 and repeat.json()['execution_id']==receipt.json()['execution_id']
            changed={**request,'items':[{**item,'dataset_version_id':two}]}
            conflict=await c.post(f'/api/v1/projects/{p}/executions',json=changed,headers={**h,'Idempotency-Key':'trial'})
            assert conflict.status_code==409
            refused=await c.post(f'/api/v1/projects/{p}/executions',json=request,headers={**h,'Idempotency-Key':'new-offline'})
            assert refused.status_code==422
    asyncio.run(run())
