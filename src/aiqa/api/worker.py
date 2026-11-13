"""Worker claim route. The route does not open a device or a model."""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from aiqa.api.auth import (
    AuthRequired,
    WorkerDenied,
    bound_auth_store,
    worker_scope_from_token,
)
from aiqa.contracts.jobs import LeaseToken
from aiqa.models.broker import (
    ModelRequestConflict,
    ModelRequestDenied,
    WorkerModelCallBridge,
    WorkerModelRequest,
)
from aiqa.security.secrets import scrub_worker_dto
from aiqa.store.database import migrate_store
from aiqa.store.evidence import (
    ArtifactBinding,
    EvidenceArtifactPart,
    EvidenceHashRejected,
    EventConflict,
    UnsanitizedEvidence,
    bind_artifact_ingest,
    commit_sanitized_evidence,
    reset_artifact_ingest,
)
from aiqa.store.models import EventEnvelope
from aiqa.contracts.worker_attempt import ClaimReceipt
from aiqa.contracts.worker_attempt import WorkerAttemptFinishInput
from aiqa.store.queue import (
    ClaimConflict,
    CleanupConfirmationInput,
    FinishConflict,
    FinishRejected,
    LeaseDenied,
    RunnerConflict,
    StaleGeneration,
)
from aiqa.worker.presence import HEARTBEAT_SECONDS, OFFLINE_AFTER, PresenceDenied, report_presence
from aiqa.worker.service import (
    acknowledge_attempt,
    bind_claim_store,
    claim_job,
    confirm_attempt_cleanup,
    finish_attempt,
    ingest_events,
    renew_lease,
)


def model_check_requires_physical_session() -> bool:
    """model_check is a maintenance management job. No device/browser session."""

    return False


def install_worker(application: FastAPI) -> None:
    """Attach the claim route once. This does not open SQLite."""

    if getattr(application.state, "worker_installed", False):
        return

    async def post_claim(request: Request) -> Response:
        rejected = _idempotency(request)
        if rejected is not None:
            return rejected
        header = request.headers.get("authorization", "")
        if not header.startswith("Bearer ") or header.removeprefix("Bearer ").strip() == "":
            return _error(401, "unauthorized", "worker token is missing", {})
        payload = await _body(request)
        if isinstance(payload, JSONResponse):
            return payload
        try:
            _instant(payload.get("now"))
        except ValueError:
            return _error(422, "validation", "invalid claim", {})
        token = header.removeprefix("Bearer ").strip()
        request_key = request.headers.get("idempotency-key", "")
        native_id: str | None = None
        intent = None
        claim_origin: str | None = None
        claim_limits: dict[str, object] | None = None
        with _bound(request) as store:
            try:
                worker = worker_scope_from_token(token)
                with bind_claim_store(store):
                    lease = claim_job(
                        worker,
                        _server_now(),
                        boot_id=payload.get("boot_id") or "",
                        request_key=request_key,
                        project_id=payload.get("project_id"),
                    )
                if isinstance(lease, ClaimReceipt):
                    with store.transaction() as connection:
                        if lease.physical_key_id is not None:
                            row = connection.execute(
                                """
                                SELECT native_id FROM physical_resource_keys
                                WHERE physical_key_id = ?
                                """,
                                (str(lease.physical_key_id),),
                            ).fetchone()
                            if row is not None and type(row[0]) is str and str(row[0]).strip() != "":
                                native_id = str(row[0]).strip()
                        if lease.snapshot.purpose == "recording":
                            from aiqa.recording.intent import load_intent_for_attempt

                            intent = load_intent_for_attempt(
                                connection, lease.project_id, lease.attempt_id
                            )
                        claim_origin = _job_origin(connection, lease.project_id, lease.job_id)
                        claim_limits = _job_limits(connection, lease.project_id, lease.job_id)
            except AuthRequired:
                return _error(401, "unauthorized", "worker token is missing", {})
            except WorkerDenied:
                return _error(403, "permission", "worker cannot claim", {})
            except ClaimConflict:
                return _error(409, "conflict", "claim idempotency conflict", {})
            except ValueError:
                return _error(422, "validation", "invalid claim", {})
        if lease is None:
            return Response(status_code=204)
        if isinstance(lease, ClaimReceipt):
            return JSONResponse(
                status_code=200,
                content=_claim_payload(
                    lease,
                    native_id=native_id,
                    intent=intent,
                    origin=claim_origin,
                    limits=claim_limits,
                ),
            )
        return JSONResponse(
            status_code=200,
            content={
                "project_id": str(lease.project_id),
                "job_id": str(lease.job_id),
                "generation": lease.generation,
                "worker_id": lease.worker_id,
                "physical_key_id": None if lease.physical_key_id is None else str(lease.physical_key_id),
                "expires_at": lease.expires_at,
                "attempt_id": str(lease.attempt_id),
            },
        )

    async def post_heartbeat(request: Request) -> Response:
        header = request.headers.get("authorization", "")
        if not header.startswith("Bearer "):
            return _error(401, "unauthorized", "worker token is missing", {})
        payload = await _body(request)
        if isinstance(payload, JSONResponse):
            return payload
        with _bound(request) as store:
            try:
                worker = worker_scope_from_token(header.removeprefix("Bearer ").strip())
                expected = {
                    "worker_id": worker.worker_id,
                    "project_id": str(worker.permitted_projects[0]),
                    "purpose": worker.permitted_purposes[0],
                }
                if any(key in payload and payload[key] != value for key, value in expected.items()):
                    raise PresenceDenied
                with store.transaction() as connection:
                    presence = report_presence(connection, worker, payload.get("boot_id"), _server_now())
            except AuthRequired:
                return _error(401, "unauthorized", "worker token is missing", {})
            except PresenceDenied:
                return _error(403, "permission", "worker cannot report presence", {})
            except ValueError:
                return _error(422, "validation", "invalid heartbeat", {})
        return JSONResponse({
            "state": presence.state,
            "last_seen": presence.last_seen.isoformat(),
            "heartbeat_seconds": HEARTBEAT_SECONDS,
            "offline_after_seconds": int(OFFLINE_AFTER.total_seconds()),
        })

    async def post_renewal(request: Request) -> Response:
        return await _lease_call(request, renew=True)

    async def post_ack(request: Request) -> Response:
        return await _lease_call(request, renew=False)

    async def post_events(request: Request) -> Response:
        rejected = _idempotency(request)
        if rejected is not None:
            return rejected
        header = request.headers.get("authorization", "")
        if not header.startswith("Bearer ") or header.removeprefix("Bearer ").strip() == "":
            return _error(401, "unauthorized", "worker token is missing", {})
        payload = await _body(request)
        if isinstance(payload, JSONResponse):
            return payload
        try:
            now = _instant(payload.get("now"))
            lease = LeaseToken(
                _uuid(payload.get("project_id")),
                _uuid(payload.get("job_id")),
                _generation(payload.get("generation")),
            )
            events = _events(lease.project_id, payload.get("events"))
        except (TypeError, ValueError):
            return _error(422, "validation", "invalid event", {})
        token = header.removeprefix("Bearer ").strip()
        with _bound(request) as store:
            try:
                worker = worker_scope_from_token(token)
                with bind_claim_store(store):
                    receipt = ingest_events(lease, events, worker, now)
            except AuthRequired:
                return _error(401, "unauthorized", "worker token is missing", {})
            except LeaseDenied:
                return _error(403, "permission", "worker cannot use this lease", {})
            except StaleGeneration:
                return _error(409, "conflict", "lease generation is stale", {})
            except EventConflict:
                return _error(409, "conflict", "event hash does not match", {})
            except ValueError:
                return _error(422, "validation", "invalid event", {})
        return JSONResponse(
            status_code=200,
            content={
                "attempt_id": str(receipt.attempt_id),
                "committed_seq": receipt.committed_seq,
                "committed_hash": receipt.committed_hash,
                "stale_count": receipt.stale_count,
            },
        )

    async def post_cleanup(request: Request) -> Response:
        rejected = _idempotency(request)
        if rejected is not None:
            return rejected
        header = request.headers.get("authorization", "")
        if not header.startswith("Bearer ") or header.removeprefix("Bearer ").strip() == "":
            return _error(401, "unauthorized", "worker token is missing", {})
        payload = await _body(request)
        if isinstance(payload, JSONResponse):
            return payload
        try:
            now = _instant(payload.get("now"))
            proofs = payload.get("proof_refs", [])
            if type(proofs) is not list or any(type(item) is not str for item in proofs):
                raise ValueError("proof refs are invalid")
            physical = payload.get("physical_key_id")
            confirmation = CleanupConfirmationInput(
                _uuid(payload.get("project_id")),
                _uuid(payload.get("job_id")),
                _uuid(payload.get("attempt_id")),
                _generation(payload.get("generation")),
                None if physical is None else _uuid(physical),
                tuple(proofs),
            )
        except (TypeError, ValueError):
            return _error(422, "validation", "invalid cleanup", {})
        token = header.removeprefix("Bearer ").strip()
        with _bound(request) as store:
            try:
                worker = worker_scope_from_token(token)
                with bind_claim_store(store):
                    receipt = confirm_attempt_cleanup(worker, confirmation, now)
            except AuthRequired:
                return _error(401, "unauthorized", "worker token is missing", {})
            except LeaseDenied:
                return _error(403, "permission", "worker cannot use this lease", {})
            except StaleGeneration:
                return _error(409, "conflict", "lease generation is stale", {})
            except ValueError:
                return _error(422, "validation", "invalid cleanup", {})
        return JSONResponse(
            status_code=200,
            content={
                "project_id": str(receipt.project_id),
                "attempt_id": str(receipt.attempt_id),
                "released": receipt.released,
                "quarantined": receipt.quarantined,
                "replayed": receipt.replayed,
            },
        )

    async def post_evidence_commit(request: Request) -> Response:
        rejected = _idempotency(request)
        if rejected is not None:
            return rejected
        header = request.headers.get("authorization", "")
        if not header.startswith("Bearer ") or header.removeprefix("Bearer ").strip() == "":
            return _error(401, "unauthorized", "worker token is missing", {})
        key = request.headers.get("idempotency-key", "").strip()
        if key == "":
            return _error(422, "validation", "Idempotency-Key is required", {"Idempotency-Key": ["required"]})
        payload = await _body(request)
        if isinstance(payload, JSONResponse):
            return payload
        try:
            now = _instant(payload.get("now"))
            lease = LeaseToken(
                _uuid(payload.get("project_id")),
                _uuid(payload.get("job_id")),
                _generation(payload.get("generation")),
            )
            sanitized = payload.get("sanitized")
            events = _commit_events(lease.project_id, payload.get("events"))
            artifacts = _commit_artifacts(payload.get("artifacts"))
            if events == [] and artifacts == []:
                raise ValueError("evidence is required")
            fingerprint = _commit_fingerprint(payload)
        except (TypeError, ValueError, EvidenceHashRejected):
            return _error(422, "validation", "invalid evidence commit", {})
        token = header.removeprefix("Bearer ").strip()
        with _bound(request) as store:
            try:
                worker = worker_scope_from_token(token)
                marker = bind_artifact_ingest(ArtifactBinding(store, worker, now))
                try:
                    ack = commit_sanitized_evidence(
                        ArtifactBinding(store, worker, now),
                        lease,
                        sanitized=bool(sanitized) and sanitized is True,
                        events=events,
                        artifacts=artifacts,
                        request_key=key,
                        body_fingerprint=fingerprint,
                    )
                finally:
                    reset_artifact_ingest(marker)
            except AuthRequired:
                return _error(401, "unauthorized", "worker token is missing", {})
            except UnsanitizedEvidence:
                return _error(422, "validation", "unsanitized evidence cannot be committed", {})
            except LeaseDenied:
                return _error(403, "permission", "worker cannot use this lease", {})
            except StaleGeneration:
                return _error(409, "conflict", "lease generation is stale", {})
            except EventConflict:
                return _error(409, "conflict", "event hash does not match", {})
            except EvidenceHashRejected:
                return _error(422, "validation", "artifact hash does not match", {})
            except ValueError:
                return _error(422, "validation", "invalid evidence commit", {})
        return JSONResponse(
            status_code=200,
            content={
                "attempt_id": str(ack.attempt_id),
                "contiguous_seq": ack.contiguous_seq,
                "prefix_hash": ack.prefix_hash,
                "stale_count": ack.stale_count,
                "late": ack.late,
                "artifact_count": ack.artifact_count,
                "artifact_ids": list(ack.artifact_ids),
            },
        )

    async def post_attempt_finish(request: Request) -> Response:
        rejected = _idempotency(request)
        if rejected is not None:
            return rejected
        header = request.headers.get("authorization", "")
        if not header.startswith("Bearer ") or header.removeprefix("Bearer ").strip() == "":
            return _error(401, "unauthorized", "worker token is missing", {})
        key = request.headers.get("idempotency-key", "").strip()
        if key == "":
            return _error(422, "validation", "Idempotency-Key is required", {"Idempotency-Key": ["required"]})
        payload = await _body(request)
        if isinstance(payload, JSONResponse):
            return payload
        try:
            now = _instant(payload.get("now"))
            finish = _attempt_finish(payload)
            fingerprint = _commit_fingerprint(payload)
        except (TypeError, ValueError):
            return _error(422, "validation", "invalid finish", {})
        token = header.removeprefix("Bearer ").strip()
        with _bound(request) as store:
            try:
                worker = worker_scope_from_token(token)
                with bind_claim_store(store):
                    receipt = finish_attempt(
                        worker,
                        finish,
                        request_key=key,
                        body_hash=fingerprint,
                        now=now,
                    )
            except AuthRequired:
                return _error(401, "unauthorized", "worker token is missing", {})
            except LeaseDenied:
                return _error(403, "permission", "worker cannot use this lease", {})
            except StaleGeneration:
                return _error(409, "conflict", "lease generation is stale", {})
            except FinishConflict:
                return _error(409, "conflict", "finish body does not match", {})
            except FinishRejected as exc:
                return _error(422, "validation", str(exc) or "finish rejected", {})
            except ValueError:
                return _error(422, "validation", "invalid finish", {})
        return JSONResponse(
            status_code=200,
            content={
                "project_id": str(receipt.project_id),
                "job_id": str(receipt.job_id),
                "attempt_id": str(receipt.attempt_id),
                "status": receipt.status,
                "outcome": receipt.outcome,
                "replayed": receipt.replayed,
                "approved": receipt.approved,
                "verdict": receipt.verdict,
                "purpose": receipt.purpose,
            },
        )

    async def post_model_observations(request: Request) -> Response:
        rejected = _idempotency(request)
        if rejected is not None:
            return rejected
        header = request.headers.get("authorization", "")
        if not header.startswith("Bearer "):
            return _model_error(401,"unauthorized","worker token is missing",{})
        payload = await _body(request)
        if isinstance(payload,JSONResponse):
            return payload
        try:
            project_id = _uuid(payload.get("project_id"))
            item_id = _text(payload.get("item_id"),"item_id")
            model_request = _model_request(payload)
        except (ValueError,TypeError):
            return _model_error(422,"validation","invalid observation",{})
        with _bound(request):
            try:
                worker = worker_scope_from_token(header.removeprefix("Bearer ").strip())
            except AuthRequired:
                return _model_error(401,"unauthorized","worker token is missing",{})
            except WorkerDenied:
                return _model_error(403,"permission","worker cannot register observation",{})
            from starlette.concurrency import run_in_threadpool
            from aiqa.models.model_observations import register_observation_http
            status,body = await run_in_threadpool(register_observation_http,request.app.state.open_store,
                worker,model_request,project_id,item_id,request.headers.get("idempotency-key","").strip(),payload)
            return JSONResponse(status_code=status,content=body)

    async def post_model_requests(request: Request) -> Response:
        rejected = _idempotency(request)
        if rejected is not None:
            return rejected
        header = request.headers.get("authorization", "")
        if not header.startswith("Bearer ") or header.removeprefix("Bearer ").strip() == "":
            return _model_error(401, "unauthorized", "worker token is missing", {})
        key = request.headers.get("idempotency-key", "").strip()
        payload = await _body(request)
        if isinstance(payload, JSONResponse):
            return payload
        try:
            model_request = _model_request(payload)
            project_id = _uuid(payload.get("project_id"))
            item_id = _text(payload.get("item_id"), "item_id")
            actor_raw = payload.get("actor_id")
            actor_id = _uuid(actor_raw) if actor_raw is not None else uuid4()
            presented_intent = payload.get("intent_hash")
            if presented_intent is not None and type(presented_intent) is not str:
                raise ValueError("intent_hash is invalid")
        except (TypeError, ValueError):
            return _model_error(422, "validation", "invalid model request", {})
        token = header.removeprefix("Bearer ").strip()
        gateway = request.app.state.model_gateway
        with _bound(request) as store:
            try:
                worker = worker_scope_from_token(token)
                if project_id not in worker.permitted_projects:
                    return _model_error(403, "permission", "worker cannot request model", {})
                from aiqa.models.recording_authorization import is_recording_attempt
                with store.transaction() as connection:
                    recording_owned = is_recording_attempt(connection,project_id,item_id)
                if recording_owned:
                    from aiqa.models.recording_requests import handle_recording_http
                    from starlette.concurrency import run_in_threadpool
                    status,body=await run_in_threadpool(handle_recording_http,request.app.state.open_store,
                        gateway,request.app.state.settings,worker,model_request,project_id,item_id,key,presented_intent)
                    return JSONResponse(status_code=status,content=body)
                if not gateway.has_policy(project_id, item_id):
                    return _model_error(404, "permission", "policy", {})
                if model_request.purpose == "recording" and model_request.role == "authoring":
                    from dataclasses import replace

                    from aiqa.recording.intent import IntentRejected, bind_authoring_sanitized_inputs

                    with store.transaction() as connection:
                        try:
                            bound_inputs = bind_authoring_sanitized_inputs(
                                connection,
                                project_id=project_id,
                                attempt_id=item_id,
                                presented_hash=presented_intent,
                                worker_inputs=model_request.sanitized_inputs,
                            )
                        except IntentRejected as exc:
                            return _model_error(403, "permission", exc.reason, {})
                    model_request = replace(model_request, sanitized_inputs=bound_inputs)
                from starlette.concurrency import run_in_threadpool
                receipt = await run_in_threadpool(_legacy_model_request, request.app.state.open_store,
                    gateway, worker, model_request, project_id, item_id, key, actor_id)
            except AuthRequired:
                return _model_error(401, "unauthorized", "worker token is missing", {})
            except WorkerDenied:
                return _model_error(403, "permission", "worker cannot request model", {})
            except ModelRequestConflict:
                return _model_error(409, "conflict", "model request idempotency conflict", {})
            except ModelRequestDenied as exc:
                status = 404 if exc.status == 404 else 403 if exc.status == 403 else exc.status
                return _model_error(status, "permission" if status in {403, 404} else "unavailable", exc.reason, {},provider_dispatched=exc.provider_dispatched)
            except ValueError:
                return _model_error(422, "validation", "invalid model request", {})
        content = scrub_worker_dto(
            {
                "call_id": str(receipt.call_id),
                "allowed": receipt.allowed,
                "reason": receipt.reason,
                "actual_model": receipt.actual_model,
                "measurement_status": receipt.measurement_status,
                "provider_request_id": receipt.provider_request_id,
                "role": receipt.role,
                "purpose": receipt.purpose,
                "replayed": receipt.replayed,
                "usage": receipt.usage,
                "content": receipt.content,
                "item_id": receipt.item_id,
                "generation": receipt.generation,
            }
        )
        return JSONResponse(status_code=200, content=content)

    application.add_api_route("/api/v1/worker/claims", post_claim, methods=["POST"])
    application.add_api_route("/api/v1/worker/heartbeats", post_heartbeat, methods=["POST"])
    application.add_api_route("/api/v1/worker/lease-renewals", post_renewal, methods=["POST"])
    application.add_api_route("/api/v1/worker/attempt-acks", post_ack, methods=["POST"])
    application.add_api_route("/api/v1/worker/events", post_events, methods=["POST"])
    application.add_api_route("/api/v1/worker/cleanup-confirmations", post_cleanup, methods=["POST"])
    application.add_api_route("/api/v1/worker/evidence-commits", post_evidence_commit, methods=["POST"])
    application.add_api_route("/api/v1/worker/attempt-finishes", post_attempt_finish, methods=["POST"])
    application.add_api_route("/api/v1/worker/model-observations", post_model_observations, methods=["POST"])
    application.add_api_route("/api/v1/worker/model-requests", post_model_requests, methods=["POST"])
    application.state.worker_installed = True


def _attempt_finish(payload: dict) -> WorkerAttemptFinishInput:
    hashes = payload.get("source_artifact_hashes", [])
    if type(hashes) is not list or any(type(item) is not str for item in hashes):
        raise ValueError("source artifact hashes are invalid")
    mapping = payload.get("action_mapping", "{}")
    if type(mapping) is not str:
        raise ValueError("action mapping is invalid")
    physical = payload.get("physical_key_id")
    evidence = payload.get("evidence_complete")
    ambiguous = payload.get("ambiguous_dispatch")
    if type(evidence) is not bool or type(ambiguous) is not bool:
        raise ValueError("finish flags are invalid")
    final_seq = payload.get("final_seq")
    last_ack_seq = payload.get("last_ack_seq")
    if type(final_seq) is not int or type(last_ack_seq) is not int:
        raise ValueError("finish seq is invalid")
    outcome = payload.get("outcome")
    last_ack_hash = payload.get("last_ack_hash")
    manifest_digest = payload.get("manifest_digest")
    if type(outcome) is not str or type(last_ack_hash) is not str or type(manifest_digest) is not str:
        raise ValueError("finish fields are invalid")
    return WorkerAttemptFinishInput(
        _uuid(payload.get("project_id")),
        _uuid(payload.get("job_id")),
        _uuid(payload.get("attempt_id")),
        _generation(payload.get("generation")),
        outcome,
        final_seq,
        last_ack_seq,
        last_ack_hash,
        manifest_digest,
        evidence,
        ambiguous,
        None if physical is None else _uuid(physical),
        tuple(hashes),
        mapping,
        bool(payload.get("cleanup_failed", False)),
        bool(payload.get("required_violation", False)),
    )


def _commit_events(project_id: UUID, value: object) -> list[EventEnvelope]:
    if value is None:
        return []
    if type(value) is not list:
        raise ValueError("events are invalid")
    if value == []:
        return []
    return _events(project_id, value)


def _commit_artifacts(value: object) -> list[EvidenceArtifactPart]:
    if value is None:
        return []
    if type(value) is not list:
        raise ValueError("artifacts are invalid")
    parts: list[EvidenceArtifactPart] = []
    for item in value:
        if type(item) is not dict:
            raise ValueError("artifact must be an object")
        filename = item.get("filename")
        media_type = item.get("media_type")
        declared_hash = item.get("declared_hash")
        declared_length = item.get("declared_length")
        body_b64 = item.get("body_b64")
        role = item.get("role", "source")
        if (
            type(filename) is not str
            or type(media_type) is not str
            or type(declared_hash) is not str
            or type(declared_length) is not int
            or type(body_b64) is not str
            or type(role) is not str
        ):
            raise ValueError("artifact fields are invalid")
        try:
            body = base64.b64decode(body_b64.encode("ascii"), validate=True)
        except Exception as exc:
            raise ValueError("artifact body is invalid") from exc
        digest = "sha256:" + hashlib.sha256(body).hexdigest()
        if declared_hash != digest or declared_length != len(body):
            raise EvidenceHashRejected("artifact hash does not match")
        owner_id = item.get("owner_id")
        attempt_id = item.get("attempt_id")
        action_id = item.get("action_id")
        if action_id is not None and type(action_id) is not str:
            raise ValueError("artifact action_id is invalid")
        parts.append(
            EvidenceArtifactPart(
                filename,
                media_type,
                declared_hash,
                declared_length,
                body,
                role,
                str(item.get("owner_kind") or "REC"),
                None if owner_id is None else _uuid(owner_id),
                None if attempt_id is None else _uuid(attempt_id),
                None if action_id is None or action_id.strip() == "" else action_id,
            )
        )
    return parts


def _commit_fingerprint(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _events(project_id: UUID, value: object) -> list[EventEnvelope]:
    if type(value) is not list or value == []:
        raise ValueError("events are required")
    events: list[EventEnvelope] = []
    for item in value:
        if type(item) is not dict:
            raise ValueError("event must be an object")
        local_seq = item.get("local_seq")
        if type(local_seq) is not int or local_seq < 1:
            raise ValueError("local seq is invalid")
        facts = item.get("minimum_facts")
        payload_hash = item.get("payload_hash")
        body_hash = item.get("body_hash")
        event_type = item.get("event_type")
        captured_at = item.get("captured_at")
        if type(facts) is not str or type(payload_hash) is not str or type(body_hash) is not str:
            raise ValueError("event hash is invalid")
        if type(event_type) is not str or type(captured_at) is not str:
            raise ValueError("event is invalid")
        detail = item.get("detail_payload")
        if detail is not None and type(detail) is not str:
            raise ValueError("event detail is invalid")
        events.append(
            EventEnvelope(
                project_id,
                _uuid(item.get("event_id")),
                _uuid(item.get("attempt_id")),
                local_seq,
                captured_at,
                event_type,
                facts,
                payload_hash,
                body_hash,
                detail,
            )
        )
    return events


async def _lease_call(request: Request, renew: bool) -> Response:
    rejected = _idempotency(request)
    if rejected is not None:
        return rejected
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer ") or header.removeprefix("Bearer ").strip() == "":
        return _error(401, "unauthorized", "worker token is missing", {})
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    try:
        now = _instant(payload.get("now"))
        lease = LeaseToken(_uuid(payload.get("project_id")), _uuid(payload.get("job_id")), _generation(payload.get("generation")))
        model_wait = payload.get("model_wait", False)
        nonce = None if renew else UUID(str(payload.get("runner_nonce")))
        if not renew and type(payload.get("runner_nonce")) is not str:
            raise ValueError("runner nonce is invalid")
        if type(model_wait) is not bool:
            raise ValueError("model wait is invalid")
    except (TypeError, ValueError):
        return _error(422, "validation", "invalid lease", {})
    token = header.removeprefix("Bearer ").strip()
    with _bound(request) as store:
        try:
            worker = worker_scope_from_token(token)
            with bind_claim_store(store):
                if renew:
                    view = renew_lease(worker, lease, now, model_wait, server_now=_server_now())
                else:
                    assert nonce is not None
                    receipt = acknowledge_attempt(lease, nonce, worker, now, server_now=_server_now())
        except AuthRequired:
            return _error(401, "unauthorized", "worker token is missing", {})
        except LeaseDenied:
            return _error(403, "permission", "worker cannot use this lease", {})
        except (StaleGeneration, RunnerConflict):
            return _error(409, "conflict", "lease generation is stale", {})
        except ValueError:
            return _error(422, "validation", "invalid lease", {})
    if renew:
        return JSONResponse(
            status_code=200,
            content={
                "project_id": str(view.project_id),
                "job_id": str(view.job_id),
                "generation": view.generation,
                "expires_at": view.expires_at,
                "lease_seconds": view.lease_seconds,
                "heartbeat_seconds": view.heartbeat_seconds,
                "poll_seconds": view.poll_seconds,
            },
        )
    return JSONResponse(
        status_code=200,
        content={
            "attempt_id": str(receipt.attempt_id),
            "runner_nonce": str(receipt.runner_nonce),
            "replayed": receipt.replayed,
        },
    )


def _job_limits(connection: object, project_id: object, job_id: object) -> dict[str, object] | None:
    """Load the job limits object for claim snapshots (probe/install routing)."""

    row = connection.execute(  # type: ignore[attr-defined]
        "SELECT limits FROM jobs WHERE project_id = ? AND job_id = ?",
        (str(project_id), str(job_id)),
    ).fetchone()
    if row is None:
        return None
    try:
        import json

        parsed = json.loads(str(row[0] or "{}"))
    except Exception:
        return None
    if type(parsed) is not dict:
        return None
    return parsed


def _job_origin(connection: object, project_id: object, job_id: object) -> str | None:
    """Read approved HTTPS origin pinned on the job limits for Web claims."""

    parsed = _job_limits(connection, project_id, job_id)
    if parsed is None:
        return None
    origin = parsed.get("origin")
    if type(origin) is str and origin.startswith("https://"):
        return origin
    return None


def _claim_payload(
    receipt: ClaimReceipt,
    *,
    native_id: str | None = None,
    intent: object | None = None,
    origin: str | None = None,
    limits: dict[str, object] | None = None,
) -> dict[str, object]:
    snapshot = receipt.snapshot
    snap: dict[str, object] = {
        "job_id": str(snapshot.job_id),
        "attempt_id": str(snapshot.attempt_id),
        "purpose": snapshot.purpose,
        "target_ref": snapshot.target_ref,
        "revision_ref": snapshot.revision_ref,
        "policy_ref": snapshot.policy_ref,
        "digest": snapshot.digest,
    }
    if snapshot.intent_hash is not None:
        snap["intent_hash"] = snapshot.intent_hash
    if snapshot.replay_package_id is not None:
        snap["replay_package_id"] = snapshot.replay_package_id
    if snapshot.replay_package_hash is not None:
        snap["replay_package_hash"] = snapshot.replay_package_hash
        snap["approved_digest"] = snapshot.replay_package_hash
    if snapshot.self_healing_enabled is not None:
        snap["self_healing_enabled"] = snapshot.self_healing_enabled
    if snapshot.approved_plan not in {None, ""}:
        snap["approved_plan"] = snapshot.approved_plan
    if intent is not None:
        from aiqa.contracts.worker_attempt import RecordingIntent
        from aiqa.recording.intent import intent_to_document

        if isinstance(intent, RecordingIntent):
            snap["intent"] = intent_to_document(intent)
    if origin is not None and origin.startswith("https://"):
        snap["origin"] = origin
    if limits is not None:
        snap["limits"] = limits
        resource = limits.get("resource_id")
        if type(resource) is str and resource.strip() != "":
            snap["resource_id"] = resource
    if native_id is not None and native_id.strip() != "":
        # Resolve registered device for Android/Web workers without changing the claim digest.
        snap["serial"] = native_id
        snap["native_id"] = native_id
    return {
        "project_id": str(receipt.project_id),
        "job_id": str(receipt.job_id),
        "generation": receipt.generation,
        "worker_id": receipt.worker_id,
        "physical_key_id": None if receipt.physical_key_id is None else str(receipt.physical_key_id),
        "expires_at": receipt.expires_at,
        "attempt_id": str(receipt.attempt_id),
        "session_id": receipt.session_id,
        "boot_id": receipt.boot_id,
        "replayed": receipt.replayed,
        "snapshot": snap,
    }


def _model_request(payload: dict[str, object]) -> WorkerModelRequest:
    inputs = payload.get("sanitized_inputs")
    if inputs is None:
        sanitized: tuple[str, ...] = ()
    elif type(inputs) is not list or any(type(item) is not str for item in inputs):
        raise ValueError("sanitized inputs are invalid")
    else:
        sanitized = tuple(inputs)
    check_id = payload.get("check_id")
    episode_id = payload.get("episode_id")
    if check_id is not None and type(check_id) is not str:
        raise ValueError("check_id is invalid")
    if episode_id is not None and type(episode_id) is not str:
        raise ValueError("episode_id is invalid")
    limit = payload.get("token_output_limit")
    if type(limit) is not int or limit < 1:
        raise ValueError("token_output_limit is invalid")
    generation = payload.get("generation")
    if generation is not None and (type(generation) is not int or generation < 1):
        raise ValueError("generation is invalid")
    return WorkerModelRequest(
        call_id=_uuid(payload.get("call_id")),
        purpose=_text(payload.get("purpose"), "purpose"),
        role=_text(payload.get("role"), "role"),
        owner_kind=_text(payload.get("owner_kind"), "owner_kind"),
        owner_id=_text(payload.get("owner_id"), "owner_id"),
        binding_revision=_generation(payload.get("binding_revision")),
        sanitized_inputs=sanitized,
        token_output_limit=limit,
        deadline=_text(payload.get("deadline"), "deadline"),
        check_id=check_id,
        episode_id=episode_id,
        generation=generation,
        model_observation_id=None if payload.get("model_observation_id") is None else str(_uuid(payload["model_observation_id"])),
    )


def _text(value: object, field: str) -> str:
    if type(value) is not str or value.strip() == "":
        raise ValueError(f"{field} is invalid")
    return value


def _uuid(value: object) -> UUID:
    if type(value) is not str:
        raise ValueError("id is invalid")
    return UUID(value)


def _generation(value: object) -> int:
    if type(value) is not int or value < 1:
        raise ValueError("generation is invalid")
    return value


def _server_now() -> datetime:
    return datetime.now(timezone.utc)


def _instant(value: object) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if type(value) is not str:
        raise ValueError("claim time is invalid")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("claim time must include a timezone")
    return parsed


@contextmanager
def _bound(request: Request) -> Iterator[object]:
    store = request.app.state.open_store()
    try:
        migrate_store(store)
        with bound_auth_store(store):
            yield store
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


def _idempotency(request: Request) -> JSONResponse | None:
    if not request.headers.get("idempotency-key"):
        return _error(422, "validation", "Idempotency-Key is required", {"Idempotency-Key": ["required"]})
    return None


def connect_verify_heal_model_bridge(
    gateway: object,
    worker: object,
    *,
    project_id: UUID,
    item_id: str,
    actor_id: UUID,
    purpose: str,
    store: object | None = None,
    binding_revision: int = 1,
    force_timeout: bool = False,
) -> WorkerModelCallBridge:
    """Build the worker model-request bridge used by replay verify/heal."""

    if not isinstance(gateway, object) or gateway is None:
        raise ValueError("model gateway is missing")
    return WorkerModelCallBridge(
        gateway,  # type: ignore[arg-type]
        worker,  # type: ignore[arg-type]
        project_id=project_id,
        item_id=item_id,
        actor_id=actor_id,
        purpose=purpose,
        store=store,
        binding_revision=binding_revision,
        force_timeout=force_timeout,
    )


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


def _model_error(status,code,message,fields,*,provider_dispatched=False):
    response=_error(status,code,message,fields)
    body=json.loads(response.body)
    body["error"].update(provider_dispatched=provider_dispatched,replayed=False)
    return JSONResponse(status_code=status,content=body)


def _legacy_model_request(open_store, gateway, worker, request, project_id, item_id, key, actor_id):
    # Legacy registered policies also wait for the gateway lock outside ASGI.
    store = open_store()
    try:
        return gateway.handle(worker, request, project_id=project_id, item_id=item_id,
            idempotency_key=key, actor_id=actor_id, store=store)
    finally:
        store.close()
