"""APK upload route. The handler stores metadata and does not run the file."""

from __future__ import annotations

import base64
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
from aiqa.environments.app_builds import ApkRejected, ApkInspectionSpec, list_app_builds, register_app_build
from aiqa.store.database import migrate_store
from aiqa.web.routes import UiQueryState, render_template

router = APIRouter(prefix="/api/v1")
pages = APIRouter()


def install_app_builds(application: FastAPI) -> None:
    """Attach APK routes. This does not open SQLite or run an APK."""

    if getattr(application.state, "app_builds_installed", False):
        return
    application.include_router(router)
    application.include_router(pages)
    application.state.app_builds_installed = True


@router.post("/projects/{project_id}/app-builds")
async def post_app_build(project_id: str, request: Request) -> JSONResponse:
    if not request.headers.get("idempotency-key"):
        return _error(422, "validation", "Idempotency-Key is required")
    project = _uuid(project_id)
    if isinstance(project, JSONResponse):
        return project
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    try:
        filename = str(payload.get("filename", ""))
        encoded = payload.get("body_base64")
        if type(encoded) is not str:
            raise ValueError("invalid apk")
        body = base64.b64decode(encoded, validate=True)
        declared = int(payload.get("declared_length"))
    except (ValueError, TypeError):
        return _error(422, "validation", "invalid apk")
    with _bound(request):
        try:
            authorize_browser(request, project, "app_build")
            receipt, view = register_app_build(
                ApkInspectionSpec(project, filename, body, declared, int(payload.get("project_total", 0)))
            )
        except ApkRejected:
            return _error(422, "validation", "invalid apk")
        except (CsrfRejected, OriginRejected):
            return _error(403, "permission", "request was rejected")
        except AuthRequired:
            return _error(401, "unauthorized", "session is missing")
        except ProjectHidden:
            return _error(404, "not_found", "project was not found")
    return JSONResponse(
        status_code=201,
        content={
            "job_id": str(receipt.job_id),
            "purpose": receipt.purpose,
            "status": receipt.status,
            "replayed": receipt.replayed,
            "body_hash": receipt.body_hash,
            "ready": view.ready,
            "signature_status": view.signature_status,
        },
    )


@pages.get("/ui/projects/{project_id}/app-builds", response_class=HTMLResponse)
async def app_builds_page(project_id: str, request: Request) -> HTMLResponse:
    project = _uuid(project_id)
    if isinstance(project, JSONResponse):
        return HTMLResponse(status_code=404, content="앱을 찾지 못했습니다.")
    with _bound(request):
        try:
            authorize_page(request, project)
            items = list_app_builds(project)
        except (OriginRejected, ProjectHidden, AuthRequired):
            return HTMLResponse(status_code=401, content="이 화면을 볼 권한이 없습니다.")
    return render_template(
        request,
        "app_builds.html",
        {
            "shell": True,
            "title": "앱 등록",
            "heading": "앱 등록",
            "section": "list",
            "connected": True,
            "state": "empty" if items == () else "ready",
            "dirty": False,
            "query": UiQueryState("", "name", "", "", ""),
            "crumbs": (("앱", f"/ui/projects/{project}/app-builds"),),
            "list_href": f"/ui/projects/{project}/app-builds",
            "detail_href": f"/ui/projects/{project}/app-builds",
            "request": request,
            "project_id": str(project),
            "builds": items,
        },
    )


@contextmanager
def _bound(request: Request) -> Iterator[None]:
    store = request.app.state.open_store()
    try:
        migrate_store(store)
        with bound_auth_store(store):
            yield
    finally:
        store.close()


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
