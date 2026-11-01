"""Project audit, worker scope, and storage views. This does not pin or delete files."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRouter

from aiqa.api.auth import (
    AuthRequired,
    CsrfRejected,
    OriginRejected,
    ProjectHidden,
    WorkerDenied,
    authorize_browser,
    bound_auth_store,
    enroll_worker,
)
from aiqa.store.artifacts import PROJECT_BYTE_LIMIT
from aiqa.store.database import Store, migrate_store

router = APIRouter(prefix="/api/v1")
_store: ContextVar[Store] = ContextVar("aiqa_audit_store")


@contextmanager
def bind_audit_store(store: Store) -> Iterator[None]:
    token = _store.set(store)
    try:
        yield
    finally:
        _store.reset(token)


def install_audit(application: FastAPI) -> None:
    """Attach read and enrollment routes. This does not open SQLite."""

    if getattr(application.state, "audit_installed", False):
        return
    application.include_router(router)
    application.state.audit_installed = True


@router.get("/projects/{project_id}/audit")
async def get_audit(project_id: str, request: Request) -> JSONResponse:
    project = _uuid(project_id)
    if isinstance(project, JSONResponse):
        return project
    with _bound(request):
        try:
            authorize_browser(request, project, "audit")
            page = list_audit(
                project,
                request.query_params.get("cursor", ""),
                request.query_params.get("kind", ""),
                _limit(request.query_params.get("limit", "25")),
            )
        except (CsrfRejected, OriginRejected):
            return _error(403, "permission", "request was rejected")
        except AuthRequired:
            return _error(401, "unauthorized", "session is missing")
        except ProjectHidden:
            return _error(404, "not_found", "audit was not found")
    return JSONResponse(status_code=200, content=page)


@router.get("/projects/{project_id}/storage")
async def get_storage(project_id: str, request: Request) -> JSONResponse:
    project = _uuid(project_id)
    if isinstance(project, JSONResponse):
        return project
    with _bound(request):
        try:
            authorize_browser(request, project, "storage")
            view = storage_view(project)
        except (CsrfRejected, OriginRejected):
            return _error(403, "permission", "request was rejected")
        except AuthRequired:
            return _error(401, "unauthorized", "session is missing")
        except ProjectHidden:
            return _error(404, "not_found", "storage was not found")
    return JSONResponse(status_code=200, content=view)


@router.get("/projects/{project_id}/workers")
async def get_workers(project_id: str, request: Request) -> JSONResponse:
    project = _uuid(project_id)
    if isinstance(project, JSONResponse):
        return project
    with _bound(request):
        try:
            authorize_browser(request, project, "workers")
            rows = list_workers(project)
        except (CsrfRejected, OriginRejected):
            return _error(403, "permission", "request was rejected")
        except AuthRequired:
            return _error(401, "unauthorized", "session is missing")
        except ProjectHidden:
            return _error(404, "not_found", "workers were not found")
    return JSONResponse(status_code=200, content={"workers": rows})


@router.post("/projects/{project_id}/worker-enrollments")
async def post_enrollment(project_id: str, request: Request) -> JSONResponse:
    if not request.headers.get("idempotency-key"):
        return _error(422, "validation", "Idempotency-Key is required")
    project = _uuid(project_id)
    if isinstance(project, JSONResponse):
        return project
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    worker_id = payload.get("worker_id")
    purpose = payload.get("purpose")
    if type(worker_id) is not str or type(purpose) is not str:
        return _error(422, "validation", "invalid worker")
    with _bound(request):
        try:
            actor = authorize_browser(request, project, "worker_enrollment")
            credential = enroll_worker(actor, worker_id, purpose)
        except (CsrfRejected, OriginRejected):
            return _error(403, "permission", "request was rejected")
        except (WorkerDenied, ProjectHidden):
            return _error(404, "not_found", "worker was not found")
        except AuthRequired:
            return _error(401, "unauthorized", "session is missing")
    return JSONResponse(
        status_code=201,
        content={"worker_id": worker_id, "purpose": purpose, "revoked": False, "credential": credential},
    )


@router.post("/workers/{worker_id}/revoke")
async def post_revoke(worker_id: str, request: Request) -> JSONResponse:
    if not request.headers.get("idempotency-key"):
        return _error(422, "validation", "Idempotency-Key is required")
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    project = _uuid(str(payload.get("project_id", "")))
    if isinstance(project, JSONResponse):
        return _error(422, "validation", "invalid worker")
    with _bound(request):
        try:
            authorize_browser(request, project, "worker_revoke")
            revoked = revoke_worker(project, worker_id)
        except (CsrfRejected, OriginRejected):
            return _error(403, "permission", "request was rejected")
        except AuthRequired:
            return _error(401, "unauthorized", "session is missing")
        except ProjectHidden:
            return _error(404, "not_found", "worker was not found")
    return JSONResponse(status_code=200, content={"worker_id": worker_id, "revoked": revoked})


def list_audit(project_id: UUID, cursor: str, kind: str, limit: int) -> dict[str, object]:
    with _bound_store().transaction() as connection:
        rows = connection.execute(
            """
            SELECT audits.audit_id, audits.actor_id, audits.action, audits.created_at, links.note
            FROM project_audits AS audits
            LEFT JOIN project_audit_links AS links
              ON links.project_id = audits.project_id AND links.audit_id = audits.audit_id
            WHERE audits.project_id = ?
              AND (? = '' OR audits.audit_id > ?)
              AND (? = '' OR audits.action = ?)
            ORDER BY audits.created_at, audits.audit_id
            LIMIT ?
            """,
            (str(project_id), cursor, cursor, kind, kind, limit + 1),
        ).fetchall()
    page = rows[:limit]
    next_cursor = None if len(rows) <= limit else str(page[-1][0])
    return {
        "items": [
            {
                "project_id": str(project_id),
                "audit_id": str(row[0]),
                "actor_id": str(row[1]),
                "action": str(row[2]),
                "created_at": str(row[3]),
                "reason": "" if row[4] is None else str(row[4]),
            }
            for row in page
        ],
        "next_cursor": next_cursor,
    }


def list_workers(project_id: UUID) -> list[dict[str, object]]:
    with _bound_store().transaction() as connection:
        rows = connection.execute(
            """
            SELECT enrollments.worker_id,
                   COALESCE(tokens.purpose, ''),
                   CASE WHEN tokens.token_id IS NULL THEN 1 ELSE 0 END
            FROM worker_enrollments AS enrollments
            LEFT JOIN worker_tokens AS tokens
              ON tokens.enrollment_id = enrollments.enrollment_id
            WHERE enrollments.project_id = ?
            ORDER BY enrollments.worker_id
            """,
            (str(project_id),),
        ).fetchall()
    return [
        {"worker_id": str(row[0]), "purpose": str(row[1]), "revoked": bool(row[2])}
        for row in rows
    ]


def storage_view(project_id: UUID) -> dict[str, object]:
    used = 0
    protected = 0
    return {
        "project_id": str(project_id),
        "used_bytes": used,
        "protected_bytes": protected,
        "limit_bytes": PROJECT_BYTE_LIMIT,
        "over_protected": protected > PROJECT_BYTE_LIMIT,
        "deletion_scheduled": 0,
    }


def revoke_worker(project_id: UUID, worker_id: str) -> bool:
    with _bound_store().transaction() as connection:
        connection.execute(
            """
            DELETE FROM worker_tokens
            WHERE enrollment_id IN (
                SELECT enrollment_id FROM worker_enrollments
                WHERE project_id = ? AND worker_id = ?
            )
            """,
            (str(project_id), worker_id),
        )
    return True


def _bound_store() -> Store:
    try:
        return _store.get()
    except LookupError as exc:
        raise RuntimeError("audit store is not bound") from exc


@contextmanager
def _bound(request: Request) -> Iterator[None]:
    store = request.app.state.open_store()
    try:
        migrate_store(store)
        with bind_audit_store(store):
            with bound_auth_store(store):
                yield
    finally:
        store.close()


def _limit(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError:
        return 25
    if parsed < 1:
        return 1
    return min(parsed, 100)


def _uuid(value: str) -> UUID | JSONResponse:
    try:
        return UUID(value)
    except ValueError:
        return _error(404, "not_found", "project was not found")


async def _body(request: Request) -> dict[str, object] | JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        return _error(422, "validation", "body must be JSON")
    if type(payload) is not dict:
        return _error(422, "validation", "body must be an object")
    return payload


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": code,
                "message": message,
                "fields": {},
                "retryable": False,
                "request_id": str(uuid4()),
            }
        },
    )
