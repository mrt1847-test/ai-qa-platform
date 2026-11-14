"""Artifact bytes cannot monopolize the management event loop or writer fence."""
import asyncio
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
import httpx
import pytest
import aiqa.store.evidence as evidence
from test_rx98_model_requests import model_job,recording,ux_app,ack,mutate
from test_rx87_evidence_authority import payload,upload


def test_slow_publish_does_not_block_worker_heartbeat(model_job,monkeypatch):
    f=model_job;ack(f);started=threading.Event();finished=threading.Event();release=threading.Event()
    original=evidence.publish_durable
    def slow(*args,**kwargs):
        started.set();release.wait(timeout=2);finished.set();return original(*args,**kwargs)
    monkeypatch.setattr(evidence,'publish_durable',slow)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=f['app']),base_url='http://127.0.0.1') as client:
            headers={'Authorization':'Bearer '+f['token'],'Idempotency-Key':'slow-upload'}
            task=asyncio.create_task(client.post('/api/v1/worker/evidence-commits',json=payload(f,datetime.now(timezone.utc)),headers=headers))
            try:
                for _ in range(30):
                    await asyncio.sleep(.01)
                    if started.is_set():break
                assert started.is_set() and not finished.is_set(),'storage blocked the ASGI event loop'
                heartbeat=await client.post('/api/v1/worker/heartbeats',json={'boot_id':'fixture-boot'},headers=headers)
                assert heartbeat.status_code==200 and not finished.is_set()
                from test_rx87_worker_checkpoints import body as checkpoint_body
                check=await client.post('/api/v1/worker/checkpoints',json=checkpoint_body(f),headers=headers)
                assert check.status_code==200 and check.json()['allowed'] is True and not finished.is_set()
                mutate(f,"UPDATE jobs SET status='cancel_requested' WHERE job_id=?",(f['job']['job_id'],))
                denied=await client.post('/api/v1/worker/checkpoints',json=checkpoint_body(f),headers=headers)
                assert denied.status_code==403 and not finished.is_set()
            finally:
                release.set();result=await task
            assert result.status_code==200,result.text
    asyncio.run(scenario())


def test_slow_publish_does_not_hold_sqlite_writer_transaction(model_job,monkeypatch):
    f=model_job;ack(f);started=threading.Event();release=threading.Event();original=evidence.publish_durable
    def slow(*args,**kwargs):started.set();release.wait(timeout=2);return original(*args,**kwargs)
    monkeypatch.setattr(evidence,'publish_durable',slow)
    writable=False
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(upload,f,payload(f,datetime.now(timezone.utc)))
        try:
            assert started.wait(timeout=1)
            with sqlite3.connect(f['database'],timeout=.1) as connection:
                try:
                    connection.execute('BEGIN IMMEDIATE');writable=True;connection.rollback()
                except sqlite3.OperationalError:pass
        finally:release.set()
        result=future.result(timeout=4)
    assert writable,'file publishing held the SQLite writer transaction'
    assert result.status_code==200,result.text


def test_lease_expiry_during_publish_never_creates_new_ready_evidence(model_job,monkeypatch):
    f=model_job;ack(f);start=datetime.now(timezone.utc);clock={'seconds':0};original=evidence.publish_durable
    mutate(f,'UPDATE leases SET expires_at=?',((start+timedelta(seconds=2)).isoformat(),))
    monkeypatch.setattr('aiqa.api.worker._server_now',lambda:start+timedelta(seconds=clock['seconds']))
    def expire(*args,**kwargs):clock['seconds']=3;return original(*args,**kwargs)
    monkeypatch.setattr(evidence,'publish_durable',expire)
    result=upload(f,payload(f,start))
    assert result.status_code==200 and result.json()['late'] is True,result.text
    assert result.json()['artifact_ids']==[]
    with sqlite3.connect(f['database']) as connection:
        assert connection.execute("SELECT COUNT(*) FROM artifact_objects WHERE status='ready'").fetchone()[0]==0
    assert f['provider'].sent==0


def _counts(f):
    with sqlite3.connect(f['database']) as connection:
        return tuple(connection.execute(sql).fetchone()[0] for sql in (
            "SELECT COUNT(*) FROM artifact_objects WHERE status='ready'",
            "SELECT COUNT(*) FROM artifact_staging",
            "SELECT COUNT(*) FROM evidence_commit_requests WHERE response_body IS NOT NULL"))


def test_metadata_failure_reuses_staged_bytes_without_publishing_twice(model_job,monkeypatch):
    f=model_job;ack(f);body=payload(f,datetime.now(timezone.utc));original=evidence._commit_evidence_metadata
    def fail(*args,**kwargs):raise RuntimeError('injected metadata failure')
    monkeypatch.setattr(evidence,'_commit_evidence_metadata',fail)
    with pytest.raises(RuntimeError,match='injected metadata failure'):upload(f,body)
    assert _counts(f)==(0,1,0)
    with sqlite3.connect(f['database']) as c:
        staged_id,key=c.execute('SELECT artifact_id,object_key FROM artifact_staging').fetchone()
    root=f['app'].state.open_store()
    try:path=root.config.artifacts_dir/key
    finally:root.close()
    original_bytes=path.read_bytes()
    monkeypatch.setattr(evidence,'_commit_evidence_metadata',original)
    def no_republish(*args,**kwargs):raise AssertionError('durable stage was rewritten')
    monkeypatch.setattr(evidence,'publish_durable',no_republish)
    result=upload(f,body)
    assert result.status_code==200 and result.json()['artifact_ids']==[staged_id],result.text
    assert _counts(f)==(1,0,1) and path.read_bytes()==original_bytes
    cached=upload(f,body)
    assert cached.status_code==200 and cached.json()==result.json()


def test_same_key_concurrent_uploads_publish_once_and_share_ack(model_job,monkeypatch):
    f=model_job;ack(f);body=payload(f,datetime.now(timezone.utc));original=evidence.publish_durable;calls=[]
    def count(*args,**kwargs):calls.append(1);return original(*args,**kwargs)
    monkeypatch.setattr(evidence,'publish_durable',count)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(upload,f,body) for _ in range(2)]
        results=[future.result(timeout=5) for future in futures]
    assert all(r.status_code==200 for r in results),[r.text for r in results]
    assert results[0].json()==results[1].json() and calls==[1]
    assert _counts(f)==(1,0,1)


def test_interrupted_request_rejects_changed_body_without_overwriting_stage(model_job,monkeypatch):
    import copy
    f=model_job;ack(f);body=payload(f,datetime.now(timezone.utc));original=evidence._commit_evidence_metadata
    monkeypatch.setattr(evidence,'_commit_evidence_metadata',lambda *a,**k:(_ for _ in ()).throw(RuntimeError('stop')))
    with pytest.raises(RuntimeError):upload(f,body)
    monkeypatch.setattr(evidence,'_commit_evidence_metadata',original)
    changed=copy.deepcopy(body);changed['artifacts'][0]['filename']='changed.png'
    result=upload(f,changed)
    assert result.status_code==409,result.text
    assert _counts(f)==(0,1,0)
    assert upload(f,body).status_code==200 and _counts(f)==(1,0,1)


def test_corrupt_staged_bytes_never_become_ready_or_get_replaced(model_job,monkeypatch):
    f=model_job;ack(f);body=payload(f,datetime.now(timezone.utc));original=evidence._commit_evidence_metadata
    monkeypatch.setattr(evidence,'_commit_evidence_metadata',lambda *a,**k:(_ for _ in ()).throw(RuntimeError('stop')))
    with pytest.raises(RuntimeError):upload(f,body)
    monkeypatch.setattr(evidence,'_commit_evidence_metadata',original)
    with sqlite3.connect(f['database']) as c:key=c.execute('SELECT object_key FROM artifact_staging').fetchone()[0]
    root=f['app'].state.open_store()
    try:path=root.config.artifacts_dir/key
    finally:root.close()
    path.write_bytes(b'corrupt-stage')
    result=upload(f,body)
    assert result.status_code==422,result.text
    assert _counts(f)==(0,1,0) and path.read_bytes()==b'corrupt-stage'


@pytest.mark.parametrize('boundary',['request','final'])
def test_legacy_artifact_clock_follows_sqlite_writer_wait(model_job,monkeypatch,boundary):
    import time
    import aiqa.api.artifacts as api
    import aiqa.store.artifact_ingest as ingest
    f=model_job;ack(f);start=datetime.now(timezone.utc);clock={'seconds':0};threads=[]
    mutate(f,'UPDATE leases SET expires_at=?',((start+timedelta(seconds=2)).isoformat(),))
    monkeypatch.setattr(api,'_server_now',lambda:start+timedelta(seconds=clock['seconds']))
    def hold_writer():
        started=threading.Event()
        def holder():
            with sqlite3.connect(f['database']) as c:
                c.execute('BEGIN IMMEDIATE');started.set();time.sleep(.15)
                clock['seconds']=3;c.commit()
        thread=threading.Thread(target=holder);thread.start();threads.append(thread)
        assert started.wait(1)
    if boundary=='request':
        original=api.ingest_upload_request
        def delayed(*args,**kwargs):hold_writer();return original(*args,**kwargs)
        monkeypatch.setattr(api,'ingest_upload_request',delayed)
    else:
        original=ingest.publish_durable
        def delayed(*args,**kwargs):
            result=original(*args,**kwargs);hold_writer();return result
        monkeypatch.setattr(ingest,'publish_durable',delayed)
    body=payload(f,start);part=body.pop('artifacts')[0];body.pop('events');body.pop('sanitized')
    body.update(part)
    with sqlite3.connect(f['database']) as c:
        body['owner_id']=c.execute('SELECT recording_id FROM jobs WHERE job_id=?',(f['job']['job_id'],)).fetchone()[0]
    try:
        from test_rx98_model_requests import post
        result=post(f,body,path='/api/v1/worker/artifacts',key='raw-wait')
    finally:
        for thread in threads:thread.join(2)
    assert result.status_code in {403,409},result.text
    assert _counts(f)[0]==0 and f['provider'].sent==0


def test_real_sql_rollback_keeps_prior_ready_bytes_and_retries_only_new_stage(model_job):
    import base64,hashlib,json
    from uuid import uuid4
    f=model_job;ack(f);start=datetime.now(timezone.utc)
    first=upload(f,payload(f,start),key='original');assert first.status_code==200
    with sqlite3.connect(f['database']) as c:
        key=c.execute('SELECT object_key FROM artifact_objects').fetchone()[0]
    root=f['app'].state.open_store()
    try:path=root.config.artifacts_dir/key
    finally:root.close()
    original_bytes=path.read_bytes()
    body=payload(f,start);log=b'new sanitized log';part=body['artifacts'][0]
    part.update(filename='worker.log',media_type='text/plain',declared_hash='sha256:'+hashlib.sha256(log).hexdigest(),
        declared_length=len(log),body_b64=base64.b64encode(log).decode(),role='log')
    detail=json.dumps({'message':'fixture'},sort_keys=True,separators=(',',':'));encoded=detail.encode()
    body['events']=[{'event_id':str(uuid4()),'attempt_id':f['job']['attempt_id'],'local_seq':1,
        'captured_at':start.isoformat(),'event_type':'worker.note','minimum_facts':'{}','detail_payload':detail,
        'payload_hash':'sha256:'+hashlib.sha256(b'1\n'+encoded).hexdigest(),
        'body_hash':'sha256:'+hashlib.sha256(encoded).hexdigest()}]
    with sqlite3.connect(f['database']) as c:
        c.execute("CREATE TRIGGER injected_reject_new_log BEFORE INSERT ON artifact_objects WHEN NEW.role='log' BEGIN SELECT RAISE(ABORT,'injected SQL failure'); END")
    with pytest.raises(sqlite3.IntegrityError,match='injected SQL failure'):upload(f,body,key='rollback')
    assert _counts(f)==(1,1,1) and path.read_bytes()==original_bytes
    with sqlite3.connect(f['database']) as c:
        assert c.execute('SELECT COUNT(*) FROM attempt_events').fetchone()[0]==0
        c.execute('DROP TRIGGER injected_reject_new_log')
    result=upload(f,body,key='rollback')
    assert result.status_code==200 and result.json()['contiguous_seq']==1,result.text
    assert _counts(f)==(2,0,2) and path.read_bytes()==original_bytes


@pytest.mark.parametrize('field,value',[('owner_kind','ITEM'),('attempt_id','00000000-0000-0000-0000-000000000001')])
def test_invalid_owner_is_rejected_before_file_publication(model_job,monkeypatch,field,value):
    f=model_job;ack(f);body=payload(f,datetime.now(timezone.utc));body['artifacts'][0][field]=value
    def no_io(*args,**kwargs):raise AssertionError('invalid owner reached file publication')
    monkeypatch.setattr(evidence,'publish_durable',no_io)
    result=upload(f,body)
    assert result.status_code in {403,422},result.text
    assert _counts(f)==(0,0,0)


def _durable_files(f):
    store=f['app'].state.open_store()
    try:return tuple((store.config.artifacts_dir/f['project']).glob('*.png'))
    finally:store.close()


def test_successful_different_step_keys_reuse_ready_bytes_without_new_stages(model_job,monkeypatch):
    f=model_job;ack(f);body=payload(f,datetime.now(timezone.utc));original=evidence.publish_durable;calls=[]
    def count(*args,**kwargs):calls.append(1);return original(*args,**kwargs)
    monkeypatch.setattr(evidence,'publish_durable',count)
    first=upload(f,body,key='step-one');second=upload(f,body,key='step-two')
    assert first.status_code==second.status_code==200 and first.json()==second.json()
    assert calls==[1],'an already-ready screenshot was published again'
    assert _counts(f)==(1,0,2) and len(_durable_files(f))==1


def test_concurrent_different_step_keys_discard_only_the_redundant_new_stage(model_job,monkeypatch):
    f=model_job;ack(f);body=payload(f,datetime.now(timezone.utc));original=evidence.publish_durable
    barrier=threading.Barrier(2)
    def publish(*args,**kwargs):
        result=original(*args,**kwargs);barrier.wait(timeout=4);return result
    monkeypatch.setattr(evidence,'publish_durable',publish)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(upload,f,body,key=key) for key in ('parallel-step-one','parallel-step-two')]
        results=[future.result(timeout=6) for future in futures]
    assert all(result.status_code==200 for result in results),[result.text for result in results]
    assert results[0].json()==results[1].json()
    assert _counts(f)==(1,0,2) and len(_durable_files(f))==1


def test_redundant_cleanup_io_failure_keeps_committed_ack_and_unpublished_stage(model_job,monkeypatch):
    from pathlib import Path
    f=model_job;ack(f);body=payload(f,datetime.now(timezone.utc));publish=evidence.publish_durable
    unlink=Path.unlink;barrier=threading.Barrier(2)
    def concurrent(*args,**kwargs):
        result=publish(*args,**kwargs);barrier.wait(timeout=4);return result
    def fail_png(path,*args,**kwargs):
        if path.suffix=='.png':raise OSError('injected cleanup refusal')
        return unlink(path,*args,**kwargs)
    monkeypatch.setattr(evidence,'publish_durable',concurrent);monkeypatch.setattr(Path,'unlink',fail_png)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(upload,f,body,key=key) for key in ('cleanup-one','cleanup-two')]
        results=[future.result(timeout=6) for future in futures]
    assert all(result.status_code==200 for result in results),[result.text for result in results]
    assert results[0].json()==results[1].json() and _counts(f)==(1,1,2)
    assert len(_durable_files(f))==2
    assert upload(f,body,key='cleanup-two').json()==results[1].json()
