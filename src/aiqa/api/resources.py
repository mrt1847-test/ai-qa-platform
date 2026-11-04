"""Dataset, environment, and model-binding routes. No provider calls."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
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
    WorkerDenied,
    authorize_browser,
    authorize_page,
    authorize_worker,
    bound_auth_store,
)
from aiqa.domain.datasets import (
    DatasetNotFound,
    ForeignSecret as DatasetForeignSecret,
    bind_dataset_store,
    get_dataset_revision,
    list_datasets,
    save_dataset_revision,
)
from aiqa.domain.environments import (
    EnvironmentNotFound,
    bind_environment_store,
    get_environment_revision,
    list_environment_profiles,
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
from aiqa.web.routes import UiQueryState, render_template
from aiqa.store.queue import JobConflict, ResourceOffline
from aiqa.worker.resources import (
    DiagnosticBlocked,
    InventoryDenied,
    PreviewDenied,
    bind_inventory_store,
    list_diagnostic_jobs,
    list_resources,
    preview_resource,
    report_inventory,
    submit_diagnostic,
)
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
assets = APIRouter(prefix="/api/v1", route_class=BrowserMutationRoute)
pages = APIRouter()
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
    application.include_router(assets)
    application.include_router(pages)
    from aiqa.api.app_builds import install_app_builds
    from aiqa.api.datasets import install_datasets

    install_datasets(application)
    install_app_builds(application)
    application.state.resources_installed = True


@router.get("/projects/{project_id}/resources")
async def get_resources(project_id: str, request: Request) -> JSONResponse:
    project = _uuid(project_id)
    if isinstance(project, JSONResponse):
        return _error(404, "not_found", "resource was not found", {})
    with _bound(request):
        try:
            authorize_page(request, project)
            items = list_resources(project)
        except _ERRORS as exc:
            return _auth_response(exc)
    return JSONResponse(status_code=200, content={"resources": items}, headers={"Cache-Control": "no-store"})


@router.get("/resources/{resource_id}/preview")
async def get_preview(resource_id: str, request: Request) -> JSONResponse:
    parsed = _uuid(resource_id)
    if isinstance(parsed, JSONResponse):
        return _error(404, "not_found", "resource was not found", {})
    project = _project_query(request)
    if isinstance(project, JSONResponse):
        return project
    with _bound(request):
        try:
            authorize_page(request, project)
            view = preview_resource(project, parsed)
        except PreviewDenied as exc:
            status = 404 if "not found" in str(exc) else 403
            code = "not_found" if status == 404 else "permission"
            return _error(status, code, "preview is not allowed", {})
        except _ERRORS as exc:
            return _auth_response(exc)
    return JSONResponse(
        status_code=200,
        content={
            "resource_id": str(view.resource_id),
            "state": view.state,
            "observed_at": view.observed_at,
            "geometry": view.geometry,
            "artifact_id": view.artifact_id,
            "reason": view.reason,
            "raw_control": view.raw_control,
        },
    )


@dataclass(frozen=True, slots=True)
class RecordingWizardState:
    """The device-first draft. Target fields that do not apply are already cleared."""

    resource_id: str
    environment_revision_id: str
    definition_buffer: str


def apply_recording_wizard(settings: dict[str, object]) -> dict[str, object]:
    """Keep the selected target. Drop fields that belong to the other target."""

    resource_id = settings.get("resource_id")
    if type(resource_id) is not str or resource_id.strip() == "":
        raise ValueError("device is required first")
    target = settings.get("target_kind")
    if target not in {"web", "android"}:
        raise ValueError("invalid settings")
    cleaned = dict(settings)
    environment_revision_id = cleaned.get("environment_revision_id", "")
    definition_buffer = cleaned.get("definition_buffer", "")
    if type(environment_revision_id) is not str or type(definition_buffer) is not str:
        raise ValueError("invalid wizard")
    if target == "web":
        cleaned["android_package"] = ""
        cleaned["build"] = ""
        cleaned["account_ref"] = ""
    else:
        cleaned["web_url"] = ""
    state = RecordingWizardState(resource_id, environment_revision_id, definition_buffer)
    cleaned["resource_id"] = state.resource_id
    cleaned["environment_revision_id"] = state.environment_revision_id
    cleaned["definition_buffer"] = state.definition_buffer
    cleaned["wizard"] = True
    return cleaned


@pages.get("/ui/projects/{project_id}/recordings/wizard", response_class=HTMLResponse)
async def recording_wizard_page(project_id: str, request: Request) -> HTMLResponse:
    project = _uuid(project_id)
    if isinstance(project, JSONResponse):
        return HTMLResponse(status_code=404, content="녹화를 찾지 못했습니다.")
    case_text = request.query_params.get("case", "")
    with _bound(request):
        try:
            authorize_page(request, project)
            items = list_resources(project)
            base_text = request.query_params.get('base', '')
            if base_text:
                try: UUID(base_text)
                except ValueError: return HTMLResponse(status_code=404,content='기준 버전을 찾지 못했습니다.')
            draft = {} if case_text == "" else _wizard_draft(project, case_text, base_text)
            if case_text and not draft:
                return HTMLResponse(status_code=404, content="케이스를 찾지 못했습니다.")
            profiles = list_environment_profiles(project)
            datasets = list_datasets(project)
            from aiqa.web.asset_options import fixed_revision_choices
            from aiqa.worker.resources import _bound_store
            profiles,datasets = fixed_revision_choices(_bound_store()._connection,project,profiles,datasets,draft)
            requested_resource = request.query_params.get("resource_id", "")
            if requested_resource:
                chosen = next((item for item in items if item["resource_id"] == requested_resource), None)
                if chosen is None:
                    return HTMLResponse(status_code=404, content="기기를 찾지 못했습니다.")
                draft["resource_id"] = requested_resource
                draft["target_kind"] = chosen["target_kind"]
        except (OriginRejected, ProjectHidden, AuthRequired):
            return HTMLResponse(status_code=401, content="이 화면을 볼 권한이 없습니다.")
    target = request.query_params.get("target") or str(draft.get("target_kind") or "web")
    if target not in {"web", "android"}:
        target = "web"
    step = request.query_params.get("step", "1")
    selected = str(draft.get("resource_id", ""))
    disconnected = any(item["resource_id"] == selected and item["connection_state"] != "online" for item in items)
    return render_template(
        request,
        "recording_setup.html",
        {
            "shell": True,
            "title": "녹화 준비",
            "heading": "녹화 준비",
            "section": "list",
            "connected": not disconnected,
            "state": "empty" if items == () else "ready",
            "dirty": False,
            "query": UiQueryState("", "name", "", "", ""),
            "crumbs": (("녹화", f"/ui/projects/{project}/recordings/wizard"),),
            "list_href": "/ui/projects",
            "detail_href": f"/ui/projects/{project}/recordings/wizard",
            "request": request,
            "project_id": str(project),
            "case_id": case_text,
            "resources": items,
            "draft": draft,
            "target": target,
            "step": step,
            "disconnected": disconnected and selected != "",
            "profiles": profiles,
            "datasets": datasets,
        },
    )


def _wizard_draft(project_id: UUID, case_id: str, base_version: str = '') -> dict[str, object]:
    from aiqa.worker.resources import _bound_store

    try:
        parsed = UUID(case_id)
    except ValueError:
        return {}
    with _bound_store().transaction() as connection:
        row = connection.execute(
            """
            SELECT versions.settings_json, versions.definition_json, versions.version_id, versions.content_hash, cases.name, versions.recorded_steps_json, versions.revision, cases.latest_draft_version_id
            FROM automation_cases AS cases
            LEFT JOIN case_versions AS versions
              ON versions.project_id = cases.project_id
             AND versions.case_id = cases.case_id
             AND versions.version_id = COALESCE(NULLIF(?, ''), cases.latest_draft_version_id)
            WHERE cases.project_id = ? AND cases.case_id = ?
            """,
            (base_version, str(project_id), str(parsed)),
        ).fetchone()
    if row is None:
        return {}
    if base_version and row[2] is None:
        return {}
    settings = {} if row[0] is None else json.loads(str(row[0]))
    definition = {} if row[1] is None else json.loads(str(row[1]))
    settings["raw_text"] = str(definition.get("raw_text", ""))
    settings["definition"] = definition
    settings["version_id"] = "" if row[2] is None else str(row[2])
    settings["input_version_hash"] = "" if row[3] is None else str(row[3])
    settings["case_name"] = str(row[4])
    settings["recorded_steps"] = [] if row[5] is None else json.loads(str(row[5]))
    settings['version_revision'] = row[6]
    settings['expected_head'] = row[7]
    if base_version:
        settings['rerecord_base_version_id'] = base_version
        settings['rerecord_reason'] = ''
        settings['rerecord_confirmed'] = False
        settings['recorded_steps'] = []
    return settings


@pages.get("/ui/projects/{project_id}/environments", response_class=HTMLResponse)
async def environments_page(project_id: str, request: Request) -> HTMLResponse:
    from aiqa.api.audit import bind_audit_store, list_workers
    from aiqa.security.worker_enrollment import actor_can_manage_workers

    project = _uuid(project_id)
    if isinstance(project, JSONResponse):
        return HTMLResponse(status_code=404, content="자원을 찾지 못했습니다.")
    can_manage = False
    workers: list[dict[str, object]] = []
    with _bound(request):
        try:
            actor = authorize_page(request, project)
            items = list_resources(project)
            diagnostics = list_diagnostic_jobs(project)
            store = request.app.state.open_store()
            try:
                migrate_store(store)
                with bind_audit_store(store):
                    with store.transaction() as connection:
                        can_manage = actor_can_manage_workers(connection, actor)
                    if can_manage:
                        workers = list_workers(project)
            finally:
                store.close()
        except (OriginRejected, ProjectHidden, AuthRequired):
            return HTMLResponse(status_code=401, content="이 화면을 볼 권한이 없습니다.")
    return render_template(
        request,
        "environments.html",
        {
            "shell": True,
            "title": "연결 자원",
            "heading": "연결 자원",
            "section": "list",
            "connected": True,
            "state": "empty" if items == () else "ready",
            "dirty": False,
            "query": UiQueryState("", "name", "", "", ""),
            "crumbs": (("환경", f"/ui/projects/{project}/environments"),),
            "list_href": "/ui/projects",
            "detail_href": f"/ui/projects/{project}/environments",
            "request": request,
            "project_id": str(project),
            "resources": items,
            "diagnostics": diagnostics,
            "can_manage_workers": can_manage,
            "registered_workers": workers,
        },
    )


@router.post("/resources/{resource_id}/probes")
async def post_probe(resource_id: str, request: Request) -> JSONResponse:
    return await _diagnostic(resource_id, "probe", request)


@router.post("/resources/{resource_id}/recoveries")
async def post_recovery(resource_id: str, request: Request) -> JSONResponse:
    return await _diagnostic(resource_id, "recovery", request)


async def _diagnostic(resource_id: str, kind: str, request: Request) -> JSONResponse:
    if not request.headers.get("idempotency-key"):
        return _error(422, "validation", "Idempotency-Key is required", {})
    parsed = _uuid(resource_id)
    project = _project_query(request)
    if isinstance(parsed, JSONResponse) or isinstance(project, JSONResponse):
        return _error(404, "not_found", "resource was not found", {})
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    provider = payload.get("provider", "")
    proof = payload.get("proof")
    if type(provider) is not str or (proof is not None and type(proof) is not str):
        return _error(422, "validation", "invalid diagnostic", {})
    with _bound(request):
        try:
            actor = authorize_browser(request, project, "resource_diagnostic")
            receipt, ready = submit_diagnostic(
                actor,
                project,
                parsed,
                kind,
                provider,
                proof,
                request.headers.get("idempotency-key", ""),
            )
        except DiagnosticBlocked:
            return _error(422, "validation", "diagnostic was blocked", {})
        except ResourceOffline as exc:
            return _error(422, "validation", str(exc), {})
        except PreviewDenied:
            return _error(404, "not_found", "resource was not found", {})
        except JobConflict:
            return _error(409, "conflict", "idempotency body does not match", {})
        except _ERRORS as exc:
            return _auth_response(exc)
    return JSONResponse(
        status_code=201,
        content={
            "job_id": str(receipt.job_id),
            "purpose": receipt.purpose,
            "status": receipt.status,
            "replayed": receipt.replayed,
            "qa": None,
            "ready": ready,
        },
    )


@pages.get("/ui/projects/{project_id}/environments/editor", response_class=HTMLResponse)
async def environment_editor_page(project_id: str, request: Request) -> HTMLResponse:
    project = _uuid(project_id)
    if isinstance(project, JSONResponse):
        return HTMLResponse(status_code=404, content="환경을 찾지 못했습니다.")
    with _bound(request):
        try:
            authorize_page(request, project)
            profiles = list_environment_profiles(project)
            chosen = request.query_params.get("environment", "")
            selected = next((item for item in profiles if item["environment_id"] == chosen), None)
            if chosen and selected is None:
                return HTMLResponse(status_code=404, content="환경을 찾지 못했습니다.")
        except (OriginRejected, ProjectHidden, AuthRequired):
            return HTMLResponse(status_code=401, content="이 화면을 볼 권한이 없습니다.")
    return render_template(
        request,
        "environment_editor.html",
        {
            "shell": True,
            "title": "환경 편집",
            "heading": "환경 편집",
            "section": "detail",
            "connected": True,
            "state": "ready",
            "dirty": False,
            "query": UiQueryState("", "name", "", "", ""),
            "crumbs": (("환경", f"/ui/projects/{project}/environments"), ("편집", "")),
            "list_href": f"/ui/projects/{project}/environments",
            "detail_href": f"/ui/projects/{project}/environments/editor",
            "profiles": profiles,
            "selected_profile": selected,
            "request": request,
            "project_id": str(project),
        },
    )


def _project_query(request: Request) -> UUID | JSONResponse:
    raw = request.query_params.get("project_id", "")
    parsed = _uuid(raw)
    if isinstance(parsed, JSONResponse):
        return _error(404, "not_found", "resource was not found", {})
    return parsed


@assets.post("/projects/{project_id}/datasets")
async def post_dataset(project_id: str, request: Request) -> JSONResponse:
    return await _save_dataset(project_id, None, request)


@assets.post("/projects/{project_id}/datasets/{dataset_id}/revisions")
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


@assets.post("/projects/{project_id}/environments")
async def post_environment(project_id: str, request: Request) -> JSONResponse:
    return await _save_environment(project_id, None, request)


@assets.post("/projects/{project_id}/environments/{environment_id}/revisions")
async def post_environment_revision(project_id: str, environment_id: str, request: Request) -> JSONResponse:
    return await _save_environment(project_id, environment_id, request)


@router.post("/environments/{environment_id}/versions")
async def post_environment_version(environment_id: str, request: Request) -> JSONResponse:
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    project_id = payload.get("project_id")
    if type(project_id) is not str:
        return _error(422, "validation", "invalid environment", {})
    request.state.environment_payload = payload
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


@assets.post("/projects/{project_id}/model-bindings")
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
    from aiqa.api.asset_validation import dataset_fields
    fields = dataset_fields(payload, require_name=parsed is None)
    if fields:
        return _error(422, "validation", "invalid dataset", fields)
    try:
        schema = payload.get("row_schema")
        rows = payload.get("rows")
        name = payload.get("name", "")
        if type(schema) is not dict or type(rows) is not list or type(name) is not str:
            raise ValueError("invalid dataset")
        if any(type(row) is not dict for row in rows):
            raise ValueError("invalid rows")
        secret = _optional_ref(payload.get("secret_ref"))
        case_id = None if payload.get("case_id") in (None, "") else UUID(str(payload.get("case_id")))
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
                    case_id=case_id,
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
    payload = getattr(request.state, "environment_payload", None)
    if payload is None:
        payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    from aiqa.api.asset_validation import environment_fields
    fields = environment_fields(payload, require_name=parsed is None)
    if fields:
        return _error(422, "validation", "invalid environment", fields)
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
                    profile=revision.profile,
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
        profile=_profile(payload),
    )


def _profile(payload: dict[str, object]) -> dict[str, object] | None:
    keys = ("start_url", "package", "dpr", "timezone", "orientation", "setup", "reset", "cleanup", "account_ref", "capabilities")
    profile = {key: payload[key] for key in keys if key in payload}
    return profile or None


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


@router.get("/projects/{project_id}/environments")
async def get_environment_profiles(project_id: str, request: Request) -> JSONResponse:
    project = _uuid(project_id)
    if isinstance(project, JSONResponse):
        return project
    with _bound(request):
        try:
            authorize_browser(request, project, "environment")
            profiles = list_environment_profiles(project)
        except _ERRORS as exc:
            return _auth_response(exc)
    return JSONResponse(content={"environments": profiles})


@router.post("/projects/{project_id}/recording-previews")
async def preview_recording_start(project_id: str, request: Request) -> JSONResponse:
    from aiqa.recording.service import RecordingStartInput, PreflightRejected, HashMismatch, inspect_recording
    project = _uuid(project_id)
    if isinstance(project, JSONResponse):
        return project
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    try:
        spec = RecordingStartInput(UUID(str(payload.get("case_id"))), UUID(str(payload.get("input_case_version_id"))), str(payload.get("input_version_hash", "")), str(payload.get("resource_id", "")))
    except ValueError:
        return _error(422, "validation", "invalid recording", {})
    with _bound(request):
        try:
            authorize_browser(request, project, "recording_preview")
            from aiqa.worker.resources import _bound_store
            report = inspect_recording(_bound_store()._connection, project, spec)
        except HashMismatch:
            return _error(409, "conflict", "version hash does not match", {})
        except PreflightRejected:
            return _error(404, "not_found", "case version was not found", {})
        except _ERRORS as exc:
            return _auth_response(exc)
    return JSONResponse(content=report)
