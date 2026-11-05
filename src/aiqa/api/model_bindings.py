"""Role binding HTTP and explicit model connection checks."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
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
from aiqa.contracts.jobs import IdempotencyKey, JobReceipt, JobSubmission
from aiqa.domain.model_bindings import (
    BindingNotFound,
    CompatibilityReport,
    ForeignSecret,
    ModelCheckBlocked,
    ModelCheckProbe,
    approved_deterministic_replay_requires_model_check,
    bind_model_store,
    current_model_store,
    get_compatibility,
    load_binding_row,
    run_model_binding_check,
    save_model_binding_revision,
)
from aiqa.security.secrets import (
    SecretScopeDenied,
    SecretUnavailable,
    bind_secret_store,
)
from aiqa.store.database import migrate_store
from aiqa.store.models import ModelBindingInput, ModelBindingView, RuntimeScope, SecretRef, Transaction
from aiqa.store.queue import JobConflict, enqueue_job

router = APIRouter(prefix="/api/v1", route_class=BrowserMutationRoute)
checks = APIRouter(prefix="/api/v1")


def install_model_bindings(application: FastAPI) -> None:
    """Attach binding and check routes. This does not open SQLite."""

    if not hasattr(application.state, "model_check_probe"):
        application.state.model_check_probe = ModelCheckProbe()
    application.include_router(router)
    application.include_router(checks)


@router.post("/model-bindings")
async def post_binding(request: Request) -> JSONResponse:
    return await _save(request, None)


@router.patch("/model-bindings/{binding_id}")
async def patch_binding(binding_id: str, request: Request) -> JSONResponse:
    parsed = _uuid(binding_id)
    if isinstance(parsed, JSONResponse):
        return parsed
    return await _save(request, parsed)


@checks.post("/model-bindings/{binding_id}/checks")
async def post_binding_check(binding_id: str, request: Request) -> JSONResponse:
    if not request.headers.get("idempotency-key"):
        return _error(422, "validation", "Idempotency-Key is required", {})
    parsed = _uuid(binding_id)
    project = _project_query(request)
    if isinstance(parsed, JSONResponse) or isinstance(project, JSONResponse):
        return _error(404, "not_found", "binding was not found", {})
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    provider = payload.get("provider", "fixture")
    if provider != "fixture":
        return _error(422, "validation", "check provider is not configured", {})
    mode = payload.get("mode", "ok")
    if type(mode) is not str or mode not in {
        "ok",
        "unauthorized",
        "rate_limited",
        "timeout",
        "incompatible",
        "key_missing",
    }:
        return _error(422, "validation", "invalid check", {})
    request_key = request.headers.get("idempotency-key", "")
    with _bound(request):
        try:
            actor = authorize_browser(request, project, "model_check")
            report, receipt = _run_check(
                request,
                actor_id=actor.actor_id,
                project_id=project,
                binding_id=parsed,
                mode=mode,
                request_key=request_key,
            )
        except BindingNotFound:
            return _error(404, "not_found", "binding was not found", {})
        except ModelCheckBlocked as exc:
            return _error(422, "validation", str(exc) or "check was blocked", {})
        except JobConflict:
            return _error(409, "conflict", "idempotency body does not match", {})
        except (CsrfRejected, OriginRejected):
            return _error(403, "permission", "request was rejected", {})
        except AuthRequired:
            return _error(401, "unauthorized", "session is missing", {})
        except ProjectHidden:
            return _error(404, "not_found", "binding was not found", {})
    body = _report_json(report)
    body.update(
        {
            "job_id": str(receipt.job_id),
            "purpose": receipt.purpose,
            "job_status": receipt.status,
            "replayed": receipt.replayed,
        }
    )
    if "secret" in json.dumps(body).lower() and any(
        token in json.dumps(body) for token in ("sk-", "api_key", "Bearer")
    ):
        return _error(500, "internal", "secret leakage blocked", {})
    return JSONResponse(status_code=201, content=body)


@checks.get("/model-bindings/{binding_id}/compatibility")
async def get_binding_compatibility(binding_id: str, request: Request) -> JSONResponse:
    parsed = _uuid(binding_id)
    project = _project_query(request)
    if isinstance(parsed, JSONResponse) or isinstance(project, JSONResponse):
        return _error(404, "not_found", "binding was not found", {})
    with _bound(request):
        try:
            authorize_page(request, project)
            report = get_compatibility(project, parsed)
        except BindingNotFound:
            return _error(404, "not_found", "binding was not found", {})
        except (OriginRejected, ProjectHidden, AuthRequired):
            return _error(401, "unauthorized", "session is missing", {})
    return JSONResponse(status_code=200, content=_report_json(report))


def _run_check(
    request: Request,
    *,
    actor_id: UUID,
    project_id: UUID,
    binding_id: UUID,
    mode: str,
    request_key: str,
) -> tuple[CompatibilityReport, JobReceipt]:
    detail = load_binding_row(project_id, binding_id)
    secret = _resolve_secret(request, project_id, detail)
    if mode == "key_missing":
        secret = None
    probe: ModelCheckProbe = request.app.state.model_check_probe
    previous = probe.mode
    probe.mode = "ok" if mode == "ok" else mode
    if mode == "key_missing":
        probe.mode = "ok"
    store = current_model_store()
    limits = {
        "kind": "model_check",
        "qa": None,
        "binding_id": str(binding_id),
        "mode": mode,
    }
    try:
        with store.transaction() as connection:
            receipt = enqueue_job(
                Transaction(connection),
                JobSubmission(
                    project_id,
                    "model_check",
                    None,
                    None,
                    (str(binding_id),),
                    json.dumps(limits, sort_keys=True),
                ),
                IdempotencyKey(actor_id, project_id, "enqueue_job", request_key),
            )
            if receipt.replayed:
                return get_compatibility(project_id, binding_id), receipt
            job_id = receipt.job_id
            body_hash = receipt.body_hash
            status_href = receipt.status_href
            recording_id = receipt.recording_id
            execution_id = receipt.execution_id
            case_run_id = receipt.case_run_id
            purpose = receipt.purpose
        report = run_model_binding_check(project_id, binding_id, secret=secret, probe=probe)
        completed = {
            **limits,
            "status": report.status,
            "reason": report.reason,
            "checked_at": report.checked_at,
            "actual_model": report.actual_model,
            "metered_calls": report.metered_calls,
            "key_present": report.key_present,
            "replay_requires_model_check": report.replay_requires_model_check,
        }
        with store.transaction() as connection:
            connection.execute(
                "UPDATE jobs SET status = 'completed', limits = ? WHERE project_id = ? AND job_id = ?",
                (json.dumps(completed, sort_keys=True), str(project_id), str(job_id)),
            )
            connection.execute(
                """
                UPDATE job_receipts SET status = 'completed'
                WHERE project_id = ? AND job_id = ? AND operation = 'enqueue_job' AND request_key = ?
                """,
                (str(project_id), str(job_id), request_key),
            )
        return (
            report,
            JobReceipt(
                job_id=job_id,
                purpose=purpose,
                status="completed",
                recording_id=recording_id,
                execution_id=execution_id,
                case_run_id=case_run_id,
                status_href=status_href,
                replayed=False,
                body_hash=body_hash,
            ),
        )
    finally:
        probe.mode = previous


def _resolve_secret(request: Request, project_id: UUID, detail: dict[str, object]) -> str | None:
    resolver = getattr(request.app.state, "secret_resolver", None)
    if resolver is None:
        return None
    ref = SecretRef(project_id, detail["key_ref_id"], int(detail["key_revision"]))  # type: ignore[arg-type]
    store = current_model_store()
    with bind_secret_store(store):
        try:
            value = resolver.resolve_for_server(
                ref, RuntimeScope(project_id=project_id, actor_id=UUID(int=0))
            )
        except (SecretUnavailable, SecretScopeDenied):
            return None
    return value.value


def _report_json(report: CompatibilityReport) -> dict[str, object]:
    return {
        "project_id": str(report.project_id),
        "binding_id": str(report.binding_id),
        "role": report.role,
        "model": report.model,
        "endpoint": report.endpoint,
        "status": report.status,
        "reason": report.reason,
        "checked_at": report.checked_at,
        "actual_model": report.actual_model,
        "key_present": report.key_present,
        "metered_calls": report.metered_calls,
        "qa": None,
        "replay_requires_model_check": report.replay_requires_model_check,
        "approved_replay_without_model_key": not approved_deterministic_replay_requires_model_check(),
    }


async def _save(request: Request, binding_id: UUID | None) -> JSONResponse:
    rejected = _idempotency(request)
    if rejected is not None:
        return rejected
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    project = _uuid(str(payload.get("project_id", "")))
    if isinstance(project, JSONResponse):
        return _error(404, "not_found", "binding was not found", {})
    try:
        revision = _input(project, binding_id, payload)
    except ValueError:
        return _error(422, "validation", "invalid binding", {})
    with _bound(request):
        try:
            actor = authorize_browser(request, project, "model-binding")
            view = save_model_binding_revision(
                ModelBindingInput(
                    project_id=project,
                    actor_id=actor.actor_id,
                    name=revision.name,
                    role=revision.role,
                    provider=revision.provider,
                    endpoint_kind=revision.endpoint_kind,
                    endpoint=revision.endpoint,
                    model=revision.model,
                    key_ref=revision.key_ref,
                    prompt_hash=revision.prompt_hash,
                    tariff_id=revision.tariff_id,
                    compatibility_status=revision.compatibility_status,
                    binding_id=binding_id,
                )
            )
        except (CsrfRejected, OriginRejected):
            return _error(403, "permission", "request was rejected", {})
        except AuthRequired:
            return _error(401, "unauthorized", "session is missing", {})
        except (ProjectHidden, BindingNotFound, ForeignSecret):
            return _error(404, "not_found", "binding was not found", {})
        except ValueError:
            return _error(422, "validation", "invalid binding", {})
    return JSONResponse(status_code=201, content=_view_json(view))


def _input(project_id: UUID, binding_id: UUID | None, payload: dict[str, object]) -> ModelBindingInput:
    name = payload.get("name", "")
    role = payload.get("role")
    provider = payload.get("provider")
    endpoint_kind = payload.get("endpoint_kind")
    endpoint = payload.get("endpoint")
    model = payload.get("model")
    prompt_hash = payload.get("prompt_hash")
    tariff_id = payload.get("tariff_id")
    status = payload.get("compatibility_status")
    if any(type(value) is not str for value in (name, role, provider, endpoint_kind, endpoint, model, prompt_hash, tariff_id, status)):
        raise ValueError("invalid binding")
    key_ref = payload.get("key_ref")
    if type(key_ref) is not dict:
        raise ValueError("invalid binding")
    return ModelBindingInput(
        project_id=project_id,
        actor_id=UUID(int=0),
        name=str(name),
        role=str(role),
        provider=str(provider),
        endpoint_kind=str(endpoint_kind),
        endpoint=str(endpoint),
        model=str(model),
        key_ref=SecretRef(
            project_id=UUID(str(key_ref.get("project_id", project_id))),
            ref_id=UUID(str(key_ref.get("ref_id"))),
            revision=int(key_ref["revision"]),
        ),
        prompt_hash=str(prompt_hash),
        tariff_id=str(tariff_id),
        compatibility_status=str(status),
        binding_id=binding_id,
    )


def _view_json(view: ModelBindingView) -> dict[str, object]:
    return {
        "project_id": str(view.project_id),
        "binding_id": str(view.binding_id),
        "id": str(view.id),
        "revision": view.revision,
        "role": view.role,
        "model": view.model,
        "content_hash": view.content_hash,
        "compatibility_status": view.compatibility_status,
    }


@contextmanager
def _bound(request: Request) -> Iterator[None]:
    store = request.app.state.open_store()
    try:
        migrate_store(store)
        with bind_model_store(store):
            with bind_secret_store(store):
                with bound_auth_store(store):
                    yield
    finally:
        store.close()


def _project_query(request: Request) -> UUID | JSONResponse:
    value = request.query_params.get("project_id", "")
    try:
        return UUID(value)
    except ValueError:
        return _error(404, "not_found", "binding was not found", {})


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
        return _error(404, "not_found", "binding was not found", {})


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
