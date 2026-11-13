"""Upload only a validated non-sensitive current frame, then bind a model-call reference."""
from __future__ import annotations
import base64
import hashlib
from dataclasses import asdict, replace
from datetime import datetime
from uuid import UUID

from aiqa.contracts.actions import Observation
from aiqa.contracts.model_observations import parse_geometry
from aiqa.domain.hashing import canonical_hash
from aiqa.security.redaction import filter_capture
from aiqa.worker.http_client import SanitizationRequired, WorkerHttpError


def upload_authoring_observation(client, claim, observation, model_request):
    snapshot = claim.get('snapshot')
    intent = snapshot.get('intent') if type(snapshot) is dict else None
    if (type(intent) is not dict or type(intent.get('secret_refs')) is not dict
        or intent['secret_refs'] or not isinstance(observation, Observation)):
        raise SanitizationRequired('pixel coverage is unavailable')
    try:
        geometry = parse_geometry(asdict(observation.geometry))
        filtered = filter_capture(replace(observation, geometry=geometry), ())
        captured = datetime.fromisoformat(observation.captured_at)
        if captured.tzinfo is None:
            raise ValueError('capture timestamp')
        if not 1 <= len(observation.observation_id) <= 128:
            raise ValueError('observation id')
    except (ValueError, TypeError, AttributeError) as exc:
        raise SanitizationRequired('observation is invalid') from exc
    clean = replace(observation, png=filtered.png, dom=filtered.dom, stdout=filtered.stdout,
        messages=filtered.messages, reasoning='')
    from aiqa.worker.android_jobs import observation_authoring_inputs
    inputs = list(observation_authoring_inputs(clean, previous_result=str(claim.get('previous_result') or '')))
    digest = 'sha256:'+hashlib.sha256(clean.png).hexdigest()
    geometry_doc = asdict(geometry)
    geometry_hash = canonical_hash(geometry_doc, 'canon-json-v1')
    identity = canonical_hash({'attempt_id':claim['attempt_id'],'call_id':model_request['call_id'],
        'image_hash':digest,'geometry_hash':geometry_hash,'source_observation_id':clean.observation_id}, 'canon-json-v1')
    try:
        ack = client.commit_evidence(sanitized=True,project_id=claim['project_id'],job_id=claim['job_id'],
            generation=claim['generation'],now=clean.captured_at,events=[],
            artifacts=[{'filename':'model-frame.png','media_type':'image/png','declared_hash':digest,
                'declared_length':len(clean.png),'body_b64':base64.b64encode(clean.png).decode('ascii'),
                'owner_kind':'REC','attempt_id':claim['attempt_id'],'role':'source'}],
            idempotency_key='observation-image:'+identity)
        ids = ack.get('artifact_ids')
        if (ack.get('late') is not False or ack.get('attempt_id')!=claim['attempt_id']
            or type(ids) is not list or len(ids)!=1):
            raise SanitizationRequired('observation image was not committed')
        payload = {**model_request,'sanitized_inputs':inputs,'artifact_id':ids[0],'image_hash':digest,
            'geometry':geometry_doc,'source_observation_id':clean.observation_id,'captured_at':clean.captured_at}
        receipt = client.register_model_observation(project_id=claim['project_id'],item_id=claim['attempt_id'],
            payload=payload,idempotency_key='observation-bind:'+identity)
        if (receipt.get('artifact_id')!=ids[0] or receipt.get('image_hash')!=digest
            or receipt.get('geometry_hash')!=geometry_hash):
            raise SanitizationRequired('observation receipt does not match')
        UUID(receipt['observation_id'])
    except WorkerHttpError as exc:
        raise WorkerHttpError('observation preparation failed',retry_class=exc.retry_class,
            status_code=exc.status_code,provider_dispatched=False,reason='observation_unavailable') from exc
    except (ValueError,TypeError,KeyError) as exc:
        raise SanitizationRequired('observation receipt is invalid') from exc
    return {**receipt,'sanitized_inputs':inputs}
