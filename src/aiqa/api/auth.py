"""Loopback browser session and worker token boundary. Importing this module opens no database."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRouter

from aiqa.store.database import Store, migrate_store
from aiqa.store.models import Actor, BrowserSession, JobRef, WorkerScope

router = APIRouter(prefix="/api/v1")
_store: ContextVar[Store] = ContextVar("aiqa_auth_store")


@contextmanager
def bound_auth_store(store: Store) -> Iterator[None]:
    """Let authorize_browser use a store the caller already opened."""

    token = _store.set(store)
    try:
        yield
    finally:
        _store.reset(token)
_NONCE_TTL = timedelta(seconds=60)
_SESSION_TTL = timedelta(hours=8)


class AuthRequired(Exception):
    """The caller has no usable session or worker token."""


class CsrfRejected(Exception):
    """A mutation did not present the session CSRF token."""


class OriginRejected(Exception):
    """The Origin is missing, foreign, or not the session origin."""


class NonceRejected(Exception):
    """The launcher nonce is unknown, expired, or already used."""


class ProjectHidden(Exception):
    """The project is outside this session. Callers see not-found."""


class WorkerDenied(Exception):
    """A worker token cannot perform this operation."""


def install_auth(application: FastAPI) -> None:
    """Attach session and worker routes. This does not open SQLite."""

    application.include_router(router)


def issue_browser_nonce(origin: str, project_id: UUID) -> str:
    if not _loopback_origin(origin):
        raise OriginRejected("origin is not loopback")
    raw = secrets.token_urlsafe(32)
    expires = _now() + _NONCE_TTL
    try:
        with _bound_store().transaction() as connection:
            connection.execute(
                """
                INSERT INTO browser_nonces (nonce_hash, origin, project_id, expires_at, used_at)
                VALUES (?, ?, ?, ?, NULL)
                """,
                (_hash(raw), origin, str(project_id), expires.isoformat()),
            )
    except sqlite3.IntegrityError as exc:
        raise ProjectHidden("project was not found") from exc
    return raw


def bootstrap_browser_session(nonce: str, origin: str) -> BrowserSession:
    if type(nonce) is not str or nonce.strip() == "" or not _loopback_origin(origin):
        raise NonceRejected("nonce was rejected")
    session_id = uuid4()
    actor_id = uuid4()
    csrf = secrets.token_urlsafe(32)
    expires = _now() + _SESSION_TTL
    with _bound_store().transaction() as connection:
        row = connection.execute(
            """
            SELECT origin, project_id, expires_at, used_at
            FROM browser_nonces
            WHERE nonce_hash = ?
            """,
            (_hash(nonce),),
        ).fetchone()
        if row is None or row[3] is not None or row[0] != origin:
            raise NonceRejected("nonce was rejected")
        if datetime.fromisoformat(str(row[2])) <= _now():
            raise NonceRejected("nonce was rejected")
        project_id = UUID(str(row[1]))
        updated = connection.execute(
            """
            UPDATE browser_nonces
            SET used_at = ?
            WHERE nonce_hash = ? AND used_at IS NULL
            """,
            (_now().isoformat(), _hash(nonce)),
        )
        if updated.rowcount != 1:
            raise NonceRejected("nonce was rejected")
        prior_owner = connection.execute('SELECT actor_id FROM browser_sessions WHERE is_local_owner=1 ORDER BY rowid LIMIT 1').fetchone()
        connection.execute('INSERT OR IGNORE INTO local_owner_identity(singleton,actor_id) VALUES(1,?)', (str(actor_id) if prior_owner is None else str(prior_owner[0]),))
        actor_id = UUID(str(connection.execute('SELECT actor_id FROM local_owner_identity WHERE singleton=1').fetchone()[0]))
        connection.execute(
            """
            INSERT INTO browser_sessions (
                session_id, origin, csrf_hash, actor_id, project_scope, is_local_owner, expires_at
            ) VALUES (?, ?, ?, ?, ?, 1, ?)
            """,
            (
                str(session_id),
                origin,
                _hash(csrf),
                str(actor_id),
                str(project_id),
                expires.isoformat(),
            ),
        )
    return BrowserSession(
        session_id=session_id,
        origin=origin,
        csrf_token=csrf,
        actor=Actor(actor_id=actor_id, project_scope=project_id, is_local_owner=True),
        expires_at=expires.isoformat(),
    )


def authorize_page(request: Request, project_id: UUID) -> Actor:
    """Read a loopback page session. A navigation does not send a mutation token."""

    if request.url.hostname not in {"127.0.0.1", "localhost"}:
        raise OriginRejected("origin is not loopback")
    session_id = request.cookies.get("aiqa_session")
    if not session_id:
        raise AuthRequired("session is missing")
    with _bound_store().transaction() as connection:
        row = connection.execute(
            """
            SELECT actor_id, project_scope, is_local_owner, expires_at
            FROM browser_sessions
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()
    if row is None or datetime.fromisoformat(str(row[3])) <= _now():
        raise AuthRequired("session is missing")
    scope = UUID(str(row[1]))
    if scope != project_id:
        raise ProjectHidden("approval was not found")
    return Actor(
        actor_id=UUID(str(row[0])),
        project_scope=scope,
        is_local_owner=bool(int(row[2])),
    )


def authorize_browser(request: Request, project_id: UUID, operation: str) -> Actor:
    if type(operation) is not str or operation.strip() == "":
        raise CsrfRejected("csrf token is missing")
    origin = request.headers.get("origin")
    if origin is None or not _loopback_origin(origin):
        raise OriginRejected("origin is not loopback")
    presented = request.headers.get("x-csrf-token")
    if presented is None or presented.strip() == "":
        raise CsrfRejected("csrf token is missing")
    session_id = request.cookies.get("aiqa_session")
    if not session_id:
        raise AuthRequired("session is missing")
    with _bound_store().transaction() as connection:
        row = connection.execute(
            """
            SELECT origin, csrf_hash, actor_id, project_scope, is_local_owner, expires_at
            FROM browser_sessions
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()
    if row is None or datetime.fromisoformat(str(row[5])) <= _now():
        raise AuthRequired("session is missing")
    if row[0] != origin:
        raise OriginRejected("origin does not match")
    if not hmac.compare_digest(_hash(presented), str(row[1])):
        raise CsrfRejected("csrf token was rejected")
    scope = UUID(str(row[3]))
    if scope != project_id:
        raise ProjectHidden("approval was not found")
    return Actor(
        actor_id=UUID(str(row[2])),
        project_scope=scope,
        is_local_owner=bool(int(row[4])),
    )


def authorize_worker(token: str, job: JobRef) -> WorkerScope:
    if type(token) is not str or token.strip() == "":
        raise AuthRequired("worker token is missing")
    with _bound_store().transaction() as connection:
        row = connection.execute(
            """
            SELECT worker_enrollments.worker_id, worker_enrollments.project_id, worker_tokens.purpose
            FROM worker_tokens
            JOIN worker_enrollments
              ON worker_enrollments.enrollment_id = worker_tokens.enrollment_id
            WHERE worker_tokens.token_hash = ?
            """,
            (_hash(token),),
        ).fetchone()
    if row is None:
        raise AuthRequired("worker token is missing")
    project_id = UUID(str(row[1]))
    purpose = str(row[2])
    if job.purpose == "approval" or job.purpose != purpose or job.project_id != project_id:
        raise WorkerDenied("worker token cannot approve")
    return WorkerScope(
        worker_id=str(row[0]),
        permitted_projects=(project_id,),
        permitted_purposes=(purpose,),
    )


def worker_scope_from_token(token: str) -> WorkerScope:
    """The projects and purpose stored for this token. This does not claim a job."""

    if type(token) is not str or token.strip() == "":
        raise AuthRequired("worker token is missing")
    with _bound_store().transaction() as connection:
        row = connection.execute(
            """
            SELECT worker_enrollments.worker_id, worker_enrollments.project_id, worker_tokens.purpose, worker_tokens.token_id
            FROM worker_tokens
            JOIN worker_enrollments
              ON worker_enrollments.enrollment_id = worker_tokens.enrollment_id
            WHERE worker_tokens.token_hash = ?
            """,
            (_hash(token),),
        ).fetchone()
    if row is None or str(row[2]) == "approval":
        raise AuthRequired("worker token is missing")
    return WorkerScope(
        worker_id=str(row[0]),
        permitted_projects=(UUID(str(row[1])),),
        permitted_purposes=(str(row[2]),),
        token_id=str(row[3]),
    )


def enroll_worker(actor: Actor, worker_id: str, purpose: str) -> str:
    if actor.project_scope is None:
        raise ProjectHidden("project was not found")
    if type(worker_id) is not str or worker_id.strip() == "":
        raise WorkerDenied("worker id is missing")
    if type(purpose) is not str or purpose.strip() == "" or purpose == "approval":
        raise WorkerDenied("purpose is not enrollable")
    raw = secrets.token_urlsafe(32)
    created_at = _now().isoformat()
    with _bound_store().transaction() as connection:
        enrollment_id = str(uuid4())
        connection.execute(
            """
            INSERT INTO worker_enrollments (enrollment_id, worker_id, project_id, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (enrollment_id, worker_id, str(actor.project_scope), created_at),
        )
        connection.execute(
            """
            INSERT INTO worker_tokens (token_id, enrollment_id, token_hash, purpose, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (str(uuid4()), enrollment_id, _hash(raw), purpose, created_at),
        )
    return raw


@router.get("/session/csrf")
async def get_session_csrf(request: Request) -> JSONResponse:
    """Read the existing cookie-bound token without rotating other tabs' state."""
    origin=request.headers.get('origin')
    if origin is None and request.headers.get('sec-fetch-site') == 'same-origin':
        origin = str(request.base_url).rstrip('/')
    if not origin or not _loopback_origin(origin) or origin != str(request.base_url).rstrip('/'):
        return _error(403,'permission','origin was rejected',{})
    with _bound(request):
        session_id=request.cookies.get('aiqa_session','')
        with _bound_store().transaction() as connection:
            row=connection.execute('SELECT origin,project_scope,expires_at,csrf_hash FROM browser_sessions WHERE session_id=?',(session_id,)).fetchone()
            if row is None or datetime.fromisoformat(str(row[2])) <= _now():
                return _error(401,'unauthorized','session is missing',{})
            if row[0] != origin:
                return _error(403,'permission','origin was rejected',{})
            token = request.cookies.get('aiqa_csrf', '')
            if not token or not hmac.compare_digest(_hash(token), str(row[3])):
                return _error(401, 'unauthorized', 'session must be bootstrapped again', {})
    return JSONResponse(content={'csrf_token':token,'project_id':str(row[1])},headers={'Cache-Control':'no-store'})


@router.post("/session/nonces")
async def post_nonce(request: Request) -> JSONResponse:
    rejected = _idempotency(request)
    if rejected is not None:
        return rejected
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    origin = payload.get("origin")
    header_origin = request.headers.get("origin")
    if type(origin) is not str or (header_origin is not None and header_origin != origin):
        return _error(403, "permission", "origin was rejected", {})
    try:
        project_id = UUID(str(payload.get("project_id")))
    except (TypeError, ValueError):
        return _error(404, "not_found", "project was not found", {})
    with _bound(request):
        try:
            nonce = issue_browser_nonce(origin, project_id)
        except OriginRejected:
            return _error(403, "permission", "origin was rejected", {})
        except ProjectHidden:
            return _error(404, "not_found", "project was not found", {})
    return JSONResponse(status_code=201, content={"nonce": nonce, "expires_in": int(_NONCE_TTL.total_seconds())})


@router.post("/session/bootstrap")
async def post_bootstrap(request: Request) -> JSONResponse:
    if "nonce" in request.query_params:
        return _error(400, "validation", "nonce must be sent in the request body", {})
    rejected = _idempotency(request)
    if rejected is not None:
        return rejected
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    origin = request.headers.get("origin")
    nonce = payload.get("nonce")
    if type(origin) is not str or type(nonce) is not str:
        return _error(401, "unauthorized", "nonce was rejected", {})
    with _bound(request):
        try:
            session = bootstrap_browser_session(nonce, origin)
        except OriginRejected:
            return _error(403, "permission", "origin was rejected", {})
        except NonceRejected:
            return _error(401, "unauthorized", "nonce was rejected", {})
    response = JSONResponse(
        status_code=201,
        content={
            "session_id": str(session.session_id),
            "csrf_token": session.csrf_token,
            "expires_at": session.expires_at,
        },
    )
    response.set_cookie("aiqa_session", str(session.session_id), httponly=True, samesite="strict", path="/")
    response.set_cookie('aiqa_csrf', session.csrf_token, httponly=True, samesite='strict', path='/')
    return response


@router.post("/workers/enrollments")
async def post_enrollment(request: Request) -> JSONResponse:
    rejected = _idempotency(request)
    if rejected is not None:
        return rejected
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    with _bound(request):
        try:
            actor = _actor_from_request(request)
            token = enroll_worker(actor, str(payload.get("worker_id")), str(payload.get("purpose")))
        except CsrfRejected:
            return _error(403, "permission", "csrf token was rejected", {})
        except OriginRejected:
            return _error(403, "permission", "origin was rejected", {})
        except ProjectHidden:
            return _error(404, "not_found", "project was not found", {})
        except AuthRequired:
            return _error(401, "unauthorized", "session is missing", {})
        except WorkerDenied:
            return _error(403, "permission", "worker enrollment was rejected", {})
    return JSONResponse(status_code=201, content={"token": token})


@router.post("/projects/{project_id}/approvals")
async def post_approval(project_id: str, request: Request) -> JSONResponse:
    rejected = _idempotency(request)
    if rejected is not None:
        return rejected
    try:
        parsed = UUID(project_id)
    except ValueError:
        return _error(404, "not_found", "approval was not found", {})
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        token = header.split(" ", 1)[1].strip()
        with _bound(request):
            try:
                authorize_worker(token, JobRef(project_id=parsed, purpose="approval"))
            except WorkerDenied:
                return _error(403, "permission", "worker token cannot approve", {})
            except AuthRequired:
                return _error(401, "unauthorized", "worker token is missing", {})
        return _error(403, "permission", "worker token cannot approve", {})
    with _bound(request):
        try:
            authorize_browser(request, parsed, "approval")
        except CsrfRejected:
            return _error(403, "permission", "csrf token was rejected", {})
        except OriginRejected:
            return _error(403, "permission", "origin was rejected", {})
        except ProjectHidden:
            return _error(404, "not_found", "approval was not found", {})
        except AuthRequired:
            return _error(401, "unauthorized", "session is missing", {})
    return _error(404, "not_found", "approval was not found", {})


def _actor_from_request(request: Request) -> Actor:
    session_id = request.cookies.get("aiqa_session")
    if not session_id:
        raise AuthRequired("session is missing")
    with _bound_store().transaction() as connection:
        row = connection.execute(
            "SELECT project_scope FROM browser_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    if row is None:
        raise AuthRequired("session is missing")
    return authorize_browser(request, UUID(str(row[0])), "enroll")


@contextmanager
def _bound(request: Request) -> Iterator[None]:
    store = request.app.state.open_store()
    try:
        migrate_store(store)
        token = _store.set(store)
        try:
            yield
        finally:
            _store.reset(token)
    finally:
        store.close()


def _bound_store() -> Store:
    try:
        return _store.get()
    except LookupError as exc:
        raise RuntimeError("auth store is not bound") from exc


async def _body(request: Request) -> dict[str, object] | JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        return _error(422, "validation", "body must be JSON", {"body": ["invalid"]})
    if type(payload) is not dict:
        return _error(422, "validation", "body must be an object", {"body": ["invalid"]})
    return payload


def _idempotency(request: Request) -> JSONResponse | None:
    if not request.headers.get("idempotency-key"):
        return _error(422, "validation", "Idempotency-Key is required", {"Idempotency-Key": ["required"]})
    return None


def _loopback_origin(origin: str) -> bool:
    if type(origin) is not str:
        return False
    parsed = urlparse(origin)
    return (
        parsed.scheme == "http"
        and parsed.hostname == "127.0.0.1"
        and parsed.username is None
        and parsed.password is None
        and parsed.path in ("", "/")
        and parsed.query == ""
        and parsed.fragment == ""
    )


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _error(status: int, code: str, message: str, fields: dict[str, list[str]]) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": code,
                "message": message,
                "fields": fields,
                "retryable": False,
                "request_id": str(uuid4()),
            }
        },
    )
