"""Worker claim service. One transaction decides the slot, device, and previous item."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from uuid import UUID

from aiqa.contracts.evidence import AckState, EvidenceEnvelope, IngestReceipt, LocalReceipt
from aiqa.contracts.jobs import AttemptReceipt, JobLease, LeaseToken, LeaseView, ReconciliationReport
from aiqa.contracts.worker_attempt import ClaimReceipt, WorkerAttemptFinishInput, WorkerAttemptFinishReceipt
from aiqa.store.database import Store
from aiqa.store.evidence import ingest_stored
from aiqa.store.models import EventEnvelope, WorkerScope
from aiqa.store.queue import (
    CleanupConfirmationInput,
    CleanupConfirmationReceipt,
    acknowledge_runner,
    claim_queued_job,
    claim_with_receipt,
    confirm_cleanup,
    finish_worker_attempt,
    reconcile_stored,
    renew_lease_row,
)
from aiqa.worker.spool import EvidenceSpool

_store: ContextVar[Store] = ContextVar("aiqa_claim_store")
_spool: ContextVar[EvidenceSpool] = ContextVar("aiqa_evidence_spool")


class ClaimUnavailable(Exception):
    """The claim store is not bound."""


@contextmanager
def bind_claim_store(store: Store) -> Iterator[None]:
    token = _store.set(store)
    try:
        yield
    finally:
        _store.reset(token)


def claim_job(
    worker: WorkerScope,
    now: datetime,
    *,
    boot_id: object = None,
    request_key: str | None = None,
    project_id: object = None,
) -> ClaimReceipt | JobLease | None:
    """Take one queued job for this worker, or nothing when the slot or device is busy."""

    _require_now(now)
    store = _bound_store()
    with store.transaction() as connection:
        if request_key is None:
            return claim_queued_job(connection, worker, now, boot_id=boot_id)
        return claim_with_receipt(
            connection,
            worker,
            now,
            request_key=request_key,
            boot_id=boot_id,
            project_id=project_id,
        )


def renew_lease(
    worker: WorkerScope, lease: LeaseToken, now: datetime, model_wait: bool = False,
    *, server_now: datetime | None = None,
) -> LeaseView:
    """Heartbeat the same generation for 45 seconds. Model wait does not stop it."""

    _require_now(now)
    store = _bound_store()
    with store.transaction() as connection:
        return renew_lease_row(connection, worker, lease, now, model_wait, server_now=server_now)


def confirm_attempt_cleanup(
    worker: WorkerScope,
    confirmation: CleanupConfirmationInput,
    now: datetime,
) -> CleanupConfirmationReceipt:
    """Accept cleanup proof and release the matching lease fence."""

    _require_now(now)
    store = _bound_store()
    with store.transaction() as connection:
        return confirm_cleanup(connection, worker, confirmation, now)


def finish_attempt(
    worker: WorkerScope,
    finish: WorkerAttemptFinishInput,
    *,
    request_key: str,
    body_hash: str,
    now: datetime,
) -> WorkerAttemptFinishReceipt:
    """Submit a terminal worker result. This path never approves."""

    _require_now(now)
    store = _bound_store()
    with store.transaction() as connection:
        return finish_worker_attempt(
            connection,
            worker,
            finish,
            request_key=request_key,
            body_hash=body_hash,
            now=now,
        )


def acknowledge_attempt(
    lease: LeaseToken, runner_nonce: UUID, worker: WorkerScope, now: datetime,
    *, server_now: datetime | None = None,
) -> AttemptReceipt:
    """Confirm the claimed attempt. The same nonce returns that attempt."""

    _require_now(now)
    store = _bound_store()
    with store.transaction() as connection:
        from aiqa.store.queue import load_attempt_incarnation

        receipt = acknowledge_runner(connection, worker, lease, runner_nonce, now, server_now=server_now)
        if load_attempt_incarnation(connection, lease.project_id, receipt.attempt_id) is None:
            connection.execute(
                """
                INSERT OR IGNORE INTO runner_hosts (project_id, attempt_id, boot_id)
                VALUES (?, ?, ?)
                """,
                (str(lease.project_id), str(receipt.attempt_id), _boot_id()),
            )
        return receipt


def reconcile_after_resume() -> ReconciliationReport:
    """Mark interrupted work lost. A checkpoint is not resumed."""

    return reconcile_jobs(datetime.now(timezone.utc))


def reconcile_jobs(now: datetime) -> ReconciliationReport:
    """Keep queued work. Continue only a runner that is still on this PC boot."""

    _require_now(now)
    store = _bound_store()
    with store.transaction() as connection:
        return reconcile_stored(connection, now, _boot_id())


def ingest_events(
    lease: LeaseToken, events: list[EventEnvelope], worker: WorkerScope, now: datetime
) -> IngestReceipt:
    """Append attempt events and return the contiguous local-seq ack."""

    _require_now(now)
    store = _bound_store()
    with store.transaction() as connection:
        return ingest_stored(connection, worker, lease, events, now)


@contextmanager
def bind_evidence_spool(spool: EvidenceSpool) -> Iterator[None]:
    token = _spool.set(spool)
    try:
        yield
    finally:
        _spool.reset(token)


def append_evidence(envelope: EvidenceEnvelope) -> LocalReceipt:
    """Flush one sanitized PNG and log. A repeat of the same seq does not add an action."""

    return _bound_spool().append(envelope)


def mark_evidence_sent(attempt_id: UUID, local_seq: int) -> None:
    """Record that the local file was handed to the upload. This is not an ACK."""

    _bound_spool().mark_sent(attempt_id, local_seq)


def acknowledge_spool(receipt: IngestReceipt) -> AckState:
    """Ack only a contiguous prefix whose hash matches the server receipt."""

    return _bound_spool().acknowledge(receipt)


def purge_evidence(now: datetime) -> int:
    """Delete aged files only after ACK. The return is the unacked delete count."""

    _require_now(now)
    return _bound_spool().purge(now)


def note_evidence_pressure() -> None:
    """Stop new spool actions while keeping every unacked file."""

    _bound_spool().note_pressure()


def recover_evidence(spec: object) -> object:
    """Preserve unsent captures. This does not dispatch a device command."""

    from aiqa.recording.recovery import EvidenceRecoverySpec, recover_evidence as recover_stored

    if not isinstance(spec, EvidenceRecoverySpec):
        raise TypeError("recovery spec is required")
    return recover_stored(spec)


def _boot_id() -> str:
    from aiqa.api.lifecycle import host_boot_id

    return host_boot_id()


def _require_now(now: datetime) -> None:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("clock time must include a timezone")


def _bound_spool() -> EvidenceSpool:
    try:
        return _spool.get()
    except LookupError as exc:
        raise ClaimUnavailable("evidence spool is not bound") from exc


def _bound_store() -> Store:
    try:
        return _store.get()
    except LookupError as exc:
        raise ClaimUnavailable("claim store is not bound") from exc
