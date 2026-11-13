"""Bind ready image evidence to an authorized recording call before model use."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from aiqa.contracts.actions import CaptureGeometry, Observation
from aiqa.domain.hashing import canonical_hash
from aiqa.models.broker import ModelRequestDenied, ModelRequestConflict
from aiqa.models.recording_authorization import authorize_recording
from aiqa.recording.intent import load_intent_for_attempt
from aiqa.security.redaction import filter_capture
from aiqa.store.artifacts import resolve_stored
from aiqa.store.model_requests import model_error, request_fingerprint

def _now():
    return datetime.now(timezone.utc)


MAX_IMAGE_BYTES = 5_000_000
MAX_FRAME_AGE = timedelta(seconds=30)
CLOCK_SKEW = timedelta(seconds=5)


from aiqa.contracts.model_observations import ObservationRejected, ProviderObservation, parse_geometry


def require_fresh_capture(captured_at, now):
    if type(captured_at) is not str:
        raise ObservationRejected('observation_time')
    try:
        captured = datetime.fromisoformat(captured_at)
    except ValueError as exc:
        raise ObservationRejected('observation_time') from exc
    if captured.tzinfo is None or not -CLOCK_SKEW <= now-captured <= MAX_FRAME_AGE:
        raise ObservationRejected('observation_time')
    return captured


def require_non_sensitive(connection, project_id, item_id):
    intent = load_intent_for_attempt(connection,project_id,item_id)
    if intent is None:
        raise ModelRequestDenied('intent_invalid')
    if intent.secret_refs:
        raise ModelRequestDenied('pixel_coverage_unavailable')
    return intent


def image_metadata(connection, project_id, item_id, artifact_id):
    row = connection.execute("""SELECT o.object_key,o.content_hash,o.byte_length,o.media_type,
        o.status,o.acked,o.owner_kind,o.owner_id,o.attempt_id,o.job_id,o.generation,
        j.recording_id,a.job_id,a.generation
        FROM artifact_objects o JOIN attempts a ON a.project_id=o.project_id AND a.attempt_id=?
        JOIN jobs j ON j.project_id=a.project_id AND j.job_id=a.job_id
        WHERE o.project_id=? AND o.artifact_id=?""",(item_id,str(project_id),artifact_id)).fetchone()
    if (row is None or row[3]!='image/png' or row[4]!='ready' or row[5]!=1 or row[6]!='REC'
        or row[7]!=row[11] or row[8]!=item_id or row[9]!=row[12] or row[10]!=row[13]
        or not 0 < row[2] <= MAX_IMAGE_BYTES):
        raise ModelRequestDenied('observation_unavailable')
    return tuple(row)


def read_validated_image(root, metadata, image_hash, geometry, captured_at):
    path = resolve_stored(root,metadata[0])
    if path is None or metadata[1]!=image_hash:
        raise ObservationRejected('observation_image')
    try:
        if path.stat().st_size != metadata[2]:
            raise ObservationRejected('observation_image')
        with path.open('rb') as stream:
            png = stream.read(MAX_IMAGE_BYTES+1)
    except OSError as exc:
        raise ObservationRejected('observation_image') from exc
    if len(png)!=metadata[2] or 'sha256:'+hashlib.sha256(png).hexdigest()!=image_hash:
        raise ObservationRejected('observation_image')
    try:
        filtered = filter_capture(Observation('server-frame',captured_at,geometry,png,'','',(),'',True,'android'),())
    except ValueError as exc:
        raise ObservationRejected('observation_image') from exc
    return filtered.png


def _view(row, replayed):
    return {'observation_id':row[0],'artifact_id':row[1],'image_hash':row[2],'geometry_hash':row[3],'replayed':replayed}


def register_observation(store,worker,request,project_id,item_id,key,payload):
    if getattr(request, "model_observation_id", None) is not None:
        raise ObservationRejected("observation_reference_on_registration")
    artifact_id = str(UUID(str(payload.get('artifact_id'))))
    image_hash = payload.get('image_hash')
    source_id = payload.get('source_observation_id')
    if type(image_hash) is not str or type(source_id) is not str or not 1 <= len(source_id) <= 128:
        raise ObservationRejected('observation_image')
    geometry = parse_geometry(payload.get('geometry'))
    geometry_doc = asdict(geometry)
    geometry_hash = canonical_hash(geometry_doc,'canon-json-v1')
    model_hash = request_fingerprint(request,project_id,item_id)
    captured_at = payload.get('captured_at')
    fingerprint = canonical_hash({'artifact_id':artifact_id,'image_hash':image_hash,'geometry':geometry_doc,
        'source_id':source_id,'captured_at':captured_at,'model_fingerprint':model_hash,'intent_hash':payload.get('intent_hash')},'canon-json-v1')
    with store.transaction() as connection:
        if project_id not in worker.permitted_projects or 'recording' not in worker.permitted_purposes:
            raise ModelRequestDenied('recording_authorization')
        existing = connection.execute("""SELECT observation_id,artifact_id,image_hash,geometry_hash,request_hash,worker_id
            FROM model_observations WHERE project_id=? AND attempt_id=? AND request_key=?""",(str(project_id),item_id,key)).fetchone()
        if existing is not None:
            if existing[5]!=worker.worker_id:
                raise ModelRequestDenied('recording_authorization')
            if existing[4]!=fingerprint:
                raise ModelRequestConflict('observation_key_conflict')
            return 200,_view(existing,True)
        grant = authorize_recording(connection,worker,request,project_id,item_id,datetime.now(timezone.utc))
        intent = require_non_sensitive(connection,project_id,item_id)
        if payload.get('intent_hash')!=intent.intent_hash:
            raise ModelRequestDenied('intent_invalid')
        metadata = image_metadata(connection,project_id,item_id,artifact_id)
    require_fresh_capture(captured_at,datetime.now(timezone.utc))
    read_validated_image(store.config.artifacts_dir,metadata,image_hash,geometry,captured_at)
    with store.transaction() as connection:
        current = authorize_recording(connection,worker,request,project_id,item_id,datetime.now(timezone.utc))
        require_non_sensitive(connection,project_id,item_id)
        if current.policy_ref!=grant.policy_ref or image_metadata(connection,project_id,item_id,artifact_id)!=metadata:
            raise ModelRequestDenied('observation_unavailable')
        existing = connection.execute("""SELECT observation_id,artifact_id,image_hash,geometry_hash,request_hash,worker_id
            FROM model_observations WHERE project_id=? AND attempt_id=? AND request_key=?""",
            (str(project_id),item_id,key)).fetchone()
        if existing is not None:
            if existing[5]!=worker.worker_id:
                raise ModelRequestDenied('recording_authorization')
            if existing[4]!=fingerprint:
                raise ModelRequestConflict('observation_key_conflict')
            return 200,_view(existing,True)
        observation_id = str(uuid4())
        try:
            connection.execute("""INSERT INTO model_observations
                (project_id,observation_id,attempt_id,call_id,request_key,worker_id,request_hash,model_fingerprint,
                 policy_ref,artifact_id,image_hash,geometry_hash,geometry_json,source_observation_id,captured_at,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (str(project_id),observation_id,item_id,str(request.call_id),key,worker.worker_id,fingerprint,model_hash,
                 grant.policy_ref,artifact_id,image_hash,geometry_hash,json.dumps(geometry_doc,sort_keys=True),source_id,captured_at,datetime.now(timezone.utc).isoformat()))
        except sqlite3.IntegrityError as exc:
            raise ModelRequestConflict('observation_key_conflict') from exc
    return 201,{'observation_id':observation_id,'artifact_id':artifact_id,'image_hash':image_hash,'geometry_hash':geometry_hash,'replayed':False}


def register_observation_http(open_store,worker,request,project_id,item_id,key,payload):
    store = open_store()
    try:
        return register_observation(store,worker,request,project_id,item_id,key,payload)
    except ModelRequestConflict:
        return 409,model_error('observation_key_conflict')
    except ModelRequestDenied as exc:
        return exc.status,model_error(exc.reason)
    except (ValueError,TypeError,KeyError):
        return 422,model_error('observation_invalid')
    finally:
        store.close()


def load_authoring_observation(store, worker, request, project_id, item_id):
    """Read bytes outside write transactions; the immutable reference must match this call."""
    reference = getattr(request, 'model_observation_id', None)
    if reference is None:
        raise ModelRequestDenied('observation_required')
    try:
        expected = request_fingerprint(replace(request, model_observation_id=None), project_id, item_id)
        with store.transaction() as connection:
            grant = authorize_recording(connection, worker, request, project_id, item_id, datetime.now(timezone.utc))
            require_non_sensitive(connection, project_id, item_id)
            row = connection.execute("""SELECT artifact_id,image_hash,geometry_hash,geometry_json,captured_at,
                model_fingerprint,worker_id,policy_ref,call_id FROM model_observations
                WHERE project_id=? AND observation_id=? AND attempt_id=?""",
                (str(project_id),reference,item_id)).fetchone()
            if (row is None or row[5]!=expected or row[6]!=worker.worker_id
                or row[7]!=grant.policy_ref or row[8]!=str(request.call_id)):
                raise ModelRequestDenied('observation_unavailable')
            metadata = image_metadata(connection, project_id, item_id, row[0])
            geometry = parse_geometry(json.loads(row[3]))
            if canonical_hash(asdict(geometry),'canon-json-v1') != row[2]:
                raise ModelRequestDenied('observation_unavailable')
        require_fresh_capture(row[4], _now())
        png = read_validated_image(store.config.artifacts_dir, metadata, row[1], geometry, row[4])
        with store.transaction() as connection:
            current = authorize_recording(connection, worker, request, project_id, item_id, datetime.now(timezone.utc))
            require_non_sensitive(connection, project_id, item_id)
            if current.policy_ref!=grant.policy_ref or image_metadata(connection,project_id,item_id,row[0])!=metadata:
                raise ModelRequestDenied('observation_unavailable')
        require_fresh_capture(row[4], _now())
        return ProviderObservation(png, row[1], asdict(geometry), row[4])
    except ModelRequestDenied:
        raise
    except (ValueError, TypeError, KeyError, OSError) as exc:
        raise ModelRequestDenied('observation_unavailable') from exc
