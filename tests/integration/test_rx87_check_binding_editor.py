import asyncio,copy
from uuid import uuid4
import httpx
from ux_support import ux_app,session
from test_rx87_check_bindings import recorded,request_payload,PAYLOAD


def test_recording_editor_exposes_source_steps_and_new_candidate_receipt(recorded):
    r=recorded;url=f"/api/v1/projects/{r['project']}/recordings/{r['recording']}/check-bindings"
    page=f"/ui/projects/{r['project']}/recordings/{r['recording']}"
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=r['app']),base_url='http://127.0.0.1') as client:
            headers=await session(client,str(r['project']))
            timeline=(await client.get(page.replace('/ui/','/api/v1/')+'/timeline',headers=headers)).json()
            assert timeline['completion_status']=='completed'
            response=await client.get(page)
            assert response.status_code==200,response.text
            assert 'id="recording-check-bindings"' in response.text
            assert 'data-step-id="s1"' in response.text and 'data-step-id="s2"' in response.text
            assert 'data-check-id="c1"' in response.text and 'data-check-id="final"' in response.text
            assert '검증 연결 후보 저장' in response.text and '실행 적용은 아직 지원하지 않습니다' in response.text
            saved=await client.post(url,json=request_payload(r),headers=headers)
            assert saved.status_code==201,saved.text
            context=(await client.get(url)).json()
            assert saved.json()['manifest_hash']==context['source_manifest']['hash']
            updated=(await client.get(page)).text
            assert 'data-approved="false"' in updated
            assert '?version='+saved.json()['case_version_id'] in updated
    asyncio.run(run())


def test_review_link_pins_exact_case_version_instead_of_newer_candidate(recorded):
    r=recorded;url=f"/api/v1/projects/{r['project']}/recordings/{r['recording']}/check-bindings"
    review=f"/ui/projects/{r['project']}/cases/{r['case']}/review"
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=r['app']),base_url='http://127.0.0.1') as client:
            headers=await session(client,str(r['project']))
            saved=(await client.post(url,json=request_payload(r),headers=headers)).json()
            old=await client.get(review+'?version='+r['old_draft'])
            assert old.status_code==200,old.text
            assert 'data-selected-version="'+r['old_draft']+'"' in old.text
            assert 'id="approve-case" data-version="'+r['old_draft']+'"' in old.text
            latest=(await client.get(review)).text
            assert 'data-selected-version="'+saved['case_version_id']+'"' in latest
            assert (await client.get(review+'?version='+str(uuid4()))).status_code==404
            assert (await client.get(review+'?version=not-a-version')).status_code==404
    asyncio.run(run())
