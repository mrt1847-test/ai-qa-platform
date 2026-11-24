"""Real local HTTP/broker/evidence/finish journey; device and provider are explicit fixtures."""
import copy,json
from datetime import datetime,timezone
import pytest
from aiqa.contracts.jobs import ControlDecision
from aiqa.worker.http_client import WorkerHttpClient,WorkerClientSettings,SyncASGITransport
from aiqa.worker.runtime import WorkerRuntime,WorkerRuntimeConfig
from aiqa.worker.step_evidence import StepEvidenceCommitter
from test_replay_visual_evaluations import visual_job,recorded,ux_app
from test_rx_34 import _replay,_observation,_geometry


@pytest.mark.parametrize('status,verdict,actions',[
    ('satisfied','PASS',5),('violated','FAIL',2),('unknown','INCONCLUSIVE',5)])
def test_saved_native_replay_to_server_assertion_and_final_item(visual_job,tmp_path,status,verdict,actions):
    f=visual_job;job=copy.deepcopy(f['job'])
    f['provider'].reply=json.dumps({'status':status,'reason':'current fixture screen'})
    handler,calls=_replay(tmp_path,digest=job['snapshot']['replay_package_hash'])
    handler.context.require_case_context=True
    handler.context.remote_checkpoint=lambda phase:ControlDecision(True,phase)
    job['snapshot']['serial']=handler.context.expected_serial
    # Source fixture uses a 1000x2000 physical device; no real Android command is issued.
    observation=_observation(geometry=_geometry(physical=(1000,2000),model=(500,1000)))
    handler.context.step_observations=tuple((observation,observation) for _ in range(5))
    with WorkerHttpClient(WorkerClientSettings('https://127.0.0.1',f['token']),transport=SyncASGITransport(f['app'])) as client:
        handler.context.step_evidence_commit=StepEvidenceCommitter(client,job)
        handler.context.verification_client=client
        result=handler.handle(job)
        assert len(calls)==result.actions==actions
        assert handler.broker.authoring_calls==0
        assert result.check_results and all(row['result']['status']==status for row in result.check_results)
        finish_time=datetime.now(timezone.utc)
        runtime=WorkerRuntime(client,WorkerRuntimeConfig('fixture-boot',frozenset({'trial'})),handler,now=lambda:finish_time)
        receipt=runtime._submit_finish(job,result)
        assert receipt is not None and receipt['verdict']==verdict
        assert f['provider'].call_count==(1 if status=='violated' else 2)
        # A lost finish response confirms metadata; it cannot re-dispatch or re-evaluate.
        again=runtime._submit_finish(job,result)
        assert again['replayed'] is True and again['verdict']==verdict
        assert len(calls)==actions
    with f['store'].transaction() as c:
        rows=c.execute('SELECT status FROM check_results WHERE attempt_id=?',(job['attempt_id'],)).fetchall()
        assert rows and all(row[0]==status for row in rows)
        final=c.execute('SELECT core_result FROM item_finalizations WHERE case_run_id=?',(job['snapshot']['case_context']['owner_id'],)).fetchone()
        assert final[0]==verdict
