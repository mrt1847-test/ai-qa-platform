"""Read frozen case goals/targets for an authenticated claim, never current permission."""
from __future__ import annotations

import json
from aiqa.domain.hashing import canonical_hash


def _checks(value):
    if type(value) is not list:
        raise ValueError('case checks are invalid')
    result = []
    for check in value:
        if type(check) is not dict or any(type(check.get(key)) is not str for key in ('id','kind','expected')):
            raise ValueError('case check is invalid')
        result.append({key:check[key] for key in ('id','kind','expected')})
    return result


def _secret_refs(value, project):
    if type(value) is not dict:
        raise ValueError('case secret references are invalid')
    result = {}
    for name, ref in value.items():
        if (type(name) is not str or type(ref) is not dict or str(ref.get('project_id')) != project
            or type(ref.get('ref_id')) is not str or type(ref.get('revision')) is not int or ref['revision'] < 1):
            raise ValueError('case secret reference is invalid')
        # Reference-only projection: never copy arbitrary nested source keys.
        result[name] = {key:ref[key] for key in ('project_id','ref_id','revision')}
    return result


def load_case_context(connection, receipt):
    """Exact REC/ITEM version join. An old receipt never follows the latest draft.

    No provider/key resolution occurs. The context hash identifies metadata; the
    authenticated management response and fresh checkpoint remain separate gates.
    """
    if receipt.snapshot.purpose not in {'recording','trial','regression'}:
        return None
    cursor = connection.execute("""SELECT j.purpose,j.recording_id,j.case_run_id,
        v.case_id,v.version_id,v.content_hash,v.verification_digest,v.definition_json,v.settings_json,v.replay_package_id
        FROM jobs j JOIN attempts a ON a.project_id=j.project_id AND a.job_id=j.job_id
        LEFT JOIN recordings r ON r.project_id=j.project_id AND r.recording_id=j.recording_id
        LEFT JOIN case_runs i ON i.project_id=j.project_id AND i.case_run_id=j.case_run_id
        JOIN case_versions v ON v.project_id=j.project_id
          AND v.version_id=CASE WHEN j.purpose='recording' THEN r.input_case_version_id ELSE i.case_version_id END
          AND v.case_id=CASE WHEN j.purpose='recording' THEN r.case_id ELSE i.case_id END
        WHERE j.project_id=? AND j.job_id=? AND a.attempt_id=? AND a.generation=?""",
        (str(receipt.project_id),str(receipt.job_id),str(receipt.attempt_id),receipt.generation))
    row = cursor.fetchone()
    if row is None:
        return None
    source = dict(zip((item[0] for item in cursor.description), row))
    if source['purpose'] != receipt.snapshot.purpose:
        raise ValueError('case context purpose mismatch')
    package = receipt.snapshot.replay_package_id
    if package is not None and source['replay_package_id'] != package:
        raise ValueError('case context package mismatch')
    definition, settings = (json.loads(source[name]) for name in ('definition_json','settings_json'))
    if type(definition) is not dict or type(settings) is not dict:
        raise ValueError('case source is invalid')
    steps = definition.get('steps', [])
    if type(steps) is not list:
        raise ValueError('case steps are invalid')
    prepared_steps = []
    for step in steps:
        if type(step) is not dict or type(step.get('id')) is not str or type(step.get('instruction')) is not str:
            raise ValueError('case step is invalid')
        prepared_steps.append({'id':step['id'],'instruction':step['instruction'],'expected':_checks(step.get('expected', []))})
    project = str(receipt.project_id)
    owner_kind = 'REC' if source['purpose']=='recording' else 'ITEM'
    context = {
        'schema':'case-context-v1','project_id':project,'job_id':str(receipt.job_id),
        'attempt_id':str(receipt.attempt_id),'generation':receipt.generation,'purpose':source['purpose'],
        'owner_kind':owner_kind,'owner_id':source['recording_id'] if owner_kind=='REC' else source['case_run_id'],
        'case_id':source['case_id'],'case_version_id':source['version_id'],
        'content_hash':source['content_hash'],'verification_digest':source['verification_digest'],
        'replay_package_id':package,'replay_package_hash':receipt.snapshot.replay_package_hash,
        'objective':definition.get('objective',''),'preconditions':definition.get('preconditions',[]),
        'steps':prepared_steps,'final_expected':_checks(definition.get('final_expected',[])),
        'path_policy':definition.get('path_policy',{'must_use':[],'forbidden':[]}),
        'secret_refs':_secret_refs(definition.get('secret_refs',{}),project),
        'target_secret_refs':_secret_refs(settings.get('secret_refs',{}),project),
        'target':{'kind':settings.get('target_kind'),'android_package':settings.get('android_package','')},
        # These are source settings, not a resolved binding revision/model grant.
        'verification':[{key:item.get(key) for key in ('method','binding_id','allow_unknown_supplement')}
            for item in settings.get('verifier_bindings',[]) if type(item) is dict],
    }
    context['context_hash'] = canonical_hash(context,'canon-json-v1')
    return context
