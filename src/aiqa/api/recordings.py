"""Recording recovery route. The route does not open a device or a model."""

from __future__ import annotations

import base64
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from aiqa.api.auth import (
    AuthRequired,
    CsrfRejected,
    OriginRejected,
    ProjectHidden,
    authorize_browser,
    bound_auth_store,
)
from aiqa.contracts.jobs import IdempotencyKey, JobSubmission
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

    application.add_api_route(
        "/api/v1/recordings/{recording_id}/evidence-recoveries",
        post_recovery,
        methods=["POST"],
    )
    application.state.recordings_installed = True


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
