"""Worker artifact ingest. The route does not open a device or a model."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from aiqa.api.auth import (
    AuthRequired,
    OriginRejected,
    ProjectHidden,
    authorize_page,
    bound_auth_store,
    worker_scope_from_token,
)
from aiqa.contracts.jobs import LeaseToken
from aiqa.store.artifacts import ArtifactStream, ArtifactUpload, EvidenceUnavailable
from aiqa.store.database import migrate_store
from aiqa.store.evidence import (
    ArtifactBinding,
    artifact_project,
    bind_artifact_ingest,
    ingest_artifact,
    open_artifact,
    reset_artifact_ingest,
)
from aiqa.store.models import WorkerScope
from aiqa.store.queue import LeaseDenied, StaleGeneration
from aiqa.store.artifact_ingest import ArtifactRequestConflict, ingest_upload_request
from aiqa.security.receipt_digest import ReceiptKeyUnavailable
from aiqa.web.routes import render_template


def install_artifacts(application: FastAPI) -> None:
    """Attach the artifact ingest route once. This does not open SQLite."""

    if getattr(application.state, "artifacts_installed", False):
        return

    async def post_artifact(request: Request) -> Response:
        if not request.headers.get("idempotency-key"):
            return _error(422, "validation", "Idempotency-Key is required", {"Idempotency-Key": ["required"]})
        header = request.headers.get("authorization", "")
        if not header.startswith("Bearer ") or header.removeprefix("Bearer ").strip() == "":
            return _error(401, "unauthorized", "worker token is missing", {})
        payload = await _body(request)
        if isinstance(payload, JSONResponse):
            return payload
        try:
            # Worker-supplied timestamps cannot extend an expired generation.
            now = datetime.now(timezone.utc)
            lease = LeaseToken(
                _uuid(payload.get("project_id")),
                _uuid(payload.get("job_id")),
                _generation(payload.get("generation")),
            )
            upload = _upload(lease.project_id, payload)
        except (TypeError, ValueError):
            return _error(422, "validation", "invalid artifact", {})
        token = header.removeprefix("Bearer ").strip()
        store = request.app.state.open_store()
        try:
            migrate_store(store)
            with bound_auth_store(store):
                try:
                    worker = worker_scope_from_token(token)
                    marker = bind_artifact_ingest(ArtifactBinding(store, worker, now))
                    try:
                        body = ingest_upload_request(ArtifactBinding(store, worker, now), lease, upload, request.headers['idempotency-key'].strip(), payload)
                    finally:
                        reset_artifact_ingest(marker)
                except AuthRequired:
                    return _error(401, "unauthorized", "worker token is missing", {})
                except LeaseDenied:
                    return _error(403, "permission", "worker cannot use this lease", {})
                except StaleGeneration:
                    return _error(409, "conflict", "lease generation is stale", {})
                except ArtifactRequestConflict:
                    return _error(409, 'conflict', 'upload key already has another body', {})
                except ReceiptKeyUnavailable:
                    return _error(503, 'receipt_key_unavailable', 'local request integrity is unavailable', {})
                except ValueError:
                    return _error(422, 'validation', 'invalid artifact ownership', {})
        finally:
            store.close()
        return JSONResponse(
            status_code=200,
            content=body,
        )

    async def get_artifact(artifact_id: str, request: Request) -> Response:
        try:
            target = UUID(artifact_id)
        except ValueError:
            return _error(404, "not_found", "artifact was not found", {})
        store = request.app.state.open_store()
        try:
            migrate_store(store)
            with bound_auth_store(store):
                marker = bind_artifact_ingest(
                    ArtifactBinding(store, WorkerScope("", (), ()), datetime.now(timezone.utc))
                )
                try:
                    project_id = artifact_project(target)
                    if project_id is None:
                        return _error(404, "not_found", "artifact was not found", {})
                    denied = _authorize_read(request, project_id)
                    if denied is not None:
                        return denied
                    opened = open_artifact(target)
                finally:
                    reset_artifact_ingest(marker)
        finally:
            store.close()
        if isinstance(opened, EvidenceUnavailable):
            return _error(409, "evidence_unavailable", opened.state, {})
        return Response(content=opened.body, media_type=opened.media_type)

    async def artifact_page(project_id: str, artifact_id: str, request: Request) -> HTMLResponse:
        try:
            project = UUID(project_id)
            target = UUID(artifact_id)
        except ValueError:
            return HTMLResponse(status_code=404, content="파일을 찾지 못했습니다.")
        store = request.app.state.open_store()
        try:
            migrate_store(store)
            with bound_auth_store(store):
                try:
                    authorize_page(request, project)
                except (OriginRejected, ProjectHidden, AuthRequired):
                    return HTMLResponse(status_code=401, content="이 화면을 볼 권한이 없습니다.")
                marker = bind_artifact_ingest(
                    ArtifactBinding(store, WorkerScope("", (), ()), datetime.now(timezone.utc))
                )
                try:
                    owner = artifact_project(target)
                    opened = open_artifact(target) if owner == project else EvidenceUnavailable("missing")
                finally:
                    reset_artifact_ingest(marker)
        finally:
            store.close()
        custody = opened.media_type if isinstance(opened, ArtifactStream) else opened.state
        if isinstance(opened, ArtifactStream):
            custody = "stored"
        return render_template(request, "components/evidence_state.html", {"custody": custody})

    application.add_api_route("/api/v1/worker/artifacts", post_artifact, methods=["POST"])
    application.add_api_route("/api/v1/artifacts/{artifact_id}", get_artifact, methods=["GET"])
    application.add_api_route(
        "/ui/projects/{project_id}/artifacts/{artifact_id}",
        artifact_page,
        methods=["GET"],
        response_class=HTMLResponse,
    )
    application.state.artifacts_installed = True


def _authorize_read(request: Request, project_id: UUID) -> JSONResponse | None:
    header = request.headers.get("authorization", "")
    if header.startswith("Bearer ") and header.removeprefix("Bearer ").strip() != "":
        try:
            worker = worker_scope_from_token(header.removeprefix("Bearer ").strip())
        except AuthRequired:
            return _error(401, "unauthorized", "worker token is missing", {})
        if project_id not in worker.permitted_projects:
            return _error(404, "not_found", "artifact was not found", {})
        return None
    try:
        authorize_page(request, project_id)
    except (OriginRejected, ProjectHidden, AuthRequired):
        return _error(401, "unauthorized", "session is missing", {})
    return None


def _upload(project_id: UUID, payload: dict[str, object]) -> ArtifactUpload:
    encoded = payload.get("body_b64")
    if type(encoded) is not str:
        raise ValueError("artifact body is invalid")
    body = base64.b64decode(encoded.encode("ascii"), validate=True)
    declared_length = payload.get("declared_length")
    if type(declared_length) is not int:
        raise ValueError("artifact length is invalid")
    filename = payload.get("filename")
    media_type = payload.get("media_type")
    declared_hash = payload.get("declared_hash")
    if type(filename) is not str or type(media_type) is not str or type(declared_hash) is not str:
        raise ValueError("artifact is invalid")
    owner_kind = payload.get('owner_kind', 'REC')
    role = payload.get('role', 'source')
    action_id, check_id = payload.get('action_id'), payload.get('check_id')
    if (type(owner_kind) is not str or type(role) is not str
            or action_id is not None and type(action_id) is not str
            or check_id is not None and type(check_id) is not str):
        raise ValueError('artifact ownership is invalid')
    return ArtifactUpload(
        project_id,
        _uuid(payload.get("owner_id")),
        filename,
        media_type,
        declared_hash,
        declared_length,
        body,
        owner_kind,
        None if payload.get('attempt_id') is None else _uuid(payload['attempt_id']),
        action_id,
        check_id,
        role,
    )


def _uuid(value: object) -> UUID:
    if type(value) is not str:
        raise ValueError("id is invalid")
    return UUID(value)


def _generation(value: object) -> int:
    if type(value) is not int or value < 1:
        raise ValueError("generation is invalid")
    return value


def _instant(value: object) -> datetime:
    if type(value) is not str:
        raise ValueError("artifact time is invalid")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("artifact time must include a timezone")
    return parsed


async def _body(request: Request) -> dict[str, object] | JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        return _error(422, "validation", "body must be JSON", {"body": ["invalid"]})
    if type(payload) is not dict:
        return _error(422, "validation", "body must be an object", {"body": ["invalid"]})
    return payload


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
