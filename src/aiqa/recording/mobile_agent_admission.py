"""Server-owned authoring report authority and side-effect-free original admission."""
from dataclasses import dataclass
from datetime import datetime,timezone
import json
from urllib.parse import urlsplit
from aiqa.contracts.mobile_agent_engine import mobile_agent_engine_ref,require_mobile_agent_engine,is_openai_endpoint
from aiqa.worker.presence import get_presence


class MobileAgentAdmissionRejected(ValueError):
    def __init__(self,message,*,kind='engine'):
        super().__init__(message);self.kind=kind


@dataclass(frozen=True,slots=True)
class AuthoringRuntime:
    provider:object
    price_mode:str


def runtime_for_app(app):
    return AuthoringRuntime(getattr(getattr(app.state,'model_gateway',None),'provider',None),getattr(app.state.settings,'model_price_mode','strict'))


def _credential(connection,token_id,project,worker,now):
    row=connection.execute("""SELECT e.project_id,e.worker_id,t.purpose,t.expires_at FROM worker_tokens t
        JOIN worker_enrollments e USING(enrollment_id) WHERE t.token_id=?""",(token_id,)).fetchone()
    if row is None or row[:3]!=(str(project),worker,'recording'):return False
    try:return row[3] is None or datetime.fromisoformat(row[3])>now
    except (ValueError,TypeError):return False


def authenticated_authoring_permissions(connection,worker,raw,*,target_kind):
    """Only server-validated recording credentials can stamp report authority."""
    try:body=json.loads(raw)
    except (ValueError,TypeError):return raw
    if type(body) is not dict:return raw
    body.pop('authoring_report',None)
    names=('authoring_mode','authoring_engine','authoring_engine_boot_id','authoring_engine_session_id')
    claimed={name:body.pop(name) for name in names if name in body}
    if target_kind!='android' or worker.permitted_purposes!=('recording',) or len(worker.permitted_projects)!=1:
        return json.dumps(body,sort_keys=True)
    project=worker.permitted_projects[0];now=datetime.now(timezone.utc)
    presence=get_presence(connection,worker.worker_id,now,project_id=project)
    mode=claimed.get('authoring_mode')
    if (presence.state=='online' and claimed.get('authoring_engine_boot_id')==presence.boot_id
        and claimed.get('authoring_engine_session_id')==presence.session_id
        and _credential(connection,worker.token_id,project,worker.worker_id,now)):
        try:
            if mode=='original':require_mobile_agent_engine(claimed.get('authoring_engine'))
            elif mode!='fixture' or 'authoring_engine' in claimed:raise ValueError()
        except (ValueError,TypeError):pass
        else:
            body.update(claimed)
            body['authoring_report']={'project_id':str(project),'worker_id':worker.worker_id,'purpose':'recording',
                'token_id':worker.token_id,'boot_id':presence.boot_id,'session_id':presence.session_id}
    return json.dumps(body,sort_keys=True)


def require_recording_report(connection,project,resource_id,*,worker_id=None,mode=None):
    row=connection.execute("""SELECT k.worker_id,i.permissions,i.state FROM physical_resource_keys k
        JOIN resource_aliases a USING(physical_key_id) JOIN resource_inventory i USING(physical_key_id)
        WHERE a.project_id=? AND a.physical_key_id=? AND a.target_kind='android'""",(str(project),resource_id)).fetchone()
    try:
        if row is None or row[2]!='ready' or worker_id is not None and row[0]!=worker_id:raise ValueError()
        permissions=json.loads(row[1]);report=permissions['authoring_report'];now=datetime.now(timezone.utc)
        presence=get_presence(connection,row[0],now,project_id=project)
        expected={'project_id':str(project),'worker_id':row[0],'purpose':'recording',
            'boot_id':presence.boot_id,'session_id':presence.session_id}
        if (type(report) is not dict or any(report.get(k)!=v for k,v in expected.items()) or presence.state!='online'
            or permissions.get('authoring_engine_boot_id')!=presence.boot_id
            or permissions.get('authoring_engine_session_id')!=presence.session_id
            or not _credential(connection,report.get('token_id'),project,row[0],now)):raise ValueError()
        kind=permissions['authoring_mode']
        if kind=='original':require_mobile_agent_engine(permissions.get('authoring_engine'))
        elif kind!='fixture' or 'authoring_engine' in permissions:raise ValueError()
        if mode is not None and kind!=mode:raise ValueError()
        return kind
    except (ValueError,TypeError,KeyError):
        raise MobileAgentAdmissionRejected('실행 PC의 현재 인증 세션에서 녹화 엔진 지원 상태를 갱신하세요.') from None


def engine_for_recording(connection,project,binding,settings,resource_id,runtime=None):
    if settings.get('target_kind')!='android':return None
    revision=connection.execute("""SELECT provider,model,endpoint,endpoint_kind FROM binding_revisions
        WHERE project_id=? AND binding_id=? AND revision_id=? AND revision=? AND content_hash=?""",
        (str(project),binding['binding_id'],binding['revision_id'],binding['revision'],binding['content_hash'])).fetchone()
    if revision is None:raise MobileAgentAdmissionRejected('authoring binding revision is unavailable',kind='settings')
    mode=require_recording_report(connection,project,resource_id)
    if mode=='fixture':
        endpoint=urlsplit(revision[2])
        if (revision[0]!='fixture' or revision[3]!='loopback' or endpoint.scheme!='http'
            or endpoint.hostname not in {'localhost','127.0.0.1','::1'} or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment):
            raise MobileAgentAdmissionRejected('명시 모의 녹화에는 loopback fixture 모델 연결이 필요합니다.',kind='settings')
        return None
    if revision[0]!='openai' or revision[1]!='gpt-6-luna' or revision[3]!='https' or not is_openai_endpoint(revision[2]):
        raise MobileAgentAdmissionRejected('Android 원본 녹화에는 OpenAI gpt-6-luna 모델 연결이 필요합니다.',kind='settings')
    from aiqa.models.openai_server import OpenAIServerProvider
    if type(runtime) is not AuthoringRuntime or type(runtime.provider) is not OpenAIServerProvider:
        raise MobileAgentAdmissionRejected('관리 서버의 실제 OpenAI provider 설정을 확인하세요.',kind='settings')
    if runtime.price_mode!='estimate':
        raise MobileAgentAdmissionRejected('가격 quote가 없어 원본 녹화를 시작할 수 없습니다. 서버 가격 정책을 확인하세요.',kind='settings')
    return mobile_agent_engine_ref()


def require_original_input(connection,project,version_id,settings):
    from uuid import UUID
    from aiqa.recording.intent import freeze_intent_for_version,IntentRejected
    from aiqa.models.mobile_agent_context import mobile_agent_instruction
    row=connection.execute('SELECT case_id FROM case_versions WHERE project_id=? AND version_id=?',(str(project),str(version_id))).fetchone()
    try:
        if row is None or settings.get('secret_refs'):raise ValueError('sensitive target unsupported')
        if settings.get('limits',{}).get('max_actions',50)<2:raise ValueError('preparation and gesture require two actions')
        intent=freeze_intent_for_version(connection,project_id=project,case_id=UUID(row[0]),case_version_id=UUID(str(version_id)))
        mobile_agent_instruction(intent)
    except (ValueError,TypeError,KeyError,IntentRejected) as exc:
        raise MobileAgentAdmissionRejected('녹화 입력을 확인하세요. 준비 포함 동작 한도2 이상, 민감 참조 제외, 목표12KB 한도가 필요합니다.',kind='input') from exc
