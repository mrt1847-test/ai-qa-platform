"""Job enqueue routes. A long job returns its ids and keeps the receipt."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
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
from aiqa.contracts.jobs import IdempotencyKey, JobReceipt, JobSnapshot, JobSubmission
from aiqa.domain.hashing import canonical_json
from aiqa.store.database import migrate_store
from aiqa.store.models import Transaction
from aiqa.store.queue import CancelRejected, JobConflict, JobNotFound, cancel_job, enqueue_job, load_job

router = APIRouter(prefix="/api/v1")
_HIDDEN = {"reasoning", "secret", "secret_plaintext", "secret_value"}


def install_jobs(application: FastAPI) -> None:
    """Attach job routes once. This does not open SQLite."""

    if getattr(application.state, "jobs_installed", False):
        return
    application.include_router(router)
    application.state.jobs_installed = True


@router.post("/projects/{project_id}/jobs")
async def post_job(project_id: str, request: Request) -> JSONResponse:
    rejected = _idempotency(request)
    if rejected is not None:
        return rejected
    project = _uuid(project_id)
    if isinstance(project, JSONResponse):
        return project
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    try:
        submission = _submission(project, payload)
    except ValueError:
        return _error(422, "validation", "invalid job", {})
    with _bound(request) as store:
        try:
            actor = authorize_browser(request, project, "job")
            key = IdempotencyKey(
                actor.actor_id,
                project,
                "enqueue_job",
                request.headers.get("idempotency-key", "").strip(),
            )
            with store.transaction() as connection:
                receipt = enqueue_job(Transaction(connection), submission, key)
        except CsrfRejected:
            return _error(403, "permission", "csrf token was rejected", {})
        except OriginRejected:
            return _error(403, "permission", "origin was rejected", {})
        except ProjectHidden:
            return _error(404, "not_found", "job was not found", {})
        except AuthRequired:
            return _error(401, "unauthorized", "session is missing", {})
        except JobConflict:
            return _error(409, "conflict", "idempotency body does not match", {})
        except ValueError:
            return _error(422, "validation", "invalid job", {})
    return _accepted(receipt)


@router.get("/projects/{project_id}/jobs/{job_id}")
async def get_job(project_id: str, job_id: str, request: Request) -> JSONResponse:
    project = _uuid(project_id)
    parsed_job = _uuid(job_id)
    if isinstance(project, JSONResponse) or isinstance(parsed_job, JSONResponse):
        return _error(404, "not_found", "job was not found", {})
    with _bound(request) as store:
        try:
            authorize_browser(request, project, "job")
            with store.transaction() as connection:
                receipt = load_job(Transaction(connection), project, parsed_job)
        except CsrfRejected:
            return _error(403, "permission", "csrf token was rejected", {})
        except OriginRejected:
            return _error(403, "permission", "origin was rejected", {})
        except (ProjectHidden, JobNotFound):
            return _error(404, "not_found", "job was not found", {})
        except AuthRequired:
            return _error(401, "unauthorized", "session is missing", {})
    return JSONResponse(status_code=200, content=_content(receipt))


@router.post("/projects/{project_id}/jobs/{job_id}/cancellations")
async def post_cancellation(project_id: str, job_id: str, request: Request) -> JSONResponse:
    rejected = _idempotency(request)
    if rejected is not None:
        return rejected
    project = _uuid(project_id)
    parsed_job = _uuid(job_id)
    if isinstance(project, JSONResponse) or isinstance(parsed_job, JSONResponse):
        return _error(404, "not_found", "job was not found", {})
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    expected = payload.get("expected_state")
    if type(expected) is not str:
        return _error(422, "validation", "invalid cancel", {})
    with _bound(request) as store:
        try:
            actor = authorize_browser(request, project, "cancel_job")
            key = IdempotencyKey(
                actor.actor_id,
                project,
                "cancel_job",
                request.headers.get("idempotency-key", "").strip(),
            )
            with store.transaction() as connection:
                snapshot = cancel_job(Transaction(connection), actor, parsed_job, expected, key)
        except CsrfRejected:
            return _error(403, "permission", "csrf token was rejected", {})
        except OriginRejected:
            return _error(403, "permission", "origin was rejected", {})
        except ProjectHidden:
            return _error(404, "not_found", "job was not found", {})
        except AuthRequired:
            return _error(401, "unauthorized", "session is missing", {})
        except JobNotFound:
            return _error(404, "not_found", "job was not found", {})
        except (JobConflict, CancelRejected):
            return _error(409, "conflict", "cancel was rejected", {})
        except ValueError:
            return _error(422, "validation", "invalid cancel", {})
    return JSONResponse(status_code=200 if snapshot.replayed else 202, content=_cancel_content(snapshot))


def _submission(project_id: UUID, payload: dict[str, object]) -> JobSubmission:
    if any(name in payload for name in _HIDDEN):
        raise ValueError("hidden field")
    purpose = payload.get("purpose")
    if type(purpose) is not str:
        raise ValueError("purpose is required")
    limits = payload.get("limits", {})
    if type(limits) is not dict:
        raise ValueError("limits must be an object")
    source_refs = payload.get("source_refs", [])
    if type(source_refs) is not list or any(type(item) is not str for item in source_refs):
        raise ValueError("source ref is invalid")
    return JobSubmission(
        project_id,
        purpose,
        _optional_uuid(payload.get("case_id")),
        _optional_uuid(payload.get("case_version_id")),
        tuple(source_refs),
        canonical_json(limits),
    )


def _optional_uuid(value: object) -> UUID | None:
    if value is None:
        return None
    if type(value) is not str:
        raise ValueError("id is invalid")
    return UUID(value)


def _accepted(receipt: JobReceipt) -> JSONResponse:
    return JSONResponse(status_code=200 if receipt.replayed else 202, content=_content(receipt))


def _cancel_content(snapshot: JobSnapshot) -> dict[str, object]:
    return {
        "job_id": str(snapshot.job_id),
        "status": snapshot.status,
        "cancel_requested": snapshot.cancel_requested,
        "runner_stopped": snapshot.runner_stopped,
        "cleanup_completed": snapshot.cleanup_completed,
        "replayed": snapshot.replayed,
    }


def _content(receipt: JobReceipt) -> dict[str, object]:
    return {
        "job_id": str(receipt.job_id),
        "purpose": receipt.purpose,
        "status": receipt.status,
        "recording_id": None if receipt.recording_id is None else str(receipt.recording_id),
        "execution_id": None if receipt.execution_id is None else str(receipt.execution_id),
        "case_run_id": None if receipt.case_run_id is None else str(receipt.case_run_id),
        "status_href": receipt.status_href,
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
        return _error(422, "validation", "body must be JSON", {"body": ["invalid"]})
    if type(payload) is not dict:
        return _error(422, "validation", "body must be an object", {"body": ["invalid"]})
    return payload


def _uuid(value: str) -> UUID | JSONResponse:
    try:
        return UUID(value)
    except ValueError:
        return _error(404, "not_found", "job was not found", {})


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
