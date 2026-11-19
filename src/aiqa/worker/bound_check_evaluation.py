"""Evaluate source-owned checks at their explicit native boundary, never by ordinal guess."""
import re
import time
from aiqa.contracts.checks import CheckResult
from aiqa.worker.replay_check_coverage import RequiredCheckCoverage,validate_observed_at


def scheduled_checks(pin,binding,native_source,*,action_index,total_actions):
    if type(action_index) is not int or not 1<=action_index<=total_actions<=50:
        raise ValueError('invalid check phase')
    boundaries=dict(binding.boundaries) if binding else {}
    current=native_source.steps[action_index-1].action_id if native_source else None
    final=action_index==total_actions
    rows=[]
    for step in pin.steps:
        boundary=boundaries.get(step.id)
        if boundary is not None and boundary==current:
            rows.extend((check,'step',step.id,'') for check in step.expected)
        elif boundary is None and final:
            rows.extend((check,'step',step.id,'logical_step_mapping_missing') for check in step.expected)
    if final:rows.extend((check,'final',None,'') for check in pin.final_expected)
    return tuple(rows)


def _compare(check,target):
    if target is None:return 'unknown','target_missing'
    if target.status!='available':return 'unknown','target_'+target.status
    if check.kind=='text':
        if target.text is None:return 'unknown','target_unavailable'
        return ('satisfied','exact_text_match') if target.text==check.expected else ('violated','text_mismatch')
    if check.kind=='state':
        match=re.fullmatch(r'(enabled|checked|selected|focused|visible)=(true|false)',check.expected)
        if not match:return 'unknown','unsupported_state_expression'
        actual=getattr(target,match[1],None)
        if actual is None:return 'unknown','state_field_unavailable'
        return ('satisfied','state_match') if actual==(match[2]=='true') else ('violated','state_mismatch')
    return 'unknown','unsupported_check_kind'


def evaluate_bound_checks(pin,binding,native_source,*,action_index,total_actions,observed_at,
                          hierarchy_observer=None,checkpoint,timeout=30,visual=None,
                          clock=time.monotonic,pause=time.sleep):
    validate_observed_at(observed_at)
    scheduled=scheduled_checks(pin,binding,native_source,action_index=action_index,total_actions=total_actions)
    if not scheduled:return ()
    policies=pin.to_document()['verification']
    policy=policies[0] if len(policies)==1 else {}
    method=policy.get('method','deterministic')
    if method not in {'deterministic','ai_visual','deterministic_then_ai_unknown'}:method='deterministic'
    # A saved target is not permission to read. Only one approved deterministic policy may.
    approved=len(policies)==1 and method in {'deterministic','deterministic_then_ai_unknown'}
    targets=dict(binding.targets) if binding else {}
    resources=tuple(sorted({targets[c.id] for c,_,_,reason in scheduled
        if approved and not reason and c.id in targets}))
    snapshot={};read_reason='';stamp=observed_at
    def gate():
        if checkpoint() is False:raise RuntimeError('verification_cancelled')
        return True
    if resources and hierarchy_observer:
        deadline=clock()+min(30,max(.001,timeout))
        for _ in range(121):
            gate()
            remaining=deadline-clock()
            if remaining<=0:read_reason='loading_timeout';break
            try:
                result=hierarchy_observer(package=pin.target.android_package,resource_ids=resources,
                    checkpoint=gate,timeout=remaining)
                gate()
                if clock()>=deadline:read_reason='loading_timeout';break
                validate_observed_at(result.captured_at);stamp=result.captured_at
                snapshot={t.resource_id:t for t in result.snapshot.targets}
                if all(snapshot.get(r) is not None and snapshot[r].status!='missing' for r in resources):break
            except (ValueError,OSError,TimeoutError):read_reason='hierarchy_unavailable';break
            pause(min(.25,max(0,deadline-clock())))
        else:read_reason='loading_timeout'
    elif resources:read_reason='hierarchy_unavailable'
    rows=[]
    for check,phase,step_id,unmapped in scheduled:
        gate();status='unknown';reason=unmapped
        if not reason:
            if len(policies)!=1:reason='verifier_policy_missing' if not policies else 'verifier_policy_ambiguous'
            elif method!='ai_visual':
                resource=targets.get(check.id)
                if not resource:reason='deterministic_subject_missing'
                elif read_reason:reason=read_reason
                else:status,reason=_compare(check,snapshot.get(resource))
            if (method=='ai_visual' or method=='deterministic_then_ai_unknown' and status=='unknown'
                and policy.get('allow_unknown_supplement') is True):
                if visual is None:reason='verifier_not_connected'
                else:
                    reply=visual(check,phase,step_id);gate()
                    if type(reply) is not dict or reply.get('status') not in {'satisfied','violated','unknown'}:
                        status,reason='unknown','verifier_response_invalid'
                    else:
                        status=reply['status'];reason=str(reply.get('reason') or 'verifier_response_invalid')[:256]
                        stamp=reply.get('observed_at',observed_at);validate_observed_at(stamp)
        result=CheckResult(check.id,status,method,check.expected,'',reason,stamp,
            'FAIL' if status=='violated' else '')
        rows.append(RequiredCheckCoverage(result,phase,step_id,pin.context_hash,pin.case_version_id,pin.content_hash,check.kind))
    return tuple(rows)
