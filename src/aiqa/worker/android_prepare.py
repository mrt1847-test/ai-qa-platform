"""Once-per-attempt app preparation with durable, evidence-only confirmation."""
from dataclasses import asdict,dataclass,replace
from datetime import datetime
import base64,hashlib,json

from aiqa.contracts.actions import Observation
from aiqa.contracts.model_observations import parse_geometry
from aiqa.security.redaction import filter_capture
from aiqa.worker.case_context import resolve_claim_case_context
from aiqa.worker.step_evidence import StepEvidenceCommitter
from aiqa.worker.files import atomic_write
import logging


class AppPreparationFailed(RuntimeError):
    def __init__(self,reason,*,ambiguous=False,native_calls=0,artifact_ids=()):
        super().__init__(reason);self.reason=reason;self.ambiguous=ambiguous
        self.native_calls=native_calls;self.artifact_ids=tuple(artifact_ids)


@dataclass(frozen=True,slots=True)
class PreparedTarget:
    observation: Observation
    artifact_ids: tuple[str,...]


class AndroidTargetPreparer:
    def __init__(self,*,capture,launch,client,journal):
        self.capture,self.launch,self.client,self.journal=capture,launch,client,journal
        self._context_hash=None;self._owner=None;self._pending=None;self._result=None;self._failure=None;self._folder=None;self._committed_ids=()

    @staticmethod
    def _gate(checkpoint):
        result=checkpoint()
        if result is not None and getattr(result,'allowed',None) is not True:
            raise AppPreparationFailed('preparation_checkpoint_blocked')

    def _observe(self,checkpoint):
        self._gate(checkpoint)
        value=self.capture()
        if not isinstance(value,Observation) or not value.capture_ok or value.platform!='android':
            raise AppPreparationFailed('preparation_capture_failed')
        geometry=parse_geometry(asdict(value.geometry))
        stamp=datetime.fromisoformat(value.captured_at)
        if stamp.tzinfo is None:raise AppPreparationFailed('preparation_capture_time_invalid')
        clean=filter_capture(replace(value,geometry=geometry),())
        return replace(value,png=clean.png,dom=clean.dom,stdout=clean.stdout,messages=clean.messages,reasoning='')

    def _save(self,name,body):
        atomic_write(self._folder/name,body)

    def _build_pending(self,claim,pin,before,after,*,state,activity='',reason=''):
        doc=pin.to_document();action='prepare-'+claim['attempt_id']
        log=json.dumps({'operation':'app_prepare','state':state,'package':pin.target.android_package,
            'activity':activity,'reason':reason,'case_context_hash':pin.context_hash,
            'attempt_id':claim['attempt_id'],'model_calls':0},sort_keys=True,separators=(',',':')).encode()
        self._save('prepare.log',log)
        sources=[('prepare-before.png','image/png',before.png,'before')]
        if after is not None:sources.append(('prepare-after.png','image/png',after.png,'after'))
        sources.append(('prepare.log','text/plain',log,'log'))
        parts=[{'filename':name,'media_type':media,'body_b64':base64.b64encode(body).decode(),
            'declared_hash':'sha256:'+hashlib.sha256(body).hexdigest(),'declared_length':len(body),
            'owner_kind':doc['owner_kind'],'owner_id':doc['owner_id'],'attempt_id':claim['attempt_id'],
            'action_id':action,'role':role} for name,media,body,role in sources]
        frame=after or before
        self._save('payload.json',json.dumps({'scope':list(self._owner),'context_hash':pin.context_hash,'artifacts':parts,'captured_at':frame.captured_at,
            'request_key':'evidence-'+claim['attempt_id']+'-prepare-1'},sort_keys=True).encode())
        self._pending=(StepEvidenceCommitter(self.client,claim,namespace='prepare',
            clock=lambda:datetime.fromisoformat(frame.captured_at)),frame,parts)

    def _restore_pending(self,claim,pin):
        path=self._folder/'payload.json'
        if not path.exists():return False
        if path.stat().st_size>32_000_000:raise AppPreparationFailed('preparation_spool_invalid')
        saved=json.loads(path.read_text(encoding='utf-8'))
        if (saved.get('scope')!=list(self._owner) or saved.get('context_hash')!=pin.context_hash
            or saved.get('request_key')!='evidence-'+claim['attempt_id']+'-prepare-1'):
            raise AppPreparationFailed('preparation_spool_owner_mismatch')
        stamp=datetime.fromisoformat(saved['captured_at'])
        if stamp.tzinfo is None:raise AppPreparationFailed('preparation_spool_invalid')
        parts=saved['artifacts']
        if type(parts) is not list or len(parts) not in (2,3):raise AppPreparationFailed('preparation_spool_invalid')
        owner=pin.to_document()
        for part in parts:
            body=base64.b64decode(part['body_b64'],validate=True)
            if (part.get('owner_kind')!=owner['owner_kind'] or part.get('owner_id')!=owner['owner_id']
                or part.get('attempt_id')!=claim['attempt_id'] or part.get('action_id')!='prepare-'+claim['attempt_id']
                or part.get('declared_length')!=len(body) or part.get('declared_hash')!='sha256:'+hashlib.sha256(body).hexdigest()):
                raise AppPreparationFailed('preparation_spool_invalid')
        self._pending=(StepEvidenceCommitter(self.client,claim,namespace='prepare',clock=lambda:stamp),None,parts)
        return True

    def _publish(self):
        committer,frame,parts=self._pending
        ack=committer(action_seq=1,action_id=parts[0]['action_id'],events=[],artifacts=parts)
        ids=tuple(ack['artifact_ids']);self._committed_ids=ids
        self._pending=None
        try:
            for name in ('before.png','after.png','prepare.log','payload.json'):
                (self._folder/name).unlink(missing_ok=True)
            self._folder.rmdir()
        except OSError:logging.getLogger(__name__).warning('Preparation spool cleanup deferred')
        return frame,ids

    def prepare(self,claim,pin,*,checkpoint,before_native_send=None):
        action='prepare-'+str(claim.get('attempt_id'));before=after=None;sent=False;launched=None
        try:
            if self.client is None:raise AppPreparationFailed('preparation_evidence_client_missing')
            current=resolve_claim_case_context(claim,required=True)
            if current.context_hash!=pin.context_hash or current.target.kind!='android':
                raise AppPreparationFailed('preparation_target_mismatch')
            doc=pin.to_document()
            if doc['secret_refs'] or doc['target_secret_refs']:
                raise AppPreparationFailed('preparation_pixel_coverage_unavailable')
            owner=tuple(claim[k] for k in ('project_id','job_id','attempt_id','generation'))
            if owner==self._owner and self._context_hash!=pin.context_hash:
                raise AppPreparationFailed('preparation_target_changed')
            if owner!=self._owner:
                self._owner=owner;self._context_hash=pin.context_hash;self._pending=None;self._result=None;self._failure=None;self._committed_ids=()
                self._folder=self.journal.path.parent/'prepare-spool'/claim['attempt_id']
                if self.journal.states(action,claim['attempt_id']):
                    self._failure=AppPreparationFailed('preparation_recovered_no_resume',ambiguous=self.journal.is_ambiguous(claim['attempt_id'],action))
                    if self._restore_pending(claim,pin):self._publish()
                    raise self._failure
            self._gate(checkpoint)
            if self._failure is not None:
                if self._pending is not None:
                    try:self._publish()
                    except Exception:pass
                raise self._failure
            if self._result is not None:return self._result
            if self._pending is None:
                if self.journal.states(action,claim['attempt_id']):
                    raise AppPreparationFailed('preparation_already_recorded',ambiguous=self.journal.is_ambiguous(claim['attempt_id'],action))
                self.journal.append(claim['attempt_id'],action,'planned')
                before=self._observe(checkpoint);self._save('before.png',before.png)
                def before_send():
                    nonlocal sent
                    self._gate(checkpoint)
                    self.journal.append(claim['attempt_id'],action,'dispatch_started')
                    try:
                        self._gate(checkpoint)
                        if before_native_send is not None:before_native_send()
                    except Exception:
                        self.journal.append(claim['attempt_id'],action,'not_sent');raise
                    sent=True
                launched=self.launch(pin.target.android_package,before_native_send=before_send)
                after=self._observe(checkpoint);self._save('after.png',after.png)
                self.journal.append(claim['attempt_id'],action,'acknowledged')
                self.journal.append(claim['attempt_id'],action,'observed')
                self._build_pending(claim,pin,before,after,state='observed',activity=launched.activity)
            self._gate(checkpoint)
            frame,ids=self._publish()
            self._result=PreparedTarget(frame,ids)
            self._gate(checkpoint)
            return self._result
        except Exception as exc:
            try:
                self.journal.mark_started_only_unknown(str(claim.get('attempt_id')),action)
                ambiguous=self.journal.is_ambiguous(str(claim.get('attempt_id')),action)
                known=1 if 'acknowledged' in self.journal.states(action,str(claim.get('attempt_id'))) else 0
            except Exception:ambiguous=True;known=0
            reason=getattr(exc,'reason','preparation_failed')
            same_owner=(tuple(claim.get(k) for k in ('project_id','job_id','attempt_id','generation'))==self._owner
                and getattr(pin,'context_hash',None)==self._context_hash)
            ids=self._committed_ids if same_owner else ()
            failure=AppPreparationFailed(reason,ambiguous=ambiguous or getattr(exc,'ambiguous',False),native_calls=known,artifact_ids=ids)
            if sent and before is not None and self._result is None and self._failure is None and self._pending is None:
                self._failure=failure
                if after is None:
                    try:after=self._observe(checkpoint);self._save('after.png',after.png)
                    except Exception:after=None
                try:
                    self._build_pending(claim,pin,before,after,state='unknown',
                        activity=getattr(launched,'activity',''),reason=reason)
                    self._publish()
                except Exception:pass  # Durable sanitized spool remains; never retry the native start.
            if same_owner:failure.artifact_ids=tuple(self._committed_ids)
            raise failure from exc
