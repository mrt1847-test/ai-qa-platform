import asyncio
from uuid import uuid4
import httpx
from ux_support import ux_app,session

def seed_resource(app,p):
    store=app.state.open_store();c=store._connection;rid=str(uuid4())
    c.execute("INSERT INTO worker_enrollments(enrollment_id,worker_id,project_id,created_at) VALUES(?,?,?,'2026-11-01')",(str(uuid4()),'ux-worker',p))
    c.execute("INSERT INTO physical_resource_keys(physical_key_id,worker_id,native_id) VALUES(?,'ux-worker',?)",(rid,rid))
    c.execute("INSERT INTO resource_aliases(project_id,physical_key_id,display_name,target_kind) VALUES(?,?,'Review Web','web')",(p,rid))
    c.execute("INSERT INTO resource_inventory(physical_key_id,state,os_build,geometry,permissions,ime,observed_at) VALUES(?,'offline','','','[]','','2026-11-01')",(rid,))
    store.close();return rid

def test_entry_preserves_selected_resource_and_foreign_resource_is_hidden(ux_app):
    app,p,_=ux_app;rid=seed_resource(app,p)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1') as c:
            await session(c,p)
            entry=await c.get(f'/ui/projects/{p}/recordings/new',params={'resource_id':rid})
            assert entry.status_code in (302,303,307)
            assert 'resource_id='+rid in entry.headers['location']
            foreign=await c.get(f'/ui/projects/{p}/recordings/wizard',params={'resource_id':str(uuid4())})
            assert foreign.status_code==404
    asyncio.run(run())
