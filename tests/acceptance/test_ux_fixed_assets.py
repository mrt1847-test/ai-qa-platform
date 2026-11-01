import asyncio
from html.parser import HTMLParser
import httpx
from ux_support import ux_app,session,ENV,DATA

def test_wizard_retains_exact_older_environment_and_data_revisions(ux_app):
    app,p,_=ux_app
    class Selected(HTMLParser):
        def __init__(self):super().__init__();self.current=None;self.values={}
        def handle_starttag(self,tag,attrs):
            a=dict(attrs)
            if tag=='select':self.current=a.get('name')
            if tag=='option' and 'selected' in a:self.values[self.current]=a.get('value')
        def handle_endtag(self,tag):
            if tag=='select':self.current=None
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1') as c:
            h=await session(c,p)
            e=await c.post(f'/api/v1/projects/{p}/environments',json=ENV,headers=h);env=e.json()
            await c.post(f'/api/v1/projects/{p}/environments/{env["environment_id"]}/revisions',json=ENV,headers={**h,'Idempotency-Key':'env2'})
            d=await c.post(f'/api/v1/projects/{p}/datasets',json=DATA,headers={**h,'Idempotency-Key':'data1'});data=d.json()
            data2=await c.post(f'/api/v1/projects/{p}/datasets/{data["dataset_id"]}/revisions',json=DATA,headers={**h,'Idempotency-Key':'data2'})
            assert data2.status_code==201,data2.text
            assert data2.json()['id']!=data['id']
            created=await c.post(f'/api/v1/projects/{p}/cases',json={'name':'고정 개정'},headers={**h,'Idempotency-Key':'case'});cid=created.json()['case_id']
            definition={'raw_text':'주문 조회','objective':'','preconditions':[],'variables':{},'secret_refs':{},'steps':[],'final_expected':[],'path_policy':{'must_use':[],'forbidden':[]}}
            saved=await c.post(f'/api/v1/projects/{p}/cases/{cid}/versions',json={'definition':definition,'settings':{'target_kind':'web','environment_revision_id':env['id'],'data_revision_id':data['id']}},headers={**h,'Idempotency-Key':'version'})
            assert saved.status_code==201,saved.text
            page=await c.get(f'/ui/projects/{p}/recordings/wizard',params={'case':cid});assert page.status_code==200
            selected=Selected();selected.feed(page.text)
            assert selected.values['environment_revision_id']==env['id']
            assert selected.values['data_revision_id']==data['id']
    asyncio.run(run())
