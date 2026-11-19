"""Normalize required native replay checks against the server's immutable source.

Worker rows are observations, never a replacement case definition or an AI verdict.
The caller must hold the finish transaction and validate the lease/ACK first.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass

from aiqa.domain.hashing import canonical_hash
from aiqa.replay.android_native_trace import COMPILER


@dataclass(frozen=True, slots=True)
class ReplayCheckSource:
    context: dict
    native: object
    binding: object | None

    def checks(self):
        rows = {}
        for step in self.context['steps']:
            for check in step['expected']:
                rows[check['id']] = (check, 'step', step['id'])
        for check in self.context['final_expected']:
            rows[check['id']] = (check, 'final', None)
        return rows


def load_replay_check_source(connection, owner):
    """Load only this ITEM's claimed version and exact native package annotation."""
    from aiqa.store.queue import load_claim_receipt_for_attempt
    from aiqa.recording.case_context import load_case_context
    from aiqa.worker.case_context import resolve_claim_case_context
    from aiqa.worker.native_source import resolve_claim_native_source
    from aiqa.worker.check_binding_pin import resolve_claim_check_binding_pin

    row = connection.execute("""SELECT j.purpose,p.compiler_ref FROM jobs j
        LEFT JOIN case_runs i ON i.project_id=j.project_id AND i.case_run_id=j.case_run_id
        LEFT JOIN case_versions v ON v.project_id=i.project_id AND v.version_id=i.case_version_id AND v.case_id=i.case_id
        LEFT JOIN replay_packages p ON p.project_id=v.project_id AND p.package_id=v.replay_package_id
        WHERE j.project_id=? AND j.job_id=?""", (str(owner.project_id), str(owner.job_id))).fetchone()
    if row is None or row[0] not in {'trial', 'regression'} or row[1] != COMPILER:
        return None
    receipt = load_claim_receipt_for_attempt(connection, owner.project_id, owner.attempt_id)
    if (receipt is None or str(receipt.job_id) != str(owner.job_id)
            or receipt.generation != owner.generation):
        raise ValueError('replay check claim missing')
    snapshot = asdict(receipt.snapshot)
    digest = {key: snapshot[key] for key in ('job_id', 'attempt_id', 'purpose', 'target_ref', 'revision_ref', 'policy_ref')}
    digest['job_id'], digest['attempt_id'] = str(receipt.job_id), str(receipt.attempt_id)
    digest.update({key: snapshot[key] for key in ('replay_package_id', 'replay_package_hash', 'self_healing_enabled')})
    if canonical_hash(digest, 'canon-json-v1') != receipt.snapshot.digest:
        raise ValueError('replay check claim source changed')
    context = load_case_context(connection, receipt)
    if context is None or context['replay_compiler_ref'] != COMPILER:
        raise ValueError('replay check source missing')
    snapshot.update(job_id=str(receipt.job_id), attempt_id=str(receipt.attempt_id), case_context=context)
    claim = dict(project_id=str(receipt.project_id), job_id=str(receipt.job_id), attempt_id=str(receipt.attempt_id), generation=receipt.generation, snapshot=snapshot)
    pin = resolve_claim_case_context(claim, required=True)
    native = resolve_claim_native_source(claim, case_context=pin)
    binding = resolve_claim_check_binding_pin(claim, case_context=pin, native_source=native)
    return ReplayCheckSource(context, native, binding)


def _observed_action(connection, owner, source, action_id):
    row = connection.execute("""SELECT dispatch_state,outcome_known,case_version_id FROM actions
        WHERE project_id=? AND attempt_id=? AND action_id=?""", (str(owner.project_id), str(owner.attempt_id), action_id)).fetchone()
    if row is None or row[0] != 'observed' or row[1] != 1 or row[2] != source.context['case_version_id']:
        raise ValueError('replay check action is not observed')
    observed = []
    for detail, in connection.execute("""SELECT detail_payload FROM attempt_events
        WHERE project_id=? AND attempt_id=? AND event_type='action.observed' AND local_seq<=?""",
        (str(owner.project_id), str(owner.attempt_id), owner.last_ack_seq)):
        try:
            facts = json.loads(detail)
        except (TypeError, ValueError):
            continue
        if type(facts) is dict and facts.get('phase') == 'after' and facts.get('action_id') == action_id:
            line = facts.get('action_seq')
            if type(line) is int and 1 <= line <= len(source.native.steps):
                observed.append(line)
    if not observed or len(set(observed)) != 1:
        raise ValueError('replay check action ACK is missing')
    return source.native.steps[observed[0]-1]


def _artifacts(connection, owner, source, action_id):
    rows = connection.execute("""SELECT o.artifact_id,o.role FROM artifact_objects o
        JOIN artifact_refs r ON r.project_id=o.project_id AND r.artifact_id=o.artifact_id
          AND r.attempt_id=o.attempt_id AND r.action_id=o.action_id
        WHERE o.project_id=? AND o.attempt_id=? AND o.action_id=? AND o.job_id=? AND o.generation=?
          AND o.owner_kind='ITEM' AND o.owner_id=? AND o.status='ready' AND o.acked=1
          AND o.custody='stored' AND o.role IN ('after','log') ORDER BY o.role,o.artifact_id""",
        (str(owner.project_id), str(owner.attempt_id), action_id, str(owner.job_id), owner.generation, source.context['owner_id'])).fetchall()
    if {row[1] for row in rows} != {'after', 'log'}:
        raise ValueError('replay check action artifacts are missing')
    return [row[0] for row in rows]


def _policy(source):
    policies = source.context['verification']
    return policies[0]['method'] if len(policies) == 1 else 'unconfigured'


def _validate_result(connection, owner, source, item):
    fields = {'result', 'phase', 'step_id', 'context_hash', 'case_version_id', 'source_hash', 'kind', 'action_id'}
    result_fields = {'check_id', 'status', 'method', 'expected_snapshot', 'sanitized_observed', 'reason', 'observed_at', 'latch'}
    if type(item) is not dict or set(item) != fields or type(item['result']) is not dict or set(item['result']) != result_fields:
        raise ValueError('replay check result shape invalid')
    result = item['result']
    if any(type(result[key]) is not str for key in result_fields) or type(item['action_id']) is not str:
        raise ValueError('replay check result fields invalid')
    if any(len(result[key].encode('utf-8')) > limit for key, limit in (('check_id', 256), ('reason', 256), ('method', 64), ('observed_at', 64), ('latch', 128))):
        raise ValueError('replay check result size invalid')
    from aiqa.worker.replay_check_coverage import validate_observed_at
    validate_observed_at(result['observed_at'])
    saved = source.checks().get(result['check_id'])
    if saved is None:
        raise ValueError('replay check identity invalid')
    check, phase, step_id = saved
    if (item['phase'] != phase or item['step_id'] != step_id or item['kind'] != check['kind']
            or item['context_hash'] != source.context['context_hash']
            or item['case_version_id'] != source.context['case_version_id']
            or item['source_hash'] != source.context['content_hash']):
        raise ValueError('replay check source identity invalid')
    status, method = result['status'], result['method']
    policy = _policy(source)
    missing_policy_placeholder = policy == 'unconfigured' and method == 'deterministic' and status in {'unknown', 'not_run'}
    if status not in {'satisfied', 'violated', 'unknown', 'not_run'} or (method != policy and not missing_policy_placeholder):
        raise ValueError('replay check source policy invalid')
    native = _observed_action(connection, owner, source, item['action_id'])
    boundary = None if source.binding is None else dict(source.binding.boundaries).get(step_id)
    if phase == 'final':
        boundary = source.native.steps[-1].action_id
    if boundary is None:
        if status not in {'unknown', 'not_run'} or native != source.native.steps[-1]:
            raise ValueError('replay check logical boundary missing')
    elif native.action_id != boundary:
        raise ValueError('replay check logical boundary differs')
    refs = _artifacts(connection, owner, source, item['action_id'])
    stored_method = 'deterministic' if method == 'unconfigured' else method
    if method == 'unconfigured' and status not in {'unknown', 'not_run'}:
        raise ValueError('replay check verifier policy missing')
    if method in {'deterministic', 'deterministic_then_ai_unknown'} and status in {'satisfied', 'violated'}:
        existing = connection.execute('SELECT method FROM check_results WHERE project_id=? AND attempt_id=? AND check_id=?', (str(owner.project_id), str(owner.attempt_id), check['id'])).fetchone()
        # The hybrid's server-written visual verdict is handled below; otherwise it
        # must meet the same explicit deterministic subject requirements.
        visual = method == 'deterministic_then_ai_unknown' and existing is not None
        if not visual:
            target = None if source.binding is None else dict(source.binding.targets).get(check['id'])
            supported = check['kind'] == 'text' or (check['kind'] == 'state' and re.fullmatch(r'(?:enabled|checked|selected|focused|visible)=(?:true|false)', check['expected']) is not None)
            reason = ('exact_text_match' if status == 'satisfied' else 'text_mismatch') if check['kind'] == 'text' else ('state_match' if status == 'satisfied' else 'state_mismatch')
            if target is None or not supported or result['reason'] != reason:
                raise ValueError('replay check deterministic subject unsupported')
    return check, stored_method, refs


def persist_replay_check_results(connection, finish):
    """Persist normalized rows and return the required-check aggregate, or legacy None.

    Missing/unknown required checks are INCONCLUSIVE. Existing verdicts are immutable,
    including the original violated result; AI results require a server-written row.
    """
    if type(finish.check_results) is not tuple or len(finish.check_results) > 256:
        raise ValueError('replay check result count invalid')
    source = load_replay_check_source(connection, finish)
    if source is None:
        if finish.check_results:
            raise ValueError('replay check native source required')
        return None
    prepared, seen = [], set()
    for item in finish.check_results:
        check, method, refs = _validate_result(connection, finish, source, item)
        result = item['result']
        if check['id'] in seen:
            raise ValueError('replay check result duplicated')
        seen.add(check['id'])
        existing = connection.execute("""SELECT action_id,status,method,expected_snapshot,reason,observed_at
            FROM check_results WHERE project_id=? AND attempt_id=? AND check_id=?""", (str(finish.project_id), str(finish.attempt_id), check['id'])).fetchone()
        if existing is not None:
            if tuple(existing[:4]) != (item['action_id'], result['status'], method, check['expected']):
                raise ValueError('replay check result is immutable')
        elif result['status'] in {'satisfied', 'violated'} and (method == 'ai_visual' or (method == 'deterministic_then_ai_unknown' and result['reason'].startswith('ai_visual'))):
            raise ValueError('replay visual result must be server written')
        prepared.append((item, check, method, refs, existing))
    # Validate the whole batch before changing any rows, even if the caller catches.
    for item, check, method, refs, existing in prepared:
        if existing is not None:
            continue
        result = item['result']
        connection.execute("""INSERT INTO check_results(project_id,attempt_id,action_id,check_id,status,method,
            expected_snapshot,sanitized_observed,reason,artifact_refs,observed_at) VALUES(?,?,?,?,?,?,?,'',?,?,?)""",
            (str(finish.project_id), str(finish.attempt_id), item['action_id'], check['id'], result['status'], method,
             check['expected'], result['reason'], json.dumps(refs, separators=(',', ':')), result['observed_at']))
    statuses = []
    for check_id, (check, phase, step_id) in source.checks().items():
        row = connection.execute('SELECT action_id,status,method,expected_snapshot,reason,observed_at FROM check_results WHERE project_id=? AND attempt_id=? AND check_id=?', (str(finish.project_id), str(finish.attempt_id), check_id)).fetchone()
        if row is None:
            statuses.append('unknown')
            continue
        action, status, method, expected, reason, observed = row
        item = dict(result=dict(check_id=check_id, status=status, method=_policy(source), expected_snapshot=expected, sanitized_observed='', reason=reason, observed_at=observed, latch=''), phase=phase, step_id=step_id, context_hash=source.context['context_hash'], case_version_id=source.context['case_version_id'], source_hash=source.context['content_hash'], kind=check['kind'], action_id=action)
        try:
            _validate_result(connection, finish, source, item)
            if expected != check['expected'] or method != ('deterministic' if _policy(source)=='unconfigured' else _policy(source)):
                raise ValueError('stored check source differs')
        except ValueError:
            statuses.append('unknown')
        else:
            statuses.append(status)
    if 'violated' in statuses:
        return 'FAIL'
    return 'PASS' if statuses and all(status == 'satisfied' for status in statuses) else 'INCONCLUSIVE'
