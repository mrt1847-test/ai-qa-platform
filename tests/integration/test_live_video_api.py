import asyncio,base64
from uuid import UUID,uuid4
import httpx
from ux_support import ux_app,session
from worker_presence_support import seed_resource_alias
from aiqa.api.auth import bound_auth_store,enroll_worker
from aiqa.store.models import Actor
from video_support import INIT,FRAME

def prepare(app,project,worker='video-pc'):
    store=app.state.open_store();resource=str(uuid4())
    with bound_auth_store(store):token=enroll_worker(Actor(uuid4(),UUID(project),True),worker,'recording')
    with store.transaction() as db:
        db.execute('INSERT INTO physical_resource_keys VALUES(?,?,?)',(resource,worker,'emulator-5580'))
        seed_resource_alias(db,project,resource,'Android','android')
        db.execute("INSERT INTO resource_inventory VALUES(?,'ready','','540x1200@0','{}','','2099-01-01')",(resource,))
    store.close();return resource,token

def test_browser_and_bound_worker_relay_real_video_bytes(ux_app):
    app,p,_=ux_app;r,token=prepare(app,p)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1') as c:
            h=await session(c,p);base=f'/api/v1/projects/{p}/resources/{r}/video'
            assert (await c.post(base,json={})).status_code==403
            started=await c.post(base,json={},headers=h);assert started.status_code==201,started.text
            sid=started.json()['session_id'];url=f'/api/v1/projects/{p}/video-sessions/{sid}'
            wh={'Authorization':'Bearer '+token};body={'operation':'poll','native_id':'emulator-5580','producer_id':str(uuid4())}
            claimed=await c.post('/api/v1/worker/video',json=body,headers=wh)
            assert claimed.status_code==200,claimed.text
            assert claimed.json()['session']['session_id']==sid
            for n,data in enumerate([INIT,FRAME]):
                res=await c.post('/api/v1/worker/video',headers=wh,json={**body,'operation':'append','session_id':sid,'sequence':n,'data':base64.b64encode(data).decode()})
                assert res.status_code==200,res.text
            state=await c.get(url+'?after=0');assert state.status_code==200
            assert [base64.b64decode(x) for x in state.json()['segments']]==[INIT,FRAME]
            assert state.headers['cache-control']=='no-store'
            assert (await c.get(url+'/download')).status_code==404
            assert (await c.post(url+'/stop',headers=h,json={})).status_code==200
            assert (await c.post('/api/v1/worker/video',json=body,headers=wh)).json()['session']['status']=='stopped'
            assert (await c.post('/api/v1/worker/video',json={**body,'operation':'closed','session_id':sid},headers=wh)).status_code==200
    asyncio.run(run())

def test_unauthenticated_and_foreign_project_worker_cannot_view_or_publish(ux_app):
    app,p,_=ux_app;r,token=prepare(app,p)
    store=app.state.open_store()
    with bound_auth_store(store):foreign=enroll_worker(Actor(uuid4(),UUID(p),True),'other-pc','recording')
    store.close()
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1') as c:
            assert (await c.post(f'/api/v1/projects/{p}/resources/{r}/video',json={})).status_code==401
            h=await session(c,p)
            result=await c.post(f'/api/v1/projects/{p}/resources/{r}/video',json={},headers=h)
            sid=result.json()['session_id'];url=f'/api/v1/projects/{p}/video-sessions/{sid}'
            payload={'operation':'append','session_id':sid,'producer_id':str(uuid4()),'sequence':0,'data':base64.b64encode(INIT).decode()}
            assert (await c.post('/api/v1/worker/video',headers={'Authorization':'Bearer '+foreign},json=payload)).status_code==404
            assert (await c.get(url.replace(p,str(uuid4())))).status_code in {401,404}
            c.cookies.clear();assert (await c.get(url)).status_code==401
    asyncio.run(run())

def test_foreign_job_waits_for_capture_stop_ack_even_after_server_buffer_restart(ux_app):
    from aiqa.api.video import manager,before_device_ack
    from aiqa.video.sessions import VideoSessions
    from aiqa.domain.projects import bind_store,create_project
    from aiqa.store.models import ProjectCreate,WorkerScope
    app,p,_=ux_app;r,token=prepare(app,p)
    store=app.state.open_store()
    with bind_store(store):q=str(create_project(Actor(uuid4(),None,True),ProjectCreate('Other','other','other','android')).project_id)
    job=str(uuid4())
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1') as c:
            h=await session(c,p)
            sid=(await c.post(f'/api/v1/projects/{p}/resources/{r}/video',json={},headers=h)).json()['session_id']
            producer=str(uuid4());wh={'Authorization':'Bearer '+token}
            b={'operation':'poll','native_id':'emulator-5580','producer_id':producer}
            assert (await c.post('/api/v1/worker/video',json=b,headers=wh)).status_code==200
            with store.transaction() as d:
                d.execute("INSERT INTO jobs(project_id,job_id,purpose,payload_hash,source_refs,limits,status) VALUES(?,?,'resource_probe','hash',?,'{}','preparing')",(q,job,'["'+r+'"]'))
                d.execute('INSERT INTO leases VALUES(?,?,1,?,?,?)',(q,job,'video-pc',r,'2099-01-01T00:00:00+00:00'))
            # The server has lost its RAM buffers. Its durable producer fence must survive.
            app.state.video_sessions=VideoSessions()
            assert manager(app).sessions[sid].status=='blocked'
            scope=WorkerScope('video-pc',(UUID(q),),('resource_probe',))
            gate=asyncio.create_task(before_device_ack(app,scope,UUID(q),UUID(job),1))
            await asyncio.sleep(.1);assert not gate.done()
            assert (await c.get(f'/api/v1/projects/{p}/video-sessions/{sid}')).status_code in {404,409}
            close=await c.post('/api/v1/worker/video',headers=wh,json={**b,'operation':'closed','session_id':sid})
            assert close.status_code==200,close.text
            assert await gate
    try:asyncio.run(run())
    finally:store.close()
