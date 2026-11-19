"""Worker-only server visual verification; provider credentials never enter this DTO."""
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from aiqa.api.auth import AuthRequired, WorkerDenied, worker_scope_from_token
from aiqa.api.worker import _bound, _body, _idempotency
from aiqa.models.replay_verification import handle_replay_evaluation_http, parse_evaluation
from aiqa.store.model_requests import model_error


def install_check_evaluations(application):
    async def post_check_evaluations(request: Request):
        rejected = _idempotency(request)
        if rejected is not None:
            return rejected
        bearer = request.headers.get('authorization','')
        if not bearer.startswith('Bearer ') or not bearer[7:].strip():
            return JSONResponse(status_code=401,content=model_error('unauthorized'))
        payload = await _body(request)
        if isinstance(payload,JSONResponse):
            return payload
        try:
            evaluation = parse_evaluation(payload)
        except (ValueError,TypeError,KeyError):
            return JSONResponse(status_code=422,content=model_error('evaluation_invalid'))
        with _bound(request):
            try:
                worker = worker_scope_from_token(bearer[7:].strip())
            except AuthRequired:
                return JSONResponse(status_code=401,content=model_error('unauthorized'))
            except WorkerDenied:
                return JSONResponse(status_code=403,content=model_error('replay_authorization'))
            status,body = await run_in_threadpool(handle_replay_evaluation_http,
                request.app.state.open_store,request.app.state.model_gateway,request.app.state.settings,
                worker,evaluation,request.headers['idempotency-key'].strip())
        return JSONResponse(status_code=status,content=body)

    application.add_api_route('/api/v1/worker/check-evaluations',post_check_evaluations,methods=['POST'])
