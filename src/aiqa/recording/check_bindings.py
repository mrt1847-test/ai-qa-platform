"""Immutable annotations connecting logical checks to an existing native recording."""
from __future__ import annotations
from dataclasses import dataclass
import re


class BindingRejected(ValueError):pass
class BindingConflict(ValueError):pass
class BindingNotFound(ValueError):pass


def _id(value):
    if type(value) is not str or not value or len(value.encode('utf-8'))>256 or any(ord(c)<32 for c in value):
        raise BindingRejected('binding identity invalid')
    return value


@dataclass(frozen=True,slots=True)
class BindingDocument:
    boundaries: tuple[tuple[str,str],...]
    targets: tuple[tuple[str,str],...]

    def to_document(self):
        return {'step_boundaries':[{'step_id':s,'after_action_id':a} for s,a in self.boundaries],
            'check_targets':[{'check_id':c,'resource_id':r} for c,r in self.targets]}


def validate_bindings(raw, *, definition,settings,action_ids):
    try:
        if type(raw) is not dict or set(raw)!={'step_boundaries','check_targets'}:raise BindingRejected('binding shape invalid')
        if any(type(raw[k]) is not list or len(raw[k])>256 for k in raw):raise BindingRejected('binding count invalid')
        if type(definition) is not dict or type(settings) is not dict or settings.get('target_kind')!='android':raise BindingRejected('Android source required')
        package=settings.get('android_package')
        if type(package) is not str or len(package)>255 or re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+',package) is None:raise BindingRejected('source package invalid')
        source_steps=definition.get('steps',[]);source_final=definition.get('final_expected',[])
        if type(source_steps) is not list or type(source_final) is not list or len(source_steps)>256:raise BindingRejected('source shape invalid')
        step_ids=[];check_ids=[]
        def checks(values):
            if type(values) is not list:raise BindingRejected('source checks invalid')
            for item in values:
                if type(item) is not dict:raise BindingRejected('source check invalid')
                check_ids.append(_id(item.get('id')))
        for step in source_steps:
            if type(step) is not dict:raise BindingRejected('source step invalid')
            step_ids.append(_id(step.get('id')));checks(step.get('expected',[]))
        checks(source_final)
        if len(check_ids)>256 or len(set(check_ids))!=len(check_ids) or len(set(step_ids))!=len(step_ids):raise BindingRejected('source identities invalid')
        if type(action_ids) not in (tuple,list) or not 1<=len(action_ids)<=50 or len(set(action_ids))!=len(action_ids):raise BindingRejected('native source identities invalid')
        actions={_id(action):i for i,action in enumerate(action_ids)}
        boundaries={};targets={}
        for item in raw['step_boundaries']:
            if type(item) is not dict or set(item)!={'step_id','after_action_id'}:raise BindingRejected('boundary shape invalid')
            step,action=_id(item['step_id']),_id(item['after_action_id'])
            if step not in step_ids or action not in actions or step in boundaries:raise BindingRejected('boundary identity invalid')
            boundaries[step]=action
        ordered=tuple((step,boundaries[step]) for step in step_ids if step in boundaries)
        indices=[actions[action] for _,action in ordered]
        if indices!=sorted(indices):raise BindingRejected('logical source order must be preserved')
        for item in raw['check_targets']:
            if type(item) is not dict or set(item)!={'check_id','resource_id'}:raise BindingRejected('target shape invalid')
            check=_id(item['check_id']);resource=item['resource_id']
            if check not in check_ids or check in targets:raise BindingRejected('target check invalid')
            if type(resource) is not str or len(resource.encode('utf-8'))>512 or re.fullmatch(re.escape(package)+r':id/[A-Za-z_][A-Za-z0-9_]{0,127}',resource) is None:raise BindingRejected('target resource invalid')
            targets[check]=resource
        return BindingDocument(ordered,tuple((check,targets[check]) for check in check_ids if check in targets))
    except (TypeError,KeyError,UnicodeError,RecursionError) as exc:
        raise BindingRejected('binding source invalid') from None



def _source(connection,project,recording,manifest=None):
    import json
    from aiqa.replay.android_native_trace import parse_native_trace
    from aiqa.replay.android_plan import PlanRejected
    where='' if manifest is None else ' AND m.manifest_id=?'
    params=(str(project),str(recording)) if manifest is None else (str(project),str(recording),str(manifest))
    cursor=connection.execute("""SELECT m.manifest_id,m.body_hash,m.revision,m.action_mapping,m.source_artifact_hashes,
        m.evidence_completeness,r.completion_status,r.case_id,r.input_case_version_id,
        v.content_hash,v.definition_json,v.settings_json,p.ready
        FROM recordings r JOIN recording_manifests m ON m.project_id=r.project_id AND m.recording_id=r.recording_id
        JOIN case_versions v ON v.project_id=r.project_id AND v.case_id=r.case_id AND v.version_id=r.input_case_version_id
        LEFT JOIN replay_packages p ON p.project_id=m.project_id AND p.source_manifest_id=m.manifest_id
        WHERE r.project_id=? AND r.recording_id=?"""+where+' ORDER BY m.revision DESC LIMIT 1',params)
    row=cursor.fetchone()
    if row is None:raise BindingNotFound('recording source not found')
    source=dict(zip((c[0] for c in cursor.description),row))
    if source['completion_status']!='completed' or source['evidence_completeness']!='complete' or source['ready']!=1:
        raise BindingRejected('completed native source required')
    try:
        source['native_steps']=parse_native_trace(source['action_mapping'])
        source['definition']=json.loads(source['definition_json']);source['settings']=json.loads(source['settings_json'])
        validate_bindings({'step_boundaries':[],'check_targets':[]},definition=source['definition'],settings=source['settings'],action_ids=tuple(s.action_id for s in source['native_steps']))
    except (PlanRejected,ValueError,TypeError) as exc:raise BindingRejected('native source is not editable') from None
    return source


def _receipt(connection,project,recording,manifest,*,replayed):
    row=connection.execute("""SELECT b.source_manifest_id,b.binding_hash,m.case_id,r.produced_version_id,v.replay_package_id
        FROM recording_check_bindings b JOIN recording_manifests m ON m.project_id=b.project_id AND m.manifest_id=b.manifest_id
        JOIN materialization_receipts r ON r.project_id=m.project_id AND r.manifest_id=m.manifest_id
        JOIN case_versions v ON v.project_id=r.project_id AND v.version_id=r.produced_version_id
        WHERE b.project_id=? AND b.recording_id=? AND b.manifest_id=?""",(str(project),str(recording),str(manifest))).fetchone()
    if row is None or row[4] is None:raise BindingRejected('binding candidate missing')
    return dict(schema='recording-check-bindings-v1',recording_id=str(recording),manifest_id=str(manifest),
        source_manifest_id=str(row[0]),binding_hash=str(row[1]),case_id=str(row[2]),case_version_id=str(row[3]),
        replay_package_id=str(row[4]),replayed=replayed,approved=False)


def load_check_binding_context(connection,project,recording):
    import json
    source=_source(connection,project,recording)
    row=connection.execute('SELECT bindings_json FROM recording_check_bindings WHERE project_id=? AND recording_id=? AND manifest_id=?',
        (str(project),str(recording),source['manifest_id'])).fetchone()
    bindings={'step_boundaries':[],'check_targets':[]} if row is None else json.loads(row[0])
    def checks(items):return [{'id':c['id'],'kind':str(c.get('kind','')),'expected_preview':str(c.get('expected',''))[:120]} for c in items]
    return {'schema':'recording-check-binding-context-v1','editable':True,
        'source_manifest':{'id':source['manifest_id'],'hash':source['body_hash'],'revision':source['revision']},
        'input_case_version_id':source['input_case_version_id'],'source_content_hash':source['content_hash'],
        'actions':[{'id':step.action_id,'ordinal':step.line,'kind':step.action.kind} for step in source['native_steps']],
        'logical_steps':[{'id':step['id'],'instruction':str(step.get('instruction',''))[:160],'checks':checks(step.get('expected',[]))} for step in source['definition'].get('steps',[])],
        'final_checks':checks(source['definition'].get('final_expected',[])),'bindings':bindings,
        'android_package':source['settings']['android_package']}


def save_check_bindings(connection,actor,project,recording,*,expected_manifest_id,expected_manifest_hash,bindings,request_key):
    """Caller holds a writer transaction; a savepoint keeps a failed candidate atomic."""
    if not getattr(connection,'in_transaction',False):raise BindingRejected('transaction required')
    connection.execute('SAVEPOINT recording_binding_save')
    try:
        result=_save(connection,actor,project,recording,expected_manifest_id,expected_manifest_hash,bindings,request_key)
    except Exception:
        connection.execute('ROLLBACK TO SAVEPOINT recording_binding_save')
        connection.execute('RELEASE SAVEPOINT recording_binding_save')
        raise
    connection.execute('RELEASE SAVEPOINT recording_binding_save')
    return result


def _save(connection,actor,project,recording,expected_manifest_id,expected_manifest_hash,bindings,request_key):
    import json
    from datetime import datetime,timezone
    from uuid import UUID,uuid4
    from aiqa.domain.hashing import canonical_hash
    from aiqa.recording.service import materialize_android_recording
    try:
        project=UUID(str(project));recording=UUID(str(recording))
        if type(expected_manifest_id) not in (str,UUID):raise ValueError()
        expected_manifest_id=UUID(str(expected_manifest_id))
    except (ValueError,TypeError):raise BindingRejected('binding owner identity invalid') from None
    if actor.project_scope not in {None,project}:raise BindingNotFound('recording source not found')
    if actor.project_scope is None and not actor.is_local_owner:raise BindingNotFound('recording source not found')
    if type(request_key) is not str or not request_key.strip() or len(request_key.encode('utf-8'))>128 or any(ord(c)<32 for c in request_key):raise BindingRejected('binding key invalid')
    source=_source(connection,project,recording,expected_manifest_id)
    if source['body_hash']!=expected_manifest_hash:raise BindingConflict('recording source changed')
    document=validate_bindings(bindings,definition=source['definition'],settings=source['settings'],action_ids=tuple(s.action_id for s in source['native_steps'])).to_document()
    binding_hash=canonical_hash(document,'canon-json-v1')
    body_hash=canonical_hash({'source_manifest_id':str(expected_manifest_id),'source_manifest_hash':source['body_hash'],
        'input_version':source['input_case_version_id'],'content_hash':source['content_hash'],
        'binding_hash':binding_hash,'actor_id':str(actor.actor_id)},'canon-json-v1')
    existing=connection.execute('SELECT manifest_id,body_hash FROM recording_check_bindings WHERE project_id=? AND recording_id=? AND request_key=?',
        (str(project),str(recording),request_key)).fetchone()
    if existing is not None:
        if str(existing[1])!=body_hash:raise BindingConflict('binding request key body changed')
        return _receipt(connection,project,recording,existing[0],replayed=True)
    latest=connection.execute('SELECT manifest_id FROM recording_manifests WHERE project_id=? AND recording_id=? ORDER BY revision DESC LIMIT 1',
        (str(project),str(recording))).fetchone()
    if latest is None or latest[0]!=str(expected_manifest_id):raise BindingConflict('recording source changed')
    manifest=uuid4()
    manifest_hash=canonical_hash({'kind':'package_rebuild','origin':'check-bindings-v1','prior_manifest_id':str(expected_manifest_id),
        'prior_hash':source['body_hash'],'recording_id':str(recording),'input_version':source['input_case_version_id'],
        'content_hash':source['content_hash'],'binding_hash':binding_hash},'canon-json-v1')
    key='check-bindings:'+str(actor.actor_id)+':'+request_key
    connection.execute("""INSERT INTO recording_manifests(project_id,case_id,recording_id,manifest_id,revision,kind,prior_manifest_id,
        input_version_hash,source_artifact_hashes,action_mapping,evidence_completeness,request_key,body_hash)
        VALUES(?,?,?,?,?,'package_rebuild',?,?,?,?,?,?,?)""",
        (str(project),source['case_id'],str(recording),str(manifest),int(source['revision'])+1,str(expected_manifest_id),
         source['content_hash'],source['source_artifact_hashes'],source['action_mapping'],'complete',key,manifest_hash))
    connection.execute("""INSERT INTO recording_check_bindings(project_id,recording_id,manifest_id,source_manifest_id,source_manifest_hash,
        input_case_version_id,bindings_json,binding_hash,body_hash,request_key,actor_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        (str(project),str(recording),str(manifest),str(expected_manifest_id),source['body_hash'],source['input_case_version_id'],
         json.dumps(document,sort_keys=True,separators=(',',':')),binding_hash,body_hash,request_key,str(actor.actor_id),datetime.now(timezone.utc).isoformat()))
    materialize_android_recording(connection,actor,project,manifest)
    return _receipt(connection,project,recording,manifest,replayed=False)
