"""Preparation is journaled once; only evidence confirmation may retry."""
from uuid import uuid4
import asyncio,copy,hashlib,json
import pytest
import httpx
from aiqa.worker.http_client import WorkerHttpError,RetryClass
from aiqa.worker.dispatch_journal import DispatchJournal
from aiqa.worker.case_context import resolve_claim_case_context
from aiqa.domain.hashing import canonical_hash
from test_rx98_model_requests import model_job,recording,ux_app
from test_rx_34 import _observation


class Client:
    def __init__(self,lose=0):self.calls=[];self.lose=lose
    def commit_evidence(self,**payload):
        self.calls.append(payload)
        if self.lose:self.lose-=1;raise WorkerHttpError('mock reply lost',retry_class=RetryClass.timeout)
        return {'attempt_id':payload['artifacts'][0]['attempt_id'],'late':False,'contiguous_seq':0,
            'prefix_hash':'sha256:'+hashlib.sha256(b'').hexdigest(),'artifact_ids':[str(uuid4()) for _ in payload['artifacts']]}


def setup(f,tmp_path,*,client=None,mode='ok'):
    from aiqa.worker.android_prepare import AndroidTargetPreparer
    from aiqa.environments.android_app_launch import AppLaunchReceipt,AppLaunchUnknown
    job=copy.deepcopy(f['job']);raw=job['snapshot']['case_context']
    raw['target']={'kind':'android','android_package':'com.ebay.kr.gmarket'}
    raw['context_hash']=canonical_hash({k:v for k,v in raw.items() if k!='context_hash'},'canon-json-v1')
    counts={'native':0,'capture':0}
    def capture():
        counts['capture']+=1
        if mode=='after_missing' and counts['capture']==2:raise OSError('mock capture lost')
        return _observation()
    def launch(package,*,before_native_send):
        before_native_send();counts['native']+=1
        if mode=='unknown':raise AppLaunchUnknown('mock device response lost')
        return AppLaunchReceipt(package,package+'/.Main')
    journal=DispatchJournal(tmp_path/'prepare.jsonl');client=client or Client()
    preparer=AndroidTargetPreparer(capture=capture,launch=launch,client=client,journal=journal)
    return preparer,job,resolve_claim_case_context(job,required=True),counts,client,journal


def test_preparation_uses_immutable_selected_app_and_saves_three_parts(model_job,tmp_path):
    p,job,pin,counts,client,journal=setup(model_job,tmp_path)
    result=p.prepare(job,pin,checkpoint=lambda:None)
    assert counts=={'native':1,'capture':2}
    assert len(result.artifact_ids)==3 and result.observation.capture_ok
    payload=client.calls[0]
    assert payload['events']==[] and '-prepare-' in payload['idempotency_key']
    assert {a['role'] for a in payload['artifacts']}=={'before','after','log'}
    assert all(a['owner_id']==pin.to_document()['owner_id'] for a in payload['artifacts'])
    assert journal.states('prepare-'+job['attempt_id'],job['attempt_id'])[-1]=='observed'


def test_lost_ack_and_repeat_only_confirm_evidence_without_native_relaunch(model_job,tmp_path):
    client=Client(lose=1);p,job,pin,counts,_,_=setup(model_job,tmp_path,client=client)
    first=p.prepare(job,pin,checkpoint=lambda:None);second=p.prepare(job,pin,checkpoint=lambda:None)
    assert counts=={'native':1,'capture':2} and first.artifact_ids==second.artifact_ids
    assert client.calls[0]==client.calls[1] and len(client.calls)==2


@pytest.mark.parametrize('mode',['unknown','after_missing'])
def test_uncertain_preparation_is_not_repeated_after_recreation(model_job,tmp_path,mode):
    from aiqa.worker.android_prepare import AppPreparationFailed
    p,job,pin,counts,client,journal=setup(model_job,tmp_path,mode=mode)
    with pytest.raises(AppPreparationFailed) as err:p.prepare(job,pin,checkpoint=lambda:None)
    assert err.value.ambiguous is True and counts['native']==1
    assert client.calls, 'attempted native preparation lost all server-side failure evidence'
    import base64
    log=json.loads(base64.b64decode(client.calls[-1]['artifacts'][-1]['body_b64']))
    assert log['state']=='unknown' and client.calls[-1]['events']==[]
    again,*_=setup(model_job,tmp_path,mode='ok')
    with pytest.raises(AppPreparationFailed):again.prepare(job,pin,checkpoint=lambda:None)
    assert counts['native']==1 and journal.is_ambiguous(job['attempt_id'],'prepare-'+job['attempt_id'])


def test_denied_or_secret_target_never_launches_or_uploads(model_job,tmp_path):
    from aiqa.worker.android_prepare import AppPreparationFailed
    p,job,pin,counts,client,_=setup(model_job,tmp_path)
    with pytest.raises(AppPreparationFailed):p.prepare(job,pin,checkpoint=lambda:False)
    assert counts=={'native':0,'capture':0} and client.calls==[]
    raw=job['snapshot']['case_context'];raw['target_secret_refs']={'account':{'project_id':job['project_id'],'ref_id':str(uuid4()),'revision':1}}
    raw['context_hash']=canonical_hash({k:v for k,v in raw.items() if k!='context_hash'},'canon-json-v1')
    with pytest.raises(AppPreparationFailed):p.prepare(job,resolve_claim_case_context(job,required=True),checkpoint=lambda:None)
    assert counts=={'native':0,'capture':0} and client.calls==[]


def test_real_api_prep_keeps_prefix_and_gesture_artifact_ownership(recording,tmp_path):
    import sqlite3,asyncio
    from aiqa.api.auth import bound_auth_store,enroll_worker
    from aiqa.store.models import Actor
    from uuid import UUID
    from aiqa.worker.http_client import WorkerHttpClient,WorkerClientSettings,SyncASGITransport
    from aiqa.worker.step_evidence import StepEvidenceCommitter
    from aiqa.worker.android_prepare import AndroidTargetPreparer
    from aiqa.environments.android_app_launch import AppLaunchReceipt
    from test_rx87_case_context_consumer import _android_api_claim
    from aiqa.worker.android_jobs import android_evidence_artifacts,android_evidence_events
    f=recording;job=_android_api_claim(f);pin=resolve_claim_case_context(job,required=True)
    store=f['app'].state.open_store()
    try:
        with bound_auth_store(store):token=enroll_worker(Actor(uuid4(),UUID(f['project']),True),'worker-w1605','recording')
    finally:store.close()
    obs=_observation();native=[]
    def launch(package,*,before_native_send):before_native_send();native.append(package);return AppLaunchReceipt(package,package+'/.Main')
    with WorkerHttpClient(WorkerClientSettings('https://127.0.0.1',token),transport=SyncASGITransport(f['app'])) as client:
        preparer=AndroidTargetPreparer(capture=lambda:obs,launch=launch,client=client,journal=DispatchJournal(tmp_path/'native.jsonl'))
        receipt=preparer.prepare(job,pin,checkpoint=lambda:None)
        with sqlite3.connect(f['database']) as c:assert c.execute('SELECT COUNT(*) FROM attempt_events').fetchone()[0]==0
        parts=android_evidence_artifacts(attempt_id=job['attempt_id'],action_id='gesture-one',before=obs,after=obs,action_seq=1)
        events=android_evidence_events(attempt_id=job['attempt_id'],action_id='gesture-one',before=obs,after=obs,action_seq=1)
        ack=StepEvidenceCommitter(client,job)(action_seq=1,action_id='gesture-one',events=events,artifacts=parts)
    assert len(native)==1 and ack['contiguous_seq']==2 and set(receipt.artifact_ids).isdisjoint(ack['artifact_ids'])
    with sqlite3.connect(f['database']) as c:
        for artifact in ack['artifact_ids']:
            assert c.execute('SELECT action_id FROM artifact_objects WHERE artifact_id=?',(artifact,)).fetchone()[0]=='gesture-one'
    async def read():
        from ux_support import session
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=f['app']),base_url='http://127.0.0.1') as browser:
            headers=await session(browser,f['project'])
            responses=[await browser.get('/api/v1/artifacts/'+artifact) for artifact in receipt.artifact_ids]
            assert all(r.status_code==200 for r in responses)
            assert json.loads(responses[-1].content)['operation']=='app_prepare'
            timeline=await browser.get('/api/v1/projects/'+f['project']+'/recordings/'+pin.to_document()['owner_id']+'/timeline',headers=headers)
            assert timeline.status_code==200
            prep=next(a for a in timeline.json()['actions'] if a['action_id']=='prepare-'+job['attempt_id'])
            assert prep['before']=='stored' and prep['after']=='stored' and prep['log']=='stored'
            page=await browser.get('/ui/projects/'+f['project']+'/recordings/'+pin.to_document()['owner_id'],params={'action_id':prep['action_id']})
            assert page.status_code==200 and all(artifact in page.text for artifact in receipt.artifact_ids[:2]) and 'app_prepare' in page.text
    with sqlite3.connect(f['database']) as c:c.execute("UPDATE leases SET expires_at='2000-01-01T00:00:00+00:00'")
    asyncio.run(read())


def test_cancel_after_evidence_ack_does_not_rewrite_committed_preparation(model_job,tmp_path):
    from aiqa.worker.android_prepare import AppPreparationFailed
    import base64
    client=Client();p,job,pin,counts,_,_=setup(model_job,tmp_path,client=client)
    with pytest.raises(AppPreparationFailed):
        p.prepare(job,pin,checkpoint=lambda:False if client.calls else None)
    assert counts=={'native':1,'capture':2}
    assert len(client.calls)==1, 'post-ACK cancellation tried to rewrite immutable evidence'
    assert json.loads(base64.b64decode(client.calls[0]['artifacts'][-1]['body_b64']))['state']=='observed'
    assert not (tmp_path/'prepare-spool'/job['attempt_id']).exists()


@pytest.mark.parametrize('state',['planned','dispatch_started'])
def test_journal_write_failure_never_sends_app_start(model_job,tmp_path,state):
    from aiqa.worker.android_prepare import AppPreparationFailed
    p,job,pin,counts,client,journal=setup(model_job,tmp_path)
    journal.fail_on(state)
    with pytest.raises(AppPreparationFailed):p.prepare(job,pin,checkpoint=lambda:None)
    assert counts['native']==0 and client.calls==[]


@pytest.mark.parametrize('mode',['ok','unknown'])
def test_recreated_preparer_confirms_frozen_spool_without_resuming_native(model_job,tmp_path,mode):
    from aiqa.worker.android_prepare import AppPreparationFailed
    client=Client(lose=2);p,job,pin,counts,_,_=setup(model_job,tmp_path,client=client,mode=mode)
    with pytest.raises(AppPreparationFailed):p.prepare(job,pin,checkpoint=lambda:None)
    assert len(client.calls)==2
    again,_,_,next_counts,_,_=setup(model_job,tmp_path,client=client)
    with pytest.raises(AppPreparationFailed):again.prepare(job,pin,checkpoint=lambda:None)
    assert len(client.calls)==3 and client.calls[0]==client.calls[-1]
    assert next_counts=={'native':0,'capture':0}
    assert not (tmp_path/'prepare-spool'/job['attempt_id']).exists()


@pytest.mark.parametrize('pending',[False,True])
def test_changed_pin_cannot_reuse_cached_or_pending_preparation(model_job,tmp_path,pending):
    from aiqa.worker.android_prepare import AppPreparationFailed
    client=Client(lose=2 if pending else 0);p,job,pin,counts,_,_=setup(model_job,tmp_path,client=client)
    if pending:
        with pytest.raises(AppPreparationFailed):p.prepare(job,pin,checkpoint=lambda:None)
    else:p.prepare(job,pin,checkpoint=lambda:None)
    changed=copy.deepcopy(job);raw=changed['snapshot']['case_context']
    raw['target']['android_package']='com.example.changed'
    raw['context_hash']=canonical_hash({k:v for k,v in raw.items() if k!='context_hash'},'canon-json-v1')
    calls=len(client.calls)
    with pytest.raises(AppPreparationFailed):p.prepare(changed,resolve_claim_case_context(changed,required=True),checkpoint=lambda:None)
    assert counts=={'native':1,'capture':2} and len(client.calls)==calls


def test_actual_api_unknown_setup_is_unknown_in_timeline(recording,tmp_path):
    from aiqa.api.auth import bound_auth_store,enroll_worker
    from aiqa.store.models import Actor
    from uuid import UUID
    from aiqa.worker.http_client import WorkerHttpClient,WorkerClientSettings,SyncASGITransport
    from aiqa.worker.android_prepare import AndroidTargetPreparer,AppPreparationFailed
    from aiqa.environments.android_app_launch import AppLaunchUnknown
    from test_rx87_case_context_consumer import _android_api_claim
    f=recording;job=_android_api_claim(f);pin=resolve_claim_case_context(job,required=True)
    store=f['app'].state.open_store()
    try:
        with bound_auth_store(store):token=enroll_worker(Actor(uuid4(),UUID(f['project']),True),'worker-w1605','recording')
    finally:store.close()
    def launch(package,*,before_native_send):before_native_send();raise AppLaunchUnknown('response lost')
    with WorkerHttpClient(WorkerClientSettings('https://127.0.0.1',token),transport=SyncASGITransport(f['app'])) as client:
        p=AndroidTargetPreparer(capture=_observation,launch=launch,client=client,journal=DispatchJournal(tmp_path/'native.jsonl'))
        with pytest.raises(AppPreparationFailed):p.prepare(job,pin,checkpoint=lambda:None)
    async def read():
        from ux_support import session
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=f['app']),base_url='http://127.0.0.1') as browser:
            headers=await session(browser,f['project'])
            r=await browser.get('/api/v1/projects/'+f['project']+'/recordings/'+pin.to_document()['owner_id']+'/timeline',headers=headers)
            assert r.status_code==200
            assert r.json()['actions'][0]['dispatch_state']=='unknown'
    asyncio.run(read())


@pytest.mark.parametrize('entrypoint',['offline','candidates','direct'])
def test_setup_only_trial_never_qualifies_as_gesture_review(ux_app,entrypoint):
    import sqlite3
    from uuid import UUID
    from acceptance.test_rx_52 import _graph,_entry
    from aiqa.recording.review_manifest import review_offline_gate,request_review,ReviewRejected
    from aiqa.web.review_context import review_candidates
    _,project,database=ux_app;g=_graph(database,project,str(uuid4()),preparation_only=True)
    with sqlite3.connect(database) as c:
        action='prepare-'+g['item_attempt']
        if entrypoint=='offline':assert not review_offline_gate(c,UUID(project),UUID(g['case']),UUID(g['version'])).allowed
        elif entrypoint=='candidates':assert not any(row['trial_case_run_id']==g['trial'] for row in review_candidates(c,project,g['case'],g['version']))
        else:
            entries=[_entry('REC',g['recording'],g['rec_attempt'],'A001',g['rec_artifact'],'hash-rec'),_entry('ITEM',g['trial'],g['item_attempt'],action,g['item_artifact'],'hash-item')]
            with pytest.raises(ReviewRejected):request_review(c,UUID(project),UUID(g['version']),{'trial_case_run_id':g['trial'],'entries':entries})


@pytest.mark.parametrize('state',[[],{},None,'invalid'])
def test_malformed_setup_disposition_is_validation_error(model_job,tmp_path,state):
    import base64
    from aiqa.api.worker import _commit_artifacts
    from aiqa.store.evidence import _preparation_dispositions
    p,job,pin,counts,client,_=setup(model_job,tmp_path)
    p.prepare(job,pin,checkpoint=lambda:None)
    parts=copy.deepcopy(client.calls[0]['artifacts'])
    log=json.loads(base64.b64decode(parts[-1]['body_b64']));log['state']=state
    body=json.dumps(log).encode();parts[-1].update(body_b64=base64.b64encode(body).decode(),declared_length=len(body),declared_hash='sha256:'+hashlib.sha256(body).hexdigest())
    with pytest.raises(ValueError):_preparation_dispositions(_commit_artifacts(parts))


def test_real_api_receipt_recovery_after_both_replies_lost_never_resumes_device(recording,tmp_path):
    import sqlite3
    from uuid import UUID
    from aiqa.api.auth import bound_auth_store,enroll_worker
    from aiqa.store.models import Actor
    from aiqa.worker.http_client import WorkerHttpClient,WorkerClientSettings,SyncASGITransport
    from aiqa.worker.android_prepare import AndroidTargetPreparer,AppPreparationFailed
    from aiqa.environments.android_app_launch import AppLaunchReceipt
    from test_rx87_case_context_consumer import _android_api_claim
    f=recording;job=_android_api_claim(f);pin=resolve_claim_case_context(job,required=True);native=[]
    store=f['app'].state.open_store()
    try:
        with bound_auth_store(store):token=enroll_worker(Actor(uuid4(),UUID(f['project']),True),'worker-w1605','recording')
    finally:store.close()
    def launch(package,*,before_native_send):before_native_send();native.append(package);return AppLaunchReceipt(package,package+'/.Main')
    journal=DispatchJournal(tmp_path/'native.jsonl')
    with WorkerHttpClient(WorkerClientSettings('https://127.0.0.1',token),transport=SyncASGITransport(f['app'])) as client:
        class LostReplies:
            sends=0
            def commit_evidence(self,**payload):
                self.sends+=1;ack=client.commit_evidence(**payload)
                if self.sends<=2:raise WorkerHttpError('mock lost committed reply',retry_class=RetryClass.timeout)
                return ack
        transport=LostReplies()
        p=AndroidTargetPreparer(capture=_observation,launch=launch,client=transport,journal=journal)
        with pytest.raises(AppPreparationFailed):p.prepare(job,pin,checkpoint=lambda:None)
        def forbidden(*args,**kwargs):pytest.fail('recovery resumed the device')
        recovered=AndroidTargetPreparer(capture=forbidden,launch=forbidden,client=transport,journal=journal)
        with sqlite3.connect(f['database']) as c:c.execute("UPDATE leases SET expires_at='2000-01-01T00:00:00+00:00'")
        with pytest.raises(AppPreparationFailed):recovered.prepare(job,pin,checkpoint=lambda:False)
    assert transport.sends==3 and len(native)==1
    assert not (tmp_path/'prepare-spool'/job['attempt_id']).exists()
    with sqlite3.connect(f['database']) as c:
        assert c.execute('SELECT COUNT(*) FROM artifact_objects').fetchone()[0]==3
        assert c.execute('SELECT COUNT(*) FROM attempt_events').fetchone()[0]==0


def test_recovery_reply_loss_never_turns_a_later_confirmation_into_execution_resume(model_job,tmp_path):
    from aiqa.worker.android_prepare import AppPreparationFailed
    client=Client(lose=4);p,job,pin,_,_,_=setup(model_job,tmp_path,client=client)
    with pytest.raises(AppPreparationFailed):p.prepare(job,pin,checkpoint=lambda:None)
    recovered,_,_,counts,_,_=setup(model_job,tmp_path,client=client)
    with pytest.raises(AppPreparationFailed):recovered.prepare(job,pin,checkpoint=lambda:None)
    with pytest.raises(AppPreparationFailed):recovered.prepare(job,pin,checkpoint=lambda:None)
    assert len(client.calls)==5 and counts=={'native':0,'capture':0}
    assert not (tmp_path/'prepare-spool'/job['attempt_id']).exists()
