"""Read project commits and attempt events. A poll does not repeat a mutation."""

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
    authorize_browser,
    bound_auth_store,
)
from aiqa.store.database import Store, migrate_store

router = APIRouter(prefix="/api/v1")
_store: ContextVar[Store] = ContextVar("aiqa_event_store")


def install_events(application: FastAPI) -> None:
    """Attach the two read cursors. This does not open SQLite."""

    if getattr(application.state, "events_installed", False):
        return
    application.include_router(router)
    application.state.events_installed = True


@router.get("/projects/{project_id}/events")
async def get_project_events(project_id: str, request: Request) -> JSONResponse:
    project = _uuid(project_id)
    if isinstance(project, JSONResponse):
        return project
    cursor = _cursor(request.query_params.get("after_commit_seq", "0"))
    if isinstance(cursor, JSONResponse):
        return cursor
    with _bound(request):
        try:
            authorize_browser(request, project, "project_events")
            page = project_events(project, cursor)
        except (CsrfRejected, OriginRejected):
            return _error(403, "permission", "request was rejected")
        except AuthRequired:
            return _error(401, "unauthorized", "session is missing")
        except ProjectHidden:
            return _error(404, "not_found", "events were not found")
    return JSONResponse(status_code=200, content=page)


@router.get("/attempts/{attempt_id}/events")
async def get_attempt_events(attempt_id: str, request: Request) -> JSONResponse:
    cursor = _cursor(request.query_params.get("after_local_seq", "0"))
    if isinstance(cursor, JSONResponse):
        return cursor
    with _bound(request):
        project = _attempt_project(attempt_id)
        if project is None:
            return _error(404, "not_found", "events were not found")
        try:
            authorize_browser(request, project, "attempt_events")
            page = attempt_events(project, attempt_id, cursor)
        except (CsrfRejected, OriginRejected):
            return _error(403, "permission", "request was rejected")
        except AuthRequired:
            return _error(401, "unauthorized", "session is missing")
        except ProjectHidden:
            return _error(404, "not_found", "events were not found")
    return JSONResponse(status_code=200, content=page)


def project_events(project_id: UUID, after_commit_seq: int) -> dict[str, object]:
    with _bound_store().transaction() as connection:
        rows = connection.execute(
            """
            SELECT audit_id, commit_seq, action
            FROM project_audits
            WHERE project_id = ? AND commit_seq > ?
            ORDER BY commit_seq
            """,
            (str(project_id), after_commit_seq),
        ).fetchall()
    return _page(rows, after_commit_seq, "commit")


def attempt_events(project_id: UUID, attempt_id: str, after_local_seq: int) -> dict[str, object]:
    with _bound_store().transaction() as connection:
        rows = connection.execute(
            """
            SELECT event_id, local_seq, event_type
            FROM attempt_events
            WHERE project_id = ? AND attempt_id = ? AND local_seq > ?
            ORDER BY local_seq
            """,
            (str(project_id), attempt_id, after_local_seq),
        ).fetchall()
    return _page(rows, after_local_seq, "local")


def _page(rows: list[tuple[object, ...]], after: int, kind: str) -> dict[str, object]:
    items = [{"id": str(row[0]), "seq": int(row[1]), "kind": str(row[2])} for row in rows]
    previous = after
    stale = False
    for item in items:
        if int(item["seq"]) > previous + 1:
            stale = True
        previous = int(item["seq"])
    nxt = after if not items else int(items[-1]["seq"])
    body: dict[str, object] = {
        "items": items,
        "stale": stale,
        "mutations": 0,
        "cursor_kind": kind,
    }
    if kind == "commit":
        body["next_commit_seq"] = nxt
    else:
        body["next_local_seq"] = nxt
    return body


def _attempt_project(attempt_id: str) -> UUID | None:
    with _bound_store().transaction() as connection:
        row = connection.execute(
            "SELECT project_id FROM attempts WHERE attempt_id = ?",
            (attempt_id,),
        ).fetchone()
    if row is None:
        return None
    return UUID(str(row[0]))


def _bound_store() -> Store:
    try:
        return _store.get()
    except LookupError as exc:
        raise RuntimeError("event store is not bound") from exc


@contextmanager
def _bound(request: Request) -> Iterator[None]:
    store = request.app.state.open_store()
    try:
        migrate_store(store)
        token = _store.set(store)
        try:
            with bound_auth_store(store):
                yield
        finally:
            _store.reset(token)
    finally:
        store.close()


def _cursor(value: str) -> int | JSONResponse:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return _error(422, "validation", "cursor must be an integer")
    if parsed < 0:
        return _error(422, "validation", "cursor must be an integer")
    return parsed


def _uuid(value: str) -> UUID | JSONResponse:
    try:
        return UUID(value)
    except ValueError:
        return _error(404, "not_found", "events were not found")


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
