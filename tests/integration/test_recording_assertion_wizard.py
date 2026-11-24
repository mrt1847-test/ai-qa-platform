import asyncio,sqlite3
from uuid import uuid4
import httpx
from ux_support import ux_app,session
from test_w16 import _binding


def test_wizard_lists_verification_binding_and_roundtrips_visual_assertion(ux_app):
    app,project,database=ux_app
    _binding(database,project,str(uuid4()))
    with sqlite3.connect(database) as c:
        c.execute("INSERT INTO model_bindings(project_id,binding_id,name,next_revision,latest_revision_id) VALUES(?,'wizard-verifier','Screen',2,'wizard-verifier-v1')",(project,))
        c.execute("""INSERT INTO binding_revisions(project_id,binding_id,revision_id,revision,role,provider,endpoint_kind,
            endpoint,model,key_ref_id,key_revision,prompt_hash,tariff_id,compatibility_status,content_hash,actor_id,created_at)
            SELECT project_id,'wizard-verifier','wizard-verifier-v1',1,'verification',provider,endpoint_kind,
            endpoint,'fixture-screen-verifier',key_ref_id,key_revision,prompt_hash,tariff_id,compatibility_status,'wizard-binding-hash',actor_id,created_at
            FROM binding_revisions WHERE project_id=? AND binding_id='bind-w1605'""",(project,))
    async def flow():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1') as client:
            headers=await session(client,project)
            page=await client.get(f'/ui/projects/{project}/recordings/wizard?target=android&step=3')
            assert page.status_code==200
            assert 'name="verifier_method"' in page.text and 'name="verifier_binding_id"' in page.text
            assert 'fixture-screen-verifier' in page.text
            case=await client.post(f'/api/v1/projects/{project}/cases',json={'name':'Screen assertion'},headers=headers)
            case_id=case.json()['case_id']
            saved=await client.post(f'/api/v1/projects/{project}/cases/{case_id}/versions',headers={**headers,'Idempotency-Key':'visual-draft'},json={
                'definition':{'raw_text':'베스트를 열어 줘.','objective':'베스트를 열어 줘.','preconditions':[],
                    'variables':{},'secret_refs':{},'steps':[],'final_expected':[{'id':'products','kind':'visual','expected':'상품 이미지와 가격이 표시된다.'}],
                    'path_policy':{'must_use':[],'forbidden':[]}},
                'settings':{'target_kind':'android','android_package':'com.example.app','verifier_bindings':[
                    {'method':'ai_visual','binding_id':'wizard-verifier','allow_unknown_supplement':False}]}})
            assert saved.status_code==201,saved.text
            reopened=await client.get(f'/ui/projects/{project}/recordings/wizard?case={case_id}&step=3')
            assert reopened.status_code==200
            assert 'value="ai_visual" selected' in reopened.text
            assert 'value="wizard-verifier" selected' in reopened.text
            assert '상품 이미지와 가격이 표시된다.' in reopened.text
    asyncio.run(flow())
