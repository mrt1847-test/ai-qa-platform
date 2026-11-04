"""Worker artifact ingest and the evidence viewer. The route does not open a device or a model."""

from __future__ import annotations

import base64
from dataclasses import dataclass
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
from aiqa.api.oidc_login import assert_route_capability
from aiqa.contracts.jobs import LeaseToken
from aiqa.domain.projects import MembershipDenied
from aiqa.store.artifacts import (
    ArtifactStream,
    ArtifactUpload,
    EvidenceUnavailable,
    content_hash,
    expired_at,
    resolve_stored,
)
from aiqa.store.retention import DEBUG_WINDOW, DETAIL_WINDOW, FILE_WINDOW, SPOOL_WINDOW
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
                    denied = _authorize_read(request, project_id, store)
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

    async def get_retention(artifact_id: str, request: Request) -> JSONResponse:
        try:
            target = UUID(artifact_id)
        except ValueError:
            return _error(404, "not_found", "artifact was not found", {})
        store = request.app.state.open_store()
        try:
            migrate_store(store)
            with bound_auth_store(store):
                with store.transaction() as connection:
                    view = _retention(connection, store.config.artifacts_dir, target, datetime.now(timezone.utc))
                    tombstone = None
                    if view is not None:
                        tombstone = connection.execute(
                            """
                            SELECT 1 FROM retention_tombstones
                            WHERE project_id = ? AND subject_id = ?
                            """,
                            (str(view.project_id), str(target)),
                        ).fetchone()
                if view is None:
                    return _error(404, "not_found", "artifact was not found", {})
                denied = _authorize_read(request, view.project_id, store)
                if denied is not None:
                    return denied
        finally:
            store.close()
        return JSONResponse(
            status_code=200,
            content={
                "artifact_id": str(target),
                "state": view.state,
                "substituted": False,
                "retain_days": 30,
                "tombstone": tombstone is not None,
                "windows": {
                    "detail_days": DETAIL_WINDOW.days,
                    "file_days": FILE_WINDOW.days,
                    "acked_spool_days": SPOOL_WINDOW.days,
                    "debug_hours": int(DEBUG_WINDOW.total_seconds() // 3600),
                },
            },
        )

    async def evidence_page(project_id: str, request: Request) -> HTMLResponse:
        try:
            project = UUID(project_id)
        except ValueError:
            return HTMLResponse(status_code=404, content="프로젝트를 찾지 못했습니다.")
        selection = _selection(request)
        if selection is None:
            return HTMLResponse(status_code=422, content="증거 선택을 다시 확인해 주세요.")
        store = request.app.state.open_store()
        try:
            migrate_store(store)
            with bound_auth_store(store):
                try:
                    authorize_page(request, project)
                except (OriginRejected, ProjectHidden, AuthRequired):
                    return HTMLResponse(status_code=401, content="이 화면을 볼 권한이 없습니다.")
                with store.transaction() as connection:
                    page = _viewer(connection, store.config.artifacts_dir, project, selection, datetime.now(timezone.utc))
        finally:
            store.close()
        return render_template(
            request,
            "components/evidence_viewer.html",
            {"shell": True, "project_id":str(project), "selection": selection, "actions": page.actions, "first_failure": page.first_failure, "crumbs":(('저장된 단계 증거',''),)},
        )

    application.add_api_route("/api/v1/worker/artifacts", post_artifact, methods=["POST"])
    application.add_api_route("/api/v1/artifacts/{artifact_id}", get_artifact, methods=["GET"])
    application.add_api_route("/api/v1/artifacts/{artifact_id}/retention", get_retention, methods=["GET"])
    application.add_api_route(
        "/ui/projects/{project_id}/evidence",
        evidence_page,
        methods=["GET"],
        response_class=HTMLResponse,
    )
    application.add_api_route(
        "/ui/projects/{project_id}/artifacts/{artifact_id}",
        artifact_page,
        methods=["GET"],
        response_class=HTMLResponse,
    )
    application.state.artifacts_installed = True


@dataclass(frozen=True, slots=True)
class EvidenceViewerSelection:
    """The exact evidence row a refresh must restore."""

    owner_kind: str
    owner_id: str
    attempt_id: str
    action_id: str


@dataclass(frozen=True, slots=True)
class _Shot:
    state: str
    artifact_id: str
    reason: str
    captured_at: str


@dataclass(frozen=True, slots=True)
class _ActionView:
    action_id: str
    step_id: str
    before: _Shot
    after: _Shot
    log_text: str
    check_status: str
    error_text: str


@dataclass(frozen=True, slots=True)
class _ViewerPage:
    actions: tuple[_ActionView, ...]
    first_failure: str


@dataclass(frozen=True, slots=True)
class _Retention:
    project_id: UUID
    state: str


def _selection(request: Request) -> EvidenceViewerSelection | None:
    kind = request.query_params.get("owner_kind", "")
    owner = request.query_params.get("owner_id", "")
    attempt = request.query_params.get("attempt_id", "")
    action = request.query_params.get("action_id", "")
    if kind not in {"REC", "ITEM"} or owner.strip() == "" or attempt.strip() == "" or action.strip() == "":
        return None
    return EvidenceViewerSelection(kind, owner, attempt, action)


def _retention(connection: object, root: object, artifact_id: UUID, now: datetime) -> _Retention | None:
    row = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT project_id, object_key, content_hash, status, custody, stored_at
        FROM artifact_objects
        WHERE artifact_id = ?
        """,
        (str(artifact_id),),
    ).fetchone()
    if row is None:
        return None
    return _Retention(UUID(str(row[0])), _state(root, row, now))


def _state(root: object, row: object, now: datetime) -> str:
    custody = "" if row[4] is None else str(row[4])  # type: ignore[index]
    stored_at = "" if row[5] is None else str(row[5])  # type: ignore[index]
    if custody == "expired" or expired_at(stored_at, now):
        return "expired"
    if custody == "delayed":
        return "delayed"
    if custody == "corrupt" or str(row[3]) != "ready":  # type: ignore[index]
        return "corrupt" if custody == "corrupt" or str(row[3]) == "quarantine" else "missing"  # type: ignore[index]
    path = resolve_stored(root, str(row[1]))  # type: ignore[arg-type, index]
    if path is None or not path.is_file():
        return "missing"
    if content_hash(path.read_bytes()) != str(row[2]):  # type: ignore[index]
        return "corrupt"
    return "stored"


def _viewer(connection: object, root: object, project_id: UUID, selection: EvidenceViewerSelection, now: datetime, artifact_ids: frozenset[str] | None = None) -> _ViewerPage:
    rows = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT actions.action_id, actions.step_id
        FROM actions
        JOIN attempts ON attempts.project_id = actions.project_id AND attempts.attempt_id = actions.attempt_id
        JOIN jobs ON jobs.project_id = attempts.project_id AND jobs.job_id = attempts.job_id
        WHERE actions.project_id = ? AND actions.attempt_id = ?
          AND ((? = 'REC' AND jobs.recording_id = ?) OR (? = 'ITEM' AND jobs.case_run_id = ?))
        ORDER BY actions.action_seq
        """,
        (str(project_id), selection.attempt_id, selection.owner_kind, selection.owner_id, selection.owner_kind, selection.owner_id),
    ).fetchall()
    files = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT action_id, role, artifact_id, object_key, content_hash, status, custody, stored_at, media_type
        FROM artifact_objects
        WHERE project_id = ? AND attempt_id = ? AND owner_kind = ? AND owner_id = ?
        """,
        (str(project_id), selection.attempt_id, selection.owner_kind, selection.owner_id),
    ).fetchall()
    checks = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT action_id, status, reason
        FROM check_results
        WHERE project_id = ? AND attempt_id = ?
        ORDER BY check_id
        """,
        (str(project_id), selection.attempt_id),
    ).fetchall()
    by_action: dict[str, dict[str, object]] = {}
    for item in files:
        if artifact_ids is not None and str(item[2]) not in artifact_ids:
            continue
        by_action.setdefault(str(item[0] or ""), {})[str(item[1])] = item
    check_by_action = {str(item[0]): (str(item[1]), str(item[2])) for item in checks}
    actions: list[_ActionView] = []
    first = ""
    for action_id, step_id in rows:
        roles = by_action.get(str(action_id), {})
        check = check_by_action.get(str(action_id))
        if first == "" and check is not None and check[0] == "violated":
            first = str(action_id)
        actions.append(
            _ActionView(
                str(action_id),
                str(step_id),
                _shot(root, roles.get("before"), now),
                _shot(root, roles.get("after"), now),
                _log(root, roles.get("log"), now),
                "" if check is None else check[0],
                "" if check is None or check[0] != "violated" else check[1],
                )
        )
    return _ViewerPage(tuple(actions), first)


def _shot(root: object, row: object, now: datetime) -> _Shot:
    if row is None:
        return _Shot("missing", "", "파일이 없습니다.", "")
    state = _state(root, (None, row[3], row[4], row[5], row[6], row[7]), now)
    return _Shot(state, str(row[2]), _reason(state), "" if row[7] is None else str(row[7]))


def _log(root: object, row: object, now: datetime) -> str:
    if row is None:
        return ""
    state = _state(root, (None, row[3], row[4], row[5], row[6], row[7]), now)
    if state != "stored":
        return _reason(state)
    path = resolve_stored(root, str(row[3]))  # type: ignore[arg-type]
    if path is None:
        return "파일이 없습니다."
    return path.read_text(encoding="utf-8")


def _reason(state: str) -> str:
    if state == "expired":
        return "보관 기한이 지났습니다."
    if state == "corrupt":
        return "파일 내용이 보관 hash와 다릅니다."
    if state == "delayed":
        return "캡처가 늦었습니다."
    if state == "stored":
        return ""
    return "파일이 없습니다."


def _authorize_read(
    request: Request,
    project_id: UUID,
    store: object | None = None,
) -> JSONResponse | None:
    """Admit download with worker scope or project evidence_download. No live worker PC required."""

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
        actor = authorize_page(request, project_id)
    except (OriginRejected, ProjectHidden, AuthRequired):
        return _error(401, "unauthorized", "session is missing", {})
    if store is None:
        return None
    try:
        with store.transaction() as connection:  # type: ignore[attr-defined]
            assert_route_capability(connection, actor, project_id, "evidence_download")
    except MembershipDenied:
        return _error(404, "not_found", "artifact was not found", {})
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
