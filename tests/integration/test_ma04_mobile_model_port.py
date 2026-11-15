from dataclasses import asdict,replace
import json,sqlite3
from uuid import uuid4
import pytest
from test_rx97_recording_pin import recording,ux_app
from test_ma03b_mobile_history import engine_job,client,commit,proof_parts
from test_rx_65 import _observation
from aiqa.worker.mobile_agent_process import MobileAgentModelFrame


def frame():
    obs=_observation()
    return MobileAgentModelFrame(obs.observation_id,obs.captured_at,obs.geometry,obs.png,obs.platform)


def make_port(f,c):
    from aiqa.worker.mobile_agent_models import MobileAgentModelPort
    return MobileAgentModelPort(c,f['job'])


def test_worker_callback_uploads_owned_before_and_sends_no_child_instructions(engine_job):
    f=engine_job;boundary=[]
    with client(f) as c:
        port=make_port(f,c);content=port({'current':frame(),'messages':['worker system override']},before_send=lambda:boundary.append(1))
        turn=port.pending
        assert turn and content==turn.content and len(boundary)==1 and port.model_requests==1
        assert turn.action_id=='ma-'+turn.call_id and turn.receipt()['usage']['input_tokens']==100
        assert turn.action.kind=='tap' and (turn.action.x,turn.action.y)==(50,100)
        with sqlite3.connect(f['database']) as connection:
            row=connection.execute('SELECT action_id,role FROM artifact_objects WHERE project_id=? AND artifact_id=(SELECT artifact_id FROM model_observations WHERE project_id=? AND call_id=?)',
                (f['project'],f['project'],turn.call_id)).fetchone()
        assert row==(turn.action_id,'before')
        assert 'worker system override' not in f['openai_sent'][0].content.decode()


def test_pending_native_evidence_blocks_next_model_until_server_ack(engine_job):
    from aiqa.worker.mobile_agent_models import ModelPortRejected
    f=engine_job
    with client(f) as c:
        port=make_port(f,c);current=frame();port({'current':current},before_send=lambda:None);turn=port.pending
        with pytest.raises(ModelPortRejected,match='evidence pending'):port({'current':frame()},before_send=lambda:None)
        assert len(f['openai_sent'])==1
        obs=replace(_observation(),observation_id=current.observation_id,captured_at=current.captured_at,png=current.png,geometry=current.geometry)
        parts=proof_parts(f,{'call_id':turn.call_id},obs);ack=commit(f,parts,'native-'+turn.call_id)
        port.accept_evidence(turn.call_id,ack,after_id=ack['artifact_ids'][0],log_id=ack['artifact_ids'][1])
        assert port.pending is None
        port({'current':frame()},before_send=lambda:None)
        assert len(f['openai_sent'])==2


def test_before_send_cancel_is_not_a_model_api_attempt(engine_job):
    f=engine_job
    with client(f) as c:
        port=make_port(f,c)
        def cancel():raise RuntimeError('cancelled')
        with pytest.raises(RuntimeError,match='cancelled'):port({'current':frame()},before_send=cancel)
        assert port.stopped and port.model_requests==0 and len(f['openai_sent'])==0


def test_wrong_ack_cannot_release_pending_step(engine_job):
    from aiqa.worker.mobile_agent_models import ModelPortRejected
    f=engine_job
    with client(f) as c:
        port=make_port(f,c);port({'current':frame()},before_send=lambda:None);turn=port.pending
        after_id,log_id=str(uuid4()),str(uuid4())
        with pytest.raises(ModelPortRejected):port.accept_evidence(turn.call_id,{'late':True,'attempt_id':f['job']['attempt_id'],'artifact_ids':[after_id,log_id]},after_id=after_id,log_id=log_id)
        assert port.pending==turn and len(f['openai_sent'])==1


def test_mismatched_server_receipt_stops_without_retry(engine_job,monkeypatch):
    from aiqa.worker.mobile_agent_models import ModelPortRejected
    f=engine_job
    with client(f) as c:
        request=c.request_model
        def mismatch(**kwargs):result=request(**kwargs);result['generation']+=1;return result
        monkeypatch.setattr(c,'request_model',mismatch);port=make_port(f,c)
        with pytest.raises(ModelPortRejected):port({'current':frame()},before_send=lambda:None)
        assert port.stopped and port.pending is None
        with pytest.raises(ModelPortRejected):port({'current':frame()},before_send=lambda:None)
        assert len(f['openai_sent'])==1


def acknowledge(f,port,current):
    turn=port.pending
    obs=replace(_observation(),observation_id=current.observation_id,captured_at=current.captured_at,png=current.png,geometry=current.geometry)
    parts=proof_parts(f,{'call_id':turn.call_id},obs);ack=commit(f,parts,'native-'+turn.call_id)
    port.accept_evidence(turn.call_id,ack,after_id=ack['artifact_ids'][0],log_id=ack['artifact_ids'][1])
    return ack


def test_reusing_a_capture_after_ack_is_refused_before_a_new_model_request(engine_job):
    from aiqa.worker.mobile_agent_models import ModelPortRejected
    f=engine_job
    with client(f) as c:
        port=make_port(f,c);current=frame();port({'current':current},before_send=lambda:None);acknowledge(f,port,current)
        with pytest.raises(ModelPortRejected,match='frame invalid'):port({'current':current},before_send=lambda:None)
        assert port.stopped and port.model_requests==1 and len(f['openai_sent'])==1


@pytest.mark.parametrize('recording',[('max_model_calls',1)],indirect=True)
def test_local_frozen_call_limit_stops_before_upload_or_model(engine_job):
    from aiqa.worker.mobile_agent_models import ModelPortRejected
    f=engine_job
    with client(f) as c:
        port=make_port(f,c);current=frame();port({'current':current},before_send=lambda:None);acknowledge(f,port,current)
        with pytest.raises(ModelPortRejected,match='request limit'):port({'current':frame()},before_send=lambda:None)
        assert port.model_requests==1 and len(f['openai_sent'])==1
        with sqlite3.connect(f['database']) as connection:assert connection.execute('SELECT COUNT(*) FROM model_observations').fetchone()[0]==1


def test_claim_and_receipt_snapshots_do_not_share_mutable_inputs(engine_job):
    f=engine_job
    with client(f) as c:
        port=make_port(f,c);f['job']['snapshot']['limits']['max_model_calls']=0
        port({'current':frame()},before_send=lambda:None)
        turn=port.pending;turn.receipt()['usage']['input_tokens']=9999
        assert turn.receipt()['usage']['input_tokens']==100 and port.model_requests==1


def test_reentrant_model_request_is_refused_without_a_second_upload(engine_job):
    from aiqa.worker.mobile_agent_models import ModelPortRejected
    f=engine_job
    with client(f) as c:
        port=make_port(f,c)
        def boundary():
            with pytest.raises(ModelPortRejected,match='in progress'):port({'current':frame()},before_send=lambda:None)
        port({'current':frame()},before_send=boundary)
        assert port.model_requests==1 and len(f['openai_sent'])==1


def test_sensitive_claim_fails_before_any_evidence_or_model(engine_job):
    from copy import deepcopy
    from aiqa.worker.mobile_agent_models import MobileAgentModelPort,ModelPortRejected
    f=engine_job;claim=deepcopy(f['job']);claim['snapshot']['intent']['secret_refs']={'target':{'ref_id':'sensitive'}}
    with client(f) as c:
        with pytest.raises(ModelPortRejected):MobileAgentModelPort(c,claim)
    with sqlite3.connect(f['database']) as connection:assert connection.execute('SELECT COUNT(*) FROM artifact_objects').fetchone()[0]==0
    assert len(f['openai_sent'])==0


def test_uncertain_model_http_error_never_retries(engine_job,monkeypatch):
    from aiqa.worker.http_client import WorkerHttpError,RetryClass
    from aiqa.worker.mobile_agent_models import ModelPortRejected
    f=engine_job;calls=[]
    with client(f) as c:
        def uncertain(**kwargs):
            calls.append(kwargs)
            raise WorkerHttpError('unknown model send',retry_class=RetryClass.fatal,provider_dispatched=None)
        monkeypatch.setattr(c,'request_model',uncertain);port=make_port(f,c)
        with pytest.raises(WorkerHttpError):port({'current':frame()},before_send=lambda:None)
        with pytest.raises(ModelPortRejected):port({'current':frame()},before_send=lambda:None)
        assert port.stopped and port.model_requests==1 and len(calls)==1


def test_prior_turn_ack_cannot_clear_the_next_pending_turn(engine_job):
    from aiqa.worker.mobile_agent_models import ModelPortRejected
    f=engine_job
    with client(f) as c:
        port=make_port(f,c);current=frame();port({'current':current},before_send=lambda:None);old_ack=acknowledge(f,port,current)
        port({'current':frame()},before_send=lambda:None);pending=port.pending
        with pytest.raises(ModelPortRejected):port.accept_evidence(pending.call_id,old_ack,after_id=old_ack['artifact_ids'][0],log_id=old_ack['artifact_ids'][1])
        assert port.pending==pending
        with pytest.raises(ModelPortRejected,match='evidence pending'):port({'current':frame()},before_send=lambda:None)
        assert port.model_requests==2 and len(f['openai_sent'])==2


def test_pending_frame_geometry_does_not_alias_caller_bounds(engine_job):
    f=engine_job;current=frame();bounds=list(current.geometry.content_bounds)
    current=replace(current,geometry=replace(current.geometry,content_bounds=bounds))
    with client(f) as c:
        port=make_port(f,c);port({'current':current},before_send=lambda:None)
        bounds[0]=1
        assert port.pending.frame.geometry.content_bounds==(0,0,100,200)


def test_non_string_claim_uuid_is_a_controlled_refusal(engine_job):
    from copy import deepcopy
    from aiqa.worker.mobile_agent_models import MobileAgentModelPort,ModelPortRejected
    f=engine_job;claim=deepcopy(f['job']);claim['project_id']=42
    with client(f) as c:
        with pytest.raises(ModelPortRejected):MobileAgentModelPort(c,claim)
    assert f['openai_sent']==[]
