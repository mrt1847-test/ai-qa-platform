import asyncio
import httpx
import pytest
from uuid import uuid4
from aiqa.api.app import create_app
from aiqa.config import load_settings
from aiqa.domain.projects import bind_store, create_project
from aiqa.store.models import Actor, ProjectCreate
from aiqa.store.database import migrate_store

@pytest.fixture
def ux_app(tmp_path):
    app=create_app(load_settings({'AIQA_HOST':'127.0.0.1','AIQA_PORT':'8000','AIQA_RUNTIME_ROOT':str(tmp_path/'runtime')}))
    store=app.state.open_store();migrate_store(store)
    with bind_store(store):
        project=create_project(Actor(uuid4(),None,True),ProjectCreate('UX','ux','review','web'))
    store.close()
    return app,str(project.project_id),tmp_path/'runtime/db/aiqa.sqlite'

async def session(client, project):
    origin='http://127.0.0.1'
    nonce=await client.post('/api/v1/session/nonces',json={'origin':origin,'project_id':project},headers={'Origin':origin,'Idempotency-Key':str(uuid4())})
    boot=await client.post('/api/v1/session/bootstrap',json={'nonce':nonce.json()['nonce']},headers={'Origin':origin,'Idempotency-Key':str(uuid4())})
    return {'Origin':origin,'X-CSRF-Token':boot.json()['csrf_token'],'Idempotency-Key':'asset-save'}

ENV={'name':'Shopping','target_kind':'web','allowlist':['https://shop.example'],'viewport':{'width':1280,'height':720},'locale':'ko-KR','reset_policy':'none','limits':{'budget':'1','currency':'USD','timeout_seconds':600,'max_actions':50},'start_url':'https://shop.example/login','dpr':1,'timezone':'Asia/Seoul'}
DATA={'name':'Orders','row_schema':{'columns':[{'name':'amount','type':'int'}]},'rows':[{'id':'r1','values':{'amount':10000}}]}
