"""Recording recovery route. The route does not open a device or a model."""

from __future__ import annotations

import base64
import json
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from aiqa.api.auth import (
    AuthRequired,
    CsrfRejected,
    OriginRejected,
    ProjectHidden,
    authorize_browser,
    bound_auth_store,
)
from aiqa.contracts.jobs import IdempotencyKey, JobSubmission
from aiqa.recording.manifests import FinishConflict, RecordingFinishInput
from aiqa.recording.service import (
    HashMismatch,
    PreflightRejected,
    RecordingStartInput,
    ResourceBusy,
    RerecordInput,
    finish_recording,
    start_recording,
    start_rerecording,
    stop_recording,
)
from aiqa.recording.recovery import (
    EvidenceRecoverySpec,
    RecoveryCapture,
    RecoveryConflict,
    RecoveryRejected,
    apply_recovery,
    prepare_recovery,
    discard_recovery,
    find_recovery,
    validate_recovery_target,
    bind_recovery,
    reset_recovery,
)
from aiqa.store.database import migrate_store
from aiqa.store.models import Transaction
from aiqa.store.queue import JobConflict, enqueue_job


def install_recordings(application: FastAPI) -> None:
    """Attach the recovery route once. This does not open SQLite."""

    if getattr(application.state, "recordings_installed", False):
        return

    async def post_recovery(recording_id: str, request: Request) -> JSONResponse:
        if not request.headers.get("idempotency-key"):
            return _error(422, "validation", "Idempotency-Key is required", {"Idempotency-Key": ["required"]})
        try:
            target = UUID(recording_id)
        except ValueError:
            return _error(404, "not_found", "recording was not found", {})
        payload = await _body(request)
        if isinstance(payload, JSONResponse):
            return payload
        try:
            project_id = UUID(str(payload.get("project_id")))
            spec = _spec(project_id, target, request.headers.get("idempotency-key", "").strip(), payload)
        except (TypeError, ValueError):
            return _error(422, "validation", "invalid recovery", {})
        store = request.app.state.open_store()
        try:
            migrate_store(store)
            with bound_auth_store(store):
                try:
                    actor = authorize_browser(request, project_id, "evidence_recovery")
                except CsrfRejected:
                    return _error(403, "permission", "csrf token was rejected", {})
                except OriginRejected:
                    return _error(403, "permission", "origin was rejected", {})
                except ProjectHidden:
                    return _error(404, "not_found", "recording was not found", {})
                except AuthRequired:
                    return _error(401, "unauthorized", "session is missing", {})
                prepared = None
                manifest_receipt = None
                committed = False
                try:
                    with store.transaction() as connection:
                        existing = find_recovery(connection, spec)
                        validate_recovery_target(connection, spec)
                    if existing is None:
                        prepared = prepare_recovery(store.config.artifacts_dir, spec)
                    with store.transaction() as connection:
                        receipt = enqueue_job(
                            Transaction(connection),
                            JobSubmission(
                                project_id,
                                "evidence_sync",
                                None,
                                None,
                                (str(target),),
                                _limits(spec),
                            ),
                            IdempotencyKey(actor.actor_id, project_id, "enqueue_job", spec.request_key),
                        )
                        manifest_receipt = apply_recovery(connection, store.config.artifacts_dir, spec, prepared=prepared)
                    committed = True
                except JobConflict:
                    return _error(409, "conflict", "idempotency body does not match", {})
                except RecoveryConflict:
                    return _error(409, "conflict", "recovery body does not match", {})
                except RecoveryRejected:
                    return _error(422, "validation", "invalid recovery", {})
                finally:
                    if prepared is not None and (not committed or manifest_receipt is None or manifest_receipt.manifest_id != prepared.manifest_id):
                        discard_recovery(prepared)
        finally:
            store.close()
        return JSONResponse(
            status_code=200,
            content={
                "job_id": str(receipt.job_id),
                "purpose": receipt.purpose,
                "status": receipt.status,
                "recording_id": None if receipt.recording_id is None else str(receipt.recording_id),
                "replayed": receipt.replayed,
            },
        )

    async def post_recording(project_id: str, request: Request) -> JSONResponse:
        request_key = request.headers.get("idempotency-key", "").strip()
        if request_key == "":
            return _error(422, "validation", "Idempotency-Key is required", {"Idempotency-Key": ["required"]})
        try:
            project = UUID(project_id)
        except ValueError:
            return _error(404, "not_found", "recording was not found", {})
        payload = await _body(request)
        if isinstance(payload, JSONResponse):
            return payload
        try:
            spec = RecordingStartInput(
                case_id=UUID(str(payload.get("case_id"))),
                input_case_version_id=UUID(str(payload.get("input_case_version_id"))),
                input_version_hash=str(payload.get("input_version_hash", "")),
                resource_id=str(payload.get("resource_id", "")),
            )
        except (TypeError, ValueError):
            return _error(422, "validation", "invalid recording", {})
        store = request.app.state.open_store()
        try:
            migrate_store(store)
            with bound_auth_store(store):
                try:
                    actor = authorize_browser(request, project, "recording_start")
                except CsrfRejected:
                    return _error(403, "permission", "csrf token was rejected", {})
                except OriginRejected:
                    return _error(403, "permission", "origin was rejected", {})
                except ProjectHidden:
                    return _error(404, "not_found", "recording was not found", {})
                except AuthRequired:
                    return _error(401, "unauthorized", "session is missing", {})
                try:
                    with store.transaction() as connection:
                        receipt = start_recording(connection, actor, project, spec, request_key)
                except HashMismatch:
                    return _error(409, "conflict", "version hash does not match", {})
                except ResourceBusy as exc:
                    return _error(
                        409,
                        "conflict",
                        "resource is busy",
                        {"queue": ["choose"], "occupant": [f"/api/v1/projects/{project}/jobs/{exc.job_id}"]},
                    )
                except JobConflict:
                    return _error(409, "conflict", "idempotency body does not match", {})
                except PreflightRejected as exc:
                    return _error(422, "validation", exc.reason, {})
                except ValueError:
                    return _error(422, "validation", "invalid recording", {})
        finally:
            store.close()
        return JSONResponse(
            status_code=200 if receipt.replayed else 201,
            content={
                "recording_id": str(receipt.recording_id),
                "job_id": str(receipt.job_id),
                "replayed": receipt.replayed,
                "status": receipt.status,
            },
        )

    application.add_api_route(
        "/api/v1/projects/{project_id}/recordings",
        post_recording,
        methods=["POST"],
    )
    async def post_finish(recording_id: str, request: Request) -> JSONResponse:
        return await _seal_route(recording_id, request, "finish")

    async def post_stop(recording_id: str, request: Request) -> JSONResponse:
        return await _seal_route(recording_id, request, "stop")

    async def recording_page(project_id: str, recording_id: str, request: Request) -> HTMLResponse:
        from aiqa.api.auth import authorize_page
        from aiqa.web.routes import UiQueryState, render_template

        try:
            project = UUID(project_id)
            recording = UUID(recording_id)
        except ValueError:
            return HTMLResponse(status_code=404, content="녹화를 찾지 못했습니다.")
        store = request.app.state.open_store()
        try:
            migrate_store(store)
            with bound_auth_store(store):
                try:
                    authorize_page(request, project)
                except (CsrfRejected, OriginRejected, ProjectHidden, AuthRequired):
                    return HTMLResponse(status_code=401, content="이 화면을 볼 권한이 없습니다.")
                with store.transaction() as connection:
                    row = connection.execute(
                        """
                        SELECT recordings.completion_status, versions.replay_package_id, cases.current_approval_id
                        FROM recordings
                        LEFT JOIN recording_manifests AS manifests
                          ON manifests.project_id = recordings.project_id
                         AND manifests.recording_id = recordings.recording_id
                        LEFT JOIN materialization_receipts AS receipts
                          ON receipts.project_id = manifests.project_id
                         AND receipts.manifest_id = manifests.manifest_id
                        LEFT JOIN case_versions AS versions
                          ON versions.project_id = receipts.project_id
                         AND versions.version_id = receipts.produced_version_id
                        LEFT JOIN automation_cases AS cases
                          ON cases.project_id = recordings.project_id
                         AND cases.case_id = recordings.case_id
                        WHERE recordings.project_id = ? AND recordings.recording_id = ?
                        ORDER BY versions.revision DESC LIMIT 1
                        """,
                        (str(project), str(recording)),
                    ).fetchone()
        finally:
            store.close()
        if row is None:
            return HTMLResponse(status_code=404, content="녹화를 찾지 못했습니다.")
        return render_template(
            request,
            "recording.html",
            {
                "shell": True,
                "title": "녹화",
                "heading": "녹화",
                "section": "detail",
                "connected": True,
                "state": "ready",
                "dirty": False,
                "query": UiQueryState("", "name", "", "", ""),
                "crumbs": (("녹화", f"/ui/projects/{project}/recordings/{recording}"),),
                "list_href": f"/ui/projects/{project}/recordings/wizard",
                "detail_href": f"/ui/projects/{project}/recordings/{recording}",
                "request": request,
                "completion_status": str(row[0]),
                "package_id": None if row[1] is None else str(row[1]),
                "approved": row[2] is not None,
            },
        )

    application.add_api_route("/api/v1/recordings/{recording_id}/finish", post_finish, methods=["POST"])
    application.add_api_route("/api/v1/recordings/{recording_id}/stop", post_stop, methods=["POST"])
    application.add_api_route(
        "/ui/projects/{project_id}/recordings/{recording_id}",
        recording_page,
        methods=["GET"],
        response_class=HTMLResponse,
    )
    async def get_case_recordings(case_id: str, request: Request) -> JSONResponse:
        parsed = _parse_uuid(case_id)
        if parsed is None:
            return _error(404, "not_found", "recordings were not found", {})
        store = request.app.state.open_store()
        try:
            migrate_store(store)
            with bound_auth_store(store):
                with store.transaction() as connection:
                    project = _case_project(connection, parsed)
                if project is None:
                    return _error(404, "not_found", "recordings were not found", {})
                try:
                    authorize_browser(request, project, "recording_history")
                except CsrfRejected:
                    return _error(403, "permission", "csrf token was rejected", {})
                except OriginRejected:
                    return _error(403, "permission", "origin was rejected", {})
                except ProjectHidden:
                    return _error(404, "not_found", "recordings were not found", {})
                except AuthRequired:
                    return _error(401, "unauthorized", "session is missing", {})
                with store.transaction() as connection:
                    page = _history_page(connection, project, parsed)
        finally:
            store.close()
        return JSONResponse(status_code=200, content=page)

    async def get_recording_manifests(recording_id: str, request: Request) -> JSONResponse:
        parsed = _parse_uuid(recording_id)
        if parsed is None:
            return _error(404, "not_found", "manifests were not found", {})
        store = request.app.state.open_store()
        try:
            migrate_store(store)
            with bound_auth_store(store):
                with store.transaction() as connection:
                    project = _recording_project(connection, parsed)
                if project is None:
                    return _error(404, "not_found", "manifests were not found", {})
                try:
                    authorize_browser(request, project, "recording_manifests")
                except CsrfRejected:
                    return _error(403, "permission", "csrf token was rejected", {})
                except OriginRejected:
                    return _error(403, "permission", "origin was rejected", {})
                except ProjectHidden:
                    return _error(404, "not_found", "manifests were not found", {})
                except AuthRequired:
                    return _error(401, "unauthorized", "session is missing", {})
                with store.transaction() as connection:
                    page = _manifest_page(connection, project, parsed)
        finally:
            store.close()
        return JSONResponse(status_code=200, content=page)

    async def history_page(project_id: str, case_id: str, request: Request) -> HTMLResponse:
        from aiqa.api.auth import authorize_page
        from aiqa.web.routes import UiQueryState, render_template

        try:
            project = UUID(project_id)
            case = UUID(case_id)
        except ValueError:
            return HTMLResponse(status_code=404, content="케이스를 찾지 못했습니다.")
        store = request.app.state.open_store()
        try:
            migrate_store(store)
            with bound_auth_store(store):
                try:
                    authorize_page(request, project)
                except (CsrfRejected, OriginRejected, ProjectHidden, AuthRequired):
                    return HTMLResponse(status_code=401, content="이 화면을 볼 권한이 없습니다.")
                with store.transaction() as connection:
                    page = _history_page(connection, project, case)
        finally:
            store.close()
        selected = request.query_params.get("action", "")
        return render_template(
            request,
            "recording_history.html",
            {
                "shell": True,
                "title": "녹화 이력",
                "heading": "녹화 이력",
                "section": "detail",
                "connected": True,
                "state": "ready",
                "dirty": False,
                "query": UiQueryState("", "name", "", "", ""),
                "crumbs": (("녹화 이력", f"/ui/projects/{project}/cases/{case}/recordings"),),
                "list_href": f"/ui/projects/{project}/cases/{case}/definition",
                "detail_href": f"/ui/projects/{project}/cases/{case}/recordings",
                "request": request,
                "project_id": str(project),
                "case_id": str(case),
                "rows": page["items"],
                "selected_action": selected,
            },
        )

    async def post_rerecording(case_id: str, request: Request) -> JSONResponse:
        request_key = request.headers.get("idempotency-key", "").strip()
        if request_key == "":
            return _error(422, "validation", "Idempotency-Key is required", {"Idempotency-Key": ["required"]})
        parsed = _parse_uuid(case_id)
        if parsed is None:
            return _error(404, "not_found", "case was not found", {})
        payload = await _body(request)
        if isinstance(payload, JSONResponse):
            return payload
        try:
            project_id = UUID(str(payload.get("project_id")))
            spec = RerecordInput(
                parsed,
                UUID(str(payload.get("base_version_id"))),
                UUID(str(payload.get("expected_head"))),
                str(payload.get("reason", "")),
                str(payload.get("resource_id", "")),
                str(payload.get("web_url", "")),
                str(payload.get("data_name", "")),
                str(payload.get("reset_policy", "")),
                payload.get("confirm_device") is True,
                payload.get("confirm_target") is True,
                payload.get("confirm_data") is True,
                payload.get("confirm_reset") is True,
                None if payload.get("objective_diff") in {None, ""} else str(payload.get("objective_diff")),
            )
        except (TypeError, ValueError):
            return _error(422, "validation", "invalid rerecording", {})
        store = request.app.state.open_store()
        try:
            migrate_store(store)
            with bound_auth_store(store):
                try:
                    actor = authorize_browser(request, project_id, "rerecord")
                except CsrfRejected:
                    return _error(403, "permission", "csrf token was rejected", {})
                except OriginRejected:
                    return _error(403, "permission", "origin was rejected", {})
                except ProjectHidden:
                    return _error(404, "not_found", "case was not found", {})
                except AuthRequired:
                    return _error(401, "unauthorized", "session is missing", {})
                try:
                    with store.transaction() as connection:
                        receipt = start_rerecording(connection, actor, project_id, spec, request_key)
                        stored = connection.execute(
                            """
                            SELECT case_id, base_case_version_id FROM recordings
                            WHERE project_id = ? AND recording_id = ?
                            """,
                            (str(project_id), str(receipt.recording_id)),
                        ).fetchone()
                except JobConflict:
                    return _error(409, "conflict", "idempotency body does not match", {})
                except (HashMismatch, ResourceBusy):
                    return _error(409, "conflict", "rerecording was rejected", {})
                except PreflightRejected as exc:
                    return _error(422, "validation", exc.reason, {})
        finally:
            store.close()
        return JSONResponse(
            status_code=200 if receipt.replayed else 201,
            content={
                "recording_id": str(receipt.recording_id),
                "job_id": str(receipt.job_id),
                "replayed": receipt.replayed,
                "case_id": None if stored is None else str(stored[0]),
                "base_case_version_id": None if stored is None or stored[1] is None else str(stored[1]),
            },
        )

    async def rerecord_page(project_id: str, case_id: str, request: Request) -> HTMLResponse:
        from aiqa.api.auth import authorize_page
        from aiqa.web.routes import UiQueryState, render_template

        try:
            project = UUID(project_id)
            case = UUID(case_id)
        except ValueError:
            return HTMLResponse(status_code=404, content="케이스를 찾지 못했습니다.")
        store = request.app.state.open_store()
        try:
            migrate_store(store)
            with bound_auth_store(store):
                try:
                    authorize_page(request, project)
                except (CsrfRejected, OriginRejected, ProjectHidden, AuthRequired):
                    return HTMLResponse(status_code=401, content="이 화면을 볼 권한이 없습니다.")
        finally:
            store.close()
        return render_template(
            request,
            "components/rerecord.html",
            {
                "shell": True,
                "title": "전체 재녹화",
                "heading": "전체 재녹화",
                "section": "detail",
                "connected": True,
                "state": "ready",
                "dirty": False,
                "query": UiQueryState("", "name", "", "", ""),
                "crumbs": (("전체 재녹화", f"/ui/projects/{project}/cases/{case}/rerecord"),),
                "list_href": f"/ui/projects/{project}/cases/{case}/recordings",
                "detail_href": f"/ui/projects/{project}/cases/{case}/rerecord",
                "request": request,
                "base_version_id": request.query_params.get("base", ""),
            },
        )

    application.add_api_route("/api/v1/cases/{case_id}/rerecordings", post_rerecording, methods=["POST"])
    application.add_api_route(
        "/ui/projects/{project_id}/cases/{case_id}/rerecord",
        rerecord_page,
        methods=["GET"],
        response_class=HTMLResponse,
    )
    application.add_api_route("/api/v1/cases/{case_id}/recordings", get_case_recordings, methods=["GET"])
    application.add_api_route("/api/v1/recordings/{recording_id}/manifests", get_recording_manifests, methods=["GET"])
    application.add_api_route(
        "/ui/projects/{project_id}/cases/{case_id}/recordings",
        history_page,
        methods=["GET"],
        response_class=HTMLResponse,
    )
    application.add_api_route(
        "/api/v1/recordings/{recording_id}/evidence-recoveries",
        post_recovery,
        methods=["POST"],
    )
    application.state.recordings_installed = True


def _parse_uuid(value: str) -> UUID | None:
    try:
        return UUID(value)
    except ValueError:
        return None


def _case_project(connection: object, case_id: UUID) -> UUID | None:
    row = connection.execute(  # type: ignore[attr-defined]
        "SELECT project_id FROM automation_cases WHERE case_id = ?",
        (str(case_id),),
    ).fetchone()
    return None if row is None else UUID(str(row[0]))


def _recording_project(connection: object, recording_id: UUID) -> UUID | None:
    row = connection.execute(  # type: ignore[attr-defined]
        "SELECT project_id FROM recordings WHERE recording_id = ?",
        (str(recording_id),),
    ).fetchone()
    return None if row is None else UUID(str(row[0]))


def _history_page(connection: object, project_id: UUID, case_id: UUID) -> dict[str, object]:
    rows = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT recordings.recording_id, recordings.input_case_version_id, recordings.base_case_version_id,
               recordings.storage_status, recordings.stop_status, recordings.completion_status,
               recordings.evidence_status, versions.settings_json, versions.created_at
        FROM recordings
        JOIN case_versions AS versions
          ON versions.project_id = recordings.project_id
         AND versions.case_id = recordings.case_id
         AND versions.version_id = recordings.input_case_version_id
        WHERE recordings.project_id = ? AND recordings.case_id = ?
        ORDER BY recordings.recording_id
        """,
        (str(project_id), str(case_id)),
    ).fetchall()
    items = []
    for row in rows:
        produced = _produced(connection, project_id, str(row[0]))
        review = _review_state(connection, project_id, case_id, str(row[1]), produced[0])
        settings = json.loads(str(row[7]))
        target = settings.get("target_kind") if type(settings) is dict else None
        items.append(
            {
                "recording_id": str(row[0]),
                "input_case_version_id": str(row[1]),
                "output_version_id": produced[0],
                "base_case_version_id": None if row[2] is None else str(row[2]),
                "target": None if target is None else str(target),
                "observed_at": str(row[8]),
                "action_count": _action_count(connection, project_id, case_id, str(row[1])),
                "storage_status": str(row[3]),
                "stop_status": str(row[4]),
                "outcome": None if str(row[5]) == "open" else str(row[5]),
                "procedure_readiness": _procedure(str(row[5]), str(row[6])),
                "evidence_completeness": str(row[6]),
                "review_status": review,
                "server_saved": str(row[3]) == "stored",
                "receipt_id": produced[1],
            }
        )
    return {"items": items, "next_cursor": None, "snapshot_seq": 0}


def _manifest_page(connection: object, project_id: UUID, recording_id: UUID) -> dict[str, object]:
    rows = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT manifests.manifest_id, manifests.revision, manifests.kind, manifests.prior_manifest_id,
               manifests.evidence_completeness, receipts.receipt_id, receipts.produced_version_id
        FROM recording_manifests AS manifests
        LEFT JOIN materialization_receipts AS receipts
          ON receipts.project_id = manifests.project_id AND receipts.manifest_id = manifests.manifest_id
        WHERE manifests.project_id = ? AND manifests.recording_id = ?
        ORDER BY manifests.revision
        """,
        (str(project_id), str(recording_id)),
    ).fetchall()
    items = [
        {
            "manifest_id": str(row[0]),
            "revision": int(row[1]),
            "kind": str(row[2]),
            "prior_manifest_id": None if row[3] is None else str(row[3]),
            "evidence_completeness": str(row[4]),
            "receipt_id": None if row[5] is None else str(row[5]),
            "produced_version_id": None if row[6] is None else str(row[6]),
        }
        for row in rows
    ]
    return {"items": items, "next_cursor": None, "snapshot_seq": 0}


def _produced(connection: object, project_id: UUID, recording_id: str) -> tuple[str | None, str | None]:
    row = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT receipts.produced_version_id, receipts.receipt_id
        FROM recording_manifests AS manifests
        JOIN materialization_receipts AS receipts
          ON receipts.project_id = manifests.project_id AND receipts.manifest_id = manifests.manifest_id
        WHERE manifests.project_id = ? AND manifests.recording_id = ?
        ORDER BY manifests.revision DESC LIMIT 1
        """,
        (str(project_id), recording_id),
    ).fetchone()
    if row is None:
        return None, None
    return str(row[0]), str(row[1])


def _review_state(
    connection: object, project_id: UUID, case_id: UUID, input_version_id: str, output_version_id: str | None
) -> str:
    rows = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT decisions.state
        FROM reviews
        JOIN review_decisions AS decisions
          ON decisions.project_id = reviews.project_id AND decisions.review_id = reviews.review_id
        WHERE reviews.project_id = ? AND reviews.case_id = ? AND reviews.case_version_id IN (?, ?)
        """,
        (str(project_id), str(case_id), input_version_id, output_version_id or input_version_id),
    ).fetchall()
    states = {str(row[0]) for row in rows}
    if "rejected" in states:
        return "rejected"
    if "approved" in states:
        return "approved"
    return "none"


def _action_count(connection: object, project_id: UUID, case_id: UUID, version_id: str) -> int:
    row = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT COUNT(*) FROM actions
        WHERE project_id = ? AND case_id = ? AND case_version_id = ?
        """,
        (str(project_id), str(case_id), version_id),
    ).fetchone()
    return 0 if row is None else int(row[0])


def _procedure(completion: str, evidence: str) -> str:
    if completion in {"error", "interrupted"}:
        return "needs_review"
    if completion == "open" or evidence != "complete":
        return "incomplete"
    return "complete"


def _limits(spec: EvidenceRecoverySpec) -> str:
    import json

    from aiqa.recording.recovery import _body_hash

    return json.dumps({"recovery_hash": _body_hash(spec)}, sort_keys=True)


def _spec(project_id: UUID, recording_id: UUID, request_key: str, payload: dict[str, object]) -> EvidenceRecoverySpec:
    raw = payload.get("captures")
    if type(raw) is not list or raw == []:
        raise ValueError("captures are required")
    captures: list[RecoveryCapture] = []
    for item in raw:
        if type(item) is not dict:
            raise ValueError("capture is invalid")
        encoded = item.get("png_b64")
        action_id = item.get("action_id")
        timing = item.get("timing")
        if type(encoded) is not str or type(action_id) is not str or type(timing) is not str:
            raise ValueError("capture is invalid")
        captures.append(
            RecoveryCapture(action_id, timing, base64.b64decode(encoded.encode("ascii"), validate=True))
        )
    return EvidenceRecoverySpec(project_id, recording_id, request_key, tuple(captures))


async def _seal_route(recording_id: str, request: Request, kind: str) -> JSONResponse:
    request_key = request.headers.get("idempotency-key", "").strip()
    if request_key == "":
        return _error(422, "validation", "Idempotency-Key is required", {"Idempotency-Key": ["required"]})
    try:
        recording = UUID(recording_id)
    except ValueError:
        return _error(404, "not_found", "recording was not found", {})
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    try:
        project_id = UUID(str(payload.get("project_id")))
    except (TypeError, ValueError):
        return _error(422, "validation", "invalid finish", {})
    store = request.app.state.open_store()
    try:
        migrate_store(store)
        with bound_auth_store(store):
            try:
                actor = authorize_browser(request, project_id, "recording_finish")
            except CsrfRejected:
                return _error(403, "permission", "csrf token was rejected", {})
            except OriginRejected:
                return _error(403, "permission", "origin was rejected", {})
            except ProjectHidden:
                return _error(404, "not_found", "recording was not found", {})
            except AuthRequired:
                return _error(401, "unauthorized", "session is missing", {})
            try:
                with store.transaction() as connection:
                    if kind == "stop":
                        view = stop_recording(connection, actor, project_id, recording, request_key)
                        body = {
                            "recording_id": str(view.recording_id),
                            "completion_status": view.completion_status,
                            "approval_id": view.approval_id,
                        }
                    else:
                        raw_ids = payload.get("artifact_ids", [])
                        if type(raw_ids) is not list or any(type(item) is not str for item in raw_ids):
                            return _error(422, "validation", "invalid finish", {})
                        spec = RecordingFinishInput(
                            recording,
                            str(payload.get("outcome", "")),
                            int(payload.get("final_seq", -1)),
                            tuple(raw_ids),
                            request_key,
                        )
                        receipt = finish_recording(connection, actor, project_id, spec)
                        body = {
                            "manifest_id": str(receipt.manifest_id),
                            "recording_id": str(receipt.recording_id),
                            "replayed": receipt.replayed,
                            "replay_package_id": None,
                        }
            except FinishConflict:
                return _error(409, "conflict", "finish body does not match", {})
            except PreflightRejected as exc:
                return _error(422, "validation", exc.reason, {})
            except (TypeError, ValueError):
                return _error(422, "validation", "invalid finish", {})
    finally:
        store.close()
    return JSONResponse(status_code=200 if body.get("replayed") else 201, content=body)


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
