"""A leased replay evaluates saved expectations using committed image evidence."""
import asyncio
import base64
import hashlib
import json
from dataclasses import asdict, replace
from datetime import datetime, timezone
from uuid import uuid4
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
import pytest

from aiqa.api.auth import bound_auth_store, enroll_worker
from aiqa.models.broker import ServerModelGateway
from aiqa.models.provider_http import FixtureProviderHttp, ProviderHttpResult
from aiqa.security.secrets import MemorySecretBackend, bind_secret_store, build_server_secret_resolver
from aiqa.store.models import SecretInput
from aiqa.worker.http_client import WorkerHttpClient, WorkerClientSettings, SyncASGITransport
from test_rx87_check_bindings import recorded, save
from ux_support import session


@pytest.fixture
def ux_app():
    from aiqa.api.app import create_app
    from aiqa.config import load_settings
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.store.models import Actor, ProjectCreate
    from aiqa.store.database import migrate_store
    with TemporaryDirectory(prefix='aiqa-visual-') as temporary:
        root = Path(temporary) / 'runtime'
        app = create_app(load_settings({'AIQA_HOST':'127.0.0.1','AIQA_PORT':'8000','AIQA_RUNTIME_ROOT':str(root)}))
        store = app.state.open_store()
        migrate_store(store)
        with bind_store(store):
            project = create_project(Actor(uuid4(),None,True),ProjectCreate('Visual','visual','review','android'))
        store.close()
        yield app, str(project.project_id), root/'db'/'aiqa.sqlite'


class VisualProvider(FixtureProviderHttp):
    def __init__(self):
        super().__init__()
        self.reply = '{"status":"satisfied","reason":"expected visible"}'
        self.after = None

    def complete(self, **kwargs):
        receipt = super().complete(**kwargs)
        if self.after:
            self.after()
        return ProviderHttpResult(self.reply, receipt.provider_request_id, 200, kwargs['model'])


def post(f, body=None, key='evaluate'):
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=f['app']), base_url='http://127.0.0.1') as client:
            return await client.post('/api/v1/worker/check-evaluations', json=body or f['payload'],
                headers={'Authorization':'Bearer '+f['token'], 'Idempotency-Key':key})
    return asyncio.run(run())


@pytest.fixture
def visual_job(ux_app, monkeypatch, request):
    import test_rx87_check_bindings as sources
    from acceptance.test_w17 import _selection
    from test_w16 import _binding
    from worker_presence_support import seed_presence
    from test_rx_65 import _observation

    app, project, database = ux_app
    _binding(database, project, str(uuid4()))
    settings = replace(app.state.settings, model_price_mode='estimate')
    app.state.settings = settings
    backend = MemorySecretBackend()
    resolver = build_server_secret_resolver(settings, backend=backend)
    app.state.secret_resolver = resolver
    store = app.state.open_store()
    from aiqa.store.models import Actor
    from uuid import UUID
    actor = Actor(uuid4(), UUID(project), True)
    with bind_secret_store(store):
        secret = resolver.put(actor, SecretInput(value='synthetic-verification-secret', name='verify'))
    with store.transaction() as c:
        from test_rx97_recording_pin import _new_revision
        _new_revision(c,project,role='verification',model='visual-model',key_ref_id=str(secret.ref_id),key_revision=secret.revision)
    store.close()
    monkeypatch.setattr(sources, 'SETTINGS', {**sources.SETTINGS, 'verifier_bindings':[
        {'method':'ai_visual','binding_id':'bind-w1605','role':'verification','allow_unknown_supplement':False}]})
    r = request.getfixturevalue('recorded')
    provider = VisualProvider()
    app.state.model_gateway = ServerModelGateway(provider=provider, resolver=resolver)
    resource, environment = str(uuid4()), str(uuid4())
    with bound_auth_store(r['store']):
        token = enroll_worker(r['actor'], 'visual-worker', 'trial')
    with r['store'].transaction() as c:
        saved = save(c, r)
        c.execute("INSERT INTO physical_resource_keys VALUES(?,'visual-worker','emulator-5580')", (resource,))
        c.execute("INSERT INTO resource_aliases(project_id,physical_key_id,display_name,target_kind) VALUES(?,?,'Android','android')", (project,resource))
        seed_presence(c, project, 'visual-worker')
        c.execute("INSERT INTO resource_inventory VALUES(?,'ready','','','[]','','2026-11-17')", (resource,))
        c.execute("INSERT INTO environments(project_id,environment_id,name,next_revision,latest_revision_id) VALUES(?,'visual-env','Local',2,?)", (project,environment))
        c.execute("INSERT INTO environment_revisions(project_id,environment_id,revision_id,revision,body_json,content_hash,actor_id,created_at) VALUES(?,'visual-env',?,1,'{}','env-hash','actor','2026-11-17T00:00:00+00:00')", (project,environment))
    async def start():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1') as client:
            headers = await session(client, project)
            selection = _selection(saved['case_version_id'], environment, resource, False)
            preview = await client.post(f'/api/v1/projects/{project}/execution-previews',json=selection,headers=headers)
            assert preview.status_code == 200 and preview.json()['ready'], preview.text
            body = {**selection,'preview_hash':preview.json()['preview_hash'],'items':preview.json()['resolved_items']}
            body.pop('selection')
            created = await client.post(f'/api/v1/projects/{project}/executions',json=body,headers={**headers,'Idempotency-Key':'visual-trial'})
            assert created.status_code == 201, created.text
            worker_headers = {'Authorization':'Bearer '+token,'Idempotency-Key':'visual-claim'}
            claim = await client.post('/api/v1/worker/claims',json={'project_id':project,'boot_id':'fixture-boot'},headers=worker_headers)
            assert claim.status_code == 200, claim.text
            job = claim.json()
            ack = await client.post('/api/v1/worker/attempt-acks',json={'project_id':project,'job_id':job['job_id'],'generation':job['generation'],'runner_nonce':str(uuid4())},headers={**worker_headers,'Idempotency-Key':'visual-ack'})
            assert ack.status_code == 200, ack.text
            return job
    job = asyncio.run(start())
    observation = _observation()
    digest = 'sha256:'+hashlib.sha256(observation.png).hexdigest()
    action = 'replay-'+job['attempt_id']+'-5'
    with WorkerHttpClient(WorkerClientSettings('https://127.0.0.1',token), transport=SyncASGITransport(app)) as client:
        committed = client.commit_evidence(sanitized=True,project_id=project,job_id=job['job_id'],generation=job['generation'],
            now=datetime.now(timezone.utc).isoformat(),events=[],artifacts=[{'filename':'after.png','media_type':'image/png',
                'declared_hash':digest,'declared_length':len(observation.png),'body_b64':base64.b64encode(observation.png).decode(),
                'owner_kind':'ITEM','attempt_id':job['attempt_id'],'action_id':action,'role':'after'}],idempotency_key='visual-evidence')
    payload = {'project_id':project,'job_id':job['job_id'],'attempt_id':job['attempt_id'],'generation':job['generation'],
        'action_id':action,'check_id':'final','artifact_id':committed['artifact_ids'][0], 'image_hash':digest,
        'geometry':asdict(observation.geometry),'captured_at':observation.captured_at}
    return {**r,'database':database,'provider':provider,'resolver':resolver,'token':token,'job':job,'payload':payload}


def test_visual_evaluation_uses_saved_expected_image_and_durable_idempotency(visual_job):
    f = visual_job
    response = post(f)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['result']['status'] == 'satisfied'
    assert body['result']['method'] == 'ai_visual' and body['provider_dispatched'] is True
    assert 'expected_snapshot' not in body['result']
    sent = f['provider'].calls[0]
    assert sent.role == 'verification' and sent.observation_hash == f['payload']['image_hash']
    assert any('visible' in value for value in sent.sanitized_inputs)
    with f['store'].transaction() as c:
        row = c.execute('SELECT status,expected_snapshot,artifact_refs FROM check_results WHERE attempt_id=?', (f['job']['attempt_id'],)).fetchone()
        assert row == ('satisfied','visible',json.dumps([f['payload']['artifact_id']],separators=(',',':')))
        assert c.execute('SELECT role,check_id FROM model_call_facts WHERE attempt_id=?',(f['job']['attempt_id'],)).fetchone() == ('verification','final')
    f['app'].state.model_gateway = ServerModelGateway(provider=f['provider'],resolver=f['resolver'])
    again = post(f)
    assert again.status_code == 200 and again.json()['replayed'] is True
    assert f['provider'].call_count == 1
    mismatch = post(f,{**f['payload'],'image_hash':'sha256:changed'})
    assert mismatch.status_code == 409 and f['provider'].call_count == 1


@pytest.mark.parametrize('damage',['check','action','artifact','hash','geometry','old','generation','cancelled','unacked','binding_role','secret'])
def test_invalid_visual_evidence_and_authority_do_not_send(visual_job, damage):
    f = visual_job
    payload = dict(f['payload'])
    with f['store'].transaction() as c:
        if damage == 'cancelled': c.execute("UPDATE jobs SET status='cancel_requested' WHERE job_id=?",(f['job']['job_id'],))
        elif damage == 'unacked': c.execute('DELETE FROM attempt_runners WHERE attempt_id=?',(f['job']['attempt_id'],))
        elif damage == 'binding_role':
            from test_rx97_recording_pin import _new_revision
            _new_revision(c,str(f['project']),role='authoring')
        elif damage == 'secret': c.execute("UPDATE secret_refs SET availability='revoked'")
    if damage == 'check': payload['check_id'] = 'foreign'
    elif damage == 'action': payload['action_id'] = 'replay-'+f['job']['attempt_id']+'-2'
    elif damage == 'artifact': payload['artifact_id'] = str(uuid4())
    elif damage == 'hash': payload['image_hash'] = 'sha256:changed'
    elif damage == 'geometry': payload['geometry'] = {**payload['geometry'],'physical_width':1}
    elif damage == 'old': payload['captured_at'] = '2020-01-01T00:00:00+00:00'
    elif damage == 'generation': payload['generation'] += 1
    response = post(f,payload)
    assert response.status_code in {403,422}, response.text
    assert f['provider'].call_count == 0


@pytest.mark.parametrize('reply,expected',[('{"status":"violated"}','violated'),('{"status":"unknown"}','unknown'),('PASS','unknown'),('{"status":"satisfied","extra":"forged"}','unknown')])
def test_provider_reply_is_normalized_and_invalid_reply_is_unknown(visual_job, reply, expected):
    f = visual_job
    f['provider'].reply = reply
    response = post(f)
    assert response.status_code == 200, response.text
    assert response.json()['result']['status'] == expected
    assert f['provider'].call_count == 1


def test_late_cancel_discards_satisfied_response(visual_job):
    f = visual_job
    def cancel():
        store = f['app'].state.open_store()
        try:
            with store.transaction() as c:
                c.execute("UPDATE jobs SET status='cancel_requested' WHERE job_id=?",(f['job']['job_id'],))
        finally:
            store.close()
    f['provider'].after = cancel
    response = post(f)
    assert response.status_code == 200, response.text
    assert response.json()['result']['status'] == 'unknown'
    assert response.json()['result']['reason'] == 'response_late'
    assert f['provider'].call_count == 1


def test_already_evaluated_check_cannot_spend_again_under_new_key(visual_job):
    f = visual_job
    assert post(f).status_code == 200
    repeated = post(f,key='different-key')
    assert repeated.status_code == 409, repeated.text
    assert f['provider'].call_count == 1


def test_worker_cannot_supply_expected_or_skip_explicit_source_policy(visual_job):
    f = visual_job
    rejected = post(f,{**f['payload'],'expected':'invented success'})
    assert rejected.status_code == 422
    assert f['provider'].call_count == 0


def test_claim_package_change_is_refused_before_provider(visual_job):
    f = visual_job
    with f['store'].transaction() as c:
        limits = json.loads(c.execute('SELECT limits FROM jobs WHERE job_id=?',(f['job']['job_id'],)).fetchone()[0])
        limits['replay_package_hash'] = 'sha256:changed'
        c.execute('UPDATE jobs SET limits=? WHERE job_id=?',(json.dumps(limits),f['job']['job_id']))
    rejected = post(f)
    assert rejected.status_code in {403,422}, rejected.text
    assert f['provider'].call_count == 0


def test_provider_failure_is_durable_and_never_retried(visual_job):
    f = visual_job
    def fail():
        raise RuntimeError('synthetic-verification-secret')
    f['provider'].after = fail
    failed = post(f)
    assert failed.status_code == 503
    assert 'synthetic-verification-secret' not in failed.text
    f['app'].state.model_gateway = ServerModelGateway(provider=f['provider'],resolver=f['resolver'])
    again = post(f)
    assert again.status_code == 503 and again.json()['error']['replayed'] is True
    assert f['provider'].call_count == 1


def test_completed_response_is_not_reused_after_cancellation(visual_job):
    f = visual_job
    assert post(f).status_code == 200
    with f['store'].transaction() as c:
        c.execute("UPDATE jobs SET status='cancel_requested' WHERE job_id=?",(f['job']['job_id'],))
    repeated = post(f)
    assert repeated.status_code == 403
    assert f['provider'].call_count == 1
