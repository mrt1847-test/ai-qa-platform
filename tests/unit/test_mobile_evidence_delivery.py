from copy import deepcopy
from datetime import datetime,timezone,timedelta
from pathlib import Path
from uuid import uuid4
import hashlib,json
import pytest
from aiqa.worker.step_evidence import StepEvidenceCommitter
from aiqa.worker.http_client import WorkerHttpError,RetryClass


def claim():return {'project_id':str(uuid4()),'job_id':str(uuid4()),'attempt_id':str(uuid4()),'generation':1,'worker_id':'worker-A'}


class Client:
    def __init__(self,owner,*,fail=False):self.owner=owner;self.sent=[];self.fail=fail;self.cursor=0
    def commit_evidence(self,**payload):
        self.sent.append(deepcopy(payload))
        if self.fail:raise WorkerHttpError('response lost',retry_class=RetryClass.fatal)
        return {'attempt_id':self.owner['attempt_id'],'late':False,'contiguous_seq':self.cursor,'prefix_hash':'sha256:'+'0'*64,
                'artifact_ids':[str(uuid4()) for _ in payload['artifacts']]}


def send(committer,seq=1,body='fixed'):
    return committer(action_seq=seq,action_id='action',events=[],artifacts=[{'fixture':body}])


def test_mobile_supports_80_model_turns_and_source_but_legacy_stays_bounded():
    owner=claim();client=Client(owner);mobile=StepEvidenceCommitter(client,owner,namespace='mobile')
    for seq in range(1,82):assert send(mobile,seq)['late'] is False
    with pytest.raises(WorkerHttpError):send(mobile,82)
    legacy=StepEvidenceCommitter(client,owner)
    with pytest.raises(WorkerHttpError):send(legacy,52)


def test_pending_packet_survives_restart_with_identical_clock_key_and_body(tmp_path):
    owner=claim();client=Client(owner,fail=True);path=tmp_path/'pending.json';now=datetime.now(timezone.utc)
    first=StepEvidenceCommitter(client,owner,namespace='mobile',pending_path=path,clock=lambda:now)
    with pytest.raises(WorkerHttpError):send(first)
    assert path.exists() and len(client.sent)==1
    client.fail=False
    recovered=StepEvidenceCommitter(client,owner,namespace='mobile',pending_path=path,clock=lambda:now+timedelta(days=1))
    receipt=recovered.resume_pending()
    assert receipt['late'] is False and client.sent[0]==client.sent[1]
    before=len(client.sent)
    again=StepEvidenceCommitter(client,owner,namespace='mobile',pending_path=path)
    assert again.resume_pending() is None and send(again)==receipt and len(client.sent)==before


@pytest.mark.parametrize('bad',['owner','corrupt','payload'])
def test_corrupted_or_foreign_durable_state_never_uploads(tmp_path,bad):
    owner=claim();client=Client(owner,fail=True);path=tmp_path/'pending.json'
    first=StepEvidenceCommitter(client,owner,namespace='mobile',pending_path=path)
    with pytest.raises(WorkerHttpError):send(first)
    raw=json.loads(path.read_text())
    changed=deepcopy(owner)
    if bad=='owner':changed['generation']=2
    elif bad=='corrupt':path.write_text('not JSON')
    else:
        raw['entries']['1']['payload']['artifacts']=[{'fixture':'tampered'}]
        path.write_text(json.dumps(raw))
    client.fail=False
    restored=StepEvidenceCommitter(client,changed,namespace='mobile',pending_path=path)
    with pytest.raises(WorkerHttpError):restored.resume_pending()
    assert len(client.sent)==1


def test_durable_pending_prefix_refuses_a_new_payload(tmp_path):
    owner=claim();client=Client(owner,fail=True);path=tmp_path/'pending.json'
    first=StepEvidenceCommitter(client,owner,namespace='mobile',pending_path=path)
    with pytest.raises(WorkerHttpError):send(first)
    restored=StepEvidenceCommitter(client,owner,namespace='mobile',pending_path=path)
    with pytest.raises(WorkerHttpError):send(restored,2)
    with pytest.raises(WorkerHttpError):send(restored,1,body='changed')
    assert len(client.sent)==1


def test_journal_write_failure_never_sends_even_on_same_instance_retry(tmp_path,monkeypatch):
    import aiqa.worker.step_evidence as evidence
    owner=claim();client=Client(owner);path=tmp_path/'pending.json'
    def no_space(*args,**kwargs):raise OSError('fixture disk full')
    monkeypatch.setattr(evidence,'atomic_write',no_space)
    committer=StepEvidenceCommitter(client,owner,namespace='mobile',pending_path=path)
    for _ in range(2):
        with pytest.raises(WorkerHttpError):send(committer)
    assert client.sent==[]


def rehash(state):
    if 'checksum' in state:
        body={key:value for key,value in state.items() if key!='checksum'}
        state['checksum']=hashlib.sha256(json.dumps(body,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    return state


@pytest.mark.parametrize('change',['clock','artifact','prefix'])
def test_journal_checksum_covers_clock_and_cached_receipt(tmp_path,change):
    owner=claim();client=Client(owner,fail=change=='clock');path=tmp_path/'pending.json'
    committer=StepEvidenceCommitter(client,owner,namespace='mobile',pending_path=path)
    if change=='clock':
        with pytest.raises(WorkerHttpError):send(committer)
    else:send(committer)
    state=json.loads(path.read_text())
    if change=='clock':state['entries']['1']['payload']['now']=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
    elif change=='artifact':state['entries']['1']['receipt']['artifact_ids'][0]=str(uuid4())
    else:state['entries']['1']['receipt']['prefix_hash']='sha256:'+'f'*64
    path.write_text(json.dumps(state));client.fail=False;before=len(client.sent)
    restored=StepEvidenceCommitter(client,owner,namespace='mobile',pending_path=path)
    with pytest.raises(WorkerHttpError):send(restored)
    assert len(client.sent)==before


@pytest.mark.parametrize('change',['owner_bool','payload_bool','pending_bool','pending_float','expected_seq','pending_before_ack'])
def test_rechecksummed_malformed_state_is_refused_before_send(tmp_path,change):
    owner=claim();client=Client(owner,fail=True);path=tmp_path/'pending.json'
    committer=StepEvidenceCommitter(client,owner,namespace='mobile',pending_path=path)
    with pytest.raises(WorkerHttpError):send(committer)
    state=json.loads(path.read_text())
    if change=='owner_bool':state['owner']['generation']=True
    elif change=='payload_bool':state['entries']['1']['payload']['generation']=True
    elif change=='pending_bool':state['pending_seq']=True
    elif change=='pending_float':state['pending_seq']=1.0
    elif change=='expected_seq':state['entries']['1']['expected_seq']=5
    else:
        later=deepcopy(state['entries']['1']);later['payload']=None
        later['receipt']={'attempt_id':owner['attempt_id'],'late':False,'contiguous_seq':0,'prefix_hash':'sha256:'+'0'*64,'artifact_ids':[str(uuid4())]}
        state['entries']['2']=later
    path.write_text(json.dumps(rehash(state)));client.fail=False;before=len(client.sent)
    restored=StepEvidenceCommitter(client,owner,namespace='mobile',pending_path=path)
    with pytest.raises(WorkerHttpError):send(restored)
    assert len(client.sent)==before


def test_pending_expected_cursor_cannot_drop_preceding_ack(tmp_path):
    owner=claim();client=Client(owner);client.cursor=1;path=tmp_path/'pending.json'
    committer=StepEvidenceCommitter(client,owner,namespace='mobile',pending_path=path);send(committer)
    client.fail=True
    with pytest.raises(WorkerHttpError):send(committer,2,body='second')
    state=json.loads(path.read_text());state['entries']['2']['expected_seq']=0
    path.write_text(json.dumps(rehash(state)));client.fail=False;before=len(client.sent)
    restored=StepEvidenceCommitter(client,owner,namespace='mobile',pending_path=path)
    with pytest.raises(WorkerHttpError):send(restored,2,body='second')
    assert len(client.sent)==before


def test_naive_durable_clock_is_refused_before_write_or_send(tmp_path):
    owner=claim();client=Client(owner);path=tmp_path/'pending.json'
    committer=StepEvidenceCommitter(client,owner,namespace='mobile',pending_path=path,clock=lambda:datetime(2026,1,1))
    with pytest.raises(WorkerHttpError):send(committer)
    assert client.sent==[] and not path.exists()


def test_lock_acquisition_failure_is_a_controlled_metadata_error(tmp_path,monkeypatch):
    from contextlib import contextmanager
    import aiqa.worker.step_evidence as evidence
    owner=claim();client=Client(owner)
    @contextmanager
    def denied(*args,**kwargs):
        raise OSError('fixture lock inaccessible')
        yield
    monkeypatch.setattr(evidence,'file_lock',denied)
    committer=StepEvidenceCommitter(client,owner,namespace='mobile',pending_path=tmp_path/'pending.json')
    with pytest.raises(WorkerHttpError):send(committer)
    assert client.sent==[]
