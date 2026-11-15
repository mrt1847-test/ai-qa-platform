"""Source-bound annotation endpoints. No worker/device/model is contacted."""
from __future__ import annotations
import json
from uuid import UUID,uuid4
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from aiqa.api.auth import authorize_browser,authorize_page,bound_auth_store,AuthRequired,CsrfRejected,OriginRejected,ProjectHidden
from aiqa.recording.check_bindings import save_check_bindings,load_check_binding_context,BindingRejected,BindingConflict,BindingNotFound
from aiqa.store.database import migrate_store


def _error(status,code,message):
    return JSONResponse(status_code=status,content={'error':{'code':code,'message':message,'fields':{},'retryable':False,'request_id':str(uuid4())}},headers={'Cache-Control':'no-store'})


def _sync(request,project,recording,*,payload=None,key=None):
    store=request.app.state.open_store()
    try:
        migrate_store(store)
        with bound_auth_store(store):
            if payload is None:
                authorize_page(request,project)
                with store.transaction() as c:result=load_check_binding_context(c,project,recording)
                status=200
            else:
                actor=authorize_browser(request,project,'recording_check_bindings')
                with store.transaction() as c:
                    result=save_check_bindings(c,actor,project,recording,
                        expected_manifest_id=payload['expected_manifest_id'],expected_manifest_hash=payload['expected_manifest_hash'],
                        bindings={k:payload[k] for k in ('step_boundaries','check_targets')},request_key=key)
                status=200 if result['replayed'] else 201
        return JSONResponse(status_code=status,content=result,headers={'Cache-Control':'no-store'})
    except AuthRequired:return _error(401,'unauthorized','로그인이 필요합니다.')
    except (CsrfRejected,OriginRejected):return _error(403,'permission','요청을 확인할 수 없습니다.')
    except (ProjectHidden,BindingNotFound):return _error(404,'not_found','저장된 녹화를 찾지 못했습니다.')
    except BindingConflict:return _error(409,'conflict','녹화 원본이나 같은 요청의 내용이 바뀌었습니다. 저장본을 다시 확인해 주세요.')
    except (BindingRejected,ValueError):return _error(422,'validation','녹화와 검증 연결 내용을 확인해 주세요.')
    finally:store.close()


def _unique(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('duplicate field')
        result[key]=value
    return result


def install_check_binding_routes(app):
    path='/api/v1/projects/{project_id}/recordings/{recording_id}/check-bindings'
    async def get(project_id:str,recording_id:str,request:Request):
        try:project,recording=UUID(project_id),UUID(recording_id)
        except ValueError:return _error(404,'not_found','저장된 녹화를 찾지 못했습니다.')
        return await run_in_threadpool(_sync,request,project,recording)
    async def post(project_id:str,recording_id:str,request:Request):
        try:project,recording=UUID(project_id),UUID(recording_id)
        except ValueError:return _error(404,'not_found','저장된 녹화를 찾지 못했습니다.')
        key=request.headers.get('idempotency-key','')
        if not key.strip():return _error(422,'validation','저장 요청 ID가 필요합니다.')
        raw=bytearray()
        try:
            async for chunk in request.stream():
                if len(raw)+len(chunk)>131072:return _error(413,'validation','검증 연결 내용이 너무 큽니다.')
                raw.extend(chunk)
            payload=json.loads(raw.decode('utf-8'),object_pairs_hook=_unique)
            if type(payload) is not dict or set(payload)!={'expected_manifest_id','expected_manifest_hash','step_boundaries','check_targets'}:raise ValueError()
            if type(payload['expected_manifest_id']) is not str or type(payload['expected_manifest_hash']) is not str or not payload['expected_manifest_hash'] or len(payload['expected_manifest_hash'])>128:raise ValueError()
            UUID(payload['expected_manifest_id'])
        except (ValueError,TypeError,UnicodeError,RecursionError):return _error(422,'validation','검증 연결 입력을 확인해 주세요.')
        return await run_in_threadpool(_sync,request,project,recording,payload=payload,key=key)
    app.add_api_route(path,get,methods=['GET'])
    app.add_api_route(path,post,methods=['POST'])
