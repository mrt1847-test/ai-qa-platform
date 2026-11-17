"""Immutable check scheduling metadata, never a verifier/model/approval grant."""
from dataclasses import dataclass
from uuid import UUID
from aiqa.domain.hashing import canonical_hash
from aiqa.recording.check_bindings import validate_bindings
from aiqa.replay.android_native_trace import COMPILER


@dataclass(frozen=True,slots=True)
class WorkerCheckBindingPin:
    manifest_id: str
    binding_hash: str
    boundaries: tuple[tuple[str,str],...]
    targets: tuple[tuple[str,str],...]


def resolve_claim_check_binding_pin(claim,*,case_context,native_source):
    if case_context is None:return None
    context=case_context.to_document()
    if 'check_bindings' not in context:return None
    try:
        raw=context['check_bindings']
        fields={'schema','recording_id','manifest_id','manifest_hash','source_manifest_id','source_manifest_hash',
            'input_case_version_id','source_content_hash','binding_hash','bindings'}
        if (type(raw) is not dict or set(raw)!=fields or raw['schema']!='recording-check-binding-pin-v1'
            or context['purpose'] not in {'trial','regression'} or case_context.target.kind!='android'
            or case_context.replay_compiler_ref!=COMPILER or native_source is None):raise ValueError()
        for key in ('recording_id','manifest_id','source_manifest_id','input_case_version_id'):
            if type(raw[key]) is not str or str(UUID(raw[key]))!=raw[key]:raise ValueError()
        for key in ('manifest_hash','source_manifest_hash','source_content_hash','binding_hash'):
            if type(raw[key]) is not str or not 1<=len(raw[key])<=256:raise ValueError()
        if raw['source_content_hash']!=case_context.content_hash:raise ValueError()
        if (native_source.manifest_id!=raw['manifest_id'] or native_source.manifest_hash!=raw['manifest_hash']
            or native_source.package_id!=context['replay_package_id'] or native_source.package_hash!=context['replay_package_hash']):raise ValueError()
        binding=validate_bindings(raw['bindings'],definition=context,
            settings={'target_kind':'android','android_package':case_context.target.android_package},
            action_ids=tuple(step.action_id for step in native_source.steps))
        binding_hash=canonical_hash(binding.to_document(),'canon-json-v1')
        if binding_hash!=raw['binding_hash']:raise ValueError()
        manifest_hash=canonical_hash({'kind':'package_rebuild','origin':'check-bindings-v1','prior_manifest_id':raw['source_manifest_id'],
            'prior_hash':raw['source_manifest_hash'],'recording_id':raw['recording_id'],'input_version':raw['input_case_version_id'],
            'content_hash':raw['source_content_hash'],'binding_hash':binding_hash},'canon-json-v1')
        if manifest_hash!=raw['manifest_hash']:raise ValueError()
        return WorkerCheckBindingPin(raw['manifest_id'],binding_hash,binding.boundaries,binding.targets)
    except (KeyError,ValueError,TypeError,AttributeError,UnicodeError,RecursionError):
        raise ValueError('replay check binding pin invalid') from None
