"""Server admission checks use temporary stores; no device/worker is contacted."""
import asyncio
import json
import sqlite3
from uuid import UUID, uuid4

import pytest
import httpx

from acceptance.test_w17 import _case, _packages, _selection
from acceptance.test_w22 import _rerun_graph
from aiqa.contracts.jobs import IdempotencyKey
from aiqa.domain.executions import preview_execution, preview_rerun
from aiqa.domain.resource_readiness import resource_readiness
from aiqa.recording.service import PreflightRejected, _require_resource
from aiqa.store.models import Actor, Transaction
from ux_support import ux_app, session


def quarantine(connection, project, resource):
    connection.execute(
        "INSERT INTO resource_quarantine(physical_key_id,reason,quarantined_at) VALUES(?,'restarted','2026-11-02T00:00:00+00:00')",
        (resource,),
    )


@pytest.fixture
def trial(ux_app):
    app, project, database = ux_app
    base, case = asyncio.run(_case(app, project))
    environment, resource = str(uuid4()), str(uuid4())
    version, _, _ = _packages(database, project, case, base, environment, resource)
    with sqlite3.connect(database) as connection:
        # The legacy replay graph inserts versions directly; restore its case
        # counter/head before exercising the public rerecord mutation.
        connection.execute(
            'UPDATE automation_cases SET next_revision=(SELECT MAX(revision)+1 FROM case_versions WHERE case_id=?),latest_draft_version_id=? WHERE case_id=?',
            (case, version, case),
        )
    return project, database, version, environment, resource


def test_recording_rejects_ready_inventory_while_resource_is_quarantined(trial):
    project, database, _, _, resource = trial
    with sqlite3.connect(database) as connection:
        quarantine(connection, project, resource)
        with pytest.raises(PreflightRejected, match='quarantin'):
            _require_resource(connection, UUID(project), resource, 'web')


def test_trial_preview_rejects_ready_inventory_while_resource_is_quarantined(trial):
    project, database, version, environment, resource = trial
    with sqlite3.connect(database) as connection:
        quarantine(connection, project, resource)
        preview = preview_execution(Transaction(connection), Actor(uuid4(), UUID(project), True), UUID(project), _selection(version, environment, resource, False))
        assert not preview.ready
        assert any(b.code == 'RESOURCE_UNAVAILABLE' for b in preview.blockers)


@pytest.mark.parametrize('purpose', ['regression', 'reverification'])
def test_formal_preview_keeps_offline_resource_blocker(trial, purpose):
    project, database, version, environment, resource = trial
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE resource_inventory SET state='offline' WHERE physical_key_id=?", (resource,))
        before = counts(connection)
        payload = _selection(version, environment, resource, False)
        payload['purpose'] = purpose
        preview = preview_execution(Transaction(connection), Actor(uuid4(), UUID(project), True), UUID(project), payload)
        assert not preview.ready
        assert any(b.code == 'RESOURCE_UNAVAILABLE' for b in preview.blockers)
        assert counts(connection) == before


def test_readiness_hides_other_projects_and_rejects_wrong_target(trial):
    project, database, _, _, resource = trial
    with sqlite3.connect(database) as connection:
        foreign = resource_readiness(connection, uuid4(), resource, 'web')
        missing = resource_readiness(connection, UUID(project), str(uuid4()), 'web')
        assert foreign == missing and not foreign.ready
        mismatch = resource_readiness(connection, UUID(project), resource, 'android')
        assert not mismatch.ready and mismatch.code == 'RESOURCE_UNAVAILABLE'
        assert resource_readiness(connection, UUID(project), resource, 'web').ready


@pytest.mark.parametrize('state', ['offline', 'unauthorized', 'busy', 'quarantine'])
def test_new_rerun_rechecks_resource_without_creating_jobs(ux_app, state):
    _, project, database = ux_app
    actor = Actor(uuid4(), UUID(project), True)
    graph = _rerun_graph(database, project, str(actor.actor_id))
    with sqlite3.connect(database) as connection:
        limits = json.loads(connection.execute('SELECT limits FROM jobs WHERE job_id=?', (graph['failed_job'],)).fetchone()[0])
        resource = limits['resource_id']
        if state == 'quarantine':
            quarantine(connection, project, resource)
        else:
            connection.execute('UPDATE resource_inventory SET state=? WHERE physical_key_id=?', (state, resource))
        before = counts(connection)
        result = preview_rerun(Transaction(connection), actor, UUID(graph['execution']), {'scope': 'failed', 'reason': 'manual retry'}, IdempotencyKey(actor.actor_id, UUID(project), 'rerun_execution', 'new-offline'))
        assert not result.ready
        assert any(b.code in {'RESOURCE_UNAVAILABLE', 'RESOURCE_BUSY'} for b in result.blockers)
        assert counts(connection) == before


def test_completed_rerun_receipt_is_readable_after_resource_goes_offline(ux_app):
    _, project, database = ux_app
    actor = Actor(uuid4(), UUID(project), True)
    graph = _rerun_graph(database, project, str(actor.actor_id))
    key = IdempotencyKey(actor.actor_id, UUID(project), 'rerun_execution', 'existing-rerun')
    body = {'scope': 'failed', 'reason': 'manual retry'}
    with sqlite3.connect(database) as connection:
        first = preview_rerun(Transaction(connection), actor, UUID(graph['execution']), body, key)
        assert first.ready
        from datetime import datetime, timezone

        from aiqa.store.models import WorkerScope
        from aiqa.store.queue import claim_queued_job

        lease = claim_queued_job(
            connection, WorkerScope("rerun-worker", (UUID(project),), ("regression",)), datetime.now(timezone.utc),
        )
        assert lease is not None and lease.physical_key_id == first.resolved_items[0].resource_id
        before = counts(connection)
        connection.execute("UPDATE resource_inventory SET state='offline'")
        again = preview_rerun(Transaction(connection), actor, UUID(graph['execution']), body, key)
        assert again.ready and again.preview_hash == first.preview_hash
        assert counts(connection) == before


@pytest.mark.parametrize('state', ['offline', 'quarantine'])
def test_public_recording_and_rerecord_rejection_leaves_no_candidate_or_job(trial, ux_app, state):
    project, database, version, _, resource = trial
    app = ux_app[0]
    with sqlite3.connect(database) as connection:
        case, content_hash = connection.execute('SELECT case_id,content_hash FROM case_versions WHERE version_id=?', (version,)).fetchone()
        if state == 'quarantine':
            quarantine(connection, project, resource)
        else:
            connection.execute("UPDATE resource_inventory SET state='offline' WHERE physical_key_id=?", (resource,))
        before = counts(connection) + tuple(connection.execute('SELECT COUNT(*) FROM ' + name).fetchone()[0] for name in ('case_versions', 'recordings'))

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1') as client:
            headers = await session(client, project)
            start = await client.post(f'/api/v1/projects/{project}/recordings', headers={**headers, 'Idempotency-Key': 'offline-record'}, json={'case_id': case, 'input_case_version_id': version, 'input_version_hash': content_hash, 'resource_id': resource})
            assert start.status_code == 422, start.text
            rerecord = await client.post(f'/api/v1/cases/{case}/rerecordings', headers={**headers, 'Idempotency-Key': 'offline-rerecord'}, json={'project_id': project, 'base_version_id': version, 'expected_head': version, 'reason': 'new recording', 'resource_id': resource, 'web_url': 'https://example.test', 'confirm_device': True, 'confirm_target': True, 'confirm_data': True, 'confirm_reset': True})
            assert rerecord.status_code == 422, rerecord.text
            assert 'resource' in rerecord.json()['error']['message']
    asyncio.run(exercise())
    with sqlite3.connect(database) as connection:
        after = counts(connection) + tuple(connection.execute('SELECT COUNT(*) FROM ' + name).fetchone()[0] for name in ('case_versions', 'recordings'))
        assert after == before


def test_public_enqueue_rechecks_resource_after_ready_preview(trial, ux_app):
    project, database, version, environment, resource = trial
    app = ux_app[0]
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1') as client:
            headers = await session(client, project)
            preview = await client.post(f'/api/v1/projects/{project}/execution-previews', headers=headers, json=_selection(version, environment, resource, False))
            assert preview.status_code == 200 and preview.json()['ready'], preview.text
            body = preview.json()
            with sqlite3.connect(database) as connection:
                before = counts(connection)
                connection.execute("UPDATE resource_inventory SET state='offline' WHERE physical_key_id=?", (resource,))
            response = await client.post(f'/api/v1/projects/{project}/executions', headers={**headers, 'Idempotency-Key': 'preview-then-offline'}, json={'name': 'offline after preview', 'purpose': 'trial', 'source': 'single', 'failure_policy': 'stop_on_non_pass', 'self_healing_enabled': False, 'preview_hash': body['preview_hash'], 'exclusions': [], 'items': body['resolved_items']})
            assert response.status_code == 422, response.text
            with sqlite3.connect(database) as connection:
                assert counts(connection) == before
    asyncio.run(exercise())


def counts(connection):
    return tuple(connection.execute('SELECT COUNT(*) FROM ' + name).fetchone()[0] for name in ('jobs', 'case_runs', 'executions'))
