from dataclasses import replace
from pathlib import Path
import json,sqlite3,subprocess
import httpx,pytest
from test_rx97_recording_pin import recording,ux_app
from test_ma03b_mobile_history import engine_job,client
from test_rx_65 import _observation
from unit.test_openai_provider_settings import response
from unit.test_mobile_agent_context import reply
from aiqa.models.broker import ServerModelGateway
from aiqa.models.openai_server import OpenAIServerProvider
from aiqa.replay.android_runner import AndroidDeterministicDriver


def prepare(f,tmp_path,*,actions=None,capture=None,runner=None,checkpoint=None,allowed=None):
    from aiqa.worker.mobile_agent_recording import MobileAgentRecordingSession
    actions=actions or [{'action':'click','coordinate':[500,500]},{'action':'terminate','status':'success'}]
    def http(req):
        index=len(f['openai_sent']);f['openai_sent'].append(req)
        raw=response();raw['output'][-1]['content'][0]['text']=reply(actions[index])
        return httpx.Response(200,json=raw)
    f['app'].state.model_gateway=ServerModelGateway(provider=OpenAIServerProvider(transport=httpx.MockTransport(http)),resolver=f['resolver'])
    sent=[]
    def adb(argv,timeout):
        sent.append(tuple(argv))
        if runner:return runner(argv,timeout)
        return subprocess.CompletedProcess(argv,0,'','')
    driver=AndroidDeterministicDriver(Path('adb.exe'),'fixture-serial',runner=adb)
    c=client(f)
    session=MobileAgentRecordingSession(c,f['job'],driver=driver,capture=capture or _observation,
        output=tmp_path/'session',expected_serial='fixture-serial',checkpoint=checkpoint or (lambda phase:True),allowed=allowed or (lambda:True))
    return c,session,sent


def test_actual_original_main_to_server_model_driver_evidence_and_source(engine_job,tmp_path):
    f=engine_job;c,session,sent=prepare(f,tmp_path)
    with c:result=session.run()
    assert result.outcome=='completed' and result.review_pending and result.evidence_complete
    assert result.native_actions==1 and result.model_requests==2 and not result.ambiguous_dispatch
    source=json.loads(result.action_mapping)
    assert source['schema']=='android-native-trace-v2' and source['native_action_count']==1
    assert source['events'][0]['native']['x']==50 and source['events'][0]['native']['y']==100
    assert sent[0][-3:]==('tap','50','100') and len(sent)==1
    assert len(result.artifact_ids)==5 and result.last_ack_seq==2
    assert json.loads((tmp_path/'session/native-prefix.json').read_text())==source
    with sqlite3.connect(f['database']) as db:
        assert db.execute("SELECT COUNT(*) FROM artifact_objects WHERE role='before'").fetchone()[0]==2
        assert db.execute("SELECT COUNT(*) FROM artifact_objects WHERE role IN ('after','log')").fetchone()[0]==4
        assert db.execute("SELECT COUNT(*) FROM artifact_objects WHERE role='source'").fetchone()[0]==1
    assert result.process.receipt['main_invocations']==1


def test_wait_is_evidenced_without_native_and_then_original_main_continues(engine_job,tmp_path):
    actions=[{'action':'wait','time':0},{'action':'click','coordinate':[500,500]},{'action':'terminate','status':'success'}]
    c,session,sent=prepare(engine_job,tmp_path,actions=actions)
    with c:r=session.run()
    assert r.outcome=='completed' and r.native_actions==1 and r.model_requests==3
    assert len(sent)==1 and r.last_ack_seq==2 and len(r.artifact_ids)==7


def test_new_recording_preserves_target_condition_and_following_wait(engine_job,tmp_path):
    actions=[{'action':'click','coordinate':[500,500]}, {'action':'wait','time':.1},
        {'action':'terminate','status':'success'}]
    c,session,sent=prepare(engine_job,tmp_path,actions=actions)
    with c:result=session.run()
    assert result.outcome=='completed' and len(sent)==1
    event=json.loads(result.action_mapping)['events'][0]
    assert event['readiness']['width']==100 and event['readiness']['height']==200
    assert event['post_wait_seconds']>=2.1


def test_after_capture_failure_preserves_known_ack_before_return(engine_job,tmp_path):
    captures=[]
    def capture():
        captures.append(1)
        if len(captures)==3:raise OSError('fixture after capture failed')
        return _observation()
    c,session,sent=prepare(engine_job,tmp_path,capture=capture)
    with c:r=session.run()
    assert r.native_actions==1 and len(sent)==1 and r.model_requests==1
    assert not r.ambiguous_dispatch and r.action_mapping=='{}' and not r.review_pending
    prefix=json.loads((tmp_path/'session/native-prefix.json').read_text())
    assert prefix['native_action_count']==1
    assert session.journal.states(prefix['events'][0]['action_id'],engine_job['job']['attempt_id'])==('planned','dispatch_started','acknowledged')


def test_native_unknown_is_never_retried_or_sealed(engine_job,tmp_path):
    def fail(argv,timeout):raise subprocess.TimeoutExpired(argv,timeout)
    c,session,sent=prepare(engine_job,tmp_path,runner=fail)
    with c:r=session.run()
    assert r.ambiguous_dispatch and len(sent)==1 and r.native_actions==0 and r.model_requests==1
    assert r.action_mapping=='{}' and not r.review_pending
    turn=session.model_port.pending
    assert session.journal.states(turn.action_id,engine_job['job']['attempt_id'])[-1]=='unknown'


def test_drift_blocks_before_native_send(engine_job,tmp_path):
    captures=[]
    def capture():
        captures.append(1)
        return _observation(fill=b'\x00\xff\x00' if len(captures)>1 else b'\xff\x00\x00')
    c,session,sent=prepare(engine_job,tmp_path,capture=capture)
    with c:r=session.run()
    assert sent==[] and r.native_actions==0 and not r.ambiguous_dispatch
    assert r.model_requests==1 and r.action_mapping=='{}'


def test_final_gate_after_started_refuses_without_unknown_or_send(engine_job,tmp_path):
    c,session,sent=prepare(engine_job,tmp_path,checkpoint=lambda phase:phase!='before_native')
    with c:r=session.run()
    assert sent==[] and r.native_actions==0 and not r.ambiguous_dispatch
    assert session.journal.states(session.model_port.pending.action_id,engine_job['job']['attempt_id'])[-1]=='not_sent'


def test_same_attempt_directory_cannot_restart_recording(engine_job,tmp_path):
    c,session,sent=prepare(engine_job,tmp_path)
    with c:
        r=session.run()
        with pytest.raises(ValueError,match='already exists'):session.run()
    assert r.native_actions==1 and len(sent)==1 and len(engine_job['openai_sent'])==2


def test_source_ack_failure_keeps_native_and_step_proofs_but_no_ready_source(engine_job,tmp_path,monkeypatch):
    from aiqa.worker.http_client import WorkerHttpError,RetryClass
    c,session,sent=prepare(engine_job,tmp_path);commit=c.commit_evidence
    def send(**payload):
        if any(p['role']=='source' for p in payload['artifacts']):raise WorkerHttpError('fixture source failure',retry_class=RetryClass.fatal)
        return commit(**payload)
    monkeypatch.setattr(c,'commit_evidence',send)
    with c:r=session.run()
    assert r.native_actions==1 and r.model_requests==2 and r.last_ack_seq==2
    assert len(sent)==1 and r.action_mapping=='{}' and not r.review_pending
    assert (tmp_path/'session/evidence-delivery.json').is_file()


def test_native_prefix_write_failure_preserves_count_and_stops(engine_job,tmp_path,monkeypatch):
    import aiqa.worker.mobile_agent_recording as recording_module
    c,session,sent=prepare(engine_job,tmp_path);write=recording_module.atomic_write
    def fail(path,data):
        if path.name=='native-prefix.json':raise OSError('fixture disk failed')
        return write(path,data)
    monkeypatch.setattr(recording_module,'atomic_write',fail)
    with c:r=session.run()
    assert r.native_actions==1 and len(sent)==1 and not r.review_pending and r.model_requests==1
    assert r.action_mapping=='{}' and r.reason=='native_persistence_failed'


def test_current_authority_is_required_before_source_promotion(engine_job,tmp_path):
    c,session,sent=prepare(engine_job,tmp_path,checkpoint=lambda phase:phase!='before_source')
    with c:r=session.run()
    assert r.native_actions==1 and r.model_requests==2 and len(sent)==1
    assert r.action_mapping=='{}' and not r.review_pending
    with sqlite3.connect(engine_job['database']) as db:
        assert db.execute("SELECT COUNT(*) FROM artifact_objects WHERE role='source'").fetchone()[0]==0


def test_terminal_without_physical_action_is_not_a_replayable_recording(engine_job,tmp_path):
    c,session,sent=prepare(engine_job,tmp_path,actions=[{'action':'terminate','status':'success'}])
    with c:r=session.run()
    assert r.native_actions==0 and r.model_requests==1 and sent==[]
    assert r.outcome=='failed' and r.reason=='no_native_actions' and not r.review_pending
    assert r.action_mapping=='{}' and r.evidence_complete


def test_attempt_cutoff_still_applies_after_original_main_returns(engine_job,tmp_path,monkeypatch):
    import aiqa.worker.mobile_agent_recording as recording_module
    clock=[0.0]
    monkeypatch.setattr(recording_module,'monotonic',lambda:clock[0],raising=False)
    def checkpoint(phase):
        if phase=='after_final_turn':clock[0]=1000.0
        return True
    c,session,sent=prepare(engine_job,tmp_path,checkpoint=checkpoint)
    with c:r=session.run()
    assert r.native_actions==1 and len(sent)==1 and r.model_requests==2
    assert r.action_mapping=='{}' and not r.review_pending
    with sqlite3.connect(engine_job['database']) as db:
        assert db.execute("SELECT COUNT(*) FROM artifact_objects WHERE role='source'").fetchone()[0]==0


def test_ack_journal_failure_still_writes_independent_native_prefix(engine_job,tmp_path):
    c,session,sent=prepare(engine_job,tmp_path)
    session.journal.fail_on('acknowledged')
    with c:r=session.run()
    assert r.native_actions==1 and len(sent)==1 and r.model_requests==1
    assert r.reason=='native_persistence_failed' and not r.review_pending
    prefix=json.loads((tmp_path/'session/native-prefix.json').read_text())
    assert prefix['native_action_count']==1 and prefix['events'][0]['native']['x']==50


@pytest.mark.parametrize('mode',['raise','deny'])
def test_final_authority_failure_retains_prior_native_and_evidence(engine_job,tmp_path,monkeypatch,mode):
    import aiqa.worker.mobile_agent_recording as recording_module
    completed=[False];run=recording_module.run_mobile_agent_process
    def process(**kwargs):
        result=run(**kwargs);completed[0]=True;return result
    def allowed():
        if completed[0]:
            if mode=='raise':raise OSError('fixture authority port failed')
            return False
        return True
    monkeypatch.setattr(recording_module,'run_mobile_agent_process',process)
    c,session,sent=prepare(engine_job,tmp_path,allowed=allowed)
    with c:r=session.run()
    assert r.native_actions==1 and len(sent)==1 and r.model_requests==2
    assert r.last_ack_seq==2 and r.reason=='final_authority_refused' and not r.review_pending
    assert r.action_mapping=='{}'


def test_cancel_during_source_upload_retains_ack_without_promotion(engine_job,tmp_path,monkeypatch):
    active=[True]
    c,session,sent=prepare(engine_job,tmp_path,allowed=lambda:active[0]);commit=c.commit_evidence
    def send(**payload):
        result=commit(**payload)
        if any(p['role']=='source' for p in payload['artifacts']):active[0]=False
        return result
    monkeypatch.setattr(c,'commit_evidence',send)
    with c:r=session.run()
    assert r.native_actions==1 and len(sent)==1 and r.model_requests==2
    assert r.action_mapping=='{}' and not r.review_pending and r.last_ack_seq==2
    assert len(r.artifact_ids)==5 and r.reason=='final_authority_refused'
    with sqlite3.connect(engine_job['database']) as db:
        assert db.execute("SELECT COUNT(*) FROM artifact_objects WHERE role='source'").fetchone()[0]==1


@pytest.mark.parametrize('worker',[None,'',' ',False])
def test_invalid_durable_owner_is_rejected_before_any_model_or_native(engine_job,tmp_path,worker):
    from copy import deepcopy
    from aiqa.worker.mobile_agent_recording import MobileAgentRecordingSession
    claim=deepcopy(engine_job['job']);claim['worker_id']=worker
    driver=AndroidDeterministicDriver(Path('adb.exe'),'fixture-serial')
    with client(engine_job) as c,pytest.raises(ValueError,match='owner'):
        MobileAgentRecordingSession(c,claim,driver=driver,capture=_observation,output=tmp_path/'session',
            expected_serial='fixture-serial',checkpoint=lambda phase:True,allowed=lambda:True)
    assert driver.native_calls==0 and engine_job['openai_sent']==[]
    assert not (tmp_path/'session').exists()


def test_child_closed_after_model_does_not_send_or_seal(engine_job,tmp_path,monkeypatch):
    import sys
    import aiqa.worker.mobile_agent_process as process
    start=subprocess.Popen
    children=[]
    prelude="import sys,time,json\nfrom aiqa.worker.mobile_agent_ipc import read_packet,write_packet\nfrom aiqa.adapters.mobile_agent_upstream import load_protocol\nconfig=read_packet(sys.stdin.buffer)\nsequence=0\ntag='AIQA_'+'a'*32+'_'*43\npath=tag+'/screenshot_0.png'\ndef rpc(op,payload):\n    global sequence\n    sequence+=1\n    write_packet(sys.stdout.buffer,{'v':1,'id':sequence,'op':op,'payload':payload})\n    return read_packet(sys.stdin.buffer)['result']\n"
    body="rpc('capture',{'path':path})\np=load_protocol()\nmessages=p.build_messages(path,tag+' ('+config['instruction']+')',[],'gpt-6-luna')\nrpc('model',{'messages':messages})\nimport os\nos._exit(1)\n"
    def track(*args,**kwargs):
        child=start([sys.executable,'-B','-c',prelude+body],**kwargs)
        children.append(child);return child
    monkeypatch.setattr(process.subprocess,'Popen',track)
    c,session,sent=prepare(engine_job,tmp_path)
    with c:result=session.run()
    assert result.outcome=='failed' and result.reason=='child_closed'
    assert sent==[] and result.native_actions==0 and result.model_requests==1
    assert not result.ambiguous_dispatch and result.action_mapping=='{}' and not result.review_pending
    assert children[0].poll() not in (None,0)
    with sqlite3.connect(engine_job['database']) as db:
        assert db.execute("SELECT COUNT(*) FROM artifact_objects WHERE role='source'").fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM approval_events').fetchone()[0]==0
