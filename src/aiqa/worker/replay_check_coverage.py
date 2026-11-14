"""Preserve required pinned checks until their approved runtime bindings exist.

This is coverage accounting, not a validator or a model permission. A PNG,
source check id, or gesture index cannot supply a missing logical/target binding.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from datetime import datetime

from aiqa.contracts.checks import CheckResult
from aiqa.worker.case_context import WorkerCaseContext


@dataclass(frozen=True, slots=True)
class RequiredCheckCoverage:
    result: CheckResult
    phase: str
    step_id: str | None
    context_hash: str
    case_version_id: str
    source_hash: str
    kind: str


def validate_observed_at(value: str) -> None:
    if type(value) is not str or len(value) > 64 or datetime.fromisoformat(value).tzinfo is None:
        raise ValueError('check observation time must be aware')


def validate_coverage_source(pin: WorkerCaseContext) -> None:
    if not isinstance(pin, WorkerCaseContext):
        raise ValueError('pinned case context is required')
    if len(pin.steps)>256 or sum(len(step.expected) for step in pin.steps)+len(pin.final_expected)>256:
        raise ValueError('check coverage count limit')
    labels=[pin.case_version_id,pin.content_hash,pin.context_hash]
    for step in pin.steps:
        labels.append(step.id)
        labels.extend(value for check in step.expected for value in (check.id,check.kind))
    labels.extend(value for check in pin.final_expected for value in (check.id,check.kind))
    if any(type(value) is not str or len(value.encode('utf-8'))>256 for value in labels):
        raise ValueError('check coverage identity limit')


def coverage_log_document(rows: tuple[RequiredCheckCoverage, ...]) -> list[dict]:
    """Keep source values private; the pinned version remains the original record."""
    if len(rows)>256:
        raise ValueError('check coverage count limit')
    result=[]
    for row in rows:
        item=asdict(row)
        expected=item['result']['expected_snapshot']
        item['result']['expected_hash']='sha256:'+hashlib.sha256(expected.encode('utf-8')).hexdigest()
        item['result']['expected_snapshot']='[source expectation omitted]'
        item['result']['sanitized_observed']=''
        result.append(item)
    return result


def required_check_coverage(
    pin: WorkerCaseContext, *, action_index: int, total_actions: int, observed_at: str
) -> tuple[RequiredCheckCoverage, ...]:
    validate_coverage_source(pin)
    if (type(action_index) is not int or type(total_actions) is not int
            or not 1 <= action_index <= total_actions <= 50):
        raise ValueError('invalid check phase')
    validate_observed_at(observed_at)
    if action_index != total_actions:
        return ()
    policies = pin.to_document()['verification']
    method = policies[0]['method'] if len(policies) == 1 else 'unconfigured'
    if not policies:
        final_reason = 'verifier_policy_missing'
    elif len(policies) != 1:
        final_reason = 'verifier_policy_ambiguous'
    elif method == 'deterministic':
        final_reason = 'deterministic_subject_missing'
    else:
        final_reason = 'verifier_not_connected'
    rows = []
    for step in pin.steps:
        for check in step.expected:
            rows.append(RequiredCheckCoverage(
                CheckResult(check.id, 'unknown', method, check.expected, '',
                            'logical_step_mapping_missing', observed_at),
                'step', step.id, pin.context_hash, pin.case_version_id, pin.content_hash, check.kind))
    for check in pin.final_expected:
        rows.append(RequiredCheckCoverage(
            CheckResult(check.id, 'unknown', method, check.expected, '', final_reason, observed_at),
            'final', None, pin.context_hash, pin.case_version_id, pin.content_hash, check.kind))
    return tuple(rows)
