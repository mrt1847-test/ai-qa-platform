"""Fresh management-side worker fence checks; no device, model or lease renewal."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from aiqa.contracts.jobs import LeaseToken
from aiqa.store.queue import LeaseDenied, StaleGeneration, _require_open_lease

PHASES = frozenset({'before_model', 'after_model', 'before_lookup', 'before_dispatch'})


class CheckpointRejected(ValueError):
    def __init__(self, reason, status=403):
        super().__init__(reason)
        self.reason = reason
        self.status = status


def read_worker_checkpoint(connection, worker, project_id, job_id, attempt_id, generation, phase, now):
    if type(phase) is not str or phase not in PHASES:
        raise CheckpointRejected('checkpoint_phase',422)
    if project_id not in worker.permitted_projects:
        raise CheckpointRejected('worker_scope')
    row = connection.execute("""SELECT a.generation,j.status,j.purpose,j.limits,r.acked_at,a.physical_key_id,
        (SELECT MIN(c.created_at) FROM claim_receipts c WHERE c.project_id=a.project_id AND c.attempt_id=a.attempt_id),
        (SELECT MAX(other.generation) FROM attempts other WHERE other.project_id=a.project_id AND other.job_id=a.job_id)
        FROM attempts a JOIN jobs j ON j.project_id=a.project_id AND j.job_id=a.job_id
        LEFT JOIN attempt_runners r ON r.project_id=a.project_id AND r.attempt_id=a.attempt_id
        WHERE a.project_id=? AND a.job_id=? AND a.attempt_id=?""",
        (str(project_id),str(job_id),str(attempt_id))).fetchone()
    if row is None or row[2] not in worker.permitted_purposes:
        raise CheckpointRejected('worker_scope')
    if row[0] != generation or row[7] != generation:
        raise CheckpointRejected('stale_generation',409)
    if row[1] not in ('preparing','running'):
        raise CheckpointRejected('job_inactive')
    if connection.execute('SELECT 1 FROM job_cancellations WHERE project_id=? AND job_id=?',
        (str(project_id),str(job_id))).fetchone():
        raise CheckpointRejected('cancelled')
    if row[4] is None or row[6] is None:
        raise CheckpointRejected('runner_unacked')
    try:
        _require_open_lease(connection,worker,LeaseToken(project_id,job_id,generation),now,now)
    except LeaseDenied as exc:
        raise CheckpointRejected('lease_unavailable') from exc
    except StaleGeneration as exc:
        raise CheckpointRejected('stale_generation',409) from exc
    lease = connection.execute('SELECT expires_at,physical_key_id FROM leases WHERE project_id=? AND job_id=? AND generation=?',
        (str(project_id),str(job_id),generation)).fetchone()
    try:
        expires = datetime.fromisoformat(lease[0])
        started = datetime.fromisoformat(row[6])
        limits = json.loads(row[3])
        seconds = limits.get('timeout_seconds',600)
        if type(seconds) is not int or not 1 <= seconds <= 600 or started.tzinfo is None or expires.tzinfo is None:
            raise ValueError('invalid deadline')
        deadline = started + timedelta(seconds=seconds)
        remaining = (expires-now).total_seconds()
    except (ValueError,TypeError,KeyError,AttributeError) as exc:
        raise CheckpointRejected('job_deadline_invalid') from exc
    if lease[1] != row[5] or remaining < 10:
        raise CheckpointRejected('lease_margin')
    if now < started or now >= deadline:
        raise CheckpointRejected('job_deadline')
    return {'allowed':True,'phase':phase,'project_id':str(project_id),'job_id':str(job_id),
        'attempt_id':str(attempt_id),'generation':generation,'server_time':now.isoformat(),
        'lease_remaining_seconds':remaining,'job_deadline':deadline.isoformat()}


def checkpoint_http(open_store,worker,project_id,job_id,attempt_id,generation,phase,clock):
    store = open_store()
    try:
        with store.transaction() as connection:
            return 200,read_worker_checkpoint(connection,worker,project_id,job_id,attempt_id,generation,phase,clock())
    except CheckpointRejected as exc:
        return exc.status,{'error':{'code':'checkpoint_blocked','message':exc.reason,'fields':{}}}
    finally:
        store.close()
