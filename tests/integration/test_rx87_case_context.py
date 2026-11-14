"""Normal claim must carry the immutable case validation source, not worker defaults."""
import asyncio
from datetime import datetime,timezone
import httpx
from test_rx97_recording_pin import recording,ux_app,request as start,claim


def test_normal_claim_supplies_frozen_case_context(recording):
    f=recording;result=start(f);assert result.status_code==201,result.text
    job=claim(f);context=job['snapshot'].get('case_context')
    assert context is not None,'normal HTTP claim omitted the case validation source'
    assert context['schema']=='case-context-v1'
    assert context['case_version_id']==f['body']['input_case_version_id']
    assert context['content_hash']==f['body']['input_version_hash']
    assert context['objective']=='Check saved target' and context['final_expected']==[]
    assert context['target']=={'kind':'web','android_package':''}
    assert context['job_id']==job['job_id'] and context['attempt_id']==job['attempt_id']
    assert context['generation']==job['generation'] and context['project_id']==f['project']


import json
import sqlite3
from types import SimpleNamespace
from uuid import UUID,uuid4
import pytest
from ux_support import session
from aiqa.domain.hashing import canonical_hash
from aiqa.recording.case_context import load_case_context


def _save(f, *, objective, target='web', package='', checks=None):
    async def save():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=f['app']),base_url='http://127.0.0.1') as client:
            headers=await session(client,f['project'])
            result=await client.post(f"/api/v1/projects/{f['project']}/cases/{f['body']['case_id']}/versions",json={
                'definition':{'objective':objective,'steps':[{'id':'saved-step','instruction':'tap','expected':[{'id':'saved-check','kind':'text','expected':'Saved'}]}],
                    'final_expected':checks or [{'id':'saved-final','kind':'text','expected':'Done'}]},
                'settings':{'target_kind':target,'android_package':package,'limits':{'timeout_seconds':31,'max_actions':4,'max_model_calls':3,'budget':'0.70','currency':'USD'}},
                'expected_head':f['body']['input_case_version_id'],'parent_version_id':f['body']['input_case_version_id']},
                headers={**headers,'Idempotency-Key':'save-'+str(uuid4())})
            assert result.status_code==201,result.text
            return result.json()
    return asyncio.run(save())


def test_latest_draft_and_response_mutation_do_not_change_frozen_context(recording):
    f=recording;assert start(f).status_code==201
    first=claim(f);context=first['snapshot']['case_context'];original=json.loads(json.dumps(context))
    _save(f,objective='A later goal')
    context['objective']='worker mutation';context['target']['kind']='android'
    again=claim(f)
    assert again['snapshot']['case_context']==original and again['snapshot']['digest']==first['snapshot']['digest']
    assert again['replayed'] is True
    unsigned={key:value for key,value in original.items() if key!='context_hash'}
    assert canonical_hash(unsigned,'canon-json-v1')==original['context_hash']


def test_android_package_and_checks_come_from_the_saved_input_version(recording):
    f=recording
    # Only fixture inventory setup uses SQL; draft/start/claim use actual HTTP.
    with sqlite3.connect(f['database']) as c:
        c.execute("UPDATE resource_aliases SET target_kind='android' WHERE project_id=? AND physical_key_id=?",(f['project'],f['body']['resource_id']))
    saved=_save(f,objective='Saved Android goal',target='android',package='com.example.saved')
    f['body'].update(input_case_version_id=saved['id'],input_version_hash=saved['content_hash'])
    result=start(f);assert result.status_code==201,result.text
    job=claim(f);context=job['snapshot']['case_context']
    assert context['target']=={'kind':'android','android_package':'com.example.saved'}
    assert context['steps']==[{'id':'saved-step','instruction':'tap','expected':[{'id':'saved-check','kind':'text','expected':'Saved'}]}]
    assert context['final_expected']==[{'id':'saved-final','kind':'text','expected':'Done'}]
    assert context['case_version_id']==saved['id'] and context['content_hash']==saved['content_hash']
    assert context['verification'][0]['method']=='deterministic'


@pytest.mark.parametrize('field',['project_id','job_id','attempt_id','generation'])
def test_case_context_requires_exact_claim_scope(recording,field):
    f=recording;assert start(f).status_code==201;job=claim(f)
    receipt=SimpleNamespace(**{key:job[key] for key in ('project_id','job_id','attempt_id','generation')},
        snapshot=SimpleNamespace(purpose='recording',replay_package_id=None,replay_package_hash=None))
    setattr(receipt,field,2 if field=='generation' else str(uuid4()))
    with sqlite3.connect(f['database']) as c:assert load_case_context(c,receipt) is None


@pytest.mark.parametrize('recording',[('target_secret',None)],indirect=True)
def test_case_context_secret_fields_are_reference_only(recording):
    f=recording;assert start(f).status_code==201;job=claim(f)
    context=job['snapshot']['case_context'];refs=context['secret_refs']
    assert refs and refs==job['snapshot']['intent']['secret_refs']
    assert all(set(value)=={'project_id','ref_id','revision'} for value in refs.values())
    assert 'settings' not in context and 'raw_text' not in context and 'api_key' not in json.dumps(context)


from test_rx95_worker_healing_pin import healing_claim,admitted_healing,healing_execution,healing_metadata


def test_replay_context_uses_the_item_version_and_package(healing_claim,admitted_healing):
    job=healing_claim;f=admitted_healing;context=job['snapshot']['case_context']
    assert context['owner_kind']=='ITEM' and context['case_version_id']==f['item']['case_version_id']
    assert context['replay_package_id']==job['snapshot']['replay_package_id']
    assert context['replay_package_hash']==job['snapshot']['replay_package_hash']
    with sqlite3.connect(f['database']) as c:
        version,definition=c.execute('SELECT case_version_id,v.definition_json FROM case_runs i JOIN case_versions v ON v.project_id=i.project_id AND v.version_id=i.case_version_id WHERE i.project_id=? AND i.case_run_id=?',(f['project'],context['owner_id'])).fetchone()
    assert version==context['case_version_id'] and context['final_expected']==json.loads(definition).get('final_expected',[])


def test_worker_supplied_context_cannot_replace_the_server_projection(recording):
    from aiqa.api.auth import bound_auth_store,enroll_worker
    from aiqa.store.models import Actor
    f=recording;assert start(f).status_code==201
    store=f['app'].state.open_store()
    try:
        with bound_auth_store(store):token=enroll_worker(Actor(uuid4(),UUID(f['project']),True),'worker-w1605','recording')
    finally:store.close()
    async def forged():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=f['app']),base_url='http://127.0.0.1') as client:
            return await client.post('/api/v1/worker/claims',json={'project_id':f['project'],'boot_id':'fixture-boot',
                'now':datetime.now(timezone.utc).isoformat(),
                'case_context':{'case_version_id':str(uuid4()),'objective':'forged','context_hash':'forged'}},
                headers={'Authorization':'Bearer '+token,'Idempotency-Key':'forged-context'})
    result=asyncio.run(forged());assert result.status_code==200,result.text
    context=result.json()['snapshot']['case_context']
    assert context['objective']=='Check saved target' and context['case_version_id']==f['body']['input_case_version_id']
    assert context['context_hash']!='forged'


@pytest.mark.parametrize('purpose',['resource_probe','app_install'])
def test_non_case_jobs_do_not_load_validation_context(purpose):
    class NoQuery:
        def execute(self,*args):raise AssertionError('non-case job attempted case lookup')
    assert load_case_context(NoQuery(),SimpleNamespace(snapshot=SimpleNamespace(purpose=purpose))) is None


def test_secret_reference_projection_drops_values_and_rejects_foreign_project():
    from aiqa.recording.case_context import _secret_refs
    project=str(uuid4());ref={'project_id':project,'ref_id':str(uuid4()),'revision':1,'value':'never-forward-this'}
    result=_secret_refs({'account':ref},project)
    assert result=={'account':{key:ref[key] for key in ('project_id','ref_id','revision')}}
    assert 'never-forward-this' not in json.dumps(result)
    with pytest.raises(ValueError):_secret_refs({'account':{**ref,'project_id':str(uuid4())}},project)


def test_case_context_cannot_pair_a_version_with_another_package(healing_claim,admitted_healing):
    job=healing_claim;f=admitted_healing
    snapshot=SimpleNamespace(purpose='regression',replay_package_id=str(uuid4()),replay_package_hash=job['snapshot']['replay_package_hash'])
    receipt=SimpleNamespace(**{key:job[key] for key in ('project_id','job_id','attempt_id','generation')},snapshot=snapshot)
    with sqlite3.connect(f['database']) as c:
        with pytest.raises(ValueError,match='package mismatch'):load_case_context(c,receipt)
