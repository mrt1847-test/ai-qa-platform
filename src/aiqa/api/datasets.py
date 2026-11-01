"""Dataset list, versions, and the data editor. Responses do not include secret text."""

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
from aiqa.domain.datasets import (
    DatasetNotFound,
    ForeignSecret,
    bind_dataset_store,
    list_datasets,
    read_dataset_version,
    save_dataset_revision,
)
from aiqa.store.database import migrate_store
from aiqa.store.models import DatasetRevisionInput, SecretRef
from aiqa.web.routes import UiQueryState, render_template

router = APIRouter(prefix="/api/v1")
pages = APIRouter()


def install_datasets(application: FastAPI) -> None:
    """Attach dataset routes. This does not open SQLite."""

    if getattr(application.state, "datasets_installed", False):
        return
    application.include_router(router)
    application.include_router(pages)
    application.state.datasets_installed = True


@router.get("/projects/{project_id}/datasets")
async def get_datasets(project_id: str, request: Request) -> JSONResponse:
    project = _uuid(project_id)
    if isinstance(project, JSONResponse):
        return project
    with _bound(request):
        try:
            authorize_browser(request, project, "dataset")
            items = list_datasets(project)
        except (CsrfRejected, OriginRejected):
            return _error(403, "permission", "request was rejected")
        except AuthRequired:
            return _error(401, "unauthorized", "session is missing")
        except ProjectHidden:
            return _error(404, "not_found", "dataset was not found")
    return JSONResponse(status_code=200, content={"datasets": items})


@router.get("/projects/{project_id}/datasets/{dataset_id}/versions/{version_id}")
async def get_dataset_version(project_id: str, dataset_id: str, version_id: str, request: Request) -> JSONResponse:
    project = _uuid(project_id)
    parsed_dataset = _uuid(dataset_id)
    parsed_version = _uuid(version_id)
    if isinstance(project, JSONResponse) or isinstance(parsed_dataset, JSONResponse) or isinstance(parsed_version, JSONResponse):
        return _error(404, "not_found", "dataset was not found")
    with _bound(request):
        try:
            authorize_browser(request, project, "dataset")
            view = read_dataset_version(project, parsed_dataset, parsed_version)
        except DatasetNotFound:
            return _error(404, "not_found", "dataset was not found")
        except (CsrfRejected, OriginRejected):
            return _error(403, "permission", "request was rejected")
        except AuthRequired:
            return _error(401, "unauthorized", "session is missing")
        except ProjectHidden:
            return _error(404, "not_found", "dataset was not found")
    return JSONResponse(status_code=200, content=view)


@router.post("/datasets/{dataset_id}/versions")
async def post_dataset_version(dataset_id: str, request: Request) -> JSONResponse:
    if not request.headers.get("idempotency-key"):
        return _error(422, "validation", "Idempotency-Key is required")
    parsed = _uuid(dataset_id)
    if isinstance(parsed, JSONResponse):
        return _error(404, "not_found", "dataset was not found")
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    project = _uuid(str(payload.get("project_id", "")))
    if isinstance(project, JSONResponse):
        return _error(422, "validation", "invalid dataset")
    try:
        revision = _revision(project, parsed, payload)
    except ValueError:
        return _error(422, "validation", "invalid dataset")
    with _bound(request):
        try:
            actor = authorize_browser(request, project, "dataset")
            view = save_dataset_revision(
                DatasetRevisionInput(
                    project_id=project,
                    actor_id=actor.actor_id,
                    name=revision.name,
                    row_schema=revision.row_schema,
                    rows=revision.rows,
                    dataset_id=parsed,
                    secret_ref=revision.secret_ref,
                    case_id=revision.case_id,
                )
            )
        except ForeignSecret:
            return _error(404, "not_found", "secret ref was not found")
        except (DatasetNotFound, ProjectHidden):
            return _error(404, "not_found", "dataset was not found")
        except ValueError:
            return _error(422, "validation", "invalid dataset")
        except (CsrfRejected, OriginRejected):
            return _error(403, "permission", "request was rejected")
        except AuthRequired:
            return _error(401, "unauthorized", "session is missing")
    return JSONResponse(
        status_code=201,
        content={
            "project_id": str(view.project_id),
            "dataset_id": str(view.dataset_id),
            "id": str(view.id),
            "revision": view.revision,
            "content_hash": view.content_hash,
        },
    )


@pages.get("/ui/projects/{project_id}/datasets", response_class=HTMLResponse)
async def datasets_page(project_id: str, request: Request) -> HTMLResponse:
    project = _uuid(project_id)
    if isinstance(project, JSONResponse):
        return HTMLResponse(status_code=404, content="데이터를 찾지 못했습니다.")
    with _bound(request):
        try:
            authorize_page(request, project)
            items = list_datasets(project)
        except (OriginRejected, ProjectHidden, AuthRequired):
            return HTMLResponse(status_code=401, content="이 화면을 볼 권한이 없습니다.")
    return render_template(
        request,
        "datasets.html",
        {
            "shell": True,
            "title": "데이터",
            "heading": "데이터",
            "section": "list",
            "connected": True,
            "state": "empty" if items == () else "ready",
            "dirty": False,
            "query": UiQueryState("", "name", "", "", ""),
            "crumbs": (("데이터", f"/ui/projects/{project}/datasets"),),
            "list_href": f"/ui/projects/{project}/datasets",
            "detail_href": f"/ui/projects/{project}/datasets",
            "request": request,
            "project_id": str(project),
            "datasets": items,
        },
    )


def _revision(project_id: UUID, dataset_id: UUID, payload: dict[str, object]) -> DatasetRevisionInput:
    schema = payload.get("row_schema")
    rows = payload.get("rows")
    name = payload.get("name", "")
    if type(schema) is not dict or type(rows) is not list or type(name) is not str:
        raise ValueError("invalid dataset")
    if any(type(row) is not dict for row in rows):
        raise ValueError("invalid rows")
    case_raw = payload.get("case_id")
    case_id = None if case_raw in (None, "") else UUID(str(case_raw))
    return DatasetRevisionInput(
        project_id=project_id,
        actor_id=UUID(int=0),
        name=name,
        row_schema=schema,
        rows=tuple(row for row in rows if type(row) is dict),
        dataset_id=dataset_id,
        secret_ref=_ref(payload.get("secret_ref")),
        case_id=case_id,
    )


def _ref(value: object) -> SecretRef | None:
    if value is None:
        return None
    if type(value) is not dict:
        raise ValueError("invalid secret ref")
    return SecretRef(
        project_id=UUID(str(value.get("project_id"))),
        ref_id=UUID(str(value.get("ref_id"))),
        revision=int(value.get("revision")),
    )


@contextmanager
def _bound(request: Request) -> Iterator[None]:
    store = request.app.state.open_store()
    try:
        migrate_store(store)
        with bind_dataset_store(store):
            with bound_auth_store(store):
                yield
    finally:
        store.close()


def _uuid(value: str) -> UUID | JSONResponse:
    try:
        return UUID(value)
    except ValueError:
        return _error(404, "not_found", "dataset was not found")


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
