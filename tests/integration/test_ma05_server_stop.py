"""Server stop paths preserve saved REC facts when no worker finish can arrive."""
from datetime import datetime,timezone,timedelta
from uuid import uuid4
import asyncio,hashlib,sqlite3
import httpx,pytest
from test_ma04_engine_authority import platform,ux_app,worker,choose,claim
from test_rx97_recording_pin import request as start
from test_ma05_failure_state import recording_state
from test_rx_65 import _observation
from aiqa.worker.model_observations import upload_authoring_observation
from aiqa.worker.service import bind_claim_store,reconcile_jobs
from ux_support import session


def cancel(f,job,key='server-cancel'):
    async def post():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=f['app']),base_url='http://127.0.0.1') as c:
            headers=await session(c,f['project'])
            return await c.post(f"/api/v1/projects/{f['project']}/jobs/{job}/cancellations",json={'expected_state':'queued'},headers={**headers,'Idempotency-Key':key})
    return asyncio.run(post())


def reconcile(f,now):
    store=f['app'].state.open_store()
    try:
        with bind_claim_store(store):return reconcile_jobs(now)
    finally:store.close()


def no_materialization(f):
    with sqlite3.connect(f['database']) as db:
        for table in ('recording_manifests','replay_packages','approval_events'):
            assert db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM case_versions').fetchone()[0]==1


def test_queued_browser_cancel_stops_only_selected_recording_without_worker(platform):
    f=platform;w=worker(f);choose(f,w)
    one=start(f);assert one.status_code==201,one.text
    two=start(f,key='second-queued');assert two.status_code==201,two.text
    other=recording_state(f,two.json()['recording_id'])
    response=cancel(f,one.json()['job_id']);assert response.status_code==202,response.text
    assert recording_state(f,one.json()['recording_id'])==('interrupted','stopped','stored','incomplete')
    assert recording_state(f,two.json()['recording_id'])==other
    assert cancel(f,one.json()['job_id']).status_code==200
    no_materialization(f)
    with sqlite3.connect(f['database']) as db:
        assert db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM resource_quarantine').fetchone()[0]==0
    assert f['model_sent']==[]


@pytest.mark.parametrize('loss',['expired','watchdog','offline','session'])
def test_server_loss_stops_saved_recording_but_preserves_acked_image_and_late_error(platform,loss):
    f=platform;w=worker(f);choose(f,w);started=start(f);assert started.status_code==201
    job=claim(f,w);assert job is not None
    w.client.acknowledge(project_id=f['project'],job_id=job['job_id'],generation=job['generation'],runner_nonce=str(uuid4()),
        now=datetime.now(timezone.utc).isoformat(),idempotency_key='ack-server-stop')
    pin=job['snapshot']['limits']
    payload={'call_id':str(uuid4()),'purpose':'recording','role':'authoring','owner_kind':'authoring','owner_id':job['attempt_id'],
        'generation':job['generation'],'binding_revision':pin['authoring_binding']['revision'],'intent_hash':job['snapshot']['intent_hash'],
        'deadline':(datetime.now(timezone.utc)+timedelta(seconds=20)).isoformat(),'token_output_limit':512}
    before=upload_authoring_observation(w.client,job,_observation(),payload)
    now=datetime.now(timezone.utc)
    live=reconcile(f,now);assert not live.dead_runner_resumed
    assert recording_state(f,started.json()['recording_id'])[0]=='open'
    if loss=='session':w.client.heartbeat('new-server-stop-boot')
    else:
        with sqlite3.connect(f['database']) as db:
            if loss=='expired':db.execute('UPDATE leases SET expires_at=? WHERE job_id=?',((now-timedelta(seconds=1)).isoformat(),job['job_id']))
            elif loss=='watchdog':db.execute('UPDATE attempt_runners SET acked_at=? WHERE attempt_id=?',((now-timedelta(seconds=31)).isoformat(),job['attempt_id']))
            else:db.execute('UPDATE worker_presence SET last_seen=? WHERE project_id=? AND worker_id=?',((now-timedelta(minutes=3)).isoformat(),f['project'],w.worker_id))
    reconcile(f,datetime.now(timezone.utc))
    assert recording_state(f,started.json()['recording_id'])==('interrupted','stopped','stored','incomplete')
    with sqlite3.connect(f['database']) as db:
        assert db.execute('SELECT status FROM jobs WHERE job_id=?',(job['job_id'],)).fetchone()[0]=='lost'
        assert db.execute('SELECT COUNT(*) FROM resource_quarantine').fetchone()[0]==1
    reconcile(f,datetime.now(timezone.utc))
    # A late worker can confirm facts, never turn this loss into a new replay source.
    receipt=w.client.finish_attempt(payload={'project_id':f['project'],'job_id':job['job_id'],'attempt_id':job['attempt_id'],
        'generation':job['generation'],'physical_key_id':job['physical_key_id'],'outcome':'error','final_seq':0,'last_ack_seq':0,
        'last_ack_hash':'sha256:'+hashlib.sha256(b'').hexdigest(),'manifest_digest':job['snapshot']['digest'],'evidence_complete':False,
        'ambiguous_dispatch':False,'cleanup_failed':False,'source_artifact_hashes':[before['artifact_id']],'action_mapping':'{}',
        'now':datetime.now(timezone.utc).isoformat()},idempotency_key='late-server-stop')
    assert receipt['status']=='lost'
    assert recording_state(f,started.json()['recording_id'])==('interrupted','stopped','stored','incomplete')
    async def read():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=f['app']),base_url='http://127.0.0.1') as c:
            headers=await session(c,f['project'])
            return await c.get('/api/v1/artifacts/'+before['artifact_id'],headers=headers)
    png=asyncio.run(read());assert png.status_code==200 and png.content.startswith(b'\x89PNG')
    no_materialization(f);assert f['model_sent']==[]
