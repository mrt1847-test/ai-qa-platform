"""Worker timestamps identify evidence; server time/purpose decide whether it is active."""
import base64
import hashlib
from datetime import datetime,timedelta,timezone
from uuid import UUID,uuid4
import sqlite3
import json
import pytest
from aiqa.api.auth import bound_auth_store,enroll_worker
from aiqa.store.models import Actor
from test_rx98_model_requests import model_job,recording,ux_app,ack,post,mutate
from test_rx_65 import _observation


def payload(f,stamp):
    png=_observation().png
    return {'sanitized':True,'project_id':f['project'],'job_id':f['job']['job_id'],
        'generation':f['job']['generation'],'now':stamp.isoformat(),'events':[],
        'artifacts':[{'filename':'frame.png','media_type':'image/png','declared_hash':'sha256:'+hashlib.sha256(png).hexdigest(),
            'declared_length':len(png),'body_b64':base64.b64encode(png).decode('ascii'),
            'owner_kind':'REC','attempt_id':f['job']['attempt_id'],'role':'source'}]}


def upload(f,body,token=None,key='authority-frame'):
    return post(f,body,token=token,key=key,path='/api/v1/worker/evidence-commits')


def test_old_worker_timestamp_cannot_make_an_expired_new_upload_active(model_job,monkeypatch):
    f=model_job;ack(f);start=datetime.now(timezone.utc)
    mutate(f,'UPDATE leases SET expires_at=?',((start+timedelta(seconds=2)).isoformat(),))
    import aiqa.api.worker as api
    clock={'seconds':0}
    monkeypatch.setattr(api,'_server_now',lambda:start+timedelta(seconds=clock['seconds']))
    original=api.commit_sanitized_evidence
    def delayed(*args,**kwargs):
        clock['seconds']=3
        return original(*args,**kwargs)
    monkeypatch.setattr(api,'commit_sanitized_evidence',delayed)
    result=upload(f,payload(f,start+timedelta(seconds=1)))
    assert result.status_code==200,result.text
    assert result.json()['late'] is True and result.json()['artifact_ids']==[]
    assert f['provider'].sent==0


def test_same_worker_wrong_purpose_cannot_write_recording_evidence(model_job):
    f=model_job;ack(f);store=f['app'].state.open_store()
    try:
        with bound_auth_store(store):token=enroll_worker(Actor(uuid4(),UUID(f['project']),True),'worker-w1605','regression')
    finally:store.close()
    result=upload(f,payload(f,datetime.now(timezone.utc)),token=token)
    assert result.status_code==403,result.text
    with sqlite3.connect(f['database']) as c:assert c.execute('SELECT COUNT(*) FROM artifact_objects').fetchone()[0]==0


def test_committed_receipt_stays_readable_after_lease_expiry_without_new_upload(model_job,monkeypatch):
    f=model_job;ack(f);start=datetime.now(timezone.utc);body=payload(f,start)
    first=upload(f,body);assert first.status_code==200 and first.json()['late'] is False
    mutate(f,'UPDATE leases SET expires_at=?',((start+timedelta(seconds=1)).isoformat(),))
    monkeypatch.setattr('aiqa.api.worker._server_now',lambda:start+timedelta(seconds=2))
    again=upload(f,body)
    assert again.status_code==200 and again.json()==first.json()
    assert f['provider'].sent==0


@pytest.mark.parametrize('change',['time','purpose'])
def test_legacy_event_port_uses_the_same_server_authority(model_job,monkeypatch,change):
    f=model_job;ack(f);start=datetime.now(timezone.utc);token=None
    if change=='time':
        mutate(f,'UPDATE leases SET expires_at=?',((start+timedelta(seconds=2)).isoformat(),))
        monkeypatch.setattr('aiqa.api.worker._server_now',lambda:start+timedelta(seconds=3))
    else:
        store=f['app'].state.open_store()
        try:
            with bound_auth_store(store):token=enroll_worker(Actor(uuid4(),UUID(f['project']),True),'worker-w1605','regression')
        finally:store.close()
    detail=json.dumps({'message':'fixture'},sort_keys=True,separators=(',',':'));encoded=detail.encode()
    body={'project_id':f['project'],'job_id':f['job']['job_id'],'generation':f['job']['generation'],
        'now':(start+timedelta(seconds=1)).isoformat(),'events':[{
            'event_id':str(uuid4()),'attempt_id':f['job']['attempt_id'],'local_seq':1,
            'captured_at':start.isoformat(),'event_type':'worker.note','minimum_facts':'{}','detail_payload':detail,
            'payload_hash':'sha256:'+hashlib.sha256(b'1\n'+encoded).hexdigest(),
            'body_hash':'sha256:'+hashlib.sha256(encoded).hexdigest()}]}
    result=post(f,body,token=token,path='/api/v1/worker/events')
    if change=='time':
        assert result.status_code==200,result.text
        assert result.json()['stale_count']==1 and result.json()['committed_seq']==0
    else:assert result.status_code==403,result.text
    with sqlite3.connect(f['database']) as c:assert c.execute('SELECT COUNT(*) FROM attempt_events').fetchone()[0]==0


def test_authority_time_is_sampled_after_actual_sqlite_writer_wait(model_job,monkeypatch):
    import threading
    import time
    import aiqa.api.worker as api
    f=model_job;ack(f);start=datetime.now(timezone.utc);clock={'seconds':0}
    mutate(f,'UPDATE leases SET expires_at=?',((start+timedelta(seconds=2)).isoformat(),))
    monkeypatch.setattr(api,'_server_now',lambda:start+timedelta(seconds=clock['seconds']))
    requested=threading.Event();locked=threading.Event();errors=[]
    def holder():
        try:
            assert requested.wait(timeout=2)
            with sqlite3.connect(f['database'],timeout=2) as connection:
                connection.execute('BEGIN IMMEDIATE');locked.set()
                time.sleep(.05)
                clock['seconds']=3
                connection.commit()
        except Exception as exc:errors.append(repr(exc));locked.set()
    original=api.commit_sanitized_evidence
    def contested(*args,**kwargs):
        requested.set();assert locked.wait(timeout=2)
        return original(*args,**kwargs)
    monkeypatch.setattr(api,'commit_sanitized_evidence',contested)
    thread=threading.Thread(target=holder)
    try:
        thread.start();result=upload(f,payload(f,start+timedelta(seconds=1)))
    finally:thread.join(timeout=3)
    assert not thread.is_alive() and not errors,errors
    assert result.status_code==200 and result.json()['late'] is True,result.text
    assert result.json()['artifact_ids']==[] and f['provider'].sent==0
