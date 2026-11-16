"""Read-only, bounded labels from stored evidence; labels never authorize an action."""
from dataclasses import dataclass
import json
from uuid import UUID


@dataclass(frozen=True,slots=True)
class TimelineDisplay:
    label:str
    state_label:str
    before_label:str
    after_label:str
    log_label:str
    check_label:str


_STATES={'planned':'동작 준비','lookup_failed':'전달 전 중단','dispatch_started':'기기 전달 중',
         'acknowledged':'기기 전달 확인','observed':'관찰 기록','unknown':'전달 결과 확인 불가'}
_SHOTS={'stored':'저장됨','missing':'미수신','corrupt':'손상됨','expired':'보관 만료','delayed':'늦게 수신'}
_CHECKS={'satisfied':'조건 충족','violated':'조건 불일치','unknown':'확인 필요','unavailable':'확인 불가','error':'검증 오류'}


def _unique(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('duplicate display log field')
        result[key]=value
    return result


def _known(action_id,dispatch,raw):
    doc=json.loads(raw,object_pairs_hook=_unique,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('nonfinite log')))
    if type(doc) is not dict:return None
    if action_id.startswith('prepare-'):
        if (doc.get('operation')=='app_prepare' and type(doc.get('attempt_id')) is str
            and action_id=='prepare-'+str(UUID(doc['attempt_id'])) and doc.get('state')==dispatch
            and type(doc.get('model_calls')) is int and doc['model_calls']==0):return ('앱 준비',None)
        return None
    if not action_id.startswith('ma-') or action_id!='ma-'+str(UUID(action_id[3:])):return None
    common={'schema','call_id','action_id','state','native_calls','native','before_image_hash'}
    schema=doc.get('schema')
    fields={'mobile-agent-step-v1':common|{'after_image_hash'},'mobile-agent-failure-v1':common|{'reason'},
            'mobile-agent-authoring-failure-v1':common|{'stage','outcome','reason'}}
    if type(schema) is not str or schema not in fields or set(doc)!=fields[schema]:return None
    if doc['call_id']!=action_id[3:] or doc['action_id']!=action_id:return None
    state=doc['state']
    if type(state) is not str or {'not_sent':'lookup_failed'}.get(state,state)!=dispatch:return None
    if schema=='mobile-agent-authoring-failure-v1':
        if (state=='planned' and doc['stage']=='authoring' and doc['outcome']=='no_accepted_action' and doc['reason']=='authoring_unavailable'
            and doc['native'] is None and type(doc['native_calls']) is int and doc['native_calls']==0):
            return ('AI 동작 준비','동작 생성 중단')
        return None
    native=doc['native']
    if schema=='mobile-agent-step-v1' and state!='observed':return None
    if schema=='mobile-agent-failure-v1' and state not in {'unknown','acknowledged','not_sent'}:return None
    calls=int(native is not None) if state=='observed' else int(state=='acknowledged')
    if type(doc['native_calls']) is not int or doc['native_calls']!=calls:return None
    if native is None:
        if schema=='mobile-agent-step-v1':return ('제어 단계',None)
        if state=='not_sent' and doc.get('reason')=='control_unobserved':return ('제어 단계','화면 확인 중단')
        return None
    if type(native) is not dict or type(native.get('kind')) is not str:return None
    label={'tap':'탭','text':'텍스트 입력','swipe':'스와이프','key':'키 입력'}.get(native['kind'])
    if label is None:return None
    if native['kind']=='key' and type(native.get('keycode')) is int and native['keycode']==4:label='뒤로가기'
    suffix={'observed':' 기록','unknown':' 요청','acknowledged':' 전달','not_sent':' 준비'}.get(state,'')
    return (label+suffix,None)


def describe_recorded_action(*,action_id,action_seq,dispatch_state,log_text,log_state,before_state,after_state,check_status=''):
    label='동작 '+str(action_seq);state=_STATES.get(dispatch_state,'상태 확인 필요')
    if dispatch_state=='observed' and before_state==after_state==log_state=='stored':state='화면·로그 수신'
    if log_state=='stored' and type(log_text) is str and len(log_text)<=16384 and len(log_text.encode('utf-8'))<=16384:
        try:
            known=_known(action_id,dispatch_state,log_text)
            if known is not None:label=known[0];state=known[1] or state
        except (ValueError,TypeError,KeyError,AttributeError,RecursionError):pass
    log_label=_SHOTS.get(log_state,'확인 필요')
    if log_text=='파일 내용이 보관 hash와 다릅니다.':log_label='손상됨'
    elif log_text=='보관 기한이 지났습니다.':log_label='보관 만료'
    elif log_text=='캡처가 늦었습니다.':log_label='늦게 수신'
    return TimelineDisplay(label,state,_SHOTS.get(before_state,'확인 필요'),_SHOTS.get(after_state,'확인 필요'),log_label,
        _CHECKS.get(check_status,'확인 필요') if check_status else '')
