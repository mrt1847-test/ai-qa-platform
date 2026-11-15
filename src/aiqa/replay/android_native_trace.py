"""Versioned native actions in physical pixels, with no model-space reinterpretation."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json

from aiqa.replay.android_plan import PlanRejected, TypedAndroidAction, build_typed_android_action

SCHEMA = 'android-native-trace-v2'
COMPILER = 'android-native-plan-v2'
LOCK = 'android-native-lock-v2'
_FIELDS = frozenset(asdict(TypedAndroidAction('tap')))
_EVENT_FIELDS = frozenset(('kind','action','intent','target','action_id','line','geometry','native'))


@dataclass(frozen=True, slots=True)
class NativeStep:
    action_id: str
    line: int
    width: int
    height: int
    rotation: int
    action: TypedAndroidAction


def _action(raw, width, height, rotation):
    if type(raw) is not dict or set(raw)!=_FIELDS:
        raise PlanRejected('native action shape invalid')
    if type(raw['kind']) is not str or raw['kind'] not in {'tap','swipe','text','key'}:
        raise PlanRejected('native action unsupported')
    if any(value is not None and type(value) is not int for name,value in raw.items() if name in {'x','y','x2','y2','keycode'}):
        raise PlanRejected('native numeric field invalid')
    if type(raw['duration_ms']) is not int:
        raise PlanRejected('native duration invalid')
    fields={key:value for key,value in raw.items() if key!='kind'}
    action=build_typed_android_action(raw['kind'],width=width,height=height,rotation=rotation,**fields)
    if asdict(action)!=raw:
        raise PlanRejected('unused native field is not canonical')
    return action


def _describe(action):
    if action.kind=='tap':return 'tap',f'{action.x},{action.y}',[action.x,action.y,action.x+1,action.y+1]
    if action.kind=='swipe':return 'swipe',f'{action.x},{action.y}->{action.x2},{action.y2}',[min(action.x,action.x2),min(action.y,action.y2),max(action.x,action.x2)+1,max(action.y,action.y2)+1]
    if action.kind=='text':return 'type','literal',[0,0,1,1]
    if action.kind=='key':return ('back' if action.keycode==4 else 'key'),str(action.keycode),[0,0,1,1]
    raise PlanRejected('native action unsupported')


def native_event(action, observation, *, action_id, line):
    geo=observation.geometry
    if geo is None:raise PlanRejected('native geometry missing')
    action=_action(asdict(action),geo.physical_width,geo.physical_height,geo.rotation)
    name,target,bounds=_describe(action)
    event={'kind':'action','action':name,'intent':'open','target':target,'action_id':action_id,'line':line,
        'geometry':{'physical_width':geo.physical_width,'physical_height':geo.physical_height,
                    'rotation':geo.rotation,'content_bounds':bounds},'native':asdict(action)}
    _step(event,line)
    return event


def _step(item, index):
    if type(item) is not dict or set(item)!=_EVENT_FIELDS or item['kind']!='action':
        raise PlanRejected('native event shape invalid')
    identity=item['action_id']
    if (type(identity) is not str or not identity or len(identity.encode('utf-8'))>256
        or any(ord(c)<32 for c in identity) or type(item['line']) is not int or item['line']!=index):
        raise PlanRejected('native action identity invalid')
    geo=item['geometry']
    if type(geo) is not dict or set(geo)!={'physical_width','physical_height','rotation','content_bounds'}:
        raise PlanRejected('native geometry shape invalid')
    width,height,rotation=(geo[k] for k in ('physical_width','physical_height','rotation'))
    if (type(width) is not int or type(height) is not int or width<1 or height<1 or width*height>16_000_000
        or type(rotation) is not int or rotation not in {0,90,180,270}):
        raise PlanRejected('native geometry invalid')
    action=_action(item['native'],width,height,rotation)
    name,target,bounds=_describe(action)
    if (type(geo['content_bounds']) is not list or len(geo['content_bounds'])!=4
        or any(type(value) is not int for value in geo['content_bounds'])):
        raise PlanRejected('native bounds type invalid')
    if item['action']!=name or item['intent']!='open' or item['target']!=target or geo['content_bounds']!=bounds:
        raise PlanRejected('native display metadata differs')
    return NativeStep(identity,index,width,height,rotation,action)


def is_native_trace(raw):
    """Surviving v2-only markers forbid a fallback into the v1 compiler."""
    if type(raw) is not dict:return False
    if 'schema' in raw or 'native_action_count' in raw:return True
    events=raw.get('events',[])
    return type(events) is list and any(type(item) is dict and (
        'native' in item or type(item.get('geometry')) is dict and
        bool({'physical_width','physical_height'} & set(item['geometry']))) for item in events)


def _unique_object(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('duplicate native JSON field')
        result[key]=value
    return result


def parse_native_trace(mapping):
    try:
        if type(mapping) is not str or len(mapping.encode('utf-8'))>1_000_000:
            raise ValueError('trace size')
        raw=json.loads(mapping,object_pairs_hook=_unique_object)
        if (type(raw) is not dict or set(raw)!={'schema','native_action_count','events'} or raw['schema']!=SCHEMA
            or type(raw['native_action_count']) is not int or type(raw['events']) is not list
            or not 1<=len(raw['events'])<=50 or raw['native_action_count']!=len(raw['events'])):
            raise ValueError('trace count/schema')
        steps=tuple(_step(item,i) for i,item in enumerate(raw['events'],1))
        if len({step.action_id for step in steps})!=len(steps):raise ValueError('duplicate action')
        return steps
    except (ValueError,TypeError,KeyError,UnicodeError,RecursionError) as exc:
        raise PlanRejected('native trace invalid') from exc


def mobile_action(action):
    if action.kind=='tap':return f'click({action.x}, {action.y})'
    if action.kind=='swipe':return f'swipe({action.x}, {action.y}, {action.x2}, {action.y2}, {action.duration_ms})'
    if action.kind=='text':return f'type({action.text!r})'
    if action.kind=='key':return f'key({action.keycode})'
    raise PlanRejected('native action unsupported')


def physical_plan(steps):
    return '\n'.join('physical:'+mobile_action(step.action) for step in steps)


def compile_native_source(source):
    from hashlib import sha256
    from aiqa.contracts.replay import ReplayPackageBody, StepMapping
    from aiqa.replay.compiler import CompiledPackage, CompiledStep
    from aiqa.replay.packages import validate_package_body, _mapping_hash
    steps=parse_native_trace(source.action_mapping)
    plan=physical_plan(steps)
    mappings=tuple(StepMapping(step.action_id,step.action_id,step.line) for step in steps)
    body=ReplayPackageBody('replay-package-v1',source.manifest_id,source.body_hash,
        sha256(source.action_mapping.encode('utf-8')).hexdigest(),sha256(plan.encode('utf-8')).hexdigest(),
        'android',COMPILER,LOCK,_mapping_hash(mappings),mappings)
    checked=validate_package_body(body,source)
    if not checked.ready:raise PlanRejected('native package source differs')
    compiled=tuple(CompiledStep(step.action_id,step.action_id,step.line,'physical:'+mobile_action(step.action),
        step.action.kind,'') for step in steps)
    return CompiledPackage(body,checked.body_hash,(),compiled,())


def native_source_document(project_id,package_id,package_hash,source):
    compiled=compile_native_source(source)
    if compiled.body_hash!=package_hash:raise PlanRejected('native package hash differs')
    return {'schema':'android-native-source-v2','project_id':str(project_id),'package_id':str(package_id),
        'package_hash':package_hash,'source_manifest_id':str(source.manifest_id),
        'source_manifest_hash':source.body_hash,'mapping':source.action_mapping}
