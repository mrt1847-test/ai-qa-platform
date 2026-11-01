import asyncio
import httpx
from ux_support import ux_app, session


def test_definition_roundtrip_preserves_settings_extensions_and_stable_checks(ux_app):
    app,p,_=ux_app
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1') as c:
            h=await session(c,p)
            created=await c.post(f'/api/v1/projects/{p}/cases',json={'name':'왕복'},headers=h);cid=created.json()['case_id']
            definition={'raw_text':'한글 검증','objective':'입력 보존','preconditions':['로그인'],'variables':{'empty':'','nil':None,'object':{'nested':[1,'한글']}},'secret_refs':{},'steps':[{'id':'stable-step','instruction':'확인','expected':[{'id':'stable-check','kind':'text','expected':'결과'}],'point':[10,20]}],'final_expected':[],'path_policy':{'must_use':[],'forbidden':[]}}
            settings={'target_kind':'web','execution_mode':'recorded_replay','web_url':'https://shop.example','future_option':{'preserve':True},'limits':{'timeout_seconds':600,'max_actions':50,'budget':'2','currency':'USD'}}
            result=await c.post(f'/api/v1/projects/{p}/cases/{cid}/versions',json={'definition':definition,'settings':settings},headers={**h,'Idempotency-Key':'roundtrip'})
            assert result.status_code==201,result.text
            store=app.state.open_store()
            import json
            row=store._connection.execute('SELECT definition_json,settings_json FROM case_versions WHERE version_id=?',(result.json()['id'],)).fetchone();store.close()
            saved_def,saved=json.loads(row[0]),json.loads(row[1])
            assert saved['future_option']==settings['future_option']
            assert saved['limits']['budget']=='2' and saved['limits']['max_actions']==50
            assert saved_def['variables']==definition['variables']
            assert saved_def['steps'][0]['id']=='stable-step' and saved_def['steps'][0]['expected'][0]['id']=='stable-check'
            from uuid import uuid4
            stale=await c.post(f'/ui/projects/{p}/cases/{cid}/definition',json={'definition':definition,'settings':settings,'expected_head':str(uuid4())},headers={**h,'Idempotency-Key':'stale'})
            assert stale.status_code==409
            assert stale.json()['server_snapshot']['expected_head']==result.json()['id']
    asyncio.run(run())
