"""Shared pytest settings. The aiqa package comes from the editable install."""

from worker_presence_support import seed_presence, seed_inventory
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4
import sqlite3
import pytest

from aiqa.api.auth import bound_auth_store, enroll_worker
from aiqa.contracts.cases import CaseDefinition, CaseRevisionInput, CaseSettings, PathPolicy
from aiqa.contracts.jobs import IdempotencyKey, JobSubmission, LeaseToken
from aiqa.domain.projects import bind_store, create_project
from aiqa.domain.versions import bind_case_store, create_case, save_case_revision
from aiqa.store.database import StorageConfig, Store, migrate_store
from aiqa.store.models import Actor, ProjectCreate, Transaction, WorkerScope
from aiqa.store.queue import enqueue_job
from aiqa.worker.service import bind_claim_store, claim_job


@pytest.fixture
def review_recording(tmp_path):
    con = sqlite3.connect(':memory:', isolation_level=None)
    con.execute('PRAGMA foreign_keys=ON')
    store = Store(StorageConfig(tmp_path, tmp_path / 'unused.sqlite', tmp_path / 'artifacts', tmp_path / 'spool'), con)
    migrate_store(store)
    owner = Actor(uuid4(), None, True)
    with bind_store(store):
        project = create_project(owner, ProjectCreate('Review', 'review', 'r', 'web'))
    actor = Actor(owner.actor_id, project.project_id, True)
    with bind_case_store(store):
        case = create_case(actor, 'Review', None)
        version = save_case_revision(actor, case.case_id, CaseRevisionInput(CaseDefinition('pay', 'pay', (), {}, {}, (), (), PathPolicy()), CaseSettings('web')), None)
    with bound_auth_store(store):
        worker_token = enroll_worker(actor, 'review-worker', 'recording')
    physical = uuid4()
    con.execute('INSERT INTO physical_resource_keys (physical_key_id,worker_id,native_id) VALUES (?,?,?)', (str(physical), 'review-worker', 'fixture-device'))
    con.execute('INSERT INTO resource_aliases (project_id,physical_key_id,display_name,target_kind) VALUES (?,?,?,?)', (str(project.project_id), str(physical), 'Fixture', 'web'))
    now = datetime(2026, 11, 1, tzinfo=timezone.utc)
    seed_presence(con, project.project_id, "review-worker", now)
    seed_inventory(con, physical)
    with store.transaction() as tx:
        receipt = enqueue_job(Transaction(tx), JobSubmission(project.project_id, 'recording', case.case_id, version.id, (str(physical),), '{}'), IdempotencyKey(actor.actor_id, project.project_id, 'enqueue_job', 'review-job'), now=now)
    worker = WorkerScope('review-worker', (project.project_id,), ('recording',))
    with bind_claim_store(store):
        job = claim_job(worker, now)
    assert job is not None
    try:
        yield SimpleNamespace(store=store, con=con, project=project, actor=actor, case=case, version=version, recording_id=receipt.recording_id, job=job, lease=LeaseToken(job.project_id, job.job_id, job.generation), worker=worker, worker_token=worker_token, now=now)
    finally:
        store.close()
