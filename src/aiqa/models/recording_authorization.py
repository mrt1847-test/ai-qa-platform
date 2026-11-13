"""Server-only recording model grant. Client identity, flags, and deadlines are not authority."""
from __future__ import annotations
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from aiqa.contracts.authoring import validate_authoring_pin
from aiqa.contracts.jobs import LeaseToken
from aiqa.contracts.models import RoleBinding
from aiqa.models.broker import AttemptModelPolicy, ModelRequestDenied
from aiqa.recording.intent import load_intent_for_attempt, intent_to_document
from aiqa.store.models import SecretRef
from aiqa.store.queue import _require_open_lease, LeaseDenied, StaleGeneration


@dataclass(frozen=True, slots=True)
class RecordingGrant:
    policy: AttemptModelPolicy
    actor_id: UUID
    policy_ref: str
    endpoint: str
    provider: str
    endpoint_kind: str
    deadline: datetime


def is_recording_attempt(connection,project_id,item_id):
    row=connection.execute("""SELECT j.purpose FROM attempts a JOIN jobs j
        ON j.project_id=a.project_id AND j.job_id=a.job_id WHERE a.project_id=? AND a.attempt_id=?""",
        (str(project_id),item_id)).fetchone()
    return row is not None and row[0]=='recording'


def authorize_recording(connection,worker,request,project_id,item_id,now):
    def deny(reason='recording_authorization'):
        raise ModelRequestDenied(reason)
    if (project_id not in worker.permitted_projects or 'recording' not in worker.permitted_purposes
        or request.purpose!='recording' or request.role!='authoring' or request.owner_kind!='authoring'
        or request.owner_id!=item_id or request.check_id is not None or request.episode_id is not None):
        deny()
    row=connection.execute("""SELECT a.job_id,a.generation,j.purpose,j.status,j.limits,r.acked_at,
         (SELECT MIN(c.created_at) FROM claim_receipts c WHERE c.project_id=a.project_id AND c.attempt_id=a.attempt_id),
         (SELECT c.policy_ref FROM claim_receipts c WHERE c.project_id=a.project_id AND c.attempt_id=a.attempt_id LIMIT 1),
         (SELECT q.actor_id FROM job_receipts q WHERE q.project_id=a.project_id AND q.job_id=a.job_id LIMIT 1)
        FROM attempts a JOIN jobs j ON j.project_id=a.project_id AND j.job_id=a.job_id
        LEFT JOIN attempt_runners r ON r.project_id=a.project_id AND r.attempt_id=a.attempt_id
        WHERE a.project_id=? AND a.attempt_id=?""",(str(project_id),item_id)).fetchone()
    if row is None or row[2]!='recording' or row[3] not in ('preparing','running') or row[5] is None or row[6] is None or row[8] is None:
        deny()
    if type(request.generation) is not int or request.generation!=row[1]:deny('stale_generation')
    try:
        _require_open_lease(connection,worker,LeaseToken(project_id,UUID(row[0]),row[1]),now,now)
    except (LeaseDenied,StaleGeneration):deny('lease_unavailable')
    if connection.execute('SELECT 1 FROM job_cancellations WHERE project_id=? AND job_id=?',(str(project_id),row[0])).fetchone():deny('cancelled')
    try:
        limits=json.loads(row[4]);intent=load_intent_for_attempt(connection,project_id,item_id)
        pin=validate_authoring_pin({'purpose':row[2],'limits':limits,'policy_ref':row[7],
            'intent':None if intent is None else intent_to_document(intent)})
        if pin is None:deny('recording_policy_missing')
        binding=pin['authoring_binding']
        selected=connection.execute("""SELECT binding_id,revision_id,revision,content_hash,key_ref_id,key_revision,
            model,endpoint,compatibility_status,provider,endpoint_kind FROM binding_revisions
            WHERE project_id=? AND binding_id=? AND revision_id=? AND role='authoring'""",
            (str(project_id),binding['binding_id'],binding['revision_id'])).fetchone()
        expected=(binding['binding_id'],binding['revision_id'],binding['revision'],binding['content_hash'],binding['key_ref_id'],binding['key_revision'])
        if selected is None or tuple(selected[:6])!=expected or selected[8] not in ('unchecked','compatible'):deny('binding_unavailable')
        if request.binding_revision!=binding['revision']:deny('binding_revision')
        key=connection.execute("SELECT 1 FROM secret_refs WHERE project_id=? AND ref_id=? AND revision=? AND availability='available'",
            (str(project_id),binding['key_ref_id'],binding['key_revision'])).fetchone()
        if key is None:deny('secret')
        ref=SecretRef(project_id,UUID(binding['key_ref_id']),binding['key_revision'])
        begin=datetime.fromisoformat(row[6])
        from datetime import timedelta
        maximum=begin+timedelta(seconds=pin['timeout_seconds'])
        deadline=datetime.fromisoformat(request.deadline)
        if begin.tzinfo is None or deadline.tzinfo is None or now>=min(maximum,deadline):deny('deadline')
        policy=AttemptModelPolicy(project_id,item_id,'recording',False,pin['max_model_calls'],pin['budget'],
            (RoleBinding('authoring',binding['revision'],selected[6],binding['key_ref_id']),),(),(),{'authoring':ref},request.generation)
        return RecordingGrant(policy,UUID(row[8]),row[7],selected[7],selected[9],selected[10],min(maximum,deadline))
    except (ValueError,TypeError,KeyError,AttributeError):deny('recording_policy_invalid')
