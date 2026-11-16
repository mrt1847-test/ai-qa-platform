"""Readonly command details from an original saved action and its bound frame metadata."""
from dataclasses import asdict,dataclass,replace
from datetime import datetime
import json
from aiqa.adapters.mobile_agent_upstream import load_protocol,render_reply,upstream_action
from aiqa.contracts.mobile_agent_engine import require_mobile_agent_engine
from aiqa.contracts.model_observations import parse_geometry
from aiqa.domain.hashing import canonical_hash
from aiqa.replay.android_plan import TypedAndroidAction,build_typed_android_action,PlanRejected
from aiqa.recording.timeline_display import describe_recorded_action,stored_log_state,load_known_recorded_log


@dataclass(frozen=True,slots=True)
class ActionEvidenceDetail:
    label:str
    state_label:str
    command_label:str='기록 내용'
    command_summary:str='명령 정보를 확인할 수 없습니다.'
    coordinates:str=''
    swipe_path:str=''
    duration:str=''
    geometry:str=''
    captured_at:str=''
    notice:str='자세한 내용은 원문 로그에서 확인하세요.'


def _bound_frame(connection,project,selection,action_id,doc,roles,before):
    source=roles.get('before')
    if (selection.owner_kind!='REC' or source is None or before.state!='stored'
        or doc.get('before_image_hash')!=source[4]):return None
    row=connection.execute("""SELECT o.image_hash,o.geometry_hash,o.geometry_json,o.captured_at,j.limits,o.worker_id,o.policy_ref,a.generation
        FROM model_observations o JOIN attempts a ON a.project_id=o.project_id AND a.attempt_id=o.attempt_id
        JOIN jobs j ON j.project_id=a.project_id AND j.job_id=a.job_id
        JOIN artifact_objects f ON f.project_id=o.project_id AND f.artifact_id=o.artifact_id
        WHERE o.project_id=? AND o.attempt_id=? AND o.call_id=? AND o.artifact_id=?
          AND j.purpose='recording' AND j.recording_id=? AND f.owner_kind='REC' AND f.owner_id=j.recording_id
          AND f.attempt_id=o.attempt_id AND f.action_id=? AND f.role='before' AND f.job_id=j.job_id
          AND f.generation=a.generation AND f.status='ready' AND f.acked=1""",
        (str(project),selection.attempt_id,doc.get('call_id'),source[2],selection.owner_id,action_id)).fetchone()
    if row is None:return None
    try:
        if row[0]!=source[4] or len(row[2])>8192 or len(row[4])>65536:return None
        require_mobile_agent_engine(json.loads(row[4]).get('authoring_engine'))
        geometry=parse_geometry(json.loads(row[2]))
        if canonical_hash(asdict(geometry),'canon-json-v1')!=row[1] or datetime.fromisoformat(row[3]).tzinfo is None:return None
        return geometry,row[3],row[5],row[6],row[7]
    except (ValueError,TypeError,KeyError,AttributeError,RecursionError):return None


def _matches_saved_response(connection,project,selection,doc,bound):
    geometry,_,worker,policy,generation=bound
    row=connection.execute("""SELECT response_json FROM model_request_receipts
        WHERE project_id=? AND attempt_id=? AND call_id=? AND worker_id=? AND policy_ref=?
          AND state='completed' AND charged=1 AND status_code=200""",
        (str(project),selection.attempt_id,doc['call_id'],worker,policy)).fetchone()
    if row is None:return False
    try:
        if type(row[0]) is not str or len(row[0])>1048576:return False
        response=json.loads(row[0])
        if (type(response) is not dict or response.get('allowed') is not True
            or response.get('action_allowed') is not True or response.get('provider_dispatched') is not True
            or response.get('call_id')!=doc['call_id'] or response.get('item_id')!=selection.attempt_id
            or type(response.get('generation')) is not int or response['generation']!=generation
            or response.get('actual_model')!='gpt-6-luna' or response.get('purpose')!='recording'
            or response.get('role')!='authoring' or response.get('image_hash')!=doc['before_image_hash']):return False
        text=render_reply(response['content'])
        if text.count('<tool_call>')!=1 or text.count('</tool_call>')!=1:return False
        protocol=load_protocol()
        native=upstream_action(protocol,protocol.parse_action(text),geometry)
        expected=None if native is None or native.kind=='finish' else asdict(native)
        return json.dumps(expected,sort_keys=True)==json.dumps(doc['native'],sort_keys=True)
    except (ValueError,TypeError,KeyError,AttributeError,RecursionError,OSError,ImportError,PlanRejected):return False


def describe_action_evidence(connection,project,selection,*,action_id,action_seq,dispatch_state,roles,before,after,log_text,check_status=''):
    display=describe_recorded_action(action_id=action_id,action_seq=action_seq,dispatch_state=dispatch_state,
        log_text=log_text,log_state=stored_log_state(log_text),before_state=before.state,after_state=after.state,check_status=check_status)
    generic=describe_recorded_action(action_id=action_id,action_seq=action_seq,dispatch_state=dispatch_state,
        log_text='',log_state=stored_log_state(log_text),before_state=before.state,after_state=after.state,check_status=check_status)
    result=ActionEvidenceDetail(generic.label,generic.state_label)
    doc=load_known_recorded_log(action_id,dispatch_state,log_text,stored_log_state(log_text))
    if doc is None or selection.owner_kind!='REC':return result
    if doc.get('operation')=='app_prepare' and roles.get('log') is not None:
        return replace(result,label=display.label,state_label=display.state_label,command_label='준비 기록',command_summary='선택 앱 실행 준비',notice='')
    source=roles.get('before')
    if source is None or doc.get('before_image_hash')!=source[4]:
        return replace(result,state_label='명령 근거 확인 필요',notice='동작 전 화면과 명령의 근거를 확인해야 합니다.')
    if doc.get('schema')=='mobile-agent-step-v1' and roles.get('after') is not None and doc.get('after_image_hash')!=roles['after'][4]:
        return replace(result,state_label='명령 근거 확인 필요',notice='동작 후 화면과 명령의 근거를 확인해야 합니다.')
    bound=_bound_frame(connection,project,selection,action_id,doc,roles,before)
    if bound is None:return replace(result,state_label='명령 근거 확인 필요',notice='명령과 연결된 화면 해상도를 확인할 수 없습니다.')
    geometry,captured=bound[:2]
    result=replace(result,geometry=f'{geometry.physical_width} × {geometry.physical_height}px · 회전 {geometry.rotation}°',captured_at=captured)
    if doc.get('schema')=='mobile-agent-authoring-failure-v1':
        return replace(result,label=display.label,state_label=display.state_label,command_label='동작 준비 기록',command_summary='생성된 동작 없음',notice='')
    if not _matches_saved_response(connection,project,selection,doc,bound):
        return replace(result,label='동작 '+str(action_seq),state_label='명령 근거 확인 필요',notice='저장된 명령과 원본 응답의 일치를 확인할 수 없습니다.')
    result=replace(result,label=display.label,state_label=display.state_label)
    native=doc.get('native')
    if native is None:return replace(result,command_label='제어 기록',command_summary='기기 명령 없는 제어 단계',notice='')
    try:
        if type(native) is not dict or set(native)!=set(asdict(TypedAndroidAction('tap'))):raise ValueError('native shape')
        args=dict(native);kind=args.pop('kind')
        checked=build_typed_android_action(kind,width=geometry.physical_width,height=geometry.physical_height,rotation=geometry.rotation,**args)
        if json.dumps(asdict(checked),sort_keys=True)!=json.dumps(native,sort_keys=True):raise ValueError('native values')
    except (ValueError,TypeError,KeyError,PlanRejected):
        return replace(result,state_label='명령 근거 확인 필요',notice='저장된 명령 값을 확인할 수 없습니다.')
    label='전달 명령' if doc['native_calls']==1 else '요청 명령'
    if checked.kind=='tap':return replace(result,command_label=label,command_summary='탭',coordinates=f'({checked.x}, {checked.y})',notice='')
    if checked.kind=='swipe':
        path=f'시작 ({checked.x}, {checked.y}) → 끝 ({checked.x2}, {checked.y2})'
        return replace(result,command_label=label,command_summary='스와이프',swipe_path=path,duration=f'{checked.duration_ms}ms',notice='')
    if checked.kind=='text':return replace(result,command_label=label,command_summary=f'텍스트 입력 · {len(checked.text)}자',notice='입력 내용은 원문 로그에서 확인할 수 있습니다.')
    if checked.kind=='key':return replace(result,command_label=label,command_summary=f"{'뒤로가기 · ' if checked.keycode==4 else ''}키 코드 {checked.keycode}",notice='')
    return result
