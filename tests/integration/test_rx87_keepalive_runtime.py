"""Runtime stops its control session before terminal upload/cleanup, including failure."""
import pytest
from aiqa.worker.http_client import WorkerHttpClient,WorkerClientSettings
from aiqa.worker.runtime import WorkerRuntime,WorkerRuntimeConfig
from aiqa.worker.keepalive import WorkerAttemptKeepalive
from test_rx99_model_observations import TraceTransport
from test_rx98_model_requests import model_job,recording,ux_app
from test_rx87_android_runtime import handler_for


@pytest.mark.parametrize('mode',['ok','shutdown_failed','failed'])
def test_runtime_control_lifetime_precedes_finish_and_cleanup(model_job,tmp_path,monkeypatch,mode):
    f=model_job;events=[];errors=[];calls=[];handler=handler_for(tmp_path,f['job'],calls)
    handler.context.fixture_responses=('finish()',)
    class Session(WorkerAttemptKeepalive):
        def start(self):
            events.append('control-start')
            if mode=='failed':self._failed.set()
            return self
        def close(self):
            events.append('control-close');super().close()
            return mode!='shutdown_failed'
    class Transport(TraceTransport):
        def handle_request(self,request):
            events.append(request.url.path);response=super().handle_request(request)
            if response.status_code>=400:errors.append((request.url.path,response.status_code,response.json()))
            return response
    monkeypatch.setattr('aiqa.worker.keepalive.WorkerAttemptKeepalive',Session)
    with WorkerHttpClient(WorkerClientSettings('https://127.0.0.1',f['token']),transport=Transport(f['app'])) as client:
        # Return the already server-owned claim receipt; runtime still performs its real ACK.
        monkeypatch.setattr(client,'claim',lambda **kwargs:f['job'])
        runtime=WorkerRuntime(client,WorkerRuntimeConfig('fixture-boot',frozenset({'recording'})),handler)
        result=runtime.run_once()
        assert 'control-start' in events and 'control-close' in events
        assert events.index('/api/v1/worker/attempt-acks')<events.index('control-start')<events.index('control-close')
        if mode=='shutdown_failed':
            assert result.finished is False and result.reason=='control_shutdown_failed'
            assert not any(path.endswith('/attempt-finishes') or path.endswith('/cleanup-confirmations') for path in events)
            assert runtime.run_once().state=='stopped'
        else:
            assert result.finished is True,errors
            assert events.index('control-close')<events.index('/api/v1/worker/attempt-finishes')
        if mode=='failed':assert handler.broker.authoring_calls==0
    assert not calls and f['provider'].sent==0


def test_nonempty_evidence_gap_never_gets_a_fabricated_empty_prefix(model_job,monkeypatch):
    from aiqa.worker.runtime import HandlerResult,InertHandler
    from test_rx98_model_requests import ack
    f=model_job;ack(f)
    with WorkerHttpClient(WorkerClientSettings('https://127.0.0.1',f['token']),transport=TraceTransport(f['app'])) as client:
        runtime=WorkerRuntime(client,WorkerRuntimeConfig('fixture-boot',frozenset({'recording'})),InertHandler())
        result=HandlerResult(actions=1,outcome='error',evidence_complete=False,ambiguous_dispatch=True,
            final_seq=1,last_ack_seq=0,last_ack_hash='')
        assert runtime._submit_finish(f['job'],result) is None
        assert runtime.pending_finish['payload']['last_ack_hash']==''
