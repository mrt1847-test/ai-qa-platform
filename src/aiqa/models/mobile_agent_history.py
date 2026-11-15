"""Build original conversation from authorized DB receipts and durable native ACK evidence.

A model proposal is not an executed action. Every prior turn needs a same-action
before/after/log commit from this worker; no worker conversation or path is accepted.
"""
from __future__ import annotations
from dataclasses import asdict,dataclass
from datetime import datetime
import hashlib,json

from aiqa.adapters.mobile_agent_upstream import load_protocol,render_reply,upstream_action
from aiqa.contracts.mobile_agent_engine import require_mobile_agent_engine
from aiqa.contracts.model_observations import ProviderObservation,parse_geometry
from aiqa.domain.hashing import canonical_hash
from aiqa.models.broker import ModelRequestDenied
from aiqa.models.mobile_agent_context import MobileAgentHistoryTurn,MobileAgentContext,build_mobile_agent_context,_unique,_not_constant
from aiqa.models.model_observations import load_authoring_observation,require_non_sensitive,image_metadata,read_validated_image
from aiqa.models.recording_authorization import authorize_recording
from aiqa.store.artifacts import resolve_stored


@dataclass(frozen=True,slots=True)
class MobileAgentHistoryState:
    context:MobileAgentContext
    fingerprint:str
    step_count:int


def _json(raw):
    if type(raw) not in (str,bytes) or len(raw)>65536:raise ValueError('history JSON size')
    try:return json.loads(raw,object_pairs_hook=_unique,parse_constant=_not_constant)
    except RecursionError:raise ValueError('history JSON nesting') from None


def _time(raw):
    value=datetime.fromisoformat(raw)
    if value.tzinfo is None:raise ValueError('history time')
    return value


def _observation(connection,project,item,reference,call,worker,policy):
    row=connection.execute("""SELECT artifact_id,image_hash,geometry_hash,geometry_json,captured_at,created_at,
        worker_id,policy_ref,call_id,source_observation_id FROM model_observations
        WHERE project_id=? AND attempt_id=? AND observation_id=?""",(str(project),item,reference)).fetchone()
    if row is None or row[6:9]!=(worker,policy,call):raise ModelRequestDenied('mobile_history_observation')
    geometry=parse_geometry(_json(row[3]))
    if canonical_hash(asdict(geometry),'canon-json-v1')!=row[2]:raise ModelRequestDenied('mobile_history_observation')
    metadata=image_metadata(connection,project,item,row[0])
    binding=connection.execute('SELECT action_id,role FROM artifact_objects WHERE project_id=? AND artifact_id=?',
        (str(project),row[0])).fetchone()
    if binding!=('ma-'+call,'before') or metadata[1]!=row[1] or metadata[2]>2000000:
        raise ModelRequestDenied('mobile_history_observation')
    return tuple(row),metadata


def _snapshot(store,worker,request,project,item):
    from datetime import timezone
    with store.transaction() as connection:
        grant=authorize_recording(connection,worker,request,project,item,datetime.now(timezone.utc))
        intent=require_non_sensitive(connection,project,item)
        job=connection.execute("""SELECT j.job_id,a.generation,j.recording_id,j.limits FROM attempts a JOIN jobs j
            ON j.project_id=a.project_id AND j.job_id=a.job_id WHERE a.project_id=? AND a.attempt_id=?""",
            (str(project),item)).fetchone()
        require_mobile_agent_engine(_json(job[3]).get('authoring_engine'))
        if grant.provider!='openai' or not any(binding.role=='authoring' and binding.model=='gpt-6-luna' for binding in grant.policy.bindings):
            raise ModelRequestDenied('mobile_engine_unsupported')
        current=_observation(connection,project,item,request.model_observation_id,str(request.call_id),worker.worker_id,grant.policy_ref)
        rows=connection.execute("""SELECT request_key,call_id,worker_id,policy_ref,state,charged,status_code,response_json,completed_at,fingerprint
            FROM model_request_receipts WHERE project_id=? AND attempt_id=? AND charged=1 ORDER BY rowid LIMIT 81""",
            (str(project),item)).fetchall()
        receipts=[];sources={current[0][9]}
        for row in rows:
            if row[2]!=worker.worker_id or row[3]!=grant.policy_ref:raise ModelRequestDenied('mobile_history_scope')
            if row[1]==str(request.call_id) and row[4]=='pending':
                from aiqa.store.model_requests import request_fingerprint
                expected=canonical_hash({'request':request_fingerprint(request,project,item),'intent_hash':intent.intent_hash},'canon-json-v1')
                if row[9]!=expected:raise ModelRequestDenied('mobile_history_scope')
                continue
            if row[1]==str(request.call_id) or row[4]!='completed' or row[6]!=200:
                raise ModelRequestDenied('mobile_history_incomplete')
            body=_json(row[7])
            if (body.get('allowed') is not True or body.get('action_allowed') is not True or body.get('provider_dispatched') is not True
                or body.get('call_id')!=row[1] or body.get('actual_model')!='gpt-6-luna' or body.get('generation')!=job[1]
                or body.get('purpose')!='recording' or body.get('role')!='authoring' or body.get('item_id')!=item):
                raise ModelRequestDenied('mobile_history_incomplete')
            before=_observation(connection,project,item,body.get('model_observation_id'),row[1],worker.worker_id,grant.policy_ref)
            if before[0][9] in sources:raise ModelRequestDenied('mobile_history_observation')
            sources.add(before[0][9])
            if body.get('image_hash')!=before[0][1]:raise ModelRequestDenied('mobile_history_observation')
            objects=connection.execute("""SELECT artifact_id,object_key,content_hash,byte_length,media_type,
                owner_kind,owner_id,attempt_id,job_id,generation,status,acked,role,action_id
                FROM artifact_objects WHERE project_id=? AND attempt_id=? AND action_id=? AND role IN ('after','log') ORDER BY role LIMIT 3""",
                (str(project),item,'ma-'+row[1])).fetchall()
            if len(objects)!=2 or {obj[12] for obj in objects}!={'after','log'}:
                raise ModelRequestDenied('mobile_history_ack_required')
            artifacts={obj[12]:tuple(obj) for obj in objects}
            for role,obj in artifacts.items():
                if (obj[5:12]!=('REC',job[2],item,job[0],job[1],'ready',1)
                    or obj[4]!=('image/png' if role=='after' else 'text/plain')
                    or not 0<obj[3]<=(2000000 if role=='after' else 16384)):
                    raise ModelRequestDenied('mobile_history_ack_invalid')
            after=image_metadata(connection,project,item,artifacts['after'][0])
            receipts.append((tuple(row),body,before,artifacts,after))
        if len(receipts)>79:raise ModelRequestDenied('mobile_history_limit')
        commits=connection.execute("""SELECT response_body,created_at FROM evidence_commit_requests
            WHERE project_id=? AND job_id=? AND generation=? AND worker_id=? AND response_body IS NOT NULL ORDER BY rowid LIMIT 401""",
            (str(project),job[0],job[1],worker.worker_id)).fetchall()
        if len(commits)>400:raise ModelRequestDenied('mobile_history_limit')
        acks=[]
        for raw,created in commits:
            body=_json(raw)
            if body.get('late') is False and body.get('attempt_id')==item and type(body.get('server_committed_at')) is str:
                ids=body.get('artifact_ids')
                if type(ids) is list and all(type(identity) is str for identity in ids):
                    acks.append((ids,body['server_committed_at'],created))
        previous_ack=None
        for row,body,before,artifacts,after in receipts:
            required={artifacts['after'][0],artifacts['log'][0]}
            observed=[(_time(committed),_time(started)) for ids,committed,started in acks if required<=set(ids)]
            if not observed:raise ModelRequestDenied('mobile_history_ack_required')
            ack,started=min(observed);captured=_time(before[0][5]);completed=_time(row[8])
            if (_time(current[0][5])<ack or captured>completed or ack<completed or started<completed
                or previous_ack is not None and captured<previous_ack):raise ModelRequestDenied('mobile_history_order')
            previous_ack=ack
        signature=canonical_hash({'policy':grant.policy_ref,'intent':intent.intent_hash,'current':current,
            'receipts':receipts,'acks':acks},'canon-json-v1')
        return intent,current,receipts,signature


def _log(root,metadata):
    path=resolve_stored(root,metadata[1])
    if path is None or path.stat().st_size!=metadata[3]:raise ModelRequestDenied('mobile_history_ack_invalid')
    with path.open('rb') as stream:raw=stream.read(16385)
    if len(raw)!=metadata[3] or 'sha256:'+hashlib.sha256(raw).hexdigest()!=metadata[2]:
        raise ModelRequestDenied('mobile_history_ack_invalid')
    return _json(raw)


def load_mobile_agent_history(store,worker,request,project_id,item_id):
    try:
        current=load_authoring_observation(store,worker,request,project_id,item_id)
        intent,identity,rows,signature=_snapshot(store,worker,request,project_id,item_id)
        if (current.image_hash!=identity[0][1] or canonical_hash(current.geometry,'canon-json-v1')!=identity[0][2]
            or current.captured_at!=identity[0][4]):raise ModelRequestDenied('observation_unavailable')
        history=[];proof=[]
        for index,(row,body,before,artifacts,after) in enumerate(rows):
            observation,metadata=before;geometry=parse_geometry(_json(observation[3]))
            png=read_validated_image(store.config.artifacts_dir,metadata,observation[1],geometry,observation[4])
            frame=ProviderObservation(png,observation[1],asdict(geometry),observation[4])
            read_validated_image(store.config.artifacts_dir,after,after[1],geometry,observation[4])
            log=_log(store.config.artifacts_dir,artifacts['log'])
            history.append(MobileAgentHistoryTurn(body['content'],frame if index>=len(rows)-4 else None))
            proof.append((row[1],geometry,metadata[1],after[1],log))
        context=build_mobile_agent_context(intent=intent,current=current,history=tuple(history))
        protocol=load_protocol()
        for turn,(call,geometry,before_hash,after_hash,log) in zip(history,proof):
            action=upstream_action(protocol,protocol.parse_action(render_reply(turn.output)),geometry)
            expected={'schema':'mobile-agent-step-v1','call_id':call,'action_id':'ma-'+call,'state':'observed',
                'native_calls':0 if action is None else 1,'native':None if action is None else asdict(action),
                'before_image_hash':before_hash,'after_image_hash':after_hash}
            if json.dumps(log,sort_keys=True)!=json.dumps(expected,sort_keys=True):
                raise ModelRequestDenied('mobile_history_ack_invalid')
        load_authoring_observation(store,worker,request,project_id,item_id)
        if _snapshot(store,worker,request,project_id,item_id)[3]!=signature:
            raise ModelRequestDenied('mobile_history_changed')
        from aiqa.models import model_observations
        try:model_observations.require_fresh_capture(current.captured_at,model_observations._now())
        except ValueError:raise ModelRequestDenied('observation_unavailable') from None
        return MobileAgentHistoryState(context,signature,len(history))
    except ModelRequestDenied:raise
    except (ValueError,TypeError,KeyError,OSError,AttributeError,RecursionError) as exc:
        raise ModelRequestDenied('mobile_history_invalid') from exc
