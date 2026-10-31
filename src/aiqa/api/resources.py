"""Dataset, environment, and model-binding routes. No provider calls."""

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
    WorkerDenied,
    authorize_browser,
    authorize_worker,
    bound_auth_store,
)
from aiqa.domain.datasets import (
    DatasetNotFound,
    ForeignSecret as DatasetForeignSecret,
    bind_dataset_store,
    get_dataset_revision,
    save_dataset_revision,
)
from aiqa.domain.environments import (
    EnvironmentNotFound,
    bind_environment_store,
    get_environment_revision,
    save_environment_revision,
)
from aiqa.domain.model_bindings import (
    BindingNotFound,
    ForeignSecret as BindingForeignSecret,
    bind_model_store,
    save_model_binding_revision,
)
from aiqa.contracts.resources import InventoryReport
from aiqa.store.database import migrate_store
from aiqa.store.models import JobRef
from aiqa.worker.resources import InventoryDenied, bind_inventory_store, report_inventory
from aiqa.store.models import (
    DatasetRevisionInput,
    DatasetVersionView,
    EnvironmentRevisionInput,
    EnvironmentRevisionView,
    ModelBindingInput,
    ModelBindingView,
    SecretRef,
)

router = APIRouter(prefix="/api/v1")
_ERRORS = (
    CsrfRejected,
    OriginRejected,
    ProjectHidden,
    AuthRequired,
    DatasetNotFound,
    EnvironmentNotFound,
    BindingNotFound,
    DatasetForeignSecret,
    BindingForeignSecret,
    ValueError,
)


@router.post("/worker/inventory")
async def post_inventory(request: Request) -> JSONResponse:
    rejected = _idempotency(request)
    if rejected is not None:
        return rejected
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer ") or header.removeprefix("Bearer ").strip() == "":
        return _error(401, "unauthorized", "worker token is missing", {})
    token = header.removeprefix("Bearer ").strip()
    try:
        project_id = UUID(str(payload.get("project_id")))
        report = InventoryReport(
            native_id=str(payload.get("native_id", "")),
            target_kind=str(payload.get("target_kind", "")),
            state=str(payload.get("state", "")),
            os_build=str(payload.get("os_build", "")),
            geometry=str(payload.get("geometry", "")),
            permissions=str(payload.get("permissions", "")),
            ime=str(payload.get("ime", "")),
            observed_at=str(payload.get("observed_at", "")),
            display_name=str(payload.get("display_name", "")),
            raw_handle=None if payload.get("raw_handle") is None else str(payload.get("raw_handle")),
        )
    except (TypeError, ValueError):
        return _error(422, "validation", "invalid inventory", {})
    with _bound(request):
        try:
            worker = authorize_worker(token, JobRef(project_id, "resource_probe"))
            receipt = report_inventory(worker, report)
        except AuthRequired:
            return _error(401, "unauthorized", "worker token is missing", {})
        except (WorkerDenied, InventoryDenied):
            return _error(403, "permission", "worker cannot report this project", {})
        except ValueError:
            return _error(422, "validation", "invalid inventory", {})
    return JSONResponse(
        status_code=200,
        content={
            "physical_key_id": str(receipt.physical_key_id),
            "resource_key": receipt.resource_key,
            "state": receipt.state,
            "project_id": str(receipt.project_id),
        },
    )


def install_resources(application: FastAPI) -> None:
    """Attach asset routes once. This does not open SQLite or call a model."""

    if getattr(application.state, "resources_installed", False):
        return
    application.include_router(router)
    application.state.resources_installed = True


@router.post("/projects/{project_id}/datasets")
async def post_dataset(project_id: str, request: Request) -> JSONResponse:
    return await _save_dataset(project_id, None, request)


@router.post("/projects/{project_id}/datasets/{dataset_id}/revisions")
async def post_dataset_revision(project_id: str, dataset_id: str, request: Request) -> JSONResponse:
    return await _save_dataset(project_id, dataset_id, request)


@router.get("/projects/{project_id}/datasets/{dataset_id}/revisions/{version_id}")
async def get_dataset(project_id: str, dataset_id: str, version_id: str, request: Request) -> JSONResponse:
    project = _uuid(project_id)
    parsed_dataset = _uuid(dataset_id)
    parsed_version = _uuid(version_id)
    if isinstance(project, JSONResponse) or isinstance(parsed_dataset, JSONResponse) or isinstance(parsed_version, JSONResponse):
        return _error(404, "not_found", "dataset was not found", {})
    with _bound(request):
        try:
            authorize_browser(request, project, "dataset")
            view = get_dataset_revision(project, parsed_dataset, parsed_version)
        except _ERRORS as exc:
            return _auth_response(exc)
    return JSONResponse(status_code=200, content=_dataset_json(view))


@router.post("/projects/{project_id}/environments")
async def post_environment(project_id: str, request: Request) -> JSONResponse:
    return await _save_environment(project_id, None, request)


@router.post("/projects/{project_id}/environments/{environment_id}/revisions")
async def post_environment_revision(project_id: str, environment_id: str, request: Request) -> JSONResponse:
    return await _save_environment(project_id, environment_id, request)


@router.get("/projects/{project_id}/environments/{environment_id}/revisions/{revision_id}")
async def get_environment(project_id: str, environment_id: str, revision_id: str, request: Request) -> JSONResponse:
    project = _uuid(project_id)
    parsed_environment = _uuid(environment_id)
    parsed_revision = _uuid(revision_id)
    if (
        isinstance(project, JSONResponse)
        or isinstance(parsed_environment, JSONResponse)
        or isinstance(parsed_revision, JSONResponse)
    ):
        return _error(404, "not_found", "environment was not found", {})
    with _bound(request):
        try:
            authorize_browser(request, project, "environment")
            view = get_environment_revision(project, parsed_environment, parsed_revision)
        except _ERRORS as exc:
            return _auth_response(exc)
    return JSONResponse(status_code=200, content=_environment_json(view))


@router.post("/projects/{project_id}/model-bindings")
async def post_binding(project_id: str, request: Request) -> JSONResponse:
    rejected = _idempotency(request)
    if rejected is not None:
        return rejected
    project = _uuid(project_id)
    if isinstance(project, JSONResponse):
        return _error(404, "not_found", "binding was not found", {})
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    try:
        revision = _binding_input(project, None, payload)
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
                )
            )
        except _ERRORS as exc:
            return _auth_response(exc)
    return JSONResponse(status_code=201, content=_binding_json(view))


async def _save_dataset(project_id: str, dataset_id: str | None, request: Request) -> JSONResponse:
    rejected = _idempotency(request)
    if rejected is not None:
        return rejected
    project = _uuid(project_id)
    parsed = None if dataset_id is None else _uuid(dataset_id)
    if isinstance(project, JSONResponse) or isinstance(parsed, JSONResponse):
        return _error(404, "not_found", "dataset was not found", {})
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    try:
        schema = payload.get("row_schema")
        rows = payload.get("rows")
        name = payload.get("name", "")
        if type(schema) is not dict or type(rows) is not list or type(name) is not str:
            raise ValueError("invalid dataset")
        if any(type(row) is not dict for row in rows):
            raise ValueError("invalid rows")
        secret = _optional_ref(payload.get("secret_ref"))
    except ValueError:
        return _error(422, "validation", "invalid dataset", {})
    with _bound(request):
        try:
            actor = authorize_browser(request, project, "dataset")
            view = save_dataset_revision(
                DatasetRevisionInput(
                    project_id=project,
                    actor_id=actor.actor_id,
                    name=name,
                    row_schema=schema,
                    rows=tuple(row for row in rows if type(row) is dict),
                    dataset_id=parsed,
                    secret_ref=secret,
                )
            )
        except _ERRORS as exc:
            return _auth_response(exc)
    return JSONResponse(status_code=201, content=_dataset_json(view))


async def _save_environment(project_id: str, environment_id: str | None, request: Request) -> JSONResponse:
    rejected = _idempotency(request)
    if rejected is not None:
        return rejected
    project = _uuid(project_id)
    parsed = None if environment_id is None else _uuid(environment_id)
    if isinstance(project, JSONResponse) or isinstance(parsed, JSONResponse):
        return _error(404, "not_found", "environment was not found", {})
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    try:
        revision = _environment_input(project, parsed, payload)
    except ValueError:
        return _error(422, "validation", "invalid environment", {})
    with _bound(request):
        try:
            actor = authorize_browser(request, project, "environment")
            view = save_environment_revision(
                EnvironmentRevisionInput(
                    project_id=project,
                    actor_id=actor.actor_id,
                    name=revision.name,
                    target_kind=revision.target_kind,
                    allowlist=revision.allowlist,
                    viewport=revision.viewport,
                    locale=revision.locale,
                    reset_policy=revision.reset_policy,
                    limits=revision.limits,
                    environment_id=parsed,
                )
            )
        except _ERRORS as exc:
            return _auth_response(exc)
    return JSONResponse(status_code=201, content=_environment_json(view))


def _environment_input(project_id: UUID, environment_id: UUID | None, payload: dict[str, object]) -> EnvironmentRevisionInput:
    allowlist = payload.get("allowlist")
    viewport = payload.get("viewport")
    limits = payload.get("limits")
    name = payload.get("name", "")
    target = payload.get("target_kind")
    locale = payload.get("locale")
    reset_policy = payload.get("reset_policy")
    if (
        type(allowlist) is not list
        or type(viewport) is not dict
        or type(limits) is not dict
        or type(name) is not str
        or type(target) is not str
        or type(locale) is not str
        or type(reset_policy) is not str
    ):
        raise ValueError("invalid environment")
    width = viewport.get("width")
    height = viewport.get("height")
    if type(width) is not int or type(height) is not int:
        raise ValueError("invalid environment")
    return EnvironmentRevisionInput(
        project_id=project_id,
        actor_id=UUID(int=0),
        name=name,
        target_kind=target,
        allowlist=tuple(str(item) for item in allowlist),
        viewport={"width": width, "height": height},
        locale=locale,
        reset_policy=reset_policy,
        limits=dict(limits),
        environment_id=environment_id,
    )


def _binding_input(project_id: UUID, binding_id: UUID | None, payload: dict[str, object]) -> ModelBindingInput:
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
    return ModelBindingInput(
        project_id=project_id,
        actor_id=UUID(int=0),
        name=str(name),
        role=str(role),
        provider=str(provider),
        endpoint_kind=str(endpoint_kind),
        endpoint=str(endpoint),
        model=str(model),
        key_ref=_required_ref(payload.get("key_ref")),
        prompt_hash=str(prompt_hash),
        tariff_id=str(tariff_id),
        compatibility_status=str(status),
        binding_id=binding_id,
    )


def _optional_ref(value: object) -> SecretRef | None:
    if value is None:
        return None
    return _required_ref(value)


def _required_ref(value: object) -> SecretRef:
    if type(value) is not dict:
        raise ValueError("invalid secret ref")
    return SecretRef(
        project_id=UUID(str(value.get("project_id"))),
        ref_id=UUID(str(value.get("ref_id"))),
        revision=int(value.get("revision")),
    )


def _dataset_json(view: DatasetVersionView) -> dict[str, object]:
    return {
        "project_id": str(view.project_id),
        "dataset_id": str(view.dataset_id),
        "id": str(view.id),
        "revision": view.revision,
        "content_hash": view.content_hash,
    }


def _environment_json(view: EnvironmentRevisionView) -> dict[str, object]:
    return {
        "project_id": str(view.project_id),
        "environment_id": str(view.environment_id),
        "id": str(view.id),
        "revision": view.revision,
        "target_kind": view.target_kind,
        "locale": view.locale,
        "content_hash": view.content_hash,
    }


def _binding_json(view: ModelBindingView) -> dict[str, object]:
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
        with bind_dataset_store(store):
            with bind_environment_store(store):
                with bind_model_store(store):
                    with bind_inventory_store(store):
                        with bound_auth_store(store):
                            yield
    finally:
        store.close()


def _auth_response(exc: Exception) -> JSONResponse:
    if isinstance(exc, CsrfRejected | OriginRejected):
        return _error(403, "permission", "request was rejected", {})
    if isinstance(exc, AuthRequired):
        return _error(401, "unauthorized", "session is missing", {})
    if isinstance(exc, ValueError):
        return _error(422, "validation", "invalid asset revision", {})
    if isinstance(exc, DatasetForeignSecret | BindingForeignSecret):
        return _error(404, "not_found", "secret ref was not found", {})
    return _error(404, "not_found", "asset was not found", {})


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
        return _error(404, "not_found", "asset was not found", {})


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
