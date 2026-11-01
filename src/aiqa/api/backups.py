"""Whole-PC backup routes. A project session cannot download the store."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from aiqa.api.auth import (
    AuthRequired,
    CsrfRejected,
    OriginRejected,
    ProjectHidden,
    authorize_browser,
    authorize_page,
    bound_auth_store,
)
from aiqa.store.backup import BackupRejected, RestoreRejected, activate_restore, create_backup, validate_restore
from aiqa.store.database import migrate_store
from aiqa.web.routes import UiQueryState, render_template


def install_backups(application: FastAPI) -> None:
    """Attach backup routes once. This does not open SQLite."""

    if getattr(application.state, "backups_installed", False):
        return
    application.add_api_route("/api/v1/projects/{project_id}/backups", post_backup, methods=["POST"])
    application.add_api_route("/api/v1/backups/{receipt_id}", get_backup, methods=["GET"])
    application.add_api_route("/api/v1/backups/{receipt_id}/download", download_backup, methods=["GET"])
    application.add_api_route(
        "/api/v1/backups/{receipt_id}/restore-validations",
        post_restore_validation,
        methods=["POST"],
    )
    application.add_api_route(
        "/api/v1/restore-validations/{validation_id}/activations",
        post_restore_activation,
        methods=["POST"],
    )
    application.add_api_route("/ui/projects/{project_id}/restore", restore_page, methods=["GET"])
    application.state.backups_installed = True


async def post_backup(project_id: str, request: Request) -> JSONResponse:
    project = _uuid(project_id)
    if project is None:
        return _error(404, "not_found", "backup was not found")
    if request.headers.get("idempotency-key", "").strip() == "":
        return _error(422, "validation", "Idempotency-Key is required")
    store = request.app.state.open_store()
    try:
        migrate_store(store)
        with bound_auth_store(store):
            try:
                actor = authorize_browser(request, project, "create_backup")
                receipt = create_backup(store, _spec(actor, project), datetime.now(timezone.utc))
            except (CsrfRejected, OriginRejected):
                return _error(403, "permission", "request was rejected")
            except ProjectHidden:
                return _error(404, "not_found", "backup was not found")
            except AuthRequired:
                return _error(401, "unauthorized", "session is missing")
            except BackupRejected:
                return _error(404, "not_found", "backup was not found")
    finally:
        store.close()
    return JSONResponse(
        status_code=201,
        content={
            "job_id": str(receipt.job_id),
            "purpose": "backup",
            "status": "completed",
            "recording_id": None,
            "execution_id": None,
            "case_run_id": None,
            "status_href": f"/api/v1/backups/{receipt.receipt_id}?project_id={project}",
            "replayed": False,
            "body_hash": receipt.content_hash,
            "receipt_id": str(receipt.receipt_id),
            "state": receipt.state,
            "qa": receipt.qa,
        },
    )


async def get_backup(receipt_id: str, request: Request) -> JSONResponse:
    project = _uuid(request.query_params.get("project_id", ""))
    receipt = _uuid(receipt_id)
    if project is None or receipt is None:
        return _error(404, "not_found", "backup was not found")
    store = request.app.state.open_store()
    try:
        migrate_store(store)
        with bound_auth_store(store):
            try:
                actor = authorize_browser(request, project, "read_backup")
                if not actor.is_local_owner:
                    raise BackupRejected("local owner required")
                with store.transaction() as connection:
                    row = connection.execute(
                        """
                        SELECT byte_length, content_hash, state, missing_count, job_id
                        FROM backup_snapshots
                        WHERE project_id = ? AND receipt_id = ?
                        """,
                        (str(project), str(receipt)),
                    ).fetchone()
            except (CsrfRejected, OriginRejected):
                return _error(403, "permission", "request was rejected")
            except ProjectHidden:
                return _error(404, "not_found", "backup was not found")
            except AuthRequired:
                return _error(401, "unauthorized", "session is missing")
            except BackupRejected:
                return _error(404, "not_found", "backup was not found")
    finally:
        store.close()
    if row is None:
        return _error(404, "not_found", "backup was not found")
    return JSONResponse(
        status_code=200,
        content={
            "receipt_id": str(receipt),
            "byte_length": int(row[0]),
            "content_hash": str(row[1]),
            "state": str(row[2]),
            "missing_count": int(row[3]),
            "job_id": str(row[4]),
            "qa": None,
        },
    )


async def download_backup(receipt_id: str, request: Request) -> Response:
    project = _uuid(request.query_params.get("project_id", ""))
    receipt = _uuid(receipt_id)
    if project is None or receipt is None:
        return _error(404, "not_found", "backup was not found")
    store = request.app.state.open_store()
    try:
        migrate_store(store)
        with bound_auth_store(store):
            try:
                actor = authorize_browser(request, project, "download_backup")
                if not actor.is_local_owner:
                    raise BackupRejected("local owner required")
                path = store.config.runtime_root / "backups" / str(receipt) / "snapshot.sqlite"
                if not path.is_file():
                    return _error(404, "not_found", "backup was not found")
                body = path.read_bytes()
            except (CsrfRejected, OriginRejected):
                return _error(403, "permission", "request was rejected")
            except ProjectHidden:
                return _error(404, "not_found", "backup was not found")
            except AuthRequired:
                return _error(401, "unauthorized", "session is missing")
            except BackupRejected:
                return _error(404, "not_found", "backup was not found")
    finally:
        store.close()
    return Response(content=body, media_type="application/octet-stream")


async def post_restore_validation(receipt_id: str, request: Request) -> JSONResponse:
    project = _uuid(request.query_params.get("project_id", ""))
    receipt = _uuid(receipt_id)
    if project is None or receipt is None:
        return _error(404, "not_found", "restore was not found")
    if request.headers.get("idempotency-key", "").strip() == "":
        return _error(422, "validation", "Idempotency-Key is required")
    store = request.app.state.open_store()
    try:
        migrate_store(store)
        with bound_auth_store(store):
            try:
                actor = authorize_browser(request, project, "validate_restore")
                result = validate_restore(store, _restore_spec(actor, project, receipt), datetime.now(timezone.utc))
            except (CsrfRejected, OriginRejected):
                return _error(403, "permission", "request was rejected")
            except ProjectHidden:
                return _error(404, "not_found", "restore was not found")
            except AuthRequired:
                return _error(401, "unauthorized", "session is missing")
            except (BackupRejected, RestoreRejected):
                return _error(404, "not_found", "restore was not found")
    finally:
        store.close()
    return JSONResponse(
        status_code=201,
        content={
            "validation_id": str(result.validation_id),
            "receipt_id": str(result.receipt_id),
            "accepted": result.accepted,
            "schema_ok": result.schema_ok,
            "foreign_keys_ok": result.foreign_keys_ok,
            "integrity_ok": result.integrity_ok,
            "manifest_ok": result.manifest_ok,
            "hash_ok": result.hash_ok,
            "missing_count": result.missing_count,
            "secret_reset_required": result.secret_reset_required,
            "separate_path": result.separate_path,
            "qa": None,
        },
    )


async def post_restore_activation(validation_id: str, request: Request) -> JSONResponse:
    project = _uuid(request.query_params.get("project_id", ""))
    validation = _uuid(validation_id)
    if project is None or validation is None:
        return _error(404, "not_found", "restore was not found")
    if request.headers.get("idempotency-key", "").strip() == "":
        return _error(422, "validation", "Idempotency-Key is required")
    body = await request.json()
    confirmed = type(body) is dict and body.get("confirmed") is True
    store = request.app.state.open_store()
    try:
        migrate_store(store)
        with bound_auth_store(store):
            try:
                actor = authorize_browser(request, project, "activate_restore")
                receipt = activate_restore(
                    store,
                    _activation(actor, project, validation, confirmed),
                    datetime.now(timezone.utc),
                )
            except (CsrfRejected, OriginRejected):
                return _error(403, "permission", "request was rejected")
            except ProjectHidden:
                return _error(404, "not_found", "restore was not found")
            except AuthRequired:
                return _error(401, "unauthorized", "session is missing")
            except BackupRejected:
                return _error(404, "not_found", "restore was not found")
            except RestoreRejected:
                return _error(409, "conflict", "restore was not activated")
    finally:
        store.close()
    return JSONResponse(
        status_code=201,
        content={
            "activation_id": str(receipt.activation_id),
            "validation_id": str(receipt.validation_id),
            "auto_replayed_jobs": receipt.auto_replayed_jobs,
            "old_leases_reused": receipt.old_leases_reused,
            "secret_reset_required": receipt.secret_reset_required,
            "qa": None,
        },
    )


async def restore_page(project_id: str, request: Request) -> HTMLResponse:
    project = _uuid(project_id)
    if project is None:
        return HTMLResponse(status_code=404, content="복원 화면을 찾지 못했습니다.")
    store = request.app.state.open_store()
    try:
        migrate_store(store)
        with bound_auth_store(store):
            try:
                actor = authorize_page(request, project)
                if not actor.is_local_owner:
                    return HTMLResponse(status_code=404, content="복원 화면을 찾지 못했습니다.")
            except (OriginRejected, ProjectHidden, AuthRequired):
                return HTMLResponse(status_code=401, content="이 화면을 볼 권한이 없습니다.")
    finally:
        store.close()
    return render_template(
        request,
        "restore.html",
        {
            "shell": False,
            "title": "복원 검사",
            "heading": "복원 검사",
            "section": "detail",
            "connected": True,
            "state": "ready",
            "dirty": False,
            "query": UiQueryState("", "name", "", "", ""),
            "crumbs": (("복원", f"/ui/projects/{project}/restore"),),
            "list_href": "/ui/projects",
            "detail_href": f"/ui/projects/{project}/restore",
            "request": request,
            "project_id": str(project),
        },
    )


def _restore_spec(actor: object, project: UUID, receipt: UUID):
    from aiqa.store.backup import RestoreSpec

    return RestoreSpec(project, receipt, actor)  # type: ignore[arg-type]


def _activation(actor: object, project: UUID, validation: UUID, confirmed: bool):
    from aiqa.store.backup import RestoreActivation

    return RestoreActivation(project, validation, actor, confirmed)  # type: ignore[arg-type]


def _spec(actor: object, project: UUID):
    from aiqa.store.backup import BackupSpec

    return BackupSpec(project, actor)  # type: ignore[arg-type]


def _uuid(value: object) -> UUID | None:
    if type(value) is not str or value.strip() == "":
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})
