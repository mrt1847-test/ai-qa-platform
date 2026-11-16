from dataclasses import replace
from datetime import datetime,timezone,timedelta
import sqlite3
import pytest
from test_rx97_recording_pin import recording,ux_app
from test_ma03b_mobile_history import engine_job,client,proof_parts
from test_ma04_mobile_model_port import frame,make_port
from test_rx_65 import _observation
from aiqa.worker.step_evidence import StepEvidenceCommitter
from aiqa.worker.http_client import WorkerHttpError,RetryClass


def post_parts(f,port):
    current=port.pending.frame
    before=replace(_observation(),observation_id=current.observation_id,captured_at=current.captured_at,geometry=current.geometry,png=current.png)
    return proof_parts(f,{'call_id':port.pending.call_id},before)


def test_lost_ack_restart_resends_only_identical_evidence_and_releases_same_turn(engine_job,tmp_path,monkeypatch):
    f=engine_job;path=tmp_path/'delivery.json';sent=[]
    with client(f) as c:
        port=make_port(f,c);port({'current':frame()},before_send=lambda:None);turn=port.pending;parts=post_parts(f,port)
        commit=c.commit_evidence
        def lose(**payload):
            sent.append(payload);commit(**payload)
            raise WorkerHttpError('lost response',retry_class=RetryClass.fatal)
        monkeypatch.setattr(c,'commit_evidence',lose)
        from aiqa.worker.android_jobs import android_evidence_events
        current=turn.frame
        before=replace(_observation(),observation_id=current.observation_id,captured_at=current.captured_at,geometry=current.geometry,png=current.png)
        events=list(android_evidence_events(attempt_id=f['job']['attempt_id'],action_id=turn.action_id,before=before,after=_observation(fill=b'\x00\xff\x00'),action_seq=1))
        delivery=StepEvidenceCommitter(c,f['job'],namespace='mobile',pending_path=path)
        with pytest.raises(WorkerHttpError):delivery(action_seq=1,action_id=turn.action_id,events=events,artifacts=parts)
        assert port.pending==turn
        def recover(**payload):sent.append(payload);return commit(**payload)
        monkeypatch.setattr(c,'commit_evidence',recover)
        restored=StepEvidenceCommitter(c,f['job'],namespace='mobile',pending_path=path,clock=lambda:datetime.now(timezone.utc)+timedelta(days=1))
        ack=restored.resume_pending()
        assert sent[0]==sent[1] and len(f['openai_sent'])==1 and ack['contiguous_seq']==2
        port.accept_evidence(turn.call_id,ack,after_id=ack['artifact_ids'][0],log_id=ack['artifact_ids'][1])
        assert port.pending is None and restored.resume_pending() is None
        with sqlite3.connect(f['database']) as connection:assert connection.execute('SELECT COUNT(*) FROM artifact_objects').fetchone()[0]==3


def test_ack_journal_write_failure_preserves_recoverable_packet(engine_job,tmp_path,monkeypatch):
    import aiqa.worker.step_evidence as evidence
    f=engine_job;path=tmp_path/'delivery.json';write=evidence.atomic_write;writes=[]
    def fail_second(*args,**kwargs):
        writes.append(1)
        if len(writes)==2:raise OSError('fixture ACK journal failure')
        return write(*args,**kwargs)
    monkeypatch.setattr(evidence,'atomic_write',fail_second)
    with client(f) as c:
        port=make_port(f,c);port({'current':frame()},before_send=lambda:None);turn=port.pending;parts=post_parts(f,port)
        delivery=StepEvidenceCommitter(c,f['job'],namespace='mobile',pending_path=path)
        with pytest.raises(WorkerHttpError):delivery(action_seq=1,action_id=turn.action_id,events=[],artifacts=parts)
        assert port.pending==turn and len(f['openai_sent'])==1
        ack=StepEvidenceCommitter(c,f['job'],namespace='mobile',pending_path=path).resume_pending()
        assert ack['late'] is False and len(f['openai_sent'])==1
        port.accept_evidence(turn.call_id,ack,after_id=ack['artifact_ids'][0],log_id=ack['artifact_ids'][1])
        with sqlite3.connect(f['database']) as connection:assert connection.execute('SELECT COUNT(*) FROM artifact_objects').fetchone()[0]==3
