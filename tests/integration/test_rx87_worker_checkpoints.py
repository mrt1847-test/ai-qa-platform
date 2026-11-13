"""Fresh server lease fence is independent of model permission and never caches allow."""
from datetime import datetime,timedelta,timezone
from uuid import UUID,uuid4
import pytest
from aiqa.api.auth import bound_auth_store,enroll_worker
from aiqa.store.models import Actor
from test_rx98_model_requests import model_job,recording,ux_app,ack,post,mutate


def body(f,**changes):
    return {'project_id':f['project'],'job_id':f['job']['job_id'],'attempt_id':f['job']['attempt_id'],
        'generation':f['job']['generation'],'phase':'before_dispatch',**changes}


def checkpoint(f,payload=None,token=None,key='fresh-check'):
    return post(f,payload or body(f),token=token,key=key,path='/api/v1/worker/checkpoints')


def test_normal_acked_worker_receives_current_fence_without_model_call(model_job):
    f=model_job;ack(f);result=checkpoint(f)
    assert result.status_code==200,result.text
    receipt=result.json();assert receipt['allowed'] is True and receipt['attempt_id']==f['job']['attempt_id']
    assert 10 < receipt['lease_remaining_seconds'] <=45
    deadline=datetime.fromisoformat(receipt['job_deadline'])
    assert datetime.now(timezone.utc)<deadline<=datetime.now(timezone.utc)+timedelta(seconds=31)
    assert receipt['phase']=='before_dispatch' and f['provider'].sent==0


@pytest.mark.parametrize('change',['unacked','job','attempt','generation','purpose','cancel','terminal','inactive','expired_lease','job_timeout','worker_boot','worker'])
def test_stale_or_cancelled_fence_cannot_authorize_native_send(model_job,change):
    f=model_job;payload=body(f);token=None
    if change!='unacked':ack(f)
    if change=='job':payload['job_id']=str(uuid4())
    elif change=='attempt':payload['attempt_id']=str(uuid4())
    elif change=='generation':payload['generation']+=1
    elif change=='purpose':
        store=f['app'].state.open_store()
        try:
            with bound_auth_store(store):token=enroll_worker(Actor(uuid4(),UUID(f['project']),True),'worker-w1605','regression')
        finally:store.close()
    elif change=='cancel':mutate(f,"UPDATE jobs SET status='cancel_requested' WHERE job_id=?",(f['job']['job_id'],))
    elif change=='terminal':mutate(f,"UPDATE jobs SET status='completed' WHERE job_id=?",(f['job']['job_id'],))
    elif change=='inactive':mutate(f,"UPDATE jobs SET status='queued' WHERE job_id=?",(f['job']['job_id'],))
    elif change=='expired_lease':mutate(f,"UPDATE leases SET expires_at=?",((datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(),))
    elif change=='job_timeout':mutate(f,"UPDATE claim_receipts SET created_at=?",((datetime.now(timezone.utc)-timedelta(seconds=32)).isoformat(),))
    elif change=='worker_boot':
        result=post(f,{'boot_id':'different-boot'},path='/api/v1/worker/heartbeats');assert result.status_code==200
    elif change=='worker':
        store=f['app'].state.open_store()
        try:
            with bound_auth_store(store):token=enroll_worker(Actor(uuid4(),UUID(f['project']),True),'foreign-worker','recording')
        finally:store.close()
    result=checkpoint(f,payload,token=token)
    assert result.status_code in (403,409),result.text
    assert f['provider'].sent==0


def test_same_key_is_fresh_after_cancellation_and_not_a_reusable_capability(model_job):
    f=model_job;ack(f);assert checkpoint(f).status_code==200
    mutate(f,"UPDATE jobs SET status='cancel_requested' WHERE job_id=?",(f['job']['job_id'],))
    denied=checkpoint(f);assert denied.status_code==403,denied.text
    assert f['provider'].sent==0


@pytest.mark.parametrize('change',[{'generation':True},{'phase':'run_shell'},{'now':'2099-01-01T00:00:00+00:00'}])
def test_worker_time_or_arbitrary_phase_is_not_server_authority(model_job,change):
    f=model_job;ack(f);result=checkpoint(f,body(f,**change))
    if 'now' in change:assert result.status_code==200 and result.json()['lease_remaining_seconds']>10
    else:assert result.status_code==422,result.text


def test_server_time_is_sampled_after_thread_queue_wait(model_job,monkeypatch):
    import aiqa.domain.worker_checkpoints as module
    f=model_job;ack(f);instant=datetime.now(timezone.utc);shift={'seconds':0}
    monkeypatch.setattr('aiqa.api.worker._server_now',lambda:instant+timedelta(seconds=shift['seconds']))
    original=module.checkpoint_http
    def queued(*args,**kwargs):
        shift['seconds']=32
        return original(*args,**kwargs)
    monkeypatch.setattr(module,'checkpoint_http',queued)
    denied=checkpoint(f);assert denied.status_code in (403,409),denied.text


def test_worker_http_client_uses_authenticated_checkpoint_without_worker_clock(model_job):
    import json
    from aiqa.worker.http_client import WorkerHttpClient,WorkerClientSettings,SyncASGITransport
    from test_rx99_model_observations import TraceTransport
    f=model_job;ack(f);transport=TraceTransport(f['app'])
    with WorkerHttpClient(WorkerClientSettings('https://127.0.0.1',f['token']),transport=transport) as client:
        receipt=client.checkpoint(project_id=f['project'],job_id=f['job']['job_id'],
            attempt_id=f['job']['attempt_id'],generation=f['job']['generation'],phase='before_dispatch',idempotency_key='http-check')
    assert receipt['allowed'] is True
    assert transport.requests[0].headers['Authorization']=='Bearer '+f['token']
    assert 'now' not in json.loads(transport.requests[0].content)
    assert f['provider'].sent==0
