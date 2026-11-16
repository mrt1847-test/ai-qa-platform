"""Parent-only original-agent model callback. Credentials remain in the HTTPS client."""
from __future__ import annotations
from copy import deepcopy
from dataclasses import asdict,dataclass,field,replace
from datetime import datetime,timedelta,timezone
import hashlib,json
from threading import Lock
from uuid import UUID,uuid4

from aiqa.adapters.mobile_agent_upstream import load_protocol,render_reply,upstream_action
from aiqa.contracts.actions import Observation
from aiqa.contracts.model_observations import parse_geometry
from aiqa.contracts.authoring import validate_authoring_pin
from aiqa.contracts.mobile_agent_engine import require_mobile_agent_engine
from aiqa.worker.mobile_agent_process import MobileAgentModelFrame
from aiqa.worker.model_observations import upload_authoring_observation
from aiqa.replay.android_plan import TypedAndroidAction


class ModelPortRejected(ValueError):pass


@dataclass(frozen=True,slots=True)
class MobileAgentWorkerTurn:
    call_id:str
    action_id:str
    content:str=field(repr=False)
    observation_id:str
    image_hash:str
    frame:MobileAgentModelFrame=field(repr=False)
    terminal:bool
    action:TypedAndroidAction|None
    _receipt_json:str=field(repr=False)
    before_artifact_id:str=''

    def receipt(self):return json.loads(self._receipt_json)


@dataclass(frozen=True,slots=True)
class MobileAgentRegisteredObservation:
    """A bound image is not an accepted action or a physical ACK."""
    call_id:str
    action_id:str
    before_artifact_id:str
    image_hash:str
    observation_id:str


class MobileAgentModelPort:
    def __init__(self,client,claim,*,token_output_limit=512):
        if type(claim) is not dict:raise ModelPortRejected('claim invalid')
        claim=deepcopy(claim);snapshot=claim.get('snapshot')
        if type(snapshot) is not dict:raise ModelPortRejected('claim invalid')
        try:
            pin=validate_authoring_pin(snapshot)
            if pin is None:raise ValueError()
            require_mobile_agent_engine(pin.get('authoring_engine'))
            for name in ('project_id','job_id','attempt_id'):
                if type(claim[name]) is not str or str(UUID(claim[name]))!=claim[name]:raise ValueError()
            if (snapshot.get('job_id')!=claim['job_id'] or snapshot.get('attempt_id')!=claim['attempt_id']
                or snapshot.get('purpose')!='recording' or type(claim['generation']) is not int or claim['generation']<1
                or type(snapshot.get('intent_hash')) is not str or not snapshot['intent_hash']
                or type(snapshot.get('intent')) is not dict or snapshot['intent'].get('secret_refs')!={}):raise ValueError()
            if type(token_output_limit) is not int or not 16<=token_output_limit<=2048:raise ValueError()
        except (ValueError,TypeError,KeyError):raise ModelPortRejected('original engine claim invalid') from None
        self._client=client;self._claim=claim;self._pin=pin;self._output_limit=token_output_limit
        self._deadline=(datetime.now(timezone.utc)+timedelta(seconds=pin['timeout_seconds'])).isoformat()
        self._lock=Lock();self._seen=set();self._consumed_artifacts=set();self._pending=None;self._last=None;self._stopped=False
        self.model_requests=0;self._before_ids=[];self._registered=None

    @property
    def before_artifact_ids(self):return tuple(self._before_ids)

    @property
    def unaccepted_observation(self):
        return self._registered if self._pending is None else None

    @property
    def pending(self):return self._pending

    @property
    def last_turn(self):return self._last

    @property
    def stopped(self):return self._stopped

    def __call__(self,request,*,before_send):
        if not self._lock.acquire(blocking=False):raise ModelPortRejected('model request in progress')
        started=False;completed=False
        try:
            if self._stopped:raise ModelPortRejected('model port stopped')
            if self._pending is not None:raise ModelPortRejected('evidence pending')
            started=True
            if self.model_requests>=self._pin['max_model_calls']:raise ModelPortRejected('model request limit')
            frame=request.get('current') if type(request) is dict else None
            if (type(frame) is not MobileAgentModelFrame or frame.platform!='android' or not callable(before_send)
                or type(frame.png) is not bytes or not 0<len(frame.png)<=2000000
                or type(frame.observation_id) is not str or not 1<=len(frame.observation_id)<=128 or frame.observation_id in self._seen):
                raise ModelPortRejected('current frame invalid')
            try:frame=replace(frame,geometry=parse_geometry(asdict(frame.geometry)))
            except (ValueError,TypeError,AttributeError):raise ModelPortRejected('current frame invalid') from None
            self._seen.add(frame.observation_id)
            call=str(uuid4());claim=self._claim
            observation=Observation(frame.observation_id,frame.captured_at,frame.geometry,frame.png,'','',(),'',True,'android')
            payload={'call_id':call,'purpose':'recording','role':'authoring','owner_kind':'authoring','owner_id':claim['attempt_id'],
                'binding_revision':self._pin['authoring_binding']['revision'],'generation':claim['generation'],
                'intent_hash':claim['snapshot']['intent_hash'],'deadline':self._deadline,'token_output_limit':self._output_limit}
            bound=upload_authoring_observation(self._client,claim,observation,payload)
            before_id=bound.get('artifact_id')
            try:
                if type(before_id) is not str or str(UUID(before_id))!=before_id:raise ValueError()
            except (ValueError,TypeError,AttributeError):raise ModelPortRejected('before artifact receipt invalid') from None
            self._before_ids.append(before_id)
            self._registered=MobileAgentRegisteredObservation(call,'ma-'+call,before_id,bound['image_hash'],bound['observation_id'])
            payload.update(model_observation_id=bound['observation_id'],sanitized_inputs=bound['sanitized_inputs'])
            before_send();self.model_requests+=1
            receipt=self._client.request_model(project_id=claim['project_id'],item_id=claim['attempt_id'],
                payload=payload,idempotency_key='mobile-model:'+claim['attempt_id']+':'+call)
            if (type(receipt) is not dict or receipt.get('allowed') is not True or receipt.get('action_allowed') is not True
                or receipt.get('provider_dispatched') is not True or receipt.get('call_id')!=call
                or receipt.get('item_id')!=claim['attempt_id'] or type(receipt.get('generation')) is not int
                or receipt['generation']!=claim['generation'] or receipt.get('role')!='authoring' or receipt.get('purpose')!='recording'
                or receipt.get('actual_model')!='gpt-6-luna' or receipt.get('model_observation_id')!=bound['observation_id']
                or receipt.get('image_hash')!='sha256:'+hashlib.sha256(frame.png).hexdigest()
                or type(receipt.get('content')) is not str or not 0<len(receipt['content'].encode('utf-8'))<=16384):
                raise ModelPortRejected('model receipt does not match')
            rendered=render_reply(receipt['content'])
            # Match the process supervisor's framing check before this becomes an accepted turn.
            if rendered.count('<tool_call>')!=1 or rendered.count('</tool_call>')!=1:
                raise ModelPortRejected('model tool block invalid')
            protocol=load_protocol();raw=protocol.parse_action(rendered)
            action=upstream_action(protocol,raw,frame.geometry)
            terminal=action is not None and action.kind=='finish'
            # Store a detached allowlisted receipt; never retain arbitrary server fields.
            allowed=('call_id','item_id','generation','purpose','role','actual_model','provider_request_id',
                     'measurement_status','model_observation_id','image_hash','usage','replayed')
            audit={name:receipt[name] for name in allowed if name in receipt}
            turn=MobileAgentWorkerTurn(call,'ma-'+call,receipt['content'],bound['observation_id'],receipt['image_hash'],
                frame,terminal,action,json.dumps(audit,ensure_ascii=False,separators=(',',':'),allow_nan=False),before_id)
            self._pending=self._last=turn;self._stopped=terminal;completed=True
            return turn.content
        finally:
            if started and not completed:self._stopped=True
            self._lock.release()

    def accept_evidence(self,call_id,receipt,*,after_id,log_id):
        if not self._lock.acquire(blocking=False):raise ModelPortRejected('model request in progress')
        try:
            turn=self._pending
            try:
                for identity in (after_id,log_id):
                    if type(identity) is not str or str(UUID(identity))!=identity:raise ValueError()
            except (ValueError,TypeError,AttributeError):raise ModelPortRejected('evidence receipt invalid') from None
            if (turn is None or turn.call_id!=call_id or type(receipt) is not dict or receipt.get('late') is not False
                or receipt.get('attempt_id')!=self._claim['attempt_id'] or after_id==log_id
                or type(receipt.get('artifact_ids')) is not list or receipt['artifact_ids']!=[after_id,log_id]
                or after_id in self._consumed_artifacts or log_id in self._consumed_artifacts):raise ModelPortRejected('evidence receipt invalid')
            self._consumed_artifacts.update((after_id,log_id));self._pending=None;self._registered=None
        finally:self._lock.release()
