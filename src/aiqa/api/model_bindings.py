"""Role binding HTTP. This module does not call a model."""

from __future__ import annotations

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
    bound_auth_store,
)
from aiqa.domain.model_bindings import BindingNotFound, ForeignSecret, bind_model_store, save_model_binding_revision
from aiqa.store.database import migrate_store
from aiqa.store.models import ModelBindingInput, ModelBindingView, SecretRef

router = APIRouter(prefix="/api/v1", route_class=BrowserMutationRoute)


def install_model_bindings(application: FastAPI) -> None:
    """Attach binding routes. This does not open SQLite."""

    application.include_router(router)


@router.post("/model-bindings")
async def post_binding(request: Request) -> JSONResponse:
    return await _save(request, None)


@router.patch("/model-bindings/{binding_id}")
async def patch_binding(binding_id: str, request: Request) -> JSONResponse:
    parsed = _uuid(binding_id)
    if isinstance(parsed, JSONResponse):
        return parsed
    return await _save(request, parsed)


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
            with bound_auth_store(store):
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
