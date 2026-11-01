"""Trial preview and admission routes. These routes do not open a device or a model."""

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
from aiqa.contracts.jobs import IdempotencyKey
from aiqa.domain.executions import ExecutionRejected, enqueue_execution, preview_execution
from aiqa.store.database import migrate_store
from aiqa.store.models import Transaction
from aiqa.store.queue import JobConflict
from aiqa.web.routes import render_template

router = APIRouter(prefix="/api/v1")
pages = APIRouter()


def install_executions(application: FastAPI) -> None:
    """Attach trial routes once. This does not open SQLite."""

    if getattr(application.state, "executions_installed", False):
        return
    application.include_router(router)
    application.include_router(pages)
    application.state.executions_installed = True


@router.post("/projects/{project_id}/execution-previews")
async def post_preview(project_id: str, request: Request) -> JSONResponse:
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
            actor = authorize_browser(request, project, "execution_preview")
            with store.transaction() as connection:
                preview = preview_execution(Transaction(connection), actor, project, payload)
        except CsrfRejected:
            return _error(403, "permission", "csrf token was rejected", {})
        except OriginRejected:
            return _error(403, "permission", "origin was rejected", {})
        except ProjectHidden:
            return _error(404, "not_found", "trial was not found", {})
        except AuthRequired:
            return _error(401, "unauthorized", "session is missing", {})
        except ExecutionRejected:
            return _error(422, "validation", "trial is not ready", {})
    return JSONResponse(status_code=200, content=_preview_json(preview))


@router.post("/projects/{project_id}/executions")
async def post_execution(project_id: str, request: Request) -> JSONResponse:
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
            actor = authorize_browser(request, project, "enqueue_execution")
            key = IdempotencyKey(actor.actor_id, project, "enqueue_execution", request.headers.get("idempotency-key", "").strip())
            with store.transaction() as connection:
                receipt = enqueue_execution(Transaction(connection), actor, project, payload, key)
        except CsrfRejected:
            return _error(403, "permission", "csrf token was rejected", {})
        except OriginRejected:
            return _error(403, "permission", "origin was rejected", {})
        except ProjectHidden:
            return _error(404, "not_found", "trial was not found", {})
        except AuthRequired:
            return _error(401, "unauthorized", "session is missing", {})
        except JobConflict:
            return _error(409, "conflict", "idempotency body does not match", {})
        except ExecutionRejected:
            return _error(422, "validation", "trial is not ready", {})
    return JSONResponse(status_code=200 if receipt.replayed else 201, content=_receipt_json(receipt))


@pages.get("/ui/projects/{project_id}/cases/{case_id}/execution-setup", response_class=HTMLResponse)
async def execution_setup_page(project_id: str, case_id: str, request: Request) -> HTMLResponse:
    project = _uuid(project_id)
    parsed = _uuid(case_id)
    if isinstance(project, JSONResponse) or isinstance(parsed, JSONResponse):
        return HTMLResponse(status_code=404, content="케이스를 찾지 못했습니다.")
    with _bound(request) as store:
        try:
            authorize_page(request, project)
        except (AuthRequired, OriginRejected, ProjectHidden):
            return HTMLResponse(status_code=403, content="이 화면을 볼 권한이 없습니다.")
    return render_template(
        request,
        "execution_setup.html",
        {"project_id": str(project), "case_id": str(parsed), "shell": False},
    )


def _preview_json(preview: object) -> dict[str, object]:
    from aiqa.domain.executions import ExecutionPreview

    assert isinstance(preview, ExecutionPreview)
    return {
        "preview_hash": preview.preview_hash,
        "proposed_n": preview.proposed_n,
        "self_healing_enabled": preview.self_healing_enabled,
        "ready": preview.ready,
        "blockers": [{"code": blocker.code, "message": blocker.message} for blocker in preview.blockers],
        "resolved_items": [
            {
                "entry_id": item.entry_id,
                "case_version_id": str(item.case_version_id),
                "manifest_hash": item.manifest_hash,
                "replay_package_id": None if item.replay_package_id is None else str(item.replay_package_id),
                "replay_package_hash": item.replay_package_hash,
                "healing_policy_hash": item.healing_policy_hash,
                "environment_revision_id": str(item.environment_revision_id),
                "resource_id": str(item.resource_id),
                "approval_id": None if item.approval_id is None else str(item.approval_id),
            }
            for item in preview.resolved_items
        ],
    }


def _receipt_json(receipt: object) -> dict[str, object]:
    from aiqa.domain.executions import ExecutionReceipt

    assert isinstance(receipt, ExecutionReceipt)
    return {
        "execution_id": str(receipt.execution_id),
        "item_ids": [str(item_id) for item_id in receipt.item_ids],
        "job_ids": [str(job_id) for job_id in receipt.job_ids],
        "committed_seq": receipt.committed_seq,
        "replayed": receipt.replayed,
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
        return _error(404, "not_found", "trial was not found", {})


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
