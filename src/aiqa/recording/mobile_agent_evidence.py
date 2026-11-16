"""Strict diagnostic/observed packets for the reserved original Mobile-Agent actions."""
from dataclasses import asdict
import hashlib, json, struct
from datetime import datetime
from uuid import UUID

from aiqa.adapters.mobile_agent_upstream import load_protocol, render_reply, upstream_action
from aiqa.contracts.mobile_agent_engine import require_mobile_agent_engine
from aiqa.contracts.model_observations import parse_geometry


def _unique(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('duplicate mobile evidence field')
        result[key]=value
    return result


def _json(raw):
    try:return json.loads(raw,object_pairs_hook=_unique,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('nonfinite JSON')))
    except (UnicodeError,RecursionError):raise ValueError('invalid mobile evidence JSON') from None


def parse_mobile_packets(artifacts, events=(), *, validate_images=True):
    """Bounded byte parsing before durable staging or a SQL writer."""
    groups={}
    for part in artifacts:
        if not part.action_id or not part.action_id.startswith('ma-'):continue
        try:
            if 'ma-'+str(UUID(part.action_id[3:]))!=part.action_id:raise ValueError()
        except (ValueError,TypeError,AttributeError):raise ValueError('mobile action identity invalid') from None
        if part.attempt_id is None or part.owner_kind!='REC':raise ValueError('mobile evidence owner invalid')
        groups.setdefault(part.action_id,[]).append(part)
    parsed={}
    for action,parts in groups.items():
        roles={part.role:part for part in parts}
        if len(roles)!=len(parts):raise ValueError('duplicate mobile evidence role')
        if set(roles)=={'before'}:
            if roles['before'].media_type!='image/png' or events:raise ValueError('mobile before packet invalid')
            parsed[action]=None
            continue
        if set(roles) not in ({'log'},{'after','log'}):raise ValueError('mobile evidence roles invalid')
        log=roles['log']
        if log.media_type!='text/plain' or not 0<len(log.body)<=16384:raise ValueError('mobile log invalid')
        doc=_json(log.body)
        common={'schema','call_id','action_id','state','native_calls','native','before_image_hash'}
        if type(doc) is not dict or doc.get('call_id')!=action[3:] or doc.get('action_id')!=action:
            raise ValueError('mobile log identity invalid')
        if doc.get('schema')=='mobile-agent-step-v1':
            if (set(doc)!=common|{'after_image_hash'} or set(roles)!={'after','log'} or doc['state']!='observed'
                or roles['after'].media_type!='image/png' or doc['after_image_hash']!=roles['after'].declared_hash):
                raise ValueError('mobile observed proof invalid')
        elif doc.get('schema')=='mobile-agent-failure-v1':
            if set(doc)!=common|{'reason'} or set(roles)!={'log'} or events:raise ValueError('mobile failure packet invalid')
            reasons={'unknown':{'dispatch_unknown'},'acknowledged':{'after_capture_failed','execution_stopped','native_persistence_failed'},
                     'not_sent':{'native_not_sent','control_unobserved'}}
            if type(doc['state']) is not str or doc['state'] not in reasons or type(doc['reason']) is not str or doc['reason'] not in reasons[doc['state']]:
                raise ValueError('mobile failure disposition invalid')
            if doc['state'] in {'unknown','acknowledged'} and doc['native'] is None:raise ValueError('mobile physical proof missing')
        else:raise ValueError('mobile proof schema invalid')
        expected_calls=int(doc['native'] is not None) if doc['state']=='observed' else int(doc['state']=='acknowledged')
        if type(doc['native_calls']) is not int or doc['native_calls']!=expected_calls:raise ValueError('mobile call count invalid')
        if doc['state']=='observed' and len(events)!=2*expected_calls:raise ValueError('mobile event count invalid')
        if 'after' in roles:
            png=roles['after'].body
            if len(png)<24:raise ValueError('mobile after PNG invalid')
            if validate_images:
                from aiqa.security.redaction import _validate_png
                _validate_png(png,*struct.unpack('>II',png[16:24]))
        if events:
            for index,(event,phase,digest) in enumerate(zip(events,('before','after'),(doc['before_image_hash'],doc.get('after_image_hash')))):
                detail=event.detail_payload
                if type(detail) is not str:raise ValueError('mobile event detail missing')
                body=_json(detail)
                expected={'phase','action_id','sanitized','review_pending','png_sha256','action_seq'}
                if (type(body) is not dict or set(body)!=expected or body['phase']!=phase or body['action_id']!=action
                    or body['sanitized'] is not True or body['review_pending'] is not True or body['png_sha256']!=digest
                    or type(body['action_seq']) is not int or body['action_seq']<1
                    or event.event_type!='action.observed' or str(event.attempt_id)!=str(log.attempt_id)
                    or type(event.local_seq) is not int or event.local_seq<1 or event.minimum_facts!='{}'
                    or event.body_hash!='sha256:'+hashlib.sha256(detail.encode()).hexdigest()
                    or event.payload_hash!='sha256:'+hashlib.sha256((str(event.local_seq)+'\n'+detail).encode()).hexdigest()):
                    raise ValueError('mobile event proof mismatch')
                captured=datetime.fromisoformat(event.captured_at)
                if captured.tzinfo is None:raise ValueError('mobile event time invalid')
                if index:
                    first=events[0]
                    if (event.local_seq!=first.local_seq+1 or event.event_id==first.event_id
                        or body['action_seq']!=_json(first.detail_payload)['action_seq']
                        or captured<datetime.fromisoformat(first.captured_at)):
                        raise ValueError('mobile event pair invalid')
        parsed[action]=doc
    if groups and (len(groups)!=1 or sum(map(len,groups.values()))!=len(artifacts)):
        raise ValueError('mobile action packet must be separate')
    return parsed


def mobile_dispositions(connection, *, project, job, attempt, worker, generation, artifacts, events=()):
    """Bind facts to this original call and server ACK before; never authorize a new action."""
    packets=parse_mobile_packets(artifacts,events,validate_images=False)
    if not packets:return {}
    limits=connection.execute('SELECT limits FROM jobs WHERE project_id=? AND job_id=?',(project,job)).fetchone()
    if limits is None:raise ValueError('mobile job missing')
    require_mobile_agent_engine(_json(limits[0]).get('authoring_engine'))
    result={}
    for action,doc in packets.items():
        if doc is None:
            result[action]='planned'
            continue
        row=connection.execute("""SELECT r.response_json,o.image_hash,o.geometry_json,o.artifact_id,o.captured_at
            FROM model_request_receipts r JOIN model_observations o
              ON o.project_id=r.project_id AND o.attempt_id=r.attempt_id AND o.call_id=r.call_id
             AND o.worker_id=r.worker_id AND o.policy_ref=r.policy_ref
            WHERE r.project_id=? AND r.attempt_id=? AND r.call_id=? AND r.worker_id=?
              AND r.state='completed' AND r.charged=1 AND r.status_code=200""",
            (project,attempt,action[3:],worker)).fetchone()
        if row is None:raise ValueError('mobile completed model receipt missing')
        response=_json(row[0])
        if (response.get('allowed') is not True or response.get('action_allowed') is not True
            or response.get('provider_dispatched') is not True or response.get('call_id')!=action[3:]
            or response.get('item_id')!=attempt or type(response.get('generation')) is not int or response['generation']!=generation
            or response.get('actual_model')!='gpt-6-luna' or response.get('purpose')!='recording' or response.get('role')!='authoring'
            or response.get('image_hash')!=row[1] or doc['before_image_hash']!=row[1]):
            raise ValueError('mobile model receipt mismatch')
        before=connection.execute("""SELECT content_hash FROM artifact_objects WHERE project_id=? AND artifact_id=?
            AND attempt_id=? AND job_id=? AND generation=? AND action_id=? AND owner_kind='REC'
            AND role='before' AND status='ready' AND acked=1""",(project,row[3],attempt,job,generation,action)).fetchone()
        if before is None or before[0]!=row[1]:raise ValueError('mobile before ACK missing')
        geometry=parse_geometry(_json(row[2]))
        for part in artifacts:
            if part.role=='after' and struct.unpack('>II',part.body[16:24])!=(geometry.physical_width,geometry.physical_height):
                raise ValueError('mobile after geometry mismatch')
        if events:
            if events[0].captured_at!=row[4]:raise ValueError('mobile before capture time mismatch')
            from aiqa.store.evidence import _cursor
            if _cursor(connection,UUID(project),attempt)[0]<events[-1].local_seq:
                raise ValueError('mobile event prefix incomplete')
        protocol=load_protocol()
        native=upstream_action(protocol,protocol.parse_action(render_reply(response['content'])),geometry)
        expected=None if native is None or native.kind=='finish' else asdict(native)
        if json.dumps(doc['native'],sort_keys=True,separators=(',',':'))!=json.dumps(expected,sort_keys=True,separators=(',',':')):raise ValueError('mobile native proof mismatch')
        result[action]={'not_sent':'lookup_failed'}.get(doc['state'],doc['state'])
    return result
