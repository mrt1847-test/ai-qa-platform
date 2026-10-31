"""Optional TC routes. Import proposal persistence belongs to a later job schema."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID, uuid4

import json

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.routing import APIRouter
from aiqa.api.mutations import BrowserMutationRoute

from aiqa.api.auth import (
    AuthRequired,
    CsrfRejected,
    OriginRejected,
    ProjectHidden,
    authorize_browser,
    authorize_page,
    bound_auth_store,
)
from aiqa.domain.tcs import (
    TcNotFound,
    archive_tc,
    bind_tc_actor,
    bind_tc_store,
    clone_tc,
    read_tc_reference,
    save_tc_revision,
    set_tc_reference,
)
from aiqa.domain.versions import CaseNotFound, ForeignTc, bind_case_store
from aiqa.api.cases import _editor_snapshot, _pending_proposals
from aiqa.store.database import migrate_store
from aiqa.store.models import CaseMetadataView, TcRevisionInput, TcVersionView
from aiqa.web.routes import UiQueryState, render_template

router = APIRouter(prefix="/api/v1", route_class=BrowserMutationRoute)
pages = APIRouter(route_class=BrowserMutationRoute)


def install_tcs(application: FastAPI) -> None:
    """Attach TC routes once. This does not open SQLite."""

    if getattr(application.state, "tcs_installed", False):
        return
    application.include_router(router)
    application.include_router(pages)
    application.state.tcs_installed = True


@router.get("/projects/{project_id}/tcs")
async def get_tcs(project_id: str, request: Request) -> JSONResponse:
    project = _uuid(project_id)
    if isinstance(project, JSONResponse):
        return project
    query = request.query_params.get("q", "")
    with _bound(request) as actor_box:
        try:
            actor_box.append(authorize_browser(request, project, "tc"))
            items = _tc_rows(project, query)
        except _AUTH_ERRORS as exc:
            return _auth_response(exc)
    return JSONResponse(status_code=200, content={"items": items, "tc_required": False})


@pages.get("/ui/projects/{project_id}/tcs", response_class=HTMLResponse)
async def tcs_page(project_id: str, request: Request) -> HTMLResponse:
    project = _uuid(project_id)
    if isinstance(project, JSONResponse):
        return HTMLResponse(status_code=404, content="선택 TC를 찾지 못했습니다.")
    query = request.query_params.get("q", "")
    with _bound(request) as actor_box:
        try:
            actor_box.append(authorize_page(request, project))
            items = _tc_rows(project, query)
            cases, selected = _case_choices(project,request.query_params.get('case_id'))
            snapshot = None if selected is None else _editor_snapshot(actor_box[0],UUID(selected['case_id']))
            proposals = [] if selected is None else _pending_proposals(actor_box[0],UUID(selected['case_id']))
        except (OriginRejected, ProjectHidden, AuthRequired):
            return HTMLResponse(status_code=401, content="이 화면을 볼 권한이 없습니다.")
    return render_template(
        request,
        "tcs.html",
        {
            "shell": True,
            "title": "선택 TC",
            "heading": "선택 TC",
            "section": "list",
            "connected": True,
            "state": "ready",
            "dirty": False,
            "query": UiQueryState(query, "name", "", "", ""),
            "crumbs": (("선택 TC", f"/ui/projects/{project}/tcs"),),
            "list_href": f"/ui/projects/{project}/tcs",
            "detail_href": f"/ui/projects/{project}/tcs",
            "request": request,
            "project_id": str(project),
            "q": query,
            "items": items,
            "cases": cases,
            "selected_case": selected,
            "snapshot": snapshot,
            "proposals": proposals,
            "case_id": "" if selected is None else selected["case_id"],
            "head": "" if snapshot is None else snapshot["expected_head"],
        },
    )



def _case_choices(project, selected_id):
    from aiqa.domain.tcs import _bound_store
    with _bound_store().transaction() as connection:
        rows=connection.execute("""SELECT c.case_id,c.name,c.lock_version,v.version_id,v.content_hash
        FROM automation_cases c LEFT JOIN case_versions v ON v.project_id=c.project_id AND v.version_id=c.latest_draft_version_id
        WHERE c.project_id=? AND c.archived_at IS NULL ORDER BY c.name""",(str(project),)).fetchall()
    cases=[{'case_id':str(r[0]),'name':str(r[1]),'lock_version':int(r[2]),'version_id':r[3],'content_hash':r[4]} for r in rows]
    selected=next((item for item in cases if item['case_id']==selected_id),None)
    return cases,selected


def _check_tc_revision(project,tc_id,payload):
    if 'expected_revision' not in payload:
        return None
    from aiqa.domain.tcs import _bound_store
    row=_bound_store()._connection.execute("""SELECT v.revision FROM test_cases t JOIN tc_versions v
        ON v.project_id=t.project_id AND v.version_id=t.latest_version_id WHERE t.project_id=? AND t.tc_id=?""",(str(project),str(tc_id))).fetchone()
    if row is None:
        return _error(404,'not_found','tc was not found',{})
    if type(payload['expected_revision']) is not int or int(row[0]) != payload['expected_revision']:
        return _error(409,'conflict','TC revision changed',{})
    return None


def _check_case_revision(project,case_id,payload):
    if 'expected_revision' not in payload:
        return None
    from aiqa.domain.tcs import _bound_store
    row=_bound_store()._connection.execute('SELECT lock_version FROM automation_cases WHERE project_id=? AND case_id=?',(str(project),str(case_id))).fetchone()
    if row is None:
        return _error(404,'not_found','case was not found',{})
    if type(payload['expected_revision']) is not int or int(row[0]) != payload['expected_revision']:
        return _error(409,'conflict','case revision changed',{})
    return None


def _tc_rows(project: UUID, query: str) -> list[dict[str, object]]:
    from aiqa.domain.tcs import _bound_store

    needle = f"%{query}%"
    with _bound_store().transaction() as connection:
        rows = connection.execute(
            """
            SELECT test_cases.tc_id, test_cases.name, test_cases.archived_at,
                   tc_versions.version_id, tc_versions.revision, tc_versions.body_json
            FROM test_cases
            JOIN tc_versions
              ON tc_versions.project_id = test_cases.project_id
             AND tc_versions.version_id = test_cases.latest_version_id
            WHERE test_cases.project_id = ? AND test_cases.name LIKE ?
            ORDER BY test_cases.name
            """,
            (str(project), needle),
        ).fetchall()
    items: list[dict[str, object]] = []
    for row in rows:
        body = json.loads(str(row[5]))
        steps = body.get("steps", [])
        first = steps[0] if type(steps) is list and steps and type(steps[0]) is dict else {}
        items.append(
            {
                "tc_id": str(row[0]),
                "name": str(row[1]),
                "archived_at": None if row[2] is None else str(row[2]),
                "version_id": str(row[3]),
                "revision": int(row[4]),
                "raw_text": str(body.get("raw_text", "")),
                "instruction": str(first.get("instruction", "")),
                "expected": str(first.get("expected", "")),
                "body": body,
            }
        )
    return items


@router.post("/projects/{project_id}/tcs")
async def post_tc(project_id: str, request: Request) -> JSONResponse:
    return await _save(project_id, None, request)


@router.post("/projects/{project_id}/tcs/{tc_id}/versions")
async def post_tc_version(project_id: str, tc_id: str, request: Request) -> JSONResponse:
    return await _save(project_id, tc_id, request)


@router.post("/projects/{project_id}/tcs/{tc_id}/clone")
async def post_clone(project_id: str, tc_id: str, request: Request) -> JSONResponse:
    rejected = _idempotency(request)
    if rejected is not None:
        return rejected
    project = _uuid(project_id)
    parsed = _uuid(tc_id)
    if isinstance(project, JSONResponse) or isinstance(parsed, JSONResponse):
        return _error(404, "not_found", "tc was not found", {})
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    with _bound(request) as actor_box:
        try:
            actor_box.append(authorize_browser(request, project, "tc"))
            conflict = _check_tc_revision(project, parsed, payload)
            if conflict is not None:
                return conflict
            with bind_tc_actor(actor_box[0]):
                view = clone_tc(parsed)
        except _AUTH_ERRORS as exc:
            return _auth_response(exc)
    return JSONResponse(status_code=201, content=_tc_json(view))


@router.post("/projects/{project_id}/tcs/{tc_id}/archive")
async def post_archive(project_id: str, tc_id: str, request: Request) -> JSONResponse:
    rejected = _idempotency(request)
    if rejected is not None:
        return rejected
    project = _uuid(project_id)
    parsed = _uuid(tc_id)
    if isinstance(project, JSONResponse) or isinstance(parsed, JSONResponse):
        return _error(404, "not_found", "tc was not found", {})
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    with _bound(request) as actor_box:
        try:
            actor_box.append(authorize_browser(request, project, "tc"))
            conflict = _check_tc_revision(project, parsed, payload)
            if conflict is not None:
                return conflict
            with bind_tc_actor(actor_box[0]):
                view = archive_tc(parsed)
        except _AUTH_ERRORS as exc:
            return _auth_response(exc)
    return JSONResponse(status_code=200, content=_tc_json(view))


@router.put("/projects/{project_id}/cases/{case_id}/tc-reference")
async def put_reference(project_id: str, case_id: str, request: Request) -> JSONResponse:
    rejected = _idempotency(request)
    if rejected is not None:
        return rejected
    project = _uuid(project_id)
    parsed_case = _uuid(case_id)
    if isinstance(project, JSONResponse) or isinstance(parsed_case, JSONResponse):
        return _error(404, "not_found", "case was not found", {})
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    try:
        version_id = None if payload.get("tc_version_id") is None else UUID(str(payload.get("tc_version_id")))
    except ValueError:
        return _error(422, "validation", "invalid tc reference", {})
    with _bound(request) as actor_box:
        try:
            actor_box.append(authorize_browser(request, project, "tc"))
            conflict = _check_case_revision(project, parsed_case, payload)
            if conflict is not None:
                return conflict
            with bind_tc_actor(actor_box[0]):
                view = set_tc_reference(parsed_case, version_id)
        except _AUTH_ERRORS as exc:
            return _auth_response(exc)
    return JSONResponse(status_code=200, content=_case_json(view))


@router.get("/projects/{project_id}/cases/{case_id}/tc-reference")
async def get_reference(project_id: str, case_id: str, request: Request) -> JSONResponse:
    project = _uuid(project_id)
    parsed_case = _uuid(case_id)
    if isinstance(project, JSONResponse) or isinstance(parsed_case, JSONResponse):
        return _error(404, "not_found", "case was not found", {})
    with _bound(request) as actor_box:
        try:
            actor_box.append(authorize_browser(request, project, "tc"))
            with bind_tc_actor(actor_box[0]):
                view = read_tc_reference(parsed_case)
        except _AUTH_ERRORS as exc:
            return _auth_response(exc)
    return JSONResponse(status_code=200, content=_case_json(view))


@router.delete("/projects/{project_id}/cases/{case_id}/tc-reference")
async def delete_reference(project_id: str, case_id: str, request: Request) -> JSONResponse:
    rejected = _idempotency(request)
    if rejected is not None:
        return rejected
    project = _uuid(project_id)
    parsed_case = _uuid(case_id)
    if isinstance(project, JSONResponse) or isinstance(parsed_case, JSONResponse):
        return _error(404, "not_found", "case was not found", {})
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    with _bound(request) as actor_box:
        try:
            actor_box.append(authorize_browser(request, project, "tc"))
            conflict = _check_case_revision(project, parsed_case, payload)
            if conflict is not None:
                return conflict
            with bind_tc_actor(actor_box[0]):
                view = set_tc_reference(parsed_case, None)
        except _AUTH_ERRORS as exc:
            return _auth_response(exc)
    return JSONResponse(status_code=200, content=_case_json(view))


async def _save(project_id: str, tc_id: str | None, request: Request) -> JSONResponse:
    rejected = _idempotency(request)
    if rejected is not None:
        return rejected
    project = _uuid(project_id)
    parsed_tc = None if tc_id is None else _uuid(tc_id)
    if isinstance(project, JSONResponse) or isinstance(parsed_tc, JSONResponse):
        return _error(404, "not_found", "tc was not found", {})
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    body = payload.get("body")
    reason = payload.get("reason", "")
    name = payload.get("name", "")
    if type(body) is not dict or type(reason) is not str or type(name) is not str:
        return _error(422, "validation", "invalid tc", {})
    with _bound(request) as actor_box:
        try:
            actor_box.append(authorize_browser(request, project, "tc"))
            view = save_tc_revision(
                TcRevisionInput(
                    project_id=project,
                    actor_id=actor_box[0].actor_id,
                    name=name if name.strip() != "" else "TC",
                    body=body,
                    tc_id=parsed_tc,
                    reason=reason,
                )
            )
        except _AUTH_ERRORS as exc:
            return _auth_response(exc)
        except ValueError:
            return _error(422, "validation", "invalid tc", {})
    return JSONResponse(status_code=201, content=_tc_json(view))


@contextmanager
def _bound(request: Request) -> Iterator[list[object]]:
    store = request.app.state.open_store()
    actor_box: list[object] = []
    try:
        migrate_store(store)
        with bind_case_store(store):
            with bind_tc_store(store):
                with bound_auth_store(store):
                    yield actor_box
    finally:
        store.close()


def _tc_json(view: TcVersionView) -> dict[str, object]:
    return {
        "project_id": str(view.project_id),
        "tc_id": str(view.tc_id),
        "id": str(view.id),
        "revision": view.revision,
        "name": view.name,
        "content_hash": view.content_hash,
        "archived_at": view.archived_at,
    }


def _case_json(view: CaseMetadataView) -> dict[str, object]:
    return {
        "project_id": str(view.project_id),
        "case_id": str(view.case_id),
        "name": view.name,
        "tc_reference": None if view.tc_reference is None else str(view.tc_reference),
        "current_approval_id": None if view.current_approval_id is None else str(view.current_approval_id),
        "latest_draft_version_id": None if view.latest_draft_version_id is None else str(view.latest_draft_version_id),
        "lock_version": view.lock_version,
    }


_AUTH_ERRORS = (CsrfRejected, OriginRejected, ProjectHidden, CaseNotFound, TcNotFound, ForeignTc, AuthRequired, ValueError)


def _auth_response(exc: Exception) -> JSONResponse:
    if isinstance(exc, CsrfRejected | OriginRejected):
        return _error(403, "permission", "request was rejected", {})
    if isinstance(exc, AuthRequired):
        return _error(401, "unauthorized", "session is missing", {})
    if isinstance(exc, ValueError):
        return _error(422, "validation", "invalid tc", {})
    return _error(404, "not_found", "tc was not found", {})


async def _body(request: Request) -> dict[str, object] | JSONResponse:
    try:
        payload = await request.json() if await request.body() else {}
    except Exception:
        return _error(422, "validation", "body must be JSON", {"body": ["invalid"]})
    if type(payload) is not dict:
        return _error(422, "validation", "body must be an object", {"body": ["invalid"]})
    return payload


def _uuid(value: str) -> UUID | JSONResponse:
    try:
        return UUID(value)
    except ValueError:
        return _error(404, "not_found", "tc was not found", {})


def _idempotency(request: Request) -> JSONResponse | None:
    if not request.headers.get("idempotency-key"):
        return _error(422, "validation", "Idempotency-Key is required", {"Idempotency-Key": ["required"]})
    return None


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
