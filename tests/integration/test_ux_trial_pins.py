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


def test_formal_multi_item_receipt_survives_resource_change(ux_app):
    from acceptance.test_w20 import _case as formal_case, _seed, _body

    app, project_id, database = ux_app
    version, case_id = asyncio.run(formal_case(app, project_id))
    environment, resource, busy = (str(uuid4()) for _ in range(3))
    seed = _seed(database, project_id, case_id, version, environment, resource, busy)

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1') as client:
            headers = await session(client, project_id)
            selection = _body(seed['old'], environment, resource, 'regression', seed['old_approval'])
            selection['source'] = 'selection'
            first = selection['selection']['items'][0]
            selection['selection']['items'].append({**first, 'entry_id': 'item-2'})
            preview = await client.post(f'/api/v1/projects/{project_id}/execution-previews', json=selection, headers=headers)
            assert preview.status_code == 200 and preview.json()['ready'], preview.text
            payload = {**selection, 'preview_hash': preview.json()['preview_hash'], 'items': preview.json()['resolved_items']}
            payload.pop('selection')
            url = f'/api/v1/projects/{project_id}/executions'
            command_headers = {**headers, 'Idempotency-Key': 'formal-multi-receipt'}
            admitted = await client.post(url, json=payload, headers=command_headers)
            assert admitted.status_code == 201, admitted.text
            receipt = admitted.json()
            assert len(set(receipt['item_ids'])) == len(set(receipt['job_ids'])) == 2
            with sqlite3.connect(database) as connection:
                for job_id in receipt['job_ids']:
                    limits = json.loads(connection.execute('SELECT limits FROM jobs WHERE job_id=?', (job_id,)).fetchone()[0])
                    assert limits['execution_snapshot']['approval_id'] == seed['old_approval']
                    assert limits['execution_snapshot']['resource_id'] == resource
                connection.execute("UPDATE resource_inventory SET state='offline' WHERE physical_key_id=?", (resource,))
            replay = await client.post(url, json=payload, headers=command_headers)
            assert replay.status_code == 200, replay.text
            assert replay.json()['execution_id'] == receipt['execution_id']
            assert set(replay.json()['item_ids']) == set(receipt['item_ids'])
            assert set(replay.json()['job_ids']) == set(receipt['job_ids'])
            changed = {**payload, 'items': [{**payload['items'][0], 'entry_id': 'changed'}, payload['items'][1]]}
            conflict = await client.post(url, json=changed, headers=command_headers)
            assert conflict.status_code == 409
            fresh = await client.post(url, json=payload, headers={**headers, 'Idempotency-Key': 'formal-multi-offline'})
            assert fresh.status_code == 422
    asyncio.run(run())
