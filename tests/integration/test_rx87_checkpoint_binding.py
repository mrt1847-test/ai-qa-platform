"""Current server cancellation reaches the native boundary through runtime binding."""
import pytest
from aiqa.worker.http_client import WorkerHttpClient,WorkerClientSettings,SyncASGITransport
from aiqa.worker.runtime import WorkerRuntime,WorkerRuntimeConfig
from aiqa.worker.android_jobs import PurposeRoutedHandler
from test_rx98_model_requests import model_job,recording,ux_app,ack,mutate
from test_rx87_android_runtime import handler_for


@pytest.mark.parametrize('cancel_phase',['model','journal'])
def test_runtime_current_server_cancel_blocks_native_without_false_unknown(model_job,tmp_path,cancel_phase,monkeypatch):
    f=model_job;ack(f);calls=[];handler=handler_for(tmp_path,f['job'],calls)
    def cancel():mutate(f,"UPDATE jobs SET status='cancel_requested' WHERE job_id=?",(f['job']['job_id'],))
    def model(claim):
        if cancel_phase=='model':cancel()
        return 'click(100,200)'
    append=handler.journal.append
    def journal(*args):
        result=append(*args)
        if args[-1]=='dispatch_started' and cancel_phase=='journal':cancel()
        return result
    handler.context.plan_provider=model;monkeypatch.setattr(handler.journal,'append',journal)
    with WorkerHttpClient(WorkerClientSettings('https://127.0.0.1',f['token']),transport=SyncASGITransport(f['app'])) as client:
        runtime=WorkerRuntime(client,WorkerRuntimeConfig('fixture-boot',frozenset({'recording'})),
            PurposeRoutedHandler({'recording':handler}))
        runtime._bind_attempt_checkpoint(f['job'])
        result=handler.handle(f['job'])
    assert result.actions==0 and not calls and result.ambiguous_dispatch is False
    assert handler.stopped_reason=='remote_checkpoint_blocked' and f['provider'].sent==0
    assert not handler.journal.is_ambiguous(f['job']['attempt_id'],f"rec-{f['job']['attempt_id']}-1")
