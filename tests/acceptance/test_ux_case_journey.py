import asyncio
from uuid import UUID, uuid4
import httpx
from ux_support import ux_app, session
from aiqa.domain.versions import bind_case_store, create_case
from aiqa.store.models import Actor


def test_case_detail_opens_by_id_beyond_first_catalog_page(ux_app):
    app, project, _ = ux_app
    store = app.state.open_store()
    with bind_case_store(store):
        actor = Actor(uuid4(), UUID(project), True)
        for i in range(101):
            case = create_case(actor, f'Case {i:03d}', None)
    store.close()

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1') as client:
            await session(client, project)
            page = await client.get(f'/ui/projects/{project}/cases/{case.case_id}')
            assert page.status_code == 200
            assert 'Case 100' in page.text
            foreign_version = uuid4()
            selected = await client.get(f'/ui/projects/{project}/cases/{case.case_id}/definition',params={'version':str(foreign_version)})
            assert selected.status_code == 404

    asyncio.run(run())
