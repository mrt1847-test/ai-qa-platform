"""Worker consumes a fresh fence response, deducting full request latency."""
from datetime import datetime,timedelta,timezone
from uuid import uuid4
import pytest
from aiqa.worker.checkpoints import WorkerAttemptCheckpoint


def claim():return {'project_id':str(uuid4()),'job_id':str(uuid4()),'attempt_id':str(uuid4()),'generation':1}


class Client:
    def __init__(self,owner):self.owner=owner;self.calls=[];self.change={}
    def checkpoint(self,**kwargs):
        self.calls.append(kwargs);now=datetime.now(timezone.utc)
        return {**self.owner,'phase':kwargs['phase'],'allowed':True,'server_time':now.isoformat(),
            'job_deadline':(now+timedelta(seconds=60)).isoformat(),'lease_remaining_seconds':45,**self.change}


def test_each_phase_uses_a_new_authenticated_check_and_never_caches_allow():
    owner=claim();client=Client(owner);control=WorkerAttemptCheckpoint(client,owner)
    assert control.checkpoint('before_dispatch').allowed is True
    assert control.checkpoint('before_dispatch').allowed is True
    assert len(client.calls)==2
    assert client.calls[0]['idempotency_key']!=client.calls[1]['idempotency_key']
    assert all('now' not in item for item in client.calls)


@pytest.mark.parametrize('change',[{'project_id':str(uuid4())},{'job_id':str(uuid4())},{'attempt_id':str(uuid4())},
    {'generation':True},{'generation':2},{'phase':'before_model'},{'allowed':'true'},
    {'lease_remaining_seconds':True},{'lease_remaining_seconds':float('nan')},
    {'lease_remaining_seconds':float('inf')},{'lease_remaining_seconds':9},
    {'lease_remaining_seconds':46},{'job_deadline':'not-a-date'},
    {'server_time':'2026-01-01T00:00:00'},{'job_deadline':'2000-01-01T00:00:00+00:00'}])
def test_malformed_or_mismatched_response_is_not_executable(change):
    owner=claim();client=Client(owner);client.change=change
    assert WorkerAttemptCheckpoint(client,owner).checkpoint('before_dispatch').allowed is False


def test_roundtrip_latency_can_exhaust_the_lease_before_native_send():
    owner=claim();client=Client(owner);ticks=iter((0.0,40.0))
    assert WorkerAttemptCheckpoint(client,owner,clock=lambda:next(ticks)).checkpoint('before_dispatch').allowed is False


def test_transport_rejection_stops_without_returning_raw_error():
    from aiqa.worker.http_client import WorkerHttpError,RetryClass
    owner=claim()
    class Rejected:
        def checkpoint(self,**kwargs):raise WorkerHttpError('raw-sensitive',retry_class=RetryClass.auth,status_code=403)
    decision=WorkerAttemptCheckpoint(Rejected(),owner).checkpoint('before_dispatch')
    assert decision.allowed is False and 'raw-sensitive' not in decision.reason


def test_missing_client_checkpoint_support_is_fail_closed():
    assert WorkerAttemptCheckpoint(object(),claim()).checkpoint('before_dispatch').allowed is False
