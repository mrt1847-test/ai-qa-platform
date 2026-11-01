"""Asset authoring contracts used by the real HTML editors."""
import asyncio
import httpx
import pytest
from ux_support import ux_app, session, ENV, DATA

def test_environment_errors_identify_the_field_and_saved_profile_can_be_reloaded(ux_app):
    app,p,_=ux_app
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1') as c:
            h=await session(c,p)
            bad=await c.post(f'/api/v1/projects/{p}/environments',json={**ENV,'viewport':{'width':0,'height':720}},headers=h)
            assert bad.status_code==422
            assert 'viewport.width' in bad.json()['error']['fields']
            good=await c.post(f'/api/v1/projects/{p}/environments',json=ENV,headers={**h,'Idempotency-Key':'good'})
            saved=good.json()
            listing=await c.get(f'/api/v1/projects/{p}/environments',headers=h)
            assert listing.status_code==200
            assert listing.json()['environments'][0]['id']==saved['id']
            page=await c.get(f'/ui/projects/{p}/environments/editor',params={'environment':saved['environment_id']})
            assert page.status_code==200
            assert 'https://shop.example/login' in page.text
    asyncio.run(run())

def test_dataset_cell_errors_and_exact_schema_are_available_to_editor(ux_app):
    app,p,_=ux_app
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1') as c:
            h=await session(c,p)
            bad=await c.post(f'/api/v1/projects/{p}/datasets',json={**DATA,'rows':[{'id':'r1','values':{'amount':'not an integer'}}]},headers=h)
            assert bad.status_code==422
            assert 'rows.0.values.amount' in bad.json()['error']['fields']
            saved=await c.post(f'/api/v1/projects/{p}/datasets',json=DATA,headers={**h,'Idempotency-Key':'good'})
            assert saved.status_code==201
            listed=await c.get(f'/api/v1/projects/{p}/datasets',headers=h)
            item=listed.json()['datasets'][0]
            assert item['id']==saved.json()['id']
            assert item['row_schema']=={'columns':[{'name':'amount','type':'int'}]}
            page=await c.get(f'/ui/projects/{p}/datasets',params={'dataset':item['dataset_id']})
            assert page.status_code==200
    asyncio.run(run())
