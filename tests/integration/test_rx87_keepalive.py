"""Long authoring work keeps one live fence; failures never resume that attempt."""
from datetime import datetime,timedelta,timezone
import sqlite3
import threading
from uuid import uuid4
import pytest
from aiqa.worker.keepalive import WorkerAttemptKeepalive
from aiqa.worker.http_client import WorkerHttpClient,WorkerClientSettings,SyncASGITransport,WorkerHttpError,RetryClass
from test_rx98_model_requests import model_job,recording,ux_app,ack,mutate


def owner():return {'project_id':str(uuid4()),'job_id':str(uuid4()),'attempt_id':str(uuid4()),'generation':1}


class Client:
    def __init__(self,claim):self.claim=claim;self.pulses=0;self.fail=False
    def heartbeat(self,boot):
        self.pulses+=1
        if self.fail:raise WorkerHttpError('synthetic-private',retry_class=RetryClass.timeout)
        return {'state':'online'}
    def checkpoint(self,**kwargs):
        now=datetime.now(timezone.utc)
        return {**self.claim,'allowed':True,'phase':kwargs['phase'],'server_time':now.isoformat(),
            'job_deadline':(now+timedelta(seconds=120)).isoformat(),'lease_remaining_seconds':45}
    def renew(self,**kwargs):
        return {**self.claim,'expires_at':(datetime.now(timezone.utc)+timedelta(seconds=45)).isoformat(),
            'lease_seconds':45,'heartbeat_seconds':10,'poll_seconds':2}


def test_failed_control_latches_until_a_new_attempt_session():
    claim=owner();client=Client(claim);control=WorkerAttemptKeepalive(client,claim,'boot')
    assert control.pulse() is True
    client.fail=True;assert control.pulse() is False and control.failed is True
    client.fail=False;before=client.pulses
    assert control.pulse() is False and control.checkpoint('before_dispatch').allowed is False
    assert client.pulses==before
    assert WorkerAttemptKeepalive(client,{**claim,'attempt_id':str(uuid4())},'boot').failed is False


def test_background_thread_stops_and_cannot_restart_closed_session():
    claim=owner();client=Client(claim);control=WorkerAttemptKeepalive(client,claim,'boot',interval=.001)
    reached=threading.Event();heartbeat=client.heartbeat
    def observe(boot):result=heartbeat(boot);reached.set();return result
    client.heartbeat=observe
    control.start();assert reached.wait(timeout=1)
    assert control.close() is True and not control._thread.is_alive()
    assert control.checkpoint('before_dispatch').allowed is False
    with pytest.raises(ValueError):control.start()


def test_unjoined_control_thread_never_claims_successful_shutdown():
    claim=owner();client=Client(claim);entered=threading.Event();release=threading.Event()
    def blocked(boot):entered.set();release.wait(timeout=2);return {'state':'online'}
    client.heartbeat=blocked
    control=WorkerAttemptKeepalive(client,claim,'boot',interval=.001,join_timeout=.001)
    try:
        control.start();assert entered.wait(timeout=1)
        assert control.close() is False and control.failed is True
        assert control.checkpoint('before_dispatch').allowed is False
    finally:
        release.set();control._thread.join(timeout=1)


@pytest.mark.parametrize('recording',[('timeout_seconds',120)],indirect=True)
def test_real_server_lease_stays_live_beyond_initial_45_seconds_without_model_calls(model_job,monkeypatch):
    f=model_job;ack(f);initial=datetime.now(timezone.utc);clock={'seconds':0}
    monkeypatch.setattr('aiqa.api.worker._server_now',lambda:initial+timedelta(seconds=clock['seconds']))
    with WorkerHttpClient(WorkerClientSettings('https://127.0.0.1',f['token']),transport=SyncASGITransport(f['app'])) as client:
        control=WorkerAttemptKeepalive(client,f['job'],'fixture-boot')
        for elapsed in (10,20,30,40,50,60):
            clock['seconds']=elapsed;assert control.pulse() is True
            assert control.checkpoint('before_dispatch').allowed is True
        with sqlite3.connect(f['database']) as c:
            expires=datetime.fromisoformat(c.execute('SELECT expires_at FROM leases').fetchone()[0])
        assert expires>=initial+timedelta(seconds=104)
        assert control.close() is True
    assert f['provider'].sent==0


def test_cancellation_is_observed_before_another_renewal(model_job):
    f=model_job;ack(f)
    with WorkerHttpClient(WorkerClientSettings('https://127.0.0.1',f['token']),transport=SyncASGITransport(f['app'])) as client:
        control=WorkerAttemptKeepalive(client,f['job'],'fixture-boot')
        with sqlite3.connect(f['database']) as c:before=c.execute('SELECT expires_at FROM leases').fetchone()[0]
        mutate(f,"UPDATE jobs SET status='cancel_requested' WHERE job_id=?",(f['job']['job_id'],))
        assert control.pulse() is False and control.failed is True
        with sqlite3.connect(f['database']) as c:after=c.execute('SELECT expires_at FROM leases').fetchone()[0]
        assert before==after and control.checkpoint('before_dispatch').allowed is False
    assert f['provider'].sent==0


def test_failed_foreground_fence_cannot_resume_even_if_network_recovers():
    claim=owner();client=Client(claim);original=client.checkpoint
    control=WorkerAttemptKeepalive(client,claim,'boot')
    def unavailable(**kwargs):raise WorkerHttpError('synthetic-private',retry_class=RetryClass.timeout)
    client.checkpoint=unavailable
    assert control.checkpoint('before_dispatch').allowed is False and control.failed is True
    client.checkpoint=original
    assert control.checkpoint('before_dispatch').allowed is False


@pytest.mark.parametrize('blocked_at',['heartbeat','checkpoint','renewal'])
def test_foreground_failure_during_pulse_does_not_start_a_new_renewal(blocked_at):
    claim=owner();client=Client(claim);entered=threading.Event();release=threading.Event()
    original_heartbeat=client.heartbeat;original_checkpoint=client.checkpoint;original_renew=client.renew
    renewals=[];results=[];control=WorkerAttemptKeepalive(client,claim,'boot')
    def wait():entered.set();assert release.wait(timeout=2)
    def heartbeat(boot):
        if blocked_at=='heartbeat':wait()
        return original_heartbeat(boot)
    def checkpoint(**kwargs):
        if kwargs['phase']=='before_dispatch':
            raise WorkerHttpError('synthetic-fence-lost',retry_class=RetryClass.timeout)
        if blocked_at=='checkpoint':wait()
        return original_checkpoint(**kwargs)
    def renewal(**kwargs):
        renewals.append(kwargs)
        if blocked_at=='renewal':wait()
        return original_renew(**kwargs)
    client.heartbeat=heartbeat;client.checkpoint=checkpoint;client.renew=renewal
    thread=threading.Thread(target=lambda:results.append(control.pulse()))
    try:
        thread.start();assert entered.wait(timeout=1)
        assert control.checkpoint('before_dispatch').allowed is False and control.failed is True
    finally:
        release.set();thread.join(timeout=2)
    assert not thread.is_alive() and results==[False]
    assert len(renewals)==(1 if blocked_at=='renewal' else 0)
