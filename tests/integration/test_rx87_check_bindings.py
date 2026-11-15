import asyncio,copy,json,sqlite3
from uuid import UUID,uuid4
import httpx,pytest
from ux_support import ux_app,session
from unit.test_recording_check_bindings import DEF,SETTINGS,PAYLOAD
from test_rx87_native_trace import mapping
from test_rx_50 import _seed_artifact
from aiqa.store.models import Actor
from aiqa.recording.manifests import RecordingFinishInput
from aiqa.recording.service import finish_recording
from aiqa.recording.check_bindings import save_check_bindings,load_check_binding_context,BindingConflict,BindingRejected,BindingNotFound


@pytest.fixture
def recorded(ux_app):
    app,project,_=ux_app
    async def create():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1') as client:
            headers=await session(client,project)
            case=(await client.post(f'/api/v1/projects/{project}/cases',json={'name':'Search'},headers=headers)).json()['case_id']
            definition={'raw_text':'search','objective':'search mouse','preconditions':[],'variables':{},'secret_refs':{},'path_policy':{'must_use':[],'forbidden':[]},**DEF}
            response=await client.post(f'/api/v1/projects/{project}/cases/{case}/versions',json={'definition':definition,'settings':SETTINGS},headers={**headers,'Idempotency-Key':'version'})
            assert response.status_code==201,response.text
            return case,response.json()['id']
    case,version=asyncio.run(create());recording=uuid4();artifact=uuid4();store=app.state.open_store();actor=Actor(uuid4(),UUID(project),True)
    with store.transaction() as c:
        c.execute("INSERT INTO recordings(project_id,case_id,recording_id,creation_kind,input_case_version_id,storage_status,stop_status,completion_status,evidence_status) VALUES(?,?,?,'recorded',?,'stored','running','open','incomplete')",(project,case,str(recording),version))
        _seed_artifact(c,UUID(project),recording,artifact,source_mapping=mapping())
        receipt=finish_recording(c,actor,UUID(project),RecordingFinishInput(recording,'completed',10,(str(artifact),),'finish',mapping()))
        old_draft=c.execute('SELECT latest_draft_version_id FROM automation_cases WHERE project_id=? AND case_id=?',(project,case)).fetchone()[0]
    value=dict(app=app,project=UUID(project),recording=recording,case=case,input_version=version,manifest=receipt.manifest_id,hash=receipt.body_hash,store=store,actor=actor,old_draft=old_draft)
    yield value
    store.close()


def save(c,r,**changes):
    args=dict(expected_manifest_id=r['manifest'],expected_manifest_hash=r['hash'],bindings=PAYLOAD,request_key='binding-save')
    args.update(changes)
    return save_check_bindings(c,r['actor'],r['project'],r['recording'],**args)


def test_bindings_derive_new_candidate_without_mutating_source_or_approval(recorded):
    r=recorded
    with r['store'].transaction() as c:
        before=c.execute('SELECT action_mapping,body_hash FROM recording_manifests WHERE manifest_id=?',(str(r['manifest']),)).fetchone()
        c.execute("CREATE TRIGGER no_binding_approval BEFORE UPDATE OF current_approval_id ON automation_cases BEGIN SELECT RAISE(ABORT,'approval cannot change'); END")
        receipt=save(c,r)
        assert receipt['manifest_id']!=str(r['manifest']) and receipt['replay_package_id']
        assert c.execute('SELECT action_mapping,body_hash FROM recording_manifests WHERE manifest_id=?',(str(r['manifest']),)).fetchone()==before
        new=c.execute('SELECT prior_manifest_id,action_mapping,body_hash FROM recording_manifests WHERE manifest_id=?',(receipt['manifest_id'],)).fetchone()
        assert new[0]==str(r['manifest']) and new[1]==before[0] and new[2]!=before[1]
        assert c.execute('SELECT latest_draft_version_id,current_approval_id FROM automation_cases WHERE case_id=?',(r['case'],)).fetchone()==(r['old_draft'],None)
        assert c.execute('SELECT is_branch FROM case_versions WHERE version_id=?',(receipt['case_version_id'],)).fetchone()==(1,)
        context=load_check_binding_context(c,r['project'],r['recording'])
        assert context['bindings']==PAYLOAD and context['source_manifest']['id']==receipt['manifest_id']


def test_retry_returns_same_candidate_after_latest_manifest_changed(recorded):
    r=recorded
    with r['store'].transaction() as c:
        one=save(c,r);two=save(c,r)
        assert one['manifest_id']==two['manifest_id'] and two['replayed'] is True
        assert c.execute('SELECT count(*) FROM recording_check_bindings').fetchone()==(1,)
        with pytest.raises(BindingConflict):save(c,r,request_key='another-save')
        changed=copy.deepcopy(PAYLOAD);changed['step_boundaries'][0]['after_action_id']='a1'
        with pytest.raises(BindingConflict):save(c,r,bindings=changed)


def test_binding_rows_are_immutable_and_scope_checked(recorded):
    r=recorded
    with r['store'].transaction() as c:
        receipt=save(c,r)
        for sql in ['UPDATE recording_check_bindings SET body_hash=body_hash','DELETE FROM recording_check_bindings']:
            with pytest.raises(sqlite3.IntegrityError):c.execute(sql)
        with pytest.raises(BindingNotFound):load_check_binding_context(c,uuid4(),r['recording'])


def test_wrong_expected_hash_or_extra_expected_edits_do_not_materialize(recorded):
    r=recorded
    with r['store'].transaction() as c:
        with pytest.raises(BindingConflict):save(c,r,expected_manifest_hash='different')
        with pytest.raises(BindingRejected):save(c,r,bindings={**PAYLOAD,'expected':'invented'})
        assert c.execute('SELECT count(*) FROM recording_check_bindings').fetchone()==(0,)



def request_payload(r):
    return {'expected_manifest_id':str(r['manifest']),'expected_manifest_hash':r['hash'],**copy.deepcopy(PAYLOAD)}


def test_api_context_save_retry_and_offline_read(recorded):
    r=recorded;url=f"/api/v1/projects/{r['project']}/recordings/{r['recording']}/check-bindings"
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=r['app']),base_url='http://127.0.0.1') as client:
            headers=await session(client,str(r['project']));headers['Idempotency-Key']='api-binding'
            context=await client.get(url)
            assert context.status_code==200,context.text
            assert context.json()['actions'][-1]['id']=='a5'
            saved=await client.post(url,json=request_payload(r),headers=headers)
            assert saved.status_code==201,saved.text
            retry=await client.post(url,json=request_payload(r),headers=headers)
            assert retry.status_code==200 and retry.json()['manifest_id']==saved.json()['manifest_id']
            assert retry.json()['approved'] is False
            current=await client.get(url)
            assert current.json()['bindings']==PAYLOAD
            stale=await client.post(url,json=request_payload(r),headers={**headers,'Idempotency-Key':'second-api-binding'})
            assert stale.status_code==409
    asyncio.run(run())


def test_api_requires_session_csrf_origin_and_exact_payload(recorded):
    r=recorded;url=f"/api/v1/projects/{r['project']}/recordings/{r['recording']}/check-bindings"
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=r['app']),base_url='http://127.0.0.1') as client:
            assert (await client.get(url)).status_code==401
            headers=await session(client,str(r['project']))
            assert (await client.post(url,json=request_payload(r),headers={'Origin':headers['Origin'],'Idempotency-Key':'no-csrf'})).status_code==403
            assert (await client.post(url,json=request_payload(r),headers={**headers,'Origin':'https://other.example'})).status_code==403
            assert (await client.post(url,json={**request_payload(r),'expected':'invented'},headers=headers)).status_code==422
    asyncio.run(run())
    with r['store'].transaction() as c:assert c.execute('SELECT count(*) FROM recording_check_bindings').fetchone()==(0,)


def test_failed_materialization_rolls_back_even_if_caller_catches(recorded,monkeypatch):
    import aiqa.recording.service as service
    r=recorded
    def fail(*args,**kwargs):raise RuntimeError('simulated candidate failure')
    monkeypatch.setattr(service,'materialize_android_recording',fail)
    with r['store'].transaction() as c:
        with pytest.raises(RuntimeError):save(c,r)
        assert c.execute('SELECT count(*) FROM recording_check_bindings').fetchone()==(0,)
        assert c.execute('SELECT count(*) FROM recording_manifests WHERE project_id=? AND recording_id=?',(str(r['project']),str(r['recording']))).fetchone()==(1,)



@pytest.mark.parametrize('damage',['recording','source_hash','prior_manifest','input_version'])
def test_schema_rejects_cross_recording_or_source_annotation_rows(recorded,damage):
    r=recorded
    with r['store'].transaction() as c:
        receipt=save(c,r);derived=str(uuid4());other=str(uuid4())
        c.execute("INSERT INTO recordings(project_id,case_id,recording_id,creation_kind,input_case_version_id,storage_status,stop_status,completion_status,evidence_status) VALUES(?,?,?,'recorded',?,'stored','stopped','completed','complete')",(str(r['project']),r['case'],other,r['input_version']))
        c.execute("""INSERT INTO recording_manifests(project_id,case_id,recording_id,manifest_id,revision,kind,prior_manifest_id,input_version_hash,source_artifact_hashes,action_mapping,evidence_completeness,request_key,body_hash)
            SELECT project_id,case_id,recording_id,?,3,'package_rebuild',manifest_id,?,source_artifact_hashes,action_mapping,evidence_completeness,'fixture-derived','fixture-derived-body' FROM recording_manifests WHERE manifest_id=?""",(derived,c.execute('SELECT content_hash FROM case_versions WHERE version_id=?',(r['input_version'],)).fetchone()[0],str(r['manifest'])))
        cur=c.execute('SELECT * FROM recording_check_bindings WHERE manifest_id=?',(receipt['manifest_id'],))
        row=dict(zip((d[0] for d in cur.description),cur.fetchone()));row.update(manifest_id=derived,request_key='forged-binding')
        if damage=='recording':row['recording_id']=other
        elif damage=='source_hash':row['source_manifest_hash']='not the immutable source hash'
        elif damage=='prior_manifest':
            row['source_manifest_id']=receipt['manifest_id'];row['source_manifest_hash']=c.execute('SELECT body_hash FROM recording_manifests WHERE manifest_id=?',(receipt['manifest_id'],)).fetchone()[0]
        else:row['input_case_version_id']=r['old_draft']
        fields=list(row)
        with pytest.raises(sqlite3.IntegrityError):c.execute('INSERT INTO recording_check_bindings('+','.join(fields)+') VALUES('+','.join('?' for _ in fields)+')',tuple(row[k] for k in fields))


def test_generic_rebuild_cannot_silently_drop_saved_check_bindings(recorded):
    from aiqa.recording.service import rebuild_android_package,PreflightRejected
    r=recorded
    with r['store'].transaction() as c:
        receipt=save(c,r)
        with pytest.raises(PreflightRejected):rebuild_android_package(c,r['actor'],r['project'],r['recording'],'unsupported-rebuild')
        assert load_check_binding_context(c,r['project'],r['recording'])['bindings']==PAYLOAD


def test_new_binding_candidate_uses_actual_creation_time(recorded):
    from datetime import datetime,timezone,timedelta
    r=recorded;before=datetime.now(timezone.utc)-timedelta(seconds=1)
    with r['store'].transaction() as c:
        receipt=save(c,r)
        stamp=c.execute('SELECT created_at FROM case_versions WHERE version_id=?',(receipt['case_version_id'],)).fetchone()[0]
        assert before<=datetime.fromisoformat(stamp)<=datetime.now(timezone.utc)+timedelta(seconds=1)


def test_stream_limit_rejects_oversize_chunk_before_copy(recorded,monkeypatch):
    import aiqa.api.recording_check_bindings as api
    r=recorded;peaks=[]
    class BoundedBuffer(bytearray):
        def extend(self,value):
            super().extend(value);peaks.append(len(self))
    monkeypatch.setattr(api,'bytearray',BoundedBuffer,raising=False)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=r['app']),base_url='http://127.0.0.1') as client:
            response=await client.post(f"/api/v1/projects/{r['project']}/recordings/{r['recording']}/check-bindings",content=b' '*131073,headers={'Idempotency-Key':'oversize'})
            assert response.status_code==413
    asyncio.run(run())
    assert max(peaks,default=0)<=131072
