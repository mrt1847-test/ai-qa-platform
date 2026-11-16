"""Advertise only the prepared recording route in this authenticated incarnation."""
from copy import deepcopy
import json
from uuid import UUID
from aiqa.adapters.mobile_agent_upstream import load_protocol
from aiqa.contracts.mobile_agent_engine import mobile_agent_engine_ref
from aiqa.worker.mobile_agent_handler import OriginalAndroidRecordingHandler
from aiqa.worker.android_jobs import AndroidRecordingHandler


class FixtureAndroidRecordingHandler(AndroidRecordingHandler):
    """Explicit local fixture adapter, never an original/paid authoring fallback."""


def inventory_with_recording_engine(payload,handler,boot_id,*,prepared,session_id=None):
    result=deepcopy(payload)
    try:permissions=json.loads(result.get('permissions','{}'))
    except (ValueError,TypeError):return result
    if type(permissions) is not dict:return result
    for name in ('authoring_mode','authoring_engine','authoring_engine_boot_id','authoring_engine_session_id','authoring_report'):permissions.pop(name,None)
    seen=set()
    while id(handler) not in seen:
        seen.add(id(handler));routes=getattr(handler,'routes',None)
        if type(routes) is not dict:break
        handler=routes.get('recording')
    try:valid_session=type(session_id) is str and str(UUID(session_id))==session_id
    except (ValueError,TypeError,AttributeError):valid_session=False
    if prepared and result.get('target_kind')=='android' and type(boot_id) is str and boot_id.strip() and valid_session:
        mode=None
        if isinstance(handler,OriginalAndroidRecordingHandler):
            try:load_protocol()
            except (ValueError,OSError,ImportError):pass
            else:mode='original';permissions['authoring_engine']=mobile_agent_engine_ref()
        elif isinstance(handler,FixtureAndroidRecordingHandler):mode='fixture'
        if mode:permissions.update(authoring_mode=mode,authoring_engine_boot_id=boot_id,authoring_engine_session_id=session_id)
    result['permissions']=json.dumps(permissions,sort_keys=True,separators=(',',':'))
    return result
