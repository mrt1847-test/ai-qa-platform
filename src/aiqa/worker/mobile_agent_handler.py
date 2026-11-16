"""Operational original-engine handler. Device/model I/O stays in existing bounded ports."""
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from aiqa.adapters.mobile_agent_upstream import load_protocol
from aiqa.contracts.mobile_agent_engine import mobile_agent_engine_ref
from aiqa.worker.android_jobs import AndroidRecordingHandler
from aiqa.worker.android_prepare import AndroidTargetPreparer,AppPreparationFailed
from aiqa.worker.case_context import resolve_claim_case_context,CaseContextRejected
from aiqa.worker.mobile_agent_models import MobileAgentModelPort
from aiqa.worker.mobile_agent_recording import MobileAgentRecordingSession
from aiqa.worker.recording_limits import resolve_recording_limits
from aiqa.worker.runtime import HandlerResult


@dataclass(kw_only=True)
class OriginalAndroidRecordingHandler(AndroidRecordingHandler):
    client:object
    runtime_root:Path

    def _local_allowed(self,claim):
        if self._is_cancelled() or claim['snapshot'].get('cancel_requested') is True:return False
        owner=getattr(self.context.remote_checkpoint,'__self__',None)
        if getattr(owner,'failed',False) is True:return False
        return self._limits is not None and self._mono_now().seconds<self._limits.timeout_seconds

    def handle(self,claim):
        self.tap_count=self.authoring_calls_seen=0;self.stopped_reason='';self.session_result=None
        self._limits=self._mono_origin=None;self.preparation_artifact_ids=();prepared_actions=0
        claim=deepcopy(claim)
        def failed(reason,*,ambiguous=False):
            self.stopped_reason=reason
            return HandlerResult(actions=prepared_actions,outcome='error',evidence_complete=False,
                ambiguous_dispatch=ambiguous,source_artifact_hashes=self.preparation_artifact_ids)
        try:self._case_context=resolve_claim_case_context(claim,required=True)
        except CaseContextRejected:return failed('case_context_invalid')
        try:
            # Validate the exact authoring/owner before preparation can issue any native command.
            MobileAgentModelPort(self.client,claim)
            load_protocol()
            if type(claim.get('worker_id')) is not str or not claim['worker_id'].strip():raise ValueError('owner invalid')
            snapshot=claim['snapshot']
            objective=snapshot['intent'].get('objective')
            if type(objective) is not str or not objective.strip() or len(objective.encode('utf-8'))>16000:
                raise ValueError('original instruction invalid')
            if self._case_context.target.kind!='android':raise ValueError('Android case required')
            serial=snapshot.get('serial') or snapshot.get('native_id')
            if serial!=self.context.expected_serial or self.driver.serial!=serial:raise ValueError('serial mismatch')
            if (not self.context.require_case_context or self.context.remote_checkpoint is None
                or not callable(self.context.live_capture) or not isinstance(self.context.target_preparer,AndroidTargetPreparer)):
                raise ValueError('runtime ports missing')
            self._limits=resolve_recording_limits(snapshot,worker_actions=self.context.max_actions,
                worker_seconds=self.context.max_seconds,supported_engine=mobile_agent_engine_ref())
            if self._limits is None or self._limits.max_actions<2:raise ValueError('preparation action reservation missing')
            project=str(UUID(claim['project_id']));attempt=str(UUID(claim['attempt_id']))
            directory=Path(self.runtime_root)/'mobile-agent'/project/attempt
            self.guard.begin_attempt(attempt)
            self._mono_now()  # Charge the first blocking remote lookup to the same attempt clock.
            self._recording_gate(claim,phase='before_lookup')
            # This guard covers preparation as well as the model session. Never resume an old attempt.
            directory.mkdir(parents=True,exist_ok=False)
        except FileExistsError:return failed('original_attempt_exists',ambiguous=True)
        except Exception:return failed('original_preflight_failed')
        try:
            target=self.context.target_preparer.prepare(claim,self._case_context,
                checkpoint=lambda:self._recording_gate(claim,phase='before_lookup'),
                before_native_send=lambda:self._recording_gate(claim,phase='before_dispatch'))
            prepared_actions=1;self.preparation_artifact_ids=target.artifact_ids
            self._recording_gate(claim,phase='before_lookup')
            remaining=self._limits.timeout_seconds-self._mono_now().seconds
            if remaining<=0:return failed('time_budget')
            def checkpoint(phase):
                mapped='before_model' if phase=='before_model' else 'before_dispatch' if phase=='before_native' else 'before_lookup'
                self._recording_gate(claim,phase=mapped)
                return True
            session=MobileAgentRecordingSession(self.client,claim,driver=self.driver,capture=self.context.live_capture,
                output=directory/'session',expected_serial=self.context.expected_serial,checkpoint=checkpoint,
                allowed=lambda:self._local_allowed(claim),worker_actions=self._limits.max_actions-prepared_actions,
                worker_seconds=remaining)
            self.session_result=result=session.run()
        except AppPreparationFailed as exc:
            # Keep already committed preparation even if the next authority check was refused.
            prepared_actions=exc.native_calls;self.preparation_artifact_ids=exc.artifact_ids
            return failed(exc.reason,ambiguous=exc.ambiguous)
        except Exception:return failed('original_runtime_failed')
        self.tap_count=result.native_actions;self.authoring_calls_seen=result.model_requests;self.stopped_reason=result.reason
        ids=self.preparation_artifact_ids+result.before_artifact_ids+result.artifact_ids
        return HandlerResult(actions=prepared_actions+result.native_actions,
            outcome='completed' if result.outcome=='completed' else 'error',
            evidence_complete=result.evidence_complete,ambiguous_dispatch=result.ambiguous_dispatch,
            final_seq=result.last_ack_seq,last_ack_seq=result.last_ack_seq,last_ack_hash=result.last_ack_hash,
            source_artifact_hashes=ids,review_pending=result.review_pending,action_mapping=result.action_mapping,cleanup_failed=result.cleanup_failed,
            evidence_recovery=(lambda seq=session.delivery.pending_sequence:session.delivery.confirm_turn(seq)) if result.evidence_pending else None)
