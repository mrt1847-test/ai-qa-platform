"""Atomic receipts for completed browser-owned CRUD routes only.

The outer writer transaction includes both business writes and the receipt. Domain
transactions become savepoints on the same request connection. Native worker,
recording, artifact, and job routes never use this route class.
"""
from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import UUID, uuid4
from datetime import datetime, timedelta, timezone

from fastapi import Request
from fastapi.routing import APIRoute
from starlette.responses import JSONResponse, Response

from aiqa.api.auth import AuthRequired, CsrfRejected, OriginRejected, ProjectHidden, authorize_browser, bound_auth_store, _loopback_origin
from aiqa.store.database import Store, migrate_store
from aiqa.security.receipt_digest import ReceiptKeyUnavailable, protected_body_digest

_request_store: ContextVar[Store | None] = ContextVar('browser_mutation_store', default=None)


def current_mutation_store() -> Store | None:
    return _request_store.get()


class _BorrowedStore(Store):
    def __init__(self, store):
        super().__init__(store.config, store._connection)
        self._savepoint = 0
        self._rollback_actions = []

    def on_rollback(self, callback):
        self._rollback_actions.append(callback)

    def rollback_side_effects(self):
        actions, self._rollback_actions = self._rollback_actions, []
        for callback in reversed(actions):
            callback()

    @contextmanager
    def transaction(self):
        self._savepoint += 1
        name = f'browser_mutation_{self._savepoint}'
        self._connection.execute(f'SAVEPOINT {name}')
        try:
            yield self._connection
        except BaseException:
            self._connection.execute(f'ROLLBACK TO {name}')
            self._connection.execute(f'RELEASE {name}')
            raise
        else:
            self._connection.execute(f'RELEASE {name}')

    def close(self):
        # The owning route closes the physical connection after its outer COMMIT.
        pass


class _RollbackResponse(Exception):
    def __init__(self, response):
        self.response = response


def _error(status, code, message):
    return JSONResponse(status_code=status,content={'error':{'code':code,'message':message,'fields':{},'retryable':False,'request_id':str(uuid4())}})


class BrowserMutationRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request):
            if request.method not in {'POST','PUT','PATCH','DELETE'}:
                return await original(request)
            key=request.headers.get('idempotency-key','').strip()
            if not key:
                return _error(422,'validation','Idempotency-Key is required')
            body=await request.body()
            try:
                payload=json.loads(body) if body else {}
                canonical=json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
            except (ValueError,TypeError,UnicodeError):
                return _error(422,'validation','body must be JSON')
            if type(payload) is not dict:
                return _error(422,'validation','body must be an object')
            store=request.app.state.open_store()
            try:
                migrate_store(store)
                borrowed=_BorrowedStore(store)
                token=_request_store.set(borrowed)
                committed = False
                try:
                    with store.transaction() as connection:
                        now = datetime.now(timezone.utc)
                        cutoff = (now - timedelta(days=7)).isoformat()
                        connection.execute('DELETE FROM browser_mutation_receipts WHERE rowid IN (SELECT rowid FROM browser_mutation_receipts WHERE created_at<? LIMIT 1000)', (cutoff,))
                        project=request.path_params.get('project_id')
                        if project is None and self.path.startswith('/api/v1/model-bindings'):
                            project = payload.get('project_id')
                            if project is None:
                                raise ProjectHidden('binding was not found')
                        with bound_auth_store(borrowed):
                            if project is not None:
                                actor=authorize_browser(request,UUID(str(project)),request.method+':'+self.path)
                                actor_id=str(actor.actor_id)
                                request.state.browser_actor=actor
                            else:
                                # Initial local-owner project creation precedes project sessions.
                                origin=request.headers.get('origin')
                                if request.url.hostname not in {'127.0.0.1','localhost'} or (origin is None or not _loopback_origin(origin) or origin != str(request.base_url).rstrip('/')):
                                    raise OriginRejected('origin was rejected')
                                if request.cookies.get('aiqa_session'):
                                    session_row=connection.execute('SELECT project_scope FROM browser_sessions WHERE session_id=?',(request.cookies['aiqa_session'],)).fetchone()
                                    if session_row is None:
                                        raise AuthRequired('session is missing')
                                    actor=authorize_browser(request,UUID(str(session_row[0])),request.method+':'+self.path)
                                    if not actor.is_local_owner:
                                        raise OriginRejected('local owner is required')
                                    actor_id=str(actor.actor_id)
                                    request.state.browser_actor=actor
                                else:
                                    raw_actor=payload.get('actor',{})
                                    actor_id=str(raw_actor.get('actor_id','')) if type(raw_actor) is dict else ''
                                    prior_receipt=connection.execute('SELECT 1 FROM browser_mutation_receipts WHERE actor_id=? AND project_id=? AND operation=? AND request_key=? AND created_at>=?',(actor_id,'',request.method+':'+request.url.path,key,cutoff)).fetchone()
                                    if prior_receipt is None and connection.execute('SELECT 1 FROM projects LIMIT 1').fetchone() is not None:
                                        raise AuthRequired('later project creation needs a local-owner session')
                                    if type(raw_actor) is not dict or raw_actor.get('is_local_owner') is not True:
                                        raise OriginRejected('local owner is required')

                        operation=request.method+':'+request.url.path
                        digest=protected_body_digest(connection,canonical)
                        identity=(actor_id,str(project or ''),operation,key)
                        connection.execute('DELETE FROM browser_mutation_receipts WHERE actor_id=? AND project_id=? AND operation=? AND request_key=? AND created_at<?', (*identity,cutoff))
                        row=connection.execute('SELECT body_hash,status_code,response_body,media_type FROM browser_mutation_receipts WHERE actor_id=? AND project_id=? AND operation=? AND request_key=?',identity).fetchone()
                        if row is not None:
                            if row[0] != digest:
                                raise _RollbackResponse(_error(409,'conflict','Idempotency-Key was used with another body'))
                            response = Response(content=bytes(row[2]),status_code=200,media_type=str(row[3]),headers={'Idempotency-Replayed':'true'})
                        else:
                            response=await original(request)
                            if response.status_code >= 400:
                                raise _RollbackResponse(response)
                            connection.execute('INSERT INTO browser_mutation_receipts(actor_id,project_id,operation,request_key,body_hash,status_code,response_body,media_type,created_at) VALUES (?,?,?,?,?,?,?,?,?)',(*identity,digest,response.status_code,response.body,response.media_type or 'application/json',now.isoformat()))
                    committed = True
                    return response
                except _RollbackResponse as exc:
                    return exc.response
                except (CsrfRejected,OriginRejected):
                    return _error(403,'permission','request was rejected')
                except AuthRequired:
                    return _error(401,'unauthorized','session is missing')
                except ReceiptKeyUnavailable:
                    return _error(503,'receipt_key_unavailable','local request integrity is unavailable')
                except (ProjectHidden,ValueError):
                    return _error(404,'not_found','project was not found')
                finally:
                    try:
                        if not committed:
                            borrowed.rollback_side_effects()
                    finally:
                        _request_store.reset(token)
            finally:
                store.close()
        return handler
