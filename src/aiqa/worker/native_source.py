"""Recompute the immutable native package witness before any capture or dispatch."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib,json
from uuid import UUID
from aiqa.replay.android_native_trace import NativeStep,compile_native_source,parse_native_trace,physical_plan
from aiqa.replay.android_plan import PlanRejected
from aiqa.store.models import RecordingManifest


@dataclass(frozen=True, slots=True)
class NativeSource:
    steps: tuple[NativeStep,...]
    package_id: str
    package_hash: str
    plan: str
    manifest_id: str
    manifest_hash: str


def resolve_claim_native_source(claim, *, case_context=None):
    snapshot=claim.get('snapshot')
    if type(snapshot) is not dict:raise ValueError('native snapshot missing')
    plan=snapshot.get('approved_plan','')
    from aiqa.replay.android_native_trace import COMPILER
    compiler=None if case_context is None else case_context.replay_compiler_ref
    if compiler==COMPILER and ('native_source' not in snapshot or not plan):
        raise ValueError('native compiler witness missing')
    if 'native_source' not in snapshot:
        if type(plan) is str and any(line.strip().startswith('physical:') for line in plan.splitlines()):
            raise ValueError('native source witness missing')
        return None
    try:
        if compiler is not None and compiler!=COMPILER:raise ValueError('native compiler scope differs')
        raw=snapshot['native_source']
        if (type(raw) is not dict or set(raw)!={'schema','project_id','package_id','package_hash','source_manifest_id','source_manifest_hash','mapping'}
            or raw['schema']!='android-native-source-v2' or snapshot.get('purpose') not in {'trial','regression'}
            or raw['project_id']!=claim['project_id'] or raw['package_id']!=snapshot.get('replay_package_id')
            or raw['package_hash']!=snapshot.get('replay_package_hash') or type(raw['source_manifest_hash']) is not str):
            raise ValueError('native source scope differs')
        if any(type(raw[key]) is not str for key in ('project_id','package_id','source_manifest_id')):
            raise ValueError('native UUID type invalid')
        project=UUID(raw['project_id']);UUID(raw['package_id']);manifest=UUID(raw['source_manifest_id'])
        steps=parse_native_trace(raw['mapping'])
        mapping=raw['mapping']
        model=RecordingManifest(project,UUID(int=0),UUID(int=0),manifest,1,'original',None,'',
            json.dumps([hashlib.sha256(mapping.encode('utf-8')).hexdigest()]),mapping,'complete','native-claim',raw['source_manifest_hash'])
        compiled=compile_native_source(model)
        expected=physical_plan(steps)
        if compiled.body_hash!=raw['package_hash'] or plan!=expected:
            raise ValueError('native source package/plan differs')
        return NativeSource(steps,raw['package_id'],raw['package_hash'],expected,raw['source_manifest_id'],raw['source_manifest_hash'])
    except (ValueError,TypeError,KeyError,PlanRejected,UnicodeError) as exc:
        raise ValueError('native source invalid') from exc
