import asyncio
from uuid import uuid4
import httpx
from ux_support import ux_app, session


def test_secret_picker_lists_only_project_reference_metadata(ux_app):
    app, project, _ = ux_app
    store = app.state.open_store()
    ref = str(uuid4())
    store._connection.execute(
        "INSERT INTO secret_refs(project_id,ref_id,revision,name,availability,created_at,actor_id) VALUES(?,?,1,'QA 계정','available','2026-11-01',?)",
        (project, ref, str(uuid4())),
    )
    store.close()

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1') as client:
            headers = await session(client, project)
            listed = await client.get(f'/api/v1/projects/{project}/secret-refs', headers=headers)
            assert listed.status_code == 200
            item = listed.json()['refs'][0]
            assert item['ref_id'] == ref and item['revision'] == 1
            assert set(item) == {'project_id', 'ref_id', 'revision', 'name', 'availability'}
            foreign = await client.get(f'/api/v1/projects/{uuid4()}/secret-refs', headers=headers)
            assert foreign.status_code == 404

    asyncio.run(run())
