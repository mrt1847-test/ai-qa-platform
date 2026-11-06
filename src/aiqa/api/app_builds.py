"""APK upload and explicit app-install routes. Handlers do not execute APK bytes."""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.routing import APIRouter

from aiqa.api.auth import (
    AuthRequired,
    CsrfRejected,
    OriginRejected,
    ProjectHidden,
    authorize_browser,
    authorize_page,
    bound_auth_store,
    worker_scope_from_token,
)
from aiqa.contracts.jobs import IdempotencyKey, JobReceipt, JobSubmission
from aiqa.environments.app_builds import (
    ApkRejected,
    ApkInspectionSpec,
    AppBuildView,
    AppInstallBlocked,
    AppPreparationResult,
    AppPreparationSpec,
    FixtureInstallDriver,
    get_app_build,
    list_app_builds,
    load_app_build_bytes,
    prepare_app,
    register_app_build,
)
from aiqa.store.artifacts import ArtifactRejected
from aiqa.store.database import Store, migrate_store
from aiqa.store.models import Transaction
from aiqa.store.queue import JobConflict, ResourceOffline, enqueue_job
from aiqa.web.routes import UiQueryState, render_template
from aiqa.worker.resources import PreviewDenied, bind_inventory_store

router = APIRouter(prefix="/api/v1")
pages = APIRouter()


def install_app_builds(application: FastAPI) -> None:
    """Attach APK routes. This does not open SQLite or run an APK."""

    if getattr(application.state, "app_builds_installed", False):
        return
    if not hasattr(application.state, "fixture_install_driver"):
        application.state.fixture_install_driver = FixtureInstallDriver()
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
    tool = payload.get("tool_path", ...)
    if tool is not ... and tool is not None and type(tool) is not str:
        return _error(422, "validation", "invalid apk")
    with _bound(request) as store:
        try:
            authorize_browser(request, project, "app_build")
            with store.transaction() as connection:
                receipt, view = register_app_build(
                    ApkInspectionSpec(project, filename, body, declared, int(payload.get("project_total", 0))),
                    tool_path=tool,
                    connection=connection,
                    artifacts_dir=store.config.artifacts_dir,
                )
        except ApkRejected:
            return _error(422, "validation", "invalid apk")
        except ArtifactRejected:
            return _error(409, "conflict", "stored apk does not match its hash")
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
            "build_id": str(view.build_id),
            "ready": view.ready,
            "signature_status": view.signature_status,
            "package_name": view.package_name,
            "content_hash": view.content_hash,
            "byte_length": view.byte_length,
        },
    )


@router.get("/projects/{project_id}/app-builds")
async def list_app_builds_json(project_id: str, request: Request) -> JSONResponse:
    project = _uuid(project_id)
    if isinstance(project, JSONResponse):
        return project
    with _bound(request) as store:
        try:
            _authorize_read(request, project)
            with store.transaction() as connection:
                items = list_app_builds(project, connection=connection)
        except _ReadDenied as denied:
            return denied.response
    return JSONResponse(status_code=200, content={"items": [_build_json(item) for item in items]})


@router.get("/projects/{project_id}/app-builds/{build_id}")
async def get_app_build_json(project_id: str, build_id: str, request: Request) -> JSONResponse:
    project = _uuid(project_id)
    build = _build_uuid(build_id)
    if isinstance(project, JSONResponse):
        return project
    if build is None:
        return _error(404, "not_found", "build was not found")
    with _bound(request) as store:
        try:
            _authorize_read(request, project)
            with store.transaction() as connection:
                view = get_app_build(project, build, connection=connection)
        except _ReadDenied as denied:
            return denied.response
    if view is None:
        return _error(404, "not_found", "build was not found")
    return JSONResponse(status_code=200, content=_build_json(view))


@router.get("/projects/{project_id}/app-builds/{build_id}/content")
async def get_app_build_content(project_id: str, build_id: str, request: Request) -> Response:
    """APK bytes for one project build. Worker Bearer token or browser session; never cross-project."""

    project = _uuid(project_id)
    build = _build_uuid(build_id)
    if isinstance(project, JSONResponse):
        return project
    if build is None:
        return _error(404, "not_found", "build was not found")
    with _bound(request) as store:
        try:
            _authorize_read(request, project)
            with store.transaction() as connection:
                loaded = load_app_build_bytes(connection, store.config.artifacts_dir, project, build)
        except _ReadDenied as denied:
            return denied.response
        except ArtifactRejected:
            return _error(409, "conflict", "stored apk is missing or does not match its hash")
    if loaded is None:
        return _error(404, "not_found", "build was not found")
    body, digest = loaded
    return Response(
        content=body,
        status_code=200,
        media_type="application/vnd.android.package-archive",
        headers={
            "Content-Hash": digest,
            "X-Content-Hash": digest,
            "Cache-Control": "no-store",
        },
    )


@router.post("/resources/{resource_id}/app-installs")
async def post_app_install(resource_id: str, request: Request) -> JSONResponse:
    if not request.headers.get("idempotency-key"):
        return _error(422, "validation", "Idempotency-Key is required")
    parsed = _uuid(resource_id)
    project = _project_query(request)
    if isinstance(parsed, JSONResponse) or isinstance(project, JSONResponse):
        return _error(404, "not_found", "resource was not found")
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    provider = payload.get("provider", "")
    build_id = payload.get("build_id")
    content_hash = payload.get("content_hash")
    policy = payload.get("policy", "use_installed")
    serial = payload.get("serial")
    confirmed = payload.get("confirmed", False)
    cancel_requested = payload.get("cancel_requested", False)
    if (
        type(provider) is not str
        or type(build_id) is not str
        or type(content_hash) is not str
        or type(policy) is not str
        or type(serial) is not str
        or type(confirmed) is not bool
        or type(cancel_requested) is not bool
    ):
        return _error(422, "validation", "invalid app install")
    if provider not in {"fixture", "worker"}:
        return _error(422, "validation", "install provider is not configured")
    try:
        build_uuid = UUID(build_id)
    except ValueError:
        return _error(422, "validation", "invalid app install")
    request_key = request.headers.get("idempotency-key", "")
    with _bound(request):
        try:
            actor = authorize_browser(request, project, "app_install")
            receipt, result, driver = _submit_app_install(
                request,
                actor_id=actor.actor_id,
                project_id=project,
                resource_id=parsed,
                build_id=build_uuid,
                content_hash=content_hash,
                policy=policy,
                serial=serial,
                confirmed=confirmed,
                cancel_requested=cancel_requested,
                request_key=request_key,
                provider=provider,
            )
        except AppInstallBlocked as exc:
            return _error(422, "validation", str(exc) or "install was blocked")
        except PreviewDenied:
            return _error(404, "not_found", "resource was not found")
        except ResourceOffline as exc:
            return _error(422, "validation", str(exc))
        except JobConflict:
            return _error(409, "conflict", "idempotency body does not match")
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
            "qa": None,
            "ready": result.ready,
            "state": result.state,
            "reason": result.reason,
            "install_calls": result.install_calls,
            "reset_calls": result.reset_calls,
            "observed_at": result.observed_at,
            "unapproved_mutations": driver.unapproved_mutations,
            "package": result.package,
            "content_hash": result.content_hash,
        },
    )


@pages.get("/ui/projects/{project_id}/app-builds", response_class=HTMLResponse)
async def app_builds_page(project_id: str, request: Request) -> HTMLResponse:
    project = _uuid(project_id)
    if isinstance(project, JSONResponse):
        return HTMLResponse(status_code=404, content="앱을 찾지 못했습니다.")
    with _bound(request) as page_store:
        try:
            authorize_page(request, project)
            with page_store.transaction() as page_connection:
                items = list_app_builds(project, connection=page_connection)
            installs = _list_install_jobs(request, project)
            resources = _list_android_resources(request, project)
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
            "installs": installs,
            "resources": resources,
        },
    )


def _submit_app_install(
    request: Request,
    *,
    actor_id: UUID,
    project_id: UUID,
    resource_id: UUID,
    build_id: UUID,
    content_hash: str,
    policy: str,
    serial: str,
    confirmed: bool,
    cancel_requested: bool,
    request_key: str,
    provider: str = "fixture",
) -> tuple[JobReceipt, AppPreparationResult, FixtureInstallDriver]:
    store = request.app.state.open_store()
    migrate_store(store)
    driver: FixtureInstallDriver = request.app.state.fixture_install_driver
    try:
        with store.transaction() as lookup:
            build = get_app_build(project_id, build_id, connection=lookup)
        if build is None:
            raise AppInstallBlocked("build was not found")
        if policy not in {"use_installed", "install_if_needed", "force_reinstall", "clear"}:
            raise AppInstallBlocked("policy is invalid")
        if policy in {"install_if_needed", "force_reinstall", "clear"} and not confirmed:
            raise AppInstallBlocked("confirmation required")
        with bind_inventory_store(store):
            with store.transaction() as connection:
                alias = connection.execute(
                    """
                    SELECT aliases.target_kind, physical.native_id
                    FROM resource_aliases AS aliases
                    JOIN physical_resource_keys AS physical USING (physical_key_id)
                    WHERE aliases.project_id = ? AND aliases.physical_key_id = ?
                    """,
                    (str(project_id), str(resource_id)),
                ).fetchone()
                if alias is None:
                    raise PreviewDenied("resource was not found")
                if str(alias[0]) != "android":
                    raise AppInstallBlocked("app install requires android")
                enrolled = str(alias[1])
                lease = connection.execute(
                    """
                    SELECT 1 FROM leases
                    WHERE project_id = ? AND physical_key_id = ?
                    """,
                    (str(project_id), str(resource_id)),
                ).fetchone()
                lease_held = lease is not None
                # Claim snapshot validation pins build_id→content_hash in app_builds.
                pin_build_hash(connection, project_id, build_id, content_hash)
                limits = {
                    "kind": "app_install",
                    "qa": None,
                    "build_id": str(build_id),
                    "build_hash": content_hash,
                    "content_hash": content_hash,
                    "policy": policy,
                    "serial": serial,
                    "confirmed": confirmed,
                    "resource_id": str(resource_id),
                    "provider": provider,
                }
                receipt = enqueue_job(
                    Transaction(connection),
                    JobSubmission(
                        project_id,
                        "app_install",
                        None,
                        None,
                        (str(resource_id),),
                        json.dumps(limits, sort_keys=True),
                    ),
                    IdempotencyKey(actor_id, project_id, "enqueue_job", request_key),
                )
                if receipt.replayed:
                    row = connection.execute(
                        "SELECT limits FROM jobs WHERE project_id = ? AND job_id = ?",
                        (str(project_id), str(receipt.job_id)),
                    ).fetchone()
                    stored = json.loads(str(row[0])) if row is not None else {}
                    result = AppPreparationResult(
                        ready=bool(stored.get("ready")),
                        state=str(stored.get("state", "failed")),
                        reason=str(stored.get("reason", "replayed")),
                        install_calls=0,
                        reset_calls=0,
                        observed_at=str(stored.get("observed_at", "")),
                        package=None if stored.get("package") is None else str(stored.get("package")),
                        content_hash=None
                        if stored.get("result_hash") is None
                        else str(stored.get("result_hash")),
                        qa=None,
                    )
                    return receipt, result, driver
                # provider=worker leaves the job queued for a registered Android worker claim.
                provider = str(limits.get("provider") or "fixture")
                if provider == "worker":
                    pending = AppPreparationResult(
                        ready=False,
                        state="queued",
                        reason="worker_pending",
                        install_calls=0,
                        reset_calls=0,
                        observed_at="",
                        package=None,
                        content_hash=None,
                        qa=None,
                    )
                    return receipt, pending, driver
                result = prepare_app(
                    AppPreparationSpec(
                        project_id,
                        resource_id,
                        build_id,
                        content_hash,
                        serial,
                        policy,
                        confirmed,
                    ),
                    build=build,
                    driver=driver,
                    enrolled_serial=enrolled,
                    lease_held=lease_held,
                    cancel_requested=cancel_requested,
                )
                completed = {
                    **limits,
                    "ready": result.ready,
                    "state": result.state,
                    "reason": result.reason,
                    "install_calls": result.install_calls,
                    "reset_calls": result.reset_calls,
                    "observed_at": result.observed_at,
                    "package": result.package,
                    "result_hash": result.content_hash,
                    "unapproved_mutations": driver.unapproved_mutations,
                }
                connection.execute(
                    "UPDATE jobs SET status = 'completed', limits = ? WHERE project_id = ? AND job_id = ?",
                    (json.dumps(completed, sort_keys=True), str(project_id), str(receipt.job_id)),
                )
                connection.execute(
                    """
                    UPDATE job_receipts SET status = 'completed'
                    WHERE project_id = ? AND job_id = ? AND operation = 'enqueue_job' AND request_key = ?
                    """,
                    (str(project_id), str(receipt.job_id), request_key),
                )
                receipt = JobReceipt(
                    job_id=receipt.job_id,
                    purpose=receipt.purpose,
                    status="completed",
                    recording_id=receipt.recording_id,
                    execution_id=receipt.execution_id,
                    case_run_id=receipt.case_run_id,
                    status_href=receipt.status_href,
                    replayed=False,
                    body_hash=receipt.body_hash,
                )
                return receipt, result, driver
    finally:
        store.close()


def pin_build_hash(connection: object, project_id: UUID, build_id: UUID, content_hash: str) -> None:
    """Pin build_id→hash for claim validation. A published build keeps its stored hash."""

    connection.execute(  # type: ignore[attr-defined]
        """
        INSERT INTO app_builds (project_id, build_id, content_hash)
        VALUES (?, ?, ?)
        ON CONFLICT(project_id, build_id) DO UPDATE SET
            content_hash = CASE
                WHEN app_builds.object_key IS NULL THEN excluded.content_hash
                ELSE app_builds.content_hash
            END
        """,
        (str(project_id), str(build_id), content_hash),
    )


def _list_install_jobs(request: Request, project_id: UUID) -> tuple[dict[str, object], ...]:
    store = request.app.state.open_store()
    try:
        migrate_store(store)
        with store.transaction() as connection:
            rows = connection.execute(
                """
                SELECT job_id, status, limits FROM jobs
                WHERE project_id = ? AND purpose = 'app_install'
                ORDER BY rowid DESC
                """,
                (str(project_id),),
            ).fetchall()
    finally:
        store.close()
    listed = []
    for row in rows:
        limits = json.loads(str(row[2]))
        listed.append(
            {
                "job_id": str(row[0]),
                "status": str(row[1]),
                "ready": bool(limits.get("ready")),
                "state": str(limits.get("state", "")),
                "reason": str(limits.get("reason", "")),
                "observed_at": str(limits.get("observed_at", "")),
                "policy": str(limits.get("policy", "")),
                "package": limits.get("package"),
                "install_calls": int(limits.get("install_calls", 0) or 0),
                "reset_calls": int(limits.get("reset_calls", 0) or 0),
            }
        )
    return tuple(listed)


def _list_android_resources(request: Request, project_id: UUID) -> tuple[dict[str, object], ...]:
    from aiqa.worker.resources import list_resources

    store = request.app.state.open_store()
    try:
        migrate_store(store)
        with bind_inventory_store(store):
            items = list_resources(project_id)
    finally:
        store.close()
    return tuple(item for item in items if item.get("target_kind") == "android")


@contextmanager
def _bound(request: Request) -> Iterator[Store]:
    store = request.app.state.open_store()
    try:
        migrate_store(store)
        with bound_auth_store(store):
            yield store
    finally:
        store.close()


class _ReadDenied(Exception):
    def __init__(self, response: JSONResponse) -> None:
        super().__init__("read denied")
        self.response = response


def _authorize_read(request: Request, project: UUID) -> None:
    """Worker Bearer token or browser session. Both stay inside one project."""

    header = request.headers.get("authorization", "")
    try:
        if header.lower().startswith("bearer "):
            worker = worker_scope_from_token(header[7:].strip())
            if project not in worker.permitted_projects:
                raise _ReadDenied(_error(404, "not_found", "project was not found"))
            return
        authorize_page(request, project)
    except AuthRequired as exc:
        raise _ReadDenied(_error(401, "unauthorized", "session is missing")) from exc
    except OriginRejected as exc:
        raise _ReadDenied(_error(403, "permission", "request was rejected")) from exc
    except ProjectHidden as exc:
        raise _ReadDenied(_error(404, "not_found", "project was not found")) from exc


def _build_uuid(value: str) -> UUID | None:
    try:
        return UUID(value)
    except ValueError:
        return None


def _build_json(view: AppBuildView) -> dict[str, object]:
    return {
        "build_id": str(view.build_id),
        "filename": view.filename,
        "package_name": view.package_name,
        "version_name": view.version_name,
        "min_sdk": view.min_sdk,
        "abi": view.abi,
        "signature_status": view.signature_status,
        "ready": view.ready,
        "content_hash": view.content_hash,
        "byte_length": view.byte_length,
        "created_at": view.created_at,
    }


def _project_query(request: Request) -> UUID | JSONResponse:
    value = request.query_params.get("project_id", "")
    try:
        return UUID(value)
    except ValueError:
        return _error(404, "not_found", "resource was not found")


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
