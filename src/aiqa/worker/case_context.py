"""Detached claim metadata. No DB, credential lookup, model call or device I/O."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from uuid import UUID

from aiqa.contracts.cases import CheckSpec
from aiqa.domain.hashing import canonical_hash


class CaseContextRejected(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CaseTarget:
    kind: str
    android_package: str


@dataclass(frozen=True, slots=True)
class CaseStep:
    id: str
    instruction: str
    expected: tuple[CheckSpec, ...]


@dataclass(frozen=True, slots=True)
class WorkerCaseContext:
    case_version_id: str
    content_hash: str
    objective: str
    target: CaseTarget
    steps: tuple[CaseStep, ...]
    final_expected: tuple[CheckSpec, ...]
    context_hash: str
    _serialized: str = field(repr=False)

    def to_document(self) -> dict:
        """Callers may edit their own copy; the detached pin stays immutable."""
        return json.loads(self._serialized)


_FIELDS = frozenset(('schema','project_id','job_id','attempt_id','generation','purpose',
    'owner_kind','owner_id','case_id','case_version_id','content_hash','verification_digest',
    'replay_package_id','replay_package_hash','objective','preconditions','steps','final_expected',
    'path_policy','secret_refs','target_secret_refs','target','verification','context_hash'))
_PACKAGE = re.compile(r'[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+')


def _text(value, *, empty=False):
    if type(value) is not str or (not empty and not value):
        raise CaseContextRejected('case context text invalid')
    return value


def _uuid(value):
    return str(UUID(_text(value)))


def _checks(raw, seen):
    if type(raw) is not list:
        raise CaseContextRejected('case checks invalid')
    result = []
    for item in raw:
        if type(item) is not dict or set(item)!={'id','kind','expected'}:
            raise CaseContextRejected('case check shape invalid')
        check = CheckSpec(_text(item['id']),_text(item['kind']),_text(item['expected'],empty=True))
        if check.id in seen:
            raise CaseContextRejected('case check identity duplicated')
        seen.add(check.id);result.append(check)
    return tuple(result)


def _references(raw, project):
    if type(raw) is not dict:
        raise CaseContextRejected('secret references invalid')
    for name, ref in raw.items():
        _text(name)
        if (type(ref) is not dict or set(ref)!={'project_id','ref_id','revision'}
            or ref['project_id']!=project or type(ref['revision']) is not int or ref['revision']<1):
            raise CaseContextRejected('secret reference invalid')
        _text(ref['ref_id'])


def resolve_claim_case_context(claim, *, required=False):
    """Validate supplied metadata always; only explicit development calls may omit it.

    The HTTPS response authenticates its source. context_hash identifies the body;
    it is not a current lease, approval or resolved verifier model permission.
    """
    try:
        snapshot = claim['snapshot']
        if type(snapshot) is not dict or type(required) is not bool:
            raise CaseContextRejected('case context input invalid')
        if 'case_context' not in snapshot:
            if required:
                raise CaseContextRejected('case context missing')
            return None
        raw = snapshot['case_context']
        if type(raw) is not dict or set(raw)!=_FIELDS or raw['schema']!='case-context-v1':
            raise CaseContextRejected('case context schema invalid')
        unsigned = {key:value for key,value in raw.items() if key!='context_hash'}
        if raw['context_hash']!=canonical_hash(unsigned,'canon-json-v1'):
            raise CaseContextRejected('case context hash invalid')
        for key in ('project_id','job_id','attempt_id'):
            if _uuid(raw[key])!=_uuid(claim[key]) or raw[key]!=claim[key]:
                raise CaseContextRejected('case context scope invalid')
        if (type(raw['generation']) is not int or type(claim['generation']) is not int
            or raw['generation']<1 or raw['generation']!=claim['generation']
            or raw['purpose']!=snapshot.get('purpose') or raw['purpose'] not in {'recording','trial','regression'}):
            raise CaseContextRejected('case context generation or purpose invalid')
        expected_owner = 'REC' if raw['purpose']=='recording' else 'ITEM'
        if raw['owner_kind']!=expected_owner:
            raise CaseContextRejected('case context owner invalid')
        for key in ('owner_id','case_id','case_version_id'):_uuid(raw[key])
        _text(raw['content_hash']);_text(raw['verification_digest']);_text(raw['objective'],empty=True)
        if raw['purpose']=='recording':
            if raw['replay_package_id'] is not None or raw['replay_package_hash'] is not None:
                raise CaseContextRejected('recording package context invalid')
            intent = snapshot.get('intent')
            if type(intent) is dict and (intent.get('case_version_id')!=raw['case_version_id'] or intent.get('content_hash')!=raw['content_hash']):
                raise CaseContextRejected('recording context version invalid')
            limits = snapshot.get('limits',{})
            if type(limits) is dict:
                for source,target in (('input_case_version_id','case_version_id'),('input_version_hash','content_hash')):
                    if source in limits and limits[source]!=raw[target]:
                        raise CaseContextRejected('recording context pin invalid')
        else:
            if (raw['replay_package_id']!=snapshot.get('replay_package_id')
                or raw['replay_package_hash']!=snapshot.get('replay_package_hash')):
                raise CaseContextRejected('replay context package invalid')
            _uuid(raw['replay_package_id']);_text(raw['replay_package_hash'])
            limits = snapshot.get('limits',{})
            execution = limits.get('execution_snapshot',{}) if type(limits) is dict else {}
            if type(execution) is dict and 'case_version_id' in execution and execution['case_version_id']!=raw['case_version_id']:
                raise CaseContextRejected('replay context version invalid')
        target = raw['target']
        if type(target) is not dict or set(target)!={'kind','android_package'} or target['kind'] not in {'web','android'}:
            raise CaseContextRejected('case target invalid')
        package = _text(target['android_package'],empty=True)
        if target['kind']=='android' and (len(package)>255 or _PACKAGE.fullmatch(package) is None):
            raise CaseContextRejected('case package invalid')
        if type(raw['preconditions']) is not list or any(type(value) is not str for value in raw['preconditions']):
            raise CaseContextRejected('case preconditions invalid')
        path = raw['path_policy']
        if (type(path) is not dict or set(path)!={'must_use','forbidden'}
            or any(type(values) is not list or any(type(value) is not str for value in values) for values in path.values())):
            raise CaseContextRejected('case path invalid')
        _references(raw['secret_refs'],raw['project_id']);_references(raw['target_secret_refs'],raw['project_id'])
        if type(raw['verification']) is not list:
            raise CaseContextRejected('verifier settings invalid')
        for verifier in raw['verification']:
            if (type(verifier) is not dict or set(verifier)!={'method','binding_id','allow_unknown_supplement'}
                or verifier['method'] not in {'deterministic','ai_visual','deterministic_then_ai_unknown'}
                or type(verifier['binding_id']) is not str or type(verifier['allow_unknown_supplement']) is not bool
                or verifier['method']!='deterministic' and not verifier['binding_id']):
                raise CaseContextRejected('verifier source settings invalid')
        if type(raw['steps']) is not list:
            raise CaseContextRejected('case steps invalid')
        seen_checks,seen_steps,steps = set(),set(),[]
        for step in raw['steps']:
            if type(step) is not dict or set(step)!={'id','instruction','expected'}:
                raise CaseContextRejected('case step invalid')
            step_id = _text(step['id'])
            if step_id in seen_steps:raise CaseContextRejected('case step duplicated')
            seen_steps.add(step_id)
            steps.append(CaseStep(step_id,_text(step['instruction'],empty=True),_checks(step['expected'],seen_checks)))
        final = _checks(raw['final_expected'],seen_checks)
        return WorkerCaseContext(raw['case_version_id'],raw['content_hash'],raw['objective'],
            CaseTarget(target['kind'],package),tuple(steps),final,raw['context_hash'],
            json.dumps(raw,sort_keys=True,separators=(',',':'),allow_nan=False))
    except (KeyError,TypeError,ValueError,OverflowError) as exc:
        if isinstance(exc,CaseContextRejected):raise
        raise CaseContextRejected('case context invalid') from exc
