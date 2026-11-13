"""Evidence retries are bounded and cannot advance an unconfirmed or changed prefix."""
import hashlib
from uuid import uuid4
from datetime import datetime,timezone
import pytest
from aiqa.worker.step_evidence import StepEvidenceCommitter
from aiqa.worker.http_client import WorkerHttpError,RetryClass


def fixture():
    owner={name:str(uuid4()) for name in ('project_id','job_id','attempt_id')};owner['generation']=1
    receipt={'attempt_id':owner['attempt_id'],'late':False,'contiguous_seq':0,
        'prefix_hash':'sha256:'+hashlib.sha256(b'').hexdigest(),'artifact_ids':[str(uuid4())]}
    class Client:
        def __init__(self):self.calls=[];self.error=None;self.receipt=receipt
        def commit_evidence(self,**kwargs):
            self.calls.append(kwargs)
            if self.error is not None:raise self.error
            return self.receipt
    return owner,Client(),{'filename':'proof.json'}


@pytest.mark.parametrize('retry,status,count',[(RetryClass.auth,401,1),(RetryClass.auth,403,1),
    (RetryClass.conflict,409,1),(RetryClass.fatal,422,1),(RetryClass.fatal,429,1),
    (RetryClass.tls,None,1),(RetryClass.timeout,None,2),(RetryClass.retryable,503,2)])
def test_only_transient_evidence_confirmation_repeats_once(retry,status,count):
    owner,client,artifact=fixture();client.error=WorkerHttpError('mock rejection',retry_class=retry,status_code=status)
    commit=StepEvidenceCommitter(client,owner)
    with pytest.raises(WorkerHttpError):commit(action_seq=1,action_id='source',events=[],artifacts=[artifact])
    assert len(client.calls)==count
    assert all(item==client.calls[0] for item in client.calls)


def test_changed_same_step_is_not_silently_replaced_by_cached_ack():
    owner,client,artifact=fixture();commit=StepEvidenceCommitter(client,owner)
    first=commit(action_seq=1,action_id='source',events=[],artifacts=[artifact])
    first['artifact_ids'].clear()
    again=commit(action_seq=1,action_id='source',events=[],artifacts=[artifact])
    assert again['artifact_ids'] and len(client.calls)==1
    with pytest.raises(WorkerHttpError) as changed:
        commit(action_seq=1,action_id='source',events=[],artifacts=[{**artifact,'filename':'different.json'}])
    assert changed.value.status_code==409 and len(client.calls)==1


def test_unconfirmed_prefix_blocks_next_step_but_same_body_can_be_confirmed():
    owner,client,artifact=fixture();commit=StepEvidenceCommitter(client,owner)
    client.error=WorkerHttpError('mock response lost',retry_class=RetryClass.timeout)
    with pytest.raises(WorkerHttpError):commit(action_seq=1,action_id='source',events=[],artifacts=[artifact])
    with pytest.raises(WorkerHttpError) as blocked:
        commit(action_seq=2,action_id='next',events=[],artifacts=[artifact])
    assert blocked.value.status_code==409 and len(client.calls)==2
    client.error=None;commit(action_seq=1,action_id='source',events=[],artifacts=[artifact])
    assert len(client.calls)==3 and client.calls[0]==client.calls[-1]


@pytest.mark.parametrize('change',[{'attempt_id':str(uuid4())},{'late':True},{'contiguous_seq':True},
    {'prefix_hash':'broken'},{'artifact_ids':[]}])
def test_bad_ack_is_not_accepted_as_saved_evidence(change):
    owner,client,artifact=fixture();client.receipt={**client.receipt,**change};commit=StepEvidenceCommitter(client,owner)
    with pytest.raises(WorkerHttpError):commit(action_seq=1,action_id='source',events=[],artifacts=[artifact])
    assert len(client.calls)==1
