"""Original Mobile-Agent callbacks with durable physical ACKs and server evidence.

Internal session only: runtime target/lease binding and admission are registered separately.
"""
from __future__ import annotations

import base64,hashlib,json
from copy import deepcopy
from dataclasses import asdict,dataclass,replace
from pathlib import Path
from time import monotonic
from uuid import UUID

from aiqa.adapters.mobile_agent_android import _physical_identity,_binding_for
from aiqa.contracts.actions import Observation
from aiqa.contracts.mobile_agent_engine import mobile_agent_engine_ref
from aiqa.contracts.model_observations import parse_geometry
from aiqa.recording.mobile_agent_frames import require_guarded_frame
from aiqa.replay.android_native_trace import native_event,parse_native_trace
from aiqa.replay.android_runner import AndroidDeterministicDriver,AndroidPreflight,GeometryLock
from aiqa.security.redaction import filter_capture
from aiqa.worker.android_jobs import android_evidence_events,android_source_artifact
from aiqa.worker.dispatch_journal import DispatchJournal
from aiqa.worker.files import atomic_write
from aiqa.worker.mobile_agent_models import MobileAgentModelPort
from aiqa.worker.mobile_agent_process import MobileAgentProcessResult,run_mobile_agent_process
from aiqa.worker.recording_limits import resolve_recording_limits
from aiqa.worker.step_evidence import StepEvidenceCommitter


def _json(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def _hash(raw):return 'sha256:'+hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True,slots=True)
class MobileAgentRecordingResult:
    outcome:str
    reason:str
    native_actions:int
    model_requests:int
    ambiguous_dispatch:bool
    evidence_complete:bool
    review_pending:bool
    action_mapping:str
    artifact_ids:tuple[str,...]
    last_ack_seq:int
    last_ack_hash:str
    process:MobileAgentProcessResult
    before_artifact_ids:tuple[str,...]=()
    cleanup_failed:bool=False


class MobileAgentRecordingSession:
    """Single use. Recovery resends evidence metadata; it never restarts this session."""
    def __init__(self,client,claim,*,driver,capture,output,expected_serial,checkpoint,allowed,secrets=(),worker_actions=50,worker_seconds=None):
        claim=deepcopy(claim)
        if type(claim) is not dict or type(claim.get('worker_id')) is not str or not claim['worker_id'].strip():
            raise ValueError('durable evidence owner invalid')
        self.model_port=MobileAgentModelPort(client,claim)
        self.limits=resolve_recording_limits(claim['snapshot'],worker_actions=worker_actions,worker_seconds=worker_seconds,
            supported_engine=mobile_agent_engine_ref())
        if (self.limits is None or self.limits.max_actions<1 or not isinstance(driver,AndroidDeterministicDriver)
            or type(expected_serial) is not str or not expected_serial or driver.serial!=expected_serial
            or not all(callable(v) for v in (capture,checkpoint,allowed))
            or type(secrets) is not tuple or any(type(v) is not str or not v for v in secrets)):
            raise ValueError('original session inputs invalid')
        self.claim=claim;self.driver=driver;self._capture_port=capture;self.output=Path(output)
        self._checkpoint_port=checkpoint;self._allowed_port=allowed;self._secrets=secrets
        self._serial=expected_serial;self._current=None;self._seen=set();self._ack_turn=None
        self._native=[];self._native_actions=0;self._turns=0;self._ids=[];self._seq=0;self._prefix=_hash(b'')
        self._fault='';self._uncertain=False;self._deadline=None
        self.journal=DispatchJournal(self.output/'dispatch.jsonl')
        self.delivery=StepEvidenceCommitter(client,claim,namespace='mobile',pending_path=self.output/'evidence-delivery.json')

    def _allowed(self):
        return (not self._fault and (self._deadline is None or monotonic()<self._deadline)
            and self._allowed_port() is True)

    def _checkpoint(self,phase):
        if not self._allowed() or self._checkpoint_port(phase) is not True or not self._allowed():
            raise ValueError('current execution authority refused')

    def _final_authority(self,phase):
        try:
            self._checkpoint(phase)
            return True
        except Exception:
            if not self._fault:self._fault='final_authority_refused'
            return False

    def _read_capture(self,phase):
        self._checkpoint(phase)
        try:
            raw=self._capture_port()
            if (type(raw) is not Observation or raw.platform!='android' or raw.observation_id in self._seen
                or type(raw.observation_id) is not str or not 0<len(raw.observation_id)<=128):
                raise ValueError('capture identity invalid')
            geometry=parse_geometry(asdict(raw.geometry))
            clean=filter_capture(raw,self._secrets)
            if not self._allowed():raise ValueError('capture authority expired')
            if len(clean.png)>2000000:raise ValueError('capture too large')
            current=replace(raw,geometry=geometry,png=clean.png,dom=clean.dom,stdout=clean.stdout,
                messages=clean.messages,reasoning='')
            self._seen.add(current.observation_id)
            return current
        except Exception:
            self._fault='capture_failed'
            raise

    def _capture(self):
        current=self._read_capture('before_capture')
        if self.model_port.pending is not None:self._flush_turn(current)
        self._current=current
        return current

    def _model(self,request,*,before_send):
        current=request.get('current')
        if (self._current is None or current is None or current.observation_id!=self._current.observation_id
            or current.png!=self._current.png or current.geometry!=self._current.geometry):
            raise ValueError('model frame changed')
        def boundary():
            self._checkpoint('before_model');before_send()
        content=self.model_port(request,before_send=boundary)
        return content

    def _dispatch(self,action,before,*,before_send):
        turn=self.model_port.pending
        if (turn is None or turn.terminal or action!=turn.action or self._current is None
            or before.observation_id!=self._current.observation_id or before.png!=turn.frame.png
            or before.geometry!=turn.frame.geometry or self._ack_turn is not None):
            raise ValueError('native turn changed')
        self._checkpoint('before_dispatch')
        fresh=self._read_capture('before_native_capture')
        if fresh.geometry!=before.geometry:raise ValueError('native geometry changed')
        require_guarded_frame(before.png,fresh.png,action,before.dom,fresh.dom)
        event=native_event(action,before,action_id=turn.action_id,line=self._native_actions+1)
        identity=_physical_identity(fresh);lock=GeometryLock.from_observation(self._serial,identity)
        attempt=self.claim['attempt_id'];started=False;sent=False
        self.journal.append(attempt,turn.action_id,'planned')
        def boundary():
            nonlocal started,sent
            self.journal.append(attempt,turn.action_id,'dispatch_started');started=True
            self._checkpoint('before_native');before_send();sent=True
        try:
            ack=self.driver.run(preflight=AndroidPreflight(),binding=_binding_for(action,lock),before=identity,
                action=action,observed_serial=self._serial,before_native_send=boundary)
            if ack.native_calls!=1 or ack.outcome!='acknowledged':raise ValueError('native ACK missing')
        except Exception:
            if started:
                if sent:self._uncertain=True
                try:self.journal.append(attempt,turn.action_id,'unknown' if sent else 'not_sent')
                except OSError:self._fault='native_persistence_failed'
            raise
        # Returning this ACK precedes after capture, so parent retains the physical count on later failure.
        self._native_actions+=1;self._native.append(event);self._ack_turn=turn.call_id
        try:
            self.journal.append(attempt,turn.action_id,'acknowledged')
        except OSError:self._fault='native_persistence_failed'
        try:
            atomic_write(self.output/'native-prefix.json',self._mapping().encode('utf-8'))
        except OSError:self._fault='native_persistence_failed'
        return ack

    def _mapping(self):
        return _json({'schema':'android-native-trace-v2','native_action_count':len(self._native),'events':self._native})

    def _flush_turn(self,after):
        turn=self.model_port.pending
        if turn is None:return
        physical=turn.action is not None and not turn.terminal
        if physical and self._ack_turn!=turn.call_id:raise ValueError('native evidence has no ACK')
        if after.geometry!=turn.frame.geometry:raise ValueError('after geometry changed')
        before=replace(after,observation_id=turn.frame.observation_id,captured_at=turn.frame.captured_at,
            geometry=turn.frame.geometry,png=turn.frame.png,dom='',stdout='',messages=(),reasoning='')
        proof={'schema':'mobile-agent-step-v1','call_id':turn.call_id,'action_id':turn.action_id,'state':'observed',
            'native_calls':1 if physical else 0,'native':asdict(turn.action) if physical else None,
            'before_image_hash':turn.image_hash,'after_image_hash':_hash(after.png)}
        parts=[]
        for role,body,media in [('after',after.png,'image/png'),('log',_json(proof).encode('utf-8'),'text/plain')]:
            parts.append({'filename':turn.action_id+'-'+('after.png' if role=='after' else 'action.log'),
                'media_type':media,'declared_hash':_hash(body),'declared_length':len(body),
                'body_b64':base64.b64encode(body).decode('ascii'),'role':role,'owner_kind':'REC',
                'attempt_id':self.claim['attempt_id'],'action_id':turn.action_id})
        events=list(android_evidence_events(attempt_id=self.claim['attempt_id'],action_id=turn.action_id,
            before=before,after=after,seq_base=self._seq,action_seq=self._turns+1)) if physical else []
        try:
            ack=self.delivery(action_seq=self._turns+1,action_id=turn.action_id,events=events,artifacts=parts)
            self.model_port.accept_evidence(turn.call_id,ack,after_id=ack['artifact_ids'][0],log_id=ack['artifact_ids'][1])
            self._accept_ack(ack);self._turns+=1
            if physical:self.journal.append(self.claim['attempt_id'],turn.action_id,'observed')
            self._ack_turn=None
        except Exception:
            self._fault='evidence_commit_failed'
            raise

    def _accept_ack(self,ack):
        self._ids.extend(ack['artifact_ids']);self._seq=ack['contiguous_seq'];self._prefix=ack['prefix_hash']

    def run(self):
        self._deadline=monotonic()+self.limits.timeout_seconds
        try:self.output.mkdir(parents=True,exist_ok=False)
        except FileExistsError:raise ValueError('recording session already exists') from None
        self.driver.bind_attempt(UUID(self.claim['attempt_id']))
        instruction=self.claim['snapshot']['intent'].get('objective','')
        result=run_mobile_agent_process(output=self.output/'upstream',instruction=instruction,capture=self._capture,
            model=self._model,dispatch=self._dispatch,secrets=self._secrets,allowed=self._allowed,
            max_steps=self.limits.max_model_calls,max_actions=self.limits.max_actions,timeout_seconds=self.limits.timeout_seconds)
        # A normal child done (including a step limit) may leave its final turn without another capture.
        if result.receipt is not None and not result.cleanup_failed and self._final_authority('after_child') and self.model_port.pending is not None:
            try:self._flush_turn(self._read_capture('after_final_turn'))
            except Exception:
                if not self._fault:self._fault='final_evidence_failed'
        mapping='{}';ready=False
        if (result.status=='claimed_success' and not self._fault and not self._uncertain and self._native_actions>0
            and self._native_actions==result.native_actions and self.model_port.pending is None
            and self._final_authority('before_source')):
            try:
                candidate=self._mapping();parse_native_trace(candidate)
                ack=self.delivery(action_seq=self._turns+1,action_id='source',events=[],
                    artifacts=[android_source_artifact(attempt_id=self.claim['attempt_id'],action_mapping=candidate)])
                self._accept_ack(ack)
                if self._final_authority('after_source'):mapping=candidate;ready=True
            except Exception:self._fault='source_commit_failed'
        return MobileAgentRecordingResult('completed' if ready else 'failed',self._fault or ('no_native_actions' if result.status=='claimed_success' and not self._native_actions else result.reason),
            self._native_actions,self.model_port.model_requests,result.ambiguous_dispatch or self._uncertain,
            self.model_port.pending is None and not self._fault,ready,mapping,tuple(self._ids),self._seq,self._prefix,result,self.model_port.before_artifact_ids,result.cleanup_failed)
