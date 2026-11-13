"""Lost evidence ACK is confirmed without rerunning the already performed action."""
import base64
import hashlib
import json
import sqlite3
import httpx
from aiqa.worker.http_client import WorkerHttpClient,WorkerClientSettings,SyncASGITransport
from aiqa.worker.runtime import WorkerRuntime,WorkerRuntimeConfig
from test_rx98_model_requests import model_job,recording,ux_app,ack
from test_rx87_android_runtime import handler_for
from test_rx_65 import _observation


class Trace(httpx.BaseTransport):
    def __init__(self,app,lose=False):self.inner=SyncASGITransport(app);self.requests=[];self.lose=lose;self.lost=False
    def handle_request(self,request):
        self.requests.append(request);response=self.inner.handle_request(request)
        if self.lose and not self.lost and request.url.path.endswith('/evidence-commits'):
            assert response.status_code==200,response.text
            self.lost=True;raise httpx.ReadTimeout('mock committed evidence reply lost',request=request)
        return response


def test_repeated_step_confirmation_keeps_the_original_body_and_artifact(model_job,tmp_path):
    f=model_job;ack(f);handler=handler_for(tmp_path,f['job'],[]);obs=_observation()
    digest='sha256:'+hashlib.sha256(obs.png).hexdigest()
    artifact={'filename':'frame.png','media_type':'image/png','declared_hash':digest,'declared_length':len(obs.png),
        'body_b64':base64.b64encode(obs.png).decode('ascii'),'owner_kind':'REC','attempt_id':f['job']['attempt_id'],'role':'source'}
    trace=Trace(f['app'])
    with WorkerHttpClient(WorkerClientSettings('https://127.0.0.1',f['token']),transport=trace) as client:
        runtime=WorkerRuntime(client,WorkerRuntimeConfig('fixture-boot',frozenset({'recording'})),handler)
        runtime._bind_step_evidence_commit(f['job']);commit=handler.context.step_evidence_commit
        first=commit(action_seq=1,action_id='frame-only',events=[],artifacts=[artifact])
        again=commit(action_seq=1,action_id='frame-only',events=[],artifacts=[artifact])
    assert first['artifact_ids']==again['artifact_ids']
    assert len({r.content for r in trace.requests})==1
    assert f['provider'].sent==0 and handler.tap_count==0


def test_committed_but_lost_step_ack_does_not_repeat_model_or_native(model_job,tmp_path):
    f=model_job;ack(f);native=[];handler=handler_for(tmp_path,f['job'],native)
    handler.context.fixture_responses=('click(100,200)','finish()');trace=Trace(f['app'],lose=True)
    with WorkerHttpClient(WorkerClientSettings('https://127.0.0.1',f['token']),transport=trace) as client:
        runtime=WorkerRuntime(client,WorkerRuntimeConfig('fixture-boot',frozenset({'recording'})),handler)
        runtime._bind_step_evidence_commit(f['job'])
        result=handler.handle(f['job'])
    assert result.outcome=='completed' and result.actions==1 and len(native)==1
    assert handler.authoring_calls_seen==2 and f['provider'].sent==0
    requests=[r for r in trace.requests if r.url.path.endswith('/evidence-commits')]
    assert len(requests)>=3 and requests[0].content==requests[1].content
    assert requests[0].headers['Idempotency-Key']==requests[1].headers['Idempotency-Key']
    with sqlite3.connect(f['database']) as c:
        assert c.execute('SELECT COUNT(*) FROM attempt_events WHERE attempt_id=?',(f['job']['attempt_id'],)).fetchone()[0]==2
