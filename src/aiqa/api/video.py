"""Authenticated opt-in continuous MP4 video. Separate from evidence/approval."""
from __future__ import annotations
import asyncio,base64,binascii,json
from contextlib import contextmanager
from uuid import UUID
from fastapi import Request
from fastapi.responses import JSONResponse
from aiqa.api.auth import (AuthRequired,CsrfRejected,OriginRejected,ProjectHidden,
    authorize_browser,authorize_page,bound_auth_store,worker_scope_from_token)
from aiqa.store.database import migrate_store
from aiqa.video.sessions import Session,VideoSessions,VideoMissing,VideoConflict,VideoInvalid
from aiqa.video.privacy import incompatible,contexts,sensitive

CACHE={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}

@contextmanager
def bound(request):
    store=request.app.state.open_store()
    try:
        migrate_store(store)
        with bound_auth_store(store):yield store
    finally:store.close()

def manager(app):
    result=app.state.video_sessions
    with result.lock:
        if not getattr(result,'restored',False):
            store=app.state.open_store()
            try:
                migrate_store(store)
                rows=store._connection.execute('SELECT * FROM live_video_publishers WHERE closed=0 AND producer_id<>\'\'').fetchall()
            finally:store.close()
            now=result.clock()
            for sid,p,r,a,w,n,producer,_ in rows:
                result.sessions[sid]=Session(sid,p,r,a,w,n,now,now,status='blocked',reason='server_restarted',producer=producer,ended=now)
            result.restored=True
    return result

def persist(app,s):
    store=app.state.open_store()
    try:
        with store.transaction() as db:
            db.execute("""INSERT INTO live_video_publishers VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(session_id) DO UPDATE SET producer_id=excluded.producer_id,closed=excluded.closed""",
                (s.session_id,s.project,s.resource,s.actor,s.worker,s.native,s.producer,int(s.producer_closed)))
    finally:store.close()

def error(status,message):return JSONResponse({'error':{'message':message}},status_code=status,headers=CACHE)

async def body(request):
    raw=bytearray()
    async for part in request.stream():
        raw.extend(part)
        if len(raw)>2_850_000:raise VideoInvalid('video request exceeds limit')
    try:value=json.loads(raw or b'{}')
    except ValueError:raise VideoInvalid('invalid video request') from None
    if type(value) is not dict:raise VideoInvalid('invalid video request')
    return value

def resource(db,project,rid):
    row=db.execute("""SELECT k.worker_id,k.native_id FROM resource_aliases a
        JOIN physical_resource_keys k USING(physical_key_id)
        WHERE a.project_id=? AND a.physical_key_id=? AND a.target_kind='android'""",(str(project),rid)).fetchone()
    if row is None:raise VideoMissing('Android resource was not found')
    return row

def check_pixels(app,db,s):
    if incompatible(db,s.native,s.project,s.worker):
        m=manager(app)
        for context in contexts(db,s.native,s.worker):m.fence(s.native,str(context[0]),sensitive=sensitive(context),worker=s.worker)
        raise VideoConflict('video blocked by device job')

async def before_device_ack(app,worker,project,job,generation):
    """A sensitive/foreign execution cannot start until capture processes close."""
    if project not in worker.permitted_projects:return True
    m=manager(app);deadline=asyncio.get_running_loop().time()+6
    while True:
        store=app.state.open_store()
        try:
            row=store._connection.execute("""SELECT k.native_id,j.purpose FROM leases l JOIN physical_resource_keys k USING(physical_key_id)
                JOIN jobs j ON j.project_id=l.project_id AND j.job_id=l.job_id
                WHERE l.project_id=? AND l.job_id=? AND l.generation=? AND l.worker_id=?""",
                (str(project),str(job),generation,worker.worker_id)).fetchone()
            if row is None:return True # Existing acknowledgement authorization still rejects this lease.
            if row[1] not in worker.permitted_purposes:return True
            current=[c for c in contexts(store._connection,row[0],worker.worker_id) if str(c[0])==str(project)]
            secret=any(sensitive(c) for c in current)
            with m.lock:
                ready=m.fence(row[0],str(project),sensitive=secret,worker=worker.worker_id)
                for s in m.sessions.values():
                    if s.worker==worker.worker_id and s.native==row[0] and s.status=='blocked':persist(app,s)
        finally:store.close()
        if ready:return True
        if asyncio.get_running_loop().time()>=deadline:return False
        await asyncio.sleep(.05)

def install_video(app):
    app.state.video_sessions=VideoSessions()

    async def create(project_id:str,resource_id:str,request:Request):
        try:
            project=UUID(project_id)
            with bound(request) as store:
                # Check the read session first, distinguishing absent auth from bad CSRF.
                authorize_page(request,project);actor=authorize_browser(request,project,'live_video')
                m=manager(app)
                with m.lock:
                    worker,native=resource(store._connection,project,resource_id)
                    if incompatible(store._connection,native,project,worker):raise VideoConflict('device is running a sensitive or different project job')
                    result=m.create(str(project),resource_id,str(actor.actor_id),worker,native)
                    persist(app,m.sessions[result['session_id']])
            return JSONResponse(result,status_code=201,headers=CACHE)
        except AuthRequired:return error(401,'session is missing')
        except (CsrfRejected,OriginRejected):return error(403,'CSRF token or origin was rejected')
        except (ProjectHidden,VideoMissing,ValueError) as exc:
            return error(409 if isinstance(exc,VideoConflict) else 404,str(exc))

    async def view(project_id:str,session_id:str,request:Request):
        try:
            project=UUID(project_id)
            with bound(request) as store:
                actor=authorize_page(request,project);m=manager(app)
                with m.lock:
                    s=m._get(session_id,str(project),str(actor.actor_id));check_pixels(app,store._connection,s)
                    result=m.read(session_id,str(project),str(actor.actor_id),int(request.query_params.get('after','0')))
                    result['segments']=[base64.b64encode(v).decode('ascii') for v in result['segments']]
            return JSONResponse(result,headers=CACHE)
        except (AuthRequired,OriginRejected):return error(401,'session is missing')
        except (ProjectHidden,VideoMissing):return error(404,'video session was not found')
        except VideoConflict:return error(409,'video blocked by device job')
        except ValueError:return error(422,'invalid video cursor')

    async def mutate(project_id:str,session_id:str,request:Request):
        try:
            project=UUID(project_id)
            with bound(request) as store:
                actor=authorize_browser(request,project,'live_video');m=manager(app)
                operation=request.url.path.rsplit('/',1)[-1]
                with m.lock:
                    s=m._get(session_id,str(project),str(actor.actor_id))
                    if operation=='keepalive':check_pixels(app,store._connection,s)
                    result=getattr(m,operation)(session_id,str(project),str(actor.actor_id));persist(app,s)
            return JSONResponse(result,headers=CACHE)
        except (AuthRequired,OriginRejected):return error(401,'session is missing')
        except CsrfRejected:return error(403,'CSRF token was rejected')
        except (ProjectHidden,VideoMissing):return error(404,'video session was not found')
        except VideoConflict:return error(409,'video stopped')
        except ValueError:return error(422,'invalid video session')

    async def worker_video(request:Request):
        try:
            header=request.headers.get('authorization','')
            if not header.startswith('Bearer '):raise AuthRequired()
            with bound(request) as store:
                worker=worker_scope_from_token(header[7:]);m=manager(app)
                if not set(worker.permitted_purposes)&{'recording','trial','regression'}:return error(403,'worker cannot capture video')
                payload=await body(request);producer=str(UUID(payload.get('producer_id','')));op=payload.get('operation')
                if op=='poll':
                    native=payload.get('native_id')
                    known=store._connection.execute('SELECT 1 FROM physical_resource_keys WHERE worker_id=? AND native_id=?',(worker.worker_id,native)).fetchone()
                    if not known:raise VideoMissing('device was not found')
                    with m.lock:
                        closing=[{'session_id':s.session_id,'producer_id':s.producer} for s in m.sessions.values()
                            if s.worker==worker.worker_id and s.native==native and s.project in map(str,worker.permitted_projects)
                            and s.producer and not s.producer_closed and s.status not in {'pending','live'}]
                        result=m.claim(worker.worker_id,native,producer,projects=set(map(str,worker.permitted_projects)))
                        if result:
                            s=m.sessions[result['session_id']]
                            if UUID(s.project) not in worker.permitted_projects:result=None
                            else:persist(app,s)
                    return JSONResponse({'session':result,'closing':closing},headers=CACHE)
                with m.lock:
                    s=m.sessions.get(payload.get('session_id'))
                    if s is None or s.worker!=worker.worker_id or UUID(s.project) not in worker.permitted_projects:raise VideoMissing('video session was not found')
                    if op=='closed':m.ack_stop(s.session_id,producer);persist(app,s);result=m.describe(s)
                    elif op=='failed':result=m.fail(s.session_id,producer,'capture_unavailable')
                    elif op=='append':
                        check_pixels(app,store._connection,s)
                        try:data=base64.b64decode(payload.get('data',''),validate=True)
                        except (ValueError,TypeError,binascii.Error):raise VideoInvalid('invalid video data') from None
                        result=m.append(s.session_id,producer,payload.get('sequence'),data)
                    else:raise VideoInvalid('unknown video operation')
                return JSONResponse(result,headers=CACHE)
        except AuthRequired:return error(401,'worker token is missing')
        except VideoMissing:return error(404,'video session was not found')
        except VideoConflict:return error(409,'video publisher stopped')
        except ValueError:return error(422,'invalid video request')

    app.add_api_route('/api/v1/projects/{project_id}/resources/{resource_id}/video',create,methods=['POST'])
    base='/api/v1/projects/{project_id}/video-sessions/{session_id}'
    app.add_api_route(base,view,methods=['GET'])
    app.add_api_route(base+'/keepalive',mutate,methods=['POST'])
    app.add_api_route(base+'/stop',mutate,methods=['POST'])
    app.add_api_route('/api/v1/worker/video',worker_video,methods=['POST'])
