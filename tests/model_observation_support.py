"""Prepare real scoped image references for model transport tests, not fake model policies."""
import base64
import hashlib
from dataclasses import asdict
from datetime import datetime,timezone
from aiqa.worker.http_client import WorkerHttpClient,WorkerClientSettings,SyncASGITransport,WorkerHttpError,RetryClass


def prepare_frame(f,payload):
    from test_rx_65 import _observation
    call_id=payload['call_id']
    frames=f.setdefault('_model_frames',{})
    if call_id in frames:return frames[call_id]
    observation=_observation()
    digest='sha256:'+hashlib.sha256(observation.png).hexdigest()
    with WorkerHttpClient(WorkerClientSettings('https://127.0.0.1',f['token']),transport=SyncASGITransport(f['app'])) as client:
        ack=client.commit_evidence(sanitized=True,project_id=f['project'],job_id=f['job']['job_id'],generation=f['job']['generation'],
            now=datetime.now(timezone.utc).isoformat(),events=[],artifacts=[{'filename':'model-test.png','media_type':'image/png',
                'declared_hash':digest,'declared_length':len(observation.png),'body_b64':base64.b64encode(observation.png).decode('ascii'),
                'owner_kind':'REC','attempt_id':f['job']['attempt_id'],'role':'source'}],idempotency_key='test-frame-'+call_id)
        if not ack.get('artifact_ids') or ack.get('late'):
            raise WorkerHttpError('test observation upload rejected',retry_class=RetryClass.fatal,status_code=403,provider_dispatched=False)
        registered=client.register_model_observation(project_id=f['project'],item_id=f['job']['attempt_id'],
            payload={**payload,'intent_hash':f['job']['snapshot']['intent_hash'],'deadline':f['payload']['deadline'],
                'artifact_id':ack['artifact_ids'][0],'image_hash':digest,'geometry':asdict(observation.geometry),
                'captured_at':observation.captured_at,'source_observation_id':observation.observation_id},
            idempotency_key='test-observation-'+call_id)
    frames[call_id]=registered['observation_id']
    return frames[call_id]
