"""Suite list routes. These routes do not open a device or a model."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.routing import APIRouter

from aiqa.api.auth import (
    AuthRequired,
    CsrfRejected,
    OriginRejected,
    ProjectHidden,
    authorize_browser,
    authorize_page,
    bound_auth_store,
)
from aiqa.domain.suites import (
    SuiteConflict,
    SuiteEntry,
    SuiteRejected,
    SuiteVersionView,
    SuiteView,
    UpgradeProposal,
    archive_suite,
    clone_suite,
    create_suite,
    decide_suite_upgrade,
    list_suites,
    list_upgrade_proposals,
    refuse_empty_execution,
    save_suite_revision,
    suite_editor,
)
from aiqa.store.database import migrate_store
from aiqa.store.models import Transaction
from aiqa.web.routes import render_template

router = APIRouter(prefix="/api/v1")
pages = APIRouter()


def install_suites(application: FastAPI) -> None:
    """Attach suite routes once. This does not open SQLite."""

    if getattr(application.state, "suites_installed", False):
        return
    application.include_router(router)
    application.include_router(pages)
    application.state.suites_installed = True


@router.get("/projects/{project_id}/suites")
async def get_suites(project_id: str, request: Request) -> JSONResponse:
    project = _uuid(project_id)
    if isinstance(project, JSONResponse):
        return project
    with _bound(request) as store:
        try:
            actor = authorize_browser(request, project, "read_suites")
        except CsrfRejected:
            return _error(403, "permission", "csrf token was rejected", {})
        except OriginRejected:
            return _error(403, "permission", "origin was rejected", {})
        except ProjectHidden:
            return _error(404, "not_found", "suite was not found", {})
        except AuthRequired:
            return _error(401, "unauthorized", "session is missing", {})
        with store.transaction() as connection:
            views = list_suites(Transaction(connection), actor, project, dict(request.query_params))
    return JSONResponse(status_code=200, content={"items": [_view_json(item) for item in views]})


@router.post("/projects/{project_id}/suites")
async def post_suite(project_id: str, request: Request) -> JSONResponse:
    rejected = _idempotency(request)
    if rejected is not None:
        return rejected
    project = _uuid(project_id)
    if isinstance(project, JSONResponse):
        return project
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    with _bound(request) as store:
        try:
            actor = authorize_browser(request, project, "create_suite")
            with store.transaction() as connection:
                view = create_suite(
                    Transaction(connection),
                    actor,
                    project,
                    payload,
                    request.headers.get("idempotency-key", "").strip(),
                )
        except CsrfRejected:
            return _error(403, "permission", "csrf token was rejected", {})
        except OriginRejected:
            return _error(403, "permission", "origin was rejected", {})
        except ProjectHidden:
            return _error(404, "not_found", "suite was not found", {})
        except AuthRequired:
            return _error(401, "unauthorized", "session is missing", {})
        except SuiteConflict:
            return _error(409, "conflict", "idempotency body does not match", {})
        except SuiteRejected as exc:
            message = str(exc) or "suite is not ready"
            fields: dict[str, list[str]] = {}
            if "name" in message:
                fields = {"name": ["required"]}
            elif "target" in message:
                fields = {"target_kind": ["invalid"]}
            elif "body" in message:
                fields = {"description": ["invalid"], "owner_name": ["invalid"], "classification": ["invalid"]}
            return _error(422, "validation", message, fields)
    return JSONResponse(status_code=200 if view.replayed else 201, content=_view_json(view))


@router.post("/suites/{suite_id}/clone")
async def post_clone(suite_id: str, request: Request) -> JSONResponse:
    return await _command(suite_id, request, "clone_suite", clone_suite)


@router.post("/suites/{suite_id}/archive")
async def post_archive(suite_id: str, request: Request) -> JSONResponse:
    return await _command(suite_id, request, "archive_suite", archive_suite)


@router.post("/suites/{suite_id}/executions")
async def post_suite_execution(suite_id: str, request: Request) -> JSONResponse:
    rejected = _idempotency(request)
    if rejected is not None:
        return rejected
    parsed = _uuid(suite_id)
    payload = await _body(request)
    if isinstance(parsed, JSONResponse) or isinstance(payload, JSONResponse):
        return _error(404, "not_found", "suite was not found", {})
    project = _uuid(str(payload.get("project_id", "")))
    if isinstance(project, JSONResponse):
        return _error(404, "not_found", "suite was not found", {})
    with _bound(request) as store:
        try:
            actor = authorize_browser(request, project, "execute_suite")
            with store.transaction() as connection:
                refuse_empty_execution(Transaction(connection), actor, project, parsed)
        except CsrfRejected:
            return _error(403, "permission", "csrf token was rejected", {})
        except OriginRejected:
            return _error(403, "permission", "origin was rejected", {})
        except ProjectHidden:
            return _error(404, "not_found", "suite was not found", {})
        except AuthRequired:
            return _error(401, "unauthorized", "session is missing", {})
        except SuiteRejected:
            return _error(422, "validation", "empty suite cannot run", {})
    return _error(422, "validation", "empty suite cannot run", {})


@router.post("/suites/{suite_id}/versions")
async def post_suite_version(suite_id: str, request: Request) -> JSONResponse:
    rejected = _idempotency(request)
    if rejected is not None:
        return rejected
    parsed = _uuid(suite_id)
    payload = await _body(request)
    if isinstance(parsed, JSONResponse) or isinstance(payload, JSONResponse):
        return _error(404, "not_found", "suite was not found", {})
    project = _uuid(str(payload.get("project_id", "")))
    if isinstance(project, JSONResponse):
        return _error(404, "not_found", "suite was not found", {})
    with _bound(request) as store:
        try:
            actor = authorize_browser(request, project, "edit_suite")
            command = decide_suite_upgrade if payload.get("decision") in {"accept", "reject"} else save_suite_revision
            with store.transaction() as connection:
                saved = command(
                    Transaction(connection),
                    actor,
                    project,
                    parsed,
                    payload,
                    request.headers.get("idempotency-key", "").strip(),
                )
        except CsrfRejected:
            return _error(403, "permission", "csrf token was rejected", {})
        except OriginRejected:
            return _error(403, "permission", "origin was rejected", {})
        except ProjectHidden:
            return _error(404, "not_found", "suite was not found", {})
        except AuthRequired:
            return _error(401, "unauthorized", "session is missing", {})
        except SuiteConflict:
            return _error(409, "conflict", "suite command conflicts", {})
        except SuiteRejected as exc:
            if exc.args and exc.args[0] == "suite was not found":
                return _error(404, "not_found", "suite was not found", {})
            return _error(422, "validation", "suite revision was rejected", {})
    status = 200 if saved.replayed or payload.get("decision") == "reject" else 201
    return JSONResponse(status_code=status, content=_version_json(saved))


@router.get("/suites/{suite_id}/upgrade-proposals")
async def get_upgrade_proposals(suite_id: str, request: Request) -> JSONResponse:
    parsed = _uuid(suite_id)
    project = _uuid(str(request.query_params.get("project_id", "")))
    if isinstance(parsed, JSONResponse) or isinstance(project, JSONResponse):
        return _error(404, "not_found", "suite was not found", {})
    with _bound(request) as store:
        try:
            actor = authorize_browser(request, project, "read_suites")
            with store.transaction() as connection:
                proposals = list_upgrade_proposals(Transaction(connection), actor, project, parsed)
        except CsrfRejected:
            return _error(403, "permission", "csrf token was rejected", {})
        except OriginRejected:
            return _error(403, "permission", "origin was rejected", {})
        except ProjectHidden:
            return _error(404, "not_found", "suite was not found", {})
        except AuthRequired:
            return _error(401, "unauthorized", "session is missing", {})
        except SuiteRejected:
            return _error(404, "not_found", "suite was not found", {})
    return JSONResponse(status_code=200, content={"items": [_proposal_json(item) for item in proposals]})


@pages.get("/ui/projects/{project_id}/suites", response_class=HTMLResponse)
async def suites_page(project_id: str, request: Request) -> HTMLResponse:
    project = _uuid(project_id)
    if isinstance(project, JSONResponse):
        return HTMLResponse(status_code=404, content="묶음을 찾지 못했습니다.")
    with _bound(request) as store:
        try:
            actor = authorize_page(request, project)
        except (AuthRequired, OriginRejected, ProjectHidden):
            return HTMLResponse(status_code=403, content="이 화면을 볼 권한이 없습니다.")
        with store.transaction() as connection:
            views = list_suites(Transaction(connection), actor, project, dict(request.query_params))
    return render_template(
        request,
        "suites.html",
        {
            "shell": False,
            "project_id": str(project),
            "query": request.query_params.get("q", ""),
            "suites": [_view_json(item) for item in views],
            "crumbs": (("테스트 묶음", ""),),
        },
    )


@pages.get("/ui/projects/{project_id}/suites/{suite_id}", response_class=HTMLResponse)
async def suite_editor_page(project_id: str, suite_id: str, request: Request) -> HTMLResponse:
    project = _uuid(project_id)
    parsed = _uuid(suite_id)
    if isinstance(project, JSONResponse) or isinstance(parsed, JSONResponse):
        return HTMLResponse(status_code=404, content="묶음을 찾지 못했습니다.")
    with _bound(request) as store:
        try:
            actor = authorize_page(request, project)
            with store.transaction() as connection:
                name, version_id, cases, entries, proposals = suite_editor(
                    Transaction(connection), actor, project, parsed, str(request.query_params.get("q", ""))
                )
        except (AuthRequired, OriginRejected, ProjectHidden, SuiteRejected):
            return HTMLResponse(status_code=404, content="묶음을 찾지 못했습니다.")
    return render_template(
        request,
        "suite_editor.html",
        {
            "shell": False,
            "project_id": str(project),
            "suite_id": str(parsed),
            "name": name,
            "version_id": str(version_id),
            "query": request.query_params.get("q", ""),
            "cases": cases,
            "entries": entries,
            "proposals": proposals,
            "crumbs": (("테스트 묶음", f"/ui/projects/{project}/suites"), ("구성", "")),
        },
    )


@pages.get("/ui/projects/{project_id}/suites/{suite_id}/execution-setup", response_class=HTMLResponse)
async def suite_execution_page(project_id: str, suite_id: str, request: Request) -> HTMLResponse:
    """Read the saved suite head; GET never previews, queues, or changes a suite."""
    project = _uuid(project_id)
    parsed = _uuid(suite_id)
    if isinstance(project, JSONResponse) or isinstance(parsed, JSONResponse):
        return HTMLResponse(status_code=404, content="묶음을 찾지 못했습니다.")
    with _bound(request) as store:
        try:
            actor = authorize_page(request, project)
            with store.transaction() as connection:
                name, version_id, _, entries, _ = suite_editor(
                    Transaction(connection), actor, project, parsed, ""
                )
        except (AuthRequired, OriginRejected, ProjectHidden, SuiteRejected):
            return HTMLResponse(status_code=404, content="묶음을 찾지 못했습니다.")
    return render_template(
        request,
        "suite_execution.html",
        {
            "shell": False,
            "project_id": str(project),
            "suite_id": str(parsed),
            "name": name,
            "version_id": str(version_id),
            "entries": entries,
        },
    )


async def _command(suite_id: str, request: Request, operation: str, command: object) -> JSONResponse:
    rejected = _idempotency(request)
    if rejected is not None:
        return rejected
    parsed = _uuid(suite_id)
    payload = await _body(request)
    if isinstance(parsed, JSONResponse) or isinstance(payload, JSONResponse):
        return _error(404, "not_found", "suite was not found", {})
    project = _uuid(str(payload.get("project_id", "")))
    if isinstance(project, JSONResponse):
        return _error(404, "not_found", "suite was not found", {})
    with _bound(request) as store:
        try:
            actor = authorize_browser(request, project, operation)
            with store.transaction() as connection:
                view = command(  # type: ignore[operator]
                    Transaction(connection),
                    actor,
                    project,
                    parsed,
                    payload,
                    request.headers.get("idempotency-key", "").strip(),
                )
        except CsrfRejected:
            return _error(403, "permission", "csrf token was rejected", {})
        except OriginRejected:
            return _error(403, "permission", "origin was rejected", {})
        except ProjectHidden:
            return _error(404, "not_found", "suite was not found", {})
        except AuthRequired:
            return _error(401, "unauthorized", "session is missing", {})
        except SuiteConflict:
            return _error(409, "conflict", "idempotency body does not match", {})
        except SuiteRejected:
            return _error(404, "not_found", "suite was not found", {})
    assert isinstance(view, SuiteView)
    status = 200 if view.replayed or operation == "archive_suite" else 201
    return JSONResponse(status_code=status, content=_view_json(view))


def _proposal_json(item: UpgradeProposal) -> dict[str, object]:
    return {
        "entry_id": item.entry_id,
        "case_id": str(item.case_id),
        "from_version_id": str(item.from_version_id),
        "from_approval_id": item.from_approval_id,
        "to_version_id": str(item.to_version_id),
        "to_approval_id": item.to_approval_id,
        "definition_from": item.definition_from,
        "definition_to": item.definition_to,
        "procedure_from": item.procedure_from,
        "procedure_to": item.procedure_to,
        "policy_from": item.policy_from,
        "policy_to": item.policy_to,
    }


def _version_json(view: SuiteVersionView) -> dict[str, object]:
    return {
        "suite_id": str(view.suite_id),
        "suite_version_id": str(view.suite_version_id),
        "previous_version_id": None if view.previous_version_id is None else str(view.previous_version_id),
        "content_hash": view.content_hash,
        "entries": [_entry_json(item) for item in view.entries],
        "replayed": view.replayed,
    }


def _entry_json(item: SuiteEntry) -> dict[str, object]:
    return {
        "entry_id": item.entry_id,
        "case_id": str(item.case_id),
        "case_version_id": str(item.case_version_id),
        "approval_id": item.approval_id,
        "data_name": item.data_name,
        "environment_revision_id": item.environment_revision_id,
        "reset_policy": item.reset_policy,
        "failure_policy": item.failure_policy,
        "resource_id": item.resource_id,
        "target_kind": item.target_kind,
        "position": item.position,
    }


def _view_json(view: SuiteView) -> dict[str, object]:
    return {
        "suite_id": str(view.suite_id),
        "name": view.name,
        "description": view.description,
        "target_kind": view.target_kind,
        "owner_name": view.owner_name,
        "classification": view.classification,
        "entry_count": view.entry_count,
        "latest_run_id": None if view.latest_run_id is None else str(view.latest_run_id),
        "latest_run_at": view.latest_run_at,
        "updated_at": view.updated_at,
        "archived_at": view.archived_at,
        "version_id": None if view.version_id is None else str(view.version_id),
        "history": [
            {
                "suite_version_id": str(item.suite_version_id),
                "content_hash": item.content_hash,
                "entry_count": item.entry_count,
            }
            for item in view.history
        ],
        "replayed": view.replayed,
    }


@contextmanager
def _bound(request: Request) -> Iterator[object]:
    store = request.app.state.open_store()
    try:
        migrate_store(store)
        with bound_auth_store(store):
            yield store
    finally:
        store.close()


async def _body(request: Request) -> dict[str, object] | JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        return _error(422, "validation", "body must be JSON", {})
    if type(payload) is not dict:
        return _error(422, "validation", "body must be an object", {})
    return payload


def _uuid(value: str) -> UUID | JSONResponse:
    try:
        return UUID(value)
    except ValueError:
        return _error(404, "not_found", "suite was not found", {})


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
