"""Worker claim route. The route does not open a device or a model."""

from __future__ import annotations

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
from aiqa.store.database import migrate_store
from aiqa.store.evidence import EventConflict
from aiqa.store.models import EventEnvelope
from aiqa.store.queue import LeaseDenied, RunnerConflict, StaleGeneration
from aiqa.worker.presence import HEARTBEAT_SECONDS, OFFLINE_AFTER, PresenceDenied, report_presence
from aiqa.worker.service import acknowledge_attempt, bind_claim_store, claim_job, ingest_events, renew_lease


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
        with _bound(request) as store:
            try:
                worker = worker_scope_from_token(token)
                with bind_claim_store(store):
                    lease = claim_job(worker, _server_now(), boot_id=payload.get("boot_id") or "")
            except AuthRequired:
                return _error(401, "unauthorized", "worker token is missing", {})
            except WorkerDenied:
                return _error(403, "permission", "worker cannot claim", {})
            except ValueError:
                return _error(422, "validation", "invalid claim", {})
        if lease is None:
            return Response(status_code=204)
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

    application.add_api_route("/api/v1/worker/claims", post_claim, methods=["POST"])
    application.add_api_route("/api/v1/worker/heartbeats", post_heartbeat, methods=["POST"])
    application.add_api_route("/api/v1/worker/lease-renewals", post_renewal, methods=["POST"])
    application.add_api_route("/api/v1/worker/attempt-acks", post_ack, methods=["POST"])
    application.add_api_route("/api/v1/worker/events", post_events, methods=["POST"])
    application.state.worker_installed = True


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
