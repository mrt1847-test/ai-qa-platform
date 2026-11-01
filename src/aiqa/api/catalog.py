"""Project catalog routes. Route installation does not open SQLite."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID, uuid4

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
    bound_auth_store,
)
from aiqa.domain.catalog import (
    CatalogNotFound,
    FolderCycle,
    ProjectOverview,
    bind_catalog_actor,
    bind_catalog_store,
    create_folder,
    create_tag,
    project_overview,
    update_folder,
)
from aiqa.domain.projects import (
    ProjectConflict,
    ProjectScopeDenied,
    ProjectValidationError,
    archive_project,
    bind_store,
    create_project,
    get_audit,
    get_project,
    link_audit,
    list_projects,
    restore_project,
)
from aiqa.web.routes import UiQueryState, render_template
from aiqa.store.database import migrate_store
from aiqa.store.models import Actor, ProjectCreate, ProjectView

router = APIRouter(prefix="/api/v1", route_class=BrowserMutationRoute)
pages = APIRouter(route_class=BrowserMutationRoute)


def install_catalog(application: FastAPI) -> None:
    """Attach completed project routes lazily to the product app."""

    if getattr(application.state, "catalog_installed", False):
        return
    application.include_router(router)
    application.include_router(pages)
    application.state.catalog_installed = True


taxonomy = APIRouter(prefix="/api/v1", route_class=BrowserMutationRoute)


def install_taxonomy(application: FastAPI) -> None:
    """Attach folder and tag routes once. This does not mount project creation."""

    if getattr(application.state, "taxonomy_installed", False):
        return
    application.include_router(taxonomy)
    application.state.taxonomy_installed = True


@router.get("/projects/{project_id}/overview")
async def get_overview(project_id: str, request: Request) -> JSONResponse:
    try:
        parsed = UUID(project_id)
    except ValueError:
        return _error(404, "not_found", "project was not found", {})
    with _bound(request):
        overview = project_overview(parsed)
    if overview is None:
        return _error(404, "not_found", "project was not found", {})
    return JSONResponse(status_code=200, content=_overview_json(overview))


@pages.get("/ui/projects/{project_id}/overview", response_class=HTMLResponse)
async def overview_page(project_id: str, request: Request) -> HTMLResponse:
    return await _overview_screen(project_id, request, "overview")


@pages.get("/ui/projects/{project_id}/recordings/new", response_class=HTMLResponse)
async def recording_step_page(project_id: str, request: Request) -> HTMLResponse:
    from fastapi.responses import RedirectResponse
    from urllib.parse import urlencode
    query = {key: request.query_params[key] for key in ("resource_id", "case", "base_version") if key in request.query_params}
    suffix = "?" + urlencode(query) if query else ""
    return RedirectResponse(f"/ui/projects/{project_id}/recordings/wizard{suffix}", status_code=303)


@pages.get("/ui/projects/{project_id}/bundles", response_class=HTMLResponse)
async def bundle_page(project_id: str, request: Request) -> HTMLResponse:
    return await _overview_screen(project_id, request, "bundles")


@router.get("/projects")
async def get_projects(request: Request) -> JSONResponse:
    archived = request.query_params.get("archived") == "true"
    query = request.query_params.get("q", "")
    if type(query) is not str:
        query = ""
    with _bound(request):
        items = list_projects(archived, query)
    return JSONResponse(status_code=200, content={"items": [_view_json(item) for item in items]})


@router.post("/projects/{project_id}/archive")
async def post_archive(project_id: str, request: Request) -> JSONResponse:
    return await _archive_change(project_id, request, archive_project)


@router.post("/projects/{project_id}/restore")
async def post_restore(project_id: str, request: Request) -> JSONResponse:
    return await _archive_change(project_id, request, restore_project)


@pages.get("/ui/projects", response_class=HTMLResponse)
async def project_page(request: Request) -> HTMLResponse:
    archived = request.query_params.get("archived") == "true"
    query = request.query_params.get("q", "")
    if type(query) is not str:
        query = ""
    with _bound(request):
        items = list_projects(archived, query)
    return render_template(
        request,
        "projects.html",
        _page_context(request, "프로젝트", "empty" if items == () else "ready", items, query, archived),
    )


@pages.get("/ui/projects/{project_id}/environment", response_class=HTMLResponse)
async def environment_page(project_id: str, request: Request) -> HTMLResponse:
    try:
        parsed = UUID(project_id)
    except ValueError:
        return HTMLResponse(status_code=404, content="프로젝트를 찾지 못했습니다.")
    with _bound(request):
        project = get_project(parsed)
    if project is None:
        return HTMLResponse(status_code=404, content="프로젝트를 찾지 못했습니다.")
    context = _page_context(request, "환경 준비", "ready", (project,), "", False)
    context["project"] = project
    return render_template(request, "environment.html", context)


@router.post("/projects")
async def post_project(request: Request) -> JSONResponse:
    if not request.headers.get("idempotency-key"):
        return _error(422, "validation", "Idempotency-Key is required", {"Idempotency-Key": ["required"]})
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    try:
        actor = getattr(request.state, "browser_actor", None) or _actor(payload.get("actor"))
        project = ProjectCreate(
            name=_text(payload, "name"),
            key=_text(payload, "key"),
            description=_text(payload, "description", allow_empty=True),
            target=_text(payload, "target"),
        )
    except ProjectValidationError as exc:
        return _error(422, "validation", "invalid project", exc.fields)
    with _bound(request):
        try:
            view = create_project(actor, project)
        except ProjectConflict:
            return _error(409, "conflict", "project key already exists", {"key": ["duplicate"]})
        except ProjectValidationError as exc:
            return _error(422, "validation", "invalid project", exc.fields)
    return JSONResponse(status_code=201, content=_view_json(view))


@router.get("/projects/{project_id}/audits/{audit_id}")
async def read_audit(project_id: str, audit_id: str, request: Request) -> JSONResponse:
    parsed = _pair(project_id, audit_id)
    if isinstance(parsed, JSONResponse):
        return parsed
    project, audit = parsed
    with _bound(request):
        row = get_audit(project, audit)
    if row is None:
        return _error(404, "not_found", "audit was not found", {})
    return JSONResponse(status_code=200, content=row)


@router.post("/projects/{project_id}/audits/{audit_id}/links")
async def post_link(project_id: str, audit_id: str, request: Request) -> JSONResponse:
    if not request.headers.get("idempotency-key"):
        return _error(422, "validation", "Idempotency-Key is required", {"Idempotency-Key": ["required"]})
    parsed = _pair(project_id, audit_id)
    if isinstance(parsed, JSONResponse):
        return parsed
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    project, audit = parsed
    try:
        note = _text(payload, "note")
    except ProjectValidationError as exc:
        return _error(422, "validation", "invalid link", exc.fields)
    with _bound(request):
        try:
            link_audit(project, audit, note)
        except ProjectScopeDenied:
            return _error(404, "not_found", "audit was not found", {})
        except ProjectValidationError as exc:
            return _error(422, "validation", "invalid link", exc.fields)
    return JSONResponse(status_code=201, content={"project_id": str(project), "audit_id": str(audit)})


@contextmanager
def _bound(request: Request) -> Iterator[None]:
    store = request.app.state.open_store()
    try:
        migrate_store(store)
        with bind_store(store):
            with bind_catalog_store(store):
                yield
    finally:
        store.close()


async def _body(request: Request) -> dict[str, object] | JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        return _error(422, "validation", "body must be JSON", {"body": ["invalid"]})
    if type(payload) is not dict:
        return _error(422, "validation", "body must be an object", {"body": ["invalid"]})
    return payload


def _pair(project_id: str, audit_id: str) -> tuple[UUID, UUID] | JSONResponse:
    try:
        return UUID(project_id), UUID(audit_id)
    except ValueError:
        return _error(404, "not_found", "audit was not found", {})


def _actor(value: object) -> Actor:
    if type(value) is not dict:
        raise ProjectValidationError({"actor": ["required"]})
    try:
        actor_id = UUID(str(value.get("actor_id")))
    except (TypeError, ValueError) as exc:
        raise ProjectValidationError({"actor_id": ["invalid"]}) from exc
    scope = value.get("project_scope")
    if scope is not None:
        try:
            project_scope = UUID(str(scope))
        except (TypeError, ValueError) as exc:
            raise ProjectValidationError({"project_scope": ["invalid"]}) from exc
    else:
        project_scope = None
    if type(value.get("is_local_owner")) is not bool:
        raise ProjectValidationError({"is_local_owner": ["required"]})
    return Actor(
        actor_id=actor_id,
        project_scope=project_scope,
        is_local_owner=bool(value.get("is_local_owner")),
    )


def _text(payload: dict[str, object], field: str, allow_empty: bool = False) -> str:
    value = payload.get(field)
    if type(value) is not str or (not allow_empty and value.strip() == ""):
        raise ProjectValidationError({field: ["required"]})
    return value


def _view_json(view: ProjectView) -> dict[str, object]:
    return {
        "project_id": str(view.project_id),
        "name": view.name,
        "key": view.key,
        "description": view.description,
        "target": view.target,
        "commit_seq": view.commit_seq,
        "audit_id": str(view.audit_id),
        "archived_at": view.archived_at,
        "case_count": view.case_count,
        "review_count": view.review_count,
        "run_count": view.run_count,
    }


async def _archive_change(project_id: str, request: Request, change) -> JSONResponse:
    if not request.headers.get("idempotency-key"):
        return _error(422, "validation", "Idempotency-Key is required", {"Idempotency-Key": ["required"]})
    try:
        parsed = UUID(project_id)
    except ValueError:
        return _error(404, "not_found", "project was not found", {})
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    try:
        actor = getattr(request.state, "browser_actor", None) or _actor(payload.get("actor"))
    except ProjectValidationError as exc:
        return _error(422, "validation", "invalid project", exc.fields)
    with _bound(request):
        try:
            view = change(actor, parsed)
        except ProjectScopeDenied:
            return _error(404, "not_found", "project was not found", {})
        except ProjectConflict as exc:
            return _error(409, "conflict", str(exc), {"project": ["rejected"]})
    return JSONResponse(status_code=200, content=_view_json(view))


def _overview_json(overview: ProjectOverview) -> dict[str, object]:
    return {
        "project_id": str(overview.project_id),
        "incomplete_recordings": overview.incomplete_recordings,
        "reviews_waiting": overview.reviews_waiting,
        "unclassified_failures": overview.unclassified_failures,
        "running_runs": overview.running_runs,
        "queued_runs": overview.queued_runs,
        "blocked_environments": overview.blocked_environments,
        "draft_cases": overview.draft_cases,
        "approved_cases": overview.approved_cases,
        "recent_scope": overview.recent_scope,
        "recent_result": overview.recent_result,
        "new_recording_href": overview.new_recording_href,
        "saved_cases_href": overview.saved_cases_href,
        "bundle_href": overview.bundle_href,
    }


async def _overview_screen(project_id: str, request: Request, step: str) -> HTMLResponse:
    try:
        parsed = UUID(project_id)
    except ValueError:
        return HTMLResponse(status_code=404, content="프로젝트를 찾지 못했습니다.")
    with _bound(request):
        overview = project_overview(parsed)
    if overview is None:
        return HTMLResponse(status_code=404, content="프로젝트를 찾지 못했습니다.")
    context = _page_context(request, "프로젝트 개요", "ready", (), "", False)
    context["overview"] = overview
    context["step"] = step
    context['crumbs'] = (('개요',''),)
    return render_template(request, "overview.html", context)


def _page_context(
    request: Request,
    heading: str,
    state: str,
    items: tuple[ProjectView, ...],
    query: str,
    archived: bool,
) -> dict[str, object]:
    return {
        "shell": True,
        "title": heading,
        "heading": heading,
        "section": "list",
        "connected": True,
        "state": state,
        "dirty": False,
        "query": UiQueryState(query, "name", "", "", ""),
        "crumbs": (("프로젝트", "/ui/projects"),),
        "list_href": "/ui/projects",
        "detail_href": "/ui/projects",
        "items": items,
        "q": query,
        "archived": archived,
        "request": request,
    }


@taxonomy.post("/projects/{project_id}/folders")
async def post_folder(project_id: str, request: Request) -> JSONResponse:
    return await _folder(project_id, None, request)


@taxonomy.patch("/projects/{project_id}/folders/{folder_id}")
async def patch_folder(project_id: str, folder_id: str, request: Request) -> JSONResponse:
    return await _folder(project_id, folder_id, request)


@taxonomy.post("/projects/{project_id}/tags")
async def post_tag(project_id: str, request: Request) -> JSONResponse:
    if not request.headers.get("idempotency-key"):
        return _error(422, "validation", "Idempotency-Key is required", {"Idempotency-Key": ["required"]})
    project = _taxonomy_uuid(project_id)
    if isinstance(project, JSONResponse):
        return project
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    name = payload.get("name")
    if type(name) is not str:
        return _error(422, "validation", "invalid tag", {})
    with _taxonomy_bound(request):
        try:
            actor = authorize_browser(request, project, "folder")
            with bind_catalog_actor(actor):
                tag_id = create_tag(name)
        except (CsrfRejected, OriginRejected, ProjectHidden, AuthRequired, CatalogNotFound, ValueError) as exc:
            return _taxonomy_error(exc)
    return JSONResponse(status_code=201, content={"tag_id": str(tag_id), "name": name})


async def _folder(project_id: str, folder_id: str | None, request: Request) -> JSONResponse:
    if not request.headers.get("idempotency-key"):
        return _error(422, "validation", "Idempotency-Key is required", {"Idempotency-Key": ["required"]})
    project = _taxonomy_uuid(project_id)
    parsed = None if folder_id is None else _taxonomy_uuid(folder_id)
    if isinstance(project, JSONResponse) or isinstance(parsed, JSONResponse):
        return _error(404, "not_found", "folder was not found", {})
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    name = payload.get("name", "")
    parent = payload.get("parent_folder_id")
    if type(name) is not str:
        return _error(422, "validation", "invalid folder", {})
    try:
        parent_id = None if parent is None else UUID(str(parent))
    except ValueError:
        return _error(422, "validation", "invalid folder", {})
    with _taxonomy_bound(request):
        try:
            actor = authorize_browser(request, project, "folder")
            with bind_catalog_actor(actor):
                if parsed is None:
                    created = create_folder(name, parent_id)
                else:
                    update_folder(parsed, parent_id)
                    created = parsed
        except (CsrfRejected, OriginRejected, ProjectHidden, AuthRequired, CatalogNotFound, FolderCycle, ValueError) as exc:
            return _taxonomy_error(exc)
    return JSONResponse(
        status_code=201 if folder_id is None else 200,
        content={"folder_id": str(created), "name": name},
    )


@contextmanager
def _taxonomy_bound(request: Request) -> Iterator[None]:
    store = request.app.state.open_store()
    try:
        migrate_store(store)
        with bind_store(store):
            with bind_catalog_store(store):
                with bound_auth_store(store):
                    yield
    finally:
        store.close()


def _taxonomy_uuid(value: str) -> UUID | JSONResponse:
    try:
        return UUID(value)
    except ValueError:
        return _error(404, "not_found", "folder was not found", {})


def _taxonomy_error(exc: Exception) -> JSONResponse:
    if isinstance(exc, CsrfRejected | OriginRejected):
        return _error(403, "permission", "request was rejected", {})
    if isinstance(exc, AuthRequired):
        return _error(401, "unauthorized", "session is missing", {})
    if isinstance(exc, FolderCycle):
        return _error(422, "validation", "folder parent cycles", {})
    if isinstance(exc, ValueError):
        return _error(422, "validation", "invalid folder", {})
    return _error(404, "not_found", "folder was not found", {})


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
