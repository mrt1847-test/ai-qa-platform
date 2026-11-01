import asyncio
from uuid import UUID, uuid4
import httpx
from ux_support import ux_app, session
from aiqa.domain.versions import bind_case_store, create_case
from aiqa.store.models import Actor


def test_trial_setup_resolves_actual_case_and_never_enqueues_on_open(ux_app):
    app,p,_=ux_app
    store=app.state.open_store()
    with bind_case_store(store): case=create_case(Actor(uuid4(),UUID(p),True),'결제 확인',None)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1') as c:
            await session(c,p)
            page=await c.get(f'/ui/projects/{p}/cases/{case.case_id}/execution-setup')
            assert page.status_code==200
            assert '결제 확인' in page.text
            assert 'name="case_version_id"' in page.text
            assert 'id="preview-trial"' in page.text and 'id="enqueue-trial"' in page.text
            hidden=await c.get(f'/ui/projects/{p}/cases/{uuid4()}/execution-setup')
            assert hidden.status_code==404
    asyncio.run(run())
    assert store._connection.execute('SELECT count(*) FROM jobs').fetchone()[0]==0
    store.close()
