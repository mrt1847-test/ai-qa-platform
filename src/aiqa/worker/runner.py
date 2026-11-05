"""Attempt budgets. Heartbeats, retries, and real actions stay on separate counters."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from aiqa.contracts.jobs import ControlDecision, LeaseView
from aiqa.worker.isolated_web import close_guest_context
from aiqa.worker.processes import StopReport, stop_owned_tree

WATCHDOG_SECONDS = 30
LEASE_MARGIN_SECONDS = 10
ATTEMPT_LIMIT_SECONDS = 600
ACTION_LIMIT = 50
MODEL_LIMIT = 80


@dataclass(frozen=True, slots=True)
class MonotonicInstant:
    """Seconds on one fake or process clock. This is not a wall-clock timestamp."""

    seconds: float

    def __post_init__(self) -> None:
        if isinstance(self.seconds, bool) or type(self.seconds) not in {int, float}:
            raise ValueError("monotonic time must be a number")
        if self.seconds < 0:
            raise ValueError("monotonic time must be zero or later")


class AttemptRunner:
    """In-memory counters for one attempt. Automatic attempt retry stays at zero."""

    def __init__(self) -> None:
        self.started_at = 0.0
        self.last_progress_at = 0.0
        self.actions = 0
        self.model_calls = 0
        self.transport_retries = 0
        self.model_retries = 0
        self.attempt_retries = 0

    def note_heartbeat(self, now: MonotonicInstant) -> None:
        """Move the watchdog baseline. This does not count an action or an attempt."""

        self.last_progress_at = now.seconds

    def record_transport_retry(self) -> None:
        """Count a send retry without dispatching another action or attempt."""

        self.transport_retries += 1

    def record_model_retry(self) -> None:
        """Count a model retry without dispatching another action or attempt."""

        self.model_retries += 1

    def authorize(self, now: MonotonicInstant, lease: LeaseView, phase: str) -> ControlDecision:
        """Apply watchdog, lease margin, and the action or model ceiling."""

        if now.seconds < self.last_progress_at or now.seconds < self.started_at:
            raise ValueError("monotonic clock moved backwards")
        if now.seconds - self.last_progress_at >= WATCHDOG_SECONDS:
            return ControlDecision(allowed=False, reason="watchdog")
        if _remaining_seconds(now, lease) < LEASE_MARGIN_SECONDS:
            return ControlDecision(allowed=False, reason="lease_margin")
        if now.seconds - self.started_at >= ATTEMPT_LIMIT_SECONDS:
            return ControlDecision(allowed=False, reason="attempt_limit")
        if phase == "before_dispatch":
            if self.actions >= ACTION_LIMIT:
                return ControlDecision(allowed=False, reason="action_limit")
            self.actions += 1
            return ControlDecision(allowed=True, reason="action")
        if phase == "before_model":
            if self.model_calls >= MODEL_LIMIT:
                return ControlDecision(allowed=False, reason="model_limit")
            self.model_calls += 1
            return ControlDecision(allowed=True, reason="model")
        if phase in {"before_lookup", "after_model"}:
            return ControlDecision(allowed=True, reason=phase)
        raise ValueError("checkpoint phase is invalid")


def _remaining_seconds(now: MonotonicInstant, lease: LeaseView) -> float:
    """Lease deadline and `now` share the monotonic clock. The value is seconds."""

    return float(lease.expires_at) - now.seconds


@dataclass(frozen=True, slots=True)
class CleanupReport:
    released: bool
    quarantined: bool
    reasons: tuple[str, ...]
    proof_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SnapshotCheck:
    supported: bool
    reason: str
    purpose: str


def verify_job_snapshot(snapshot: object, prepared_adapters: frozenset[str]) -> SnapshotCheck:
    """Accept only purposes with a prepared adapter. Unsupported targets dispatch zero actions."""

    if type(snapshot) is not dict:
        return SnapshotCheck(False, "snapshot_invalid", "")
    purpose = snapshot.get("purpose")
    if type(purpose) is not str or purpose.strip() == "":
        return SnapshotCheck(False, "purpose_missing", "")
    digest = snapshot.get("digest")
    if type(digest) is not str or not digest.startswith("sha256:"):
        return SnapshotCheck(False, "digest_invalid", purpose)
    if purpose not in prepared_adapters:
        return SnapshotCheck(False, "unsupported_target", purpose)
    return SnapshotCheck(True, "ok", purpose)


def control_finish(purpose: str, finish: object) -> tuple[str | None, str]:
    """Keep the QA verdict independent of a cleanup failure."""

    from aiqa.domain.verdicts import JobFinishInput, decide_verdict

    if not isinstance(finish, JobFinishInput):
        raise ValueError("finish input is invalid")
    verdict = decide_verdict(purpose, finish)
    return verdict, "quarantine" if finish.cleanup_failed else "unchanged"


def stop_runner(attempt_id: UUID, grace_seconds: int = 5) -> StopReport:
    """Wait the cancel grace, then stop the process tree recorded for this attempt."""

    return stop_owned_tree(attempt_id, grace_seconds)


_CLEANUP: dict[UUID, str] = {}


def verify_and_heal_after_replay(**kwargs: object) -> object:
    """Connect replay check evaluation and healing to the worker model-request path.

    Shared by Android and Web trial/regression handlers after a sealed plan dispatch.
    Deterministic Check runs first; healing stays OFF unless explicitly enabled with budget.
    """

    from aiqa.healing.service import run_replay_verify_and_heal

    return run_replay_verify_and_heal(**kwargs)  # type: ignore[arg-type]


def cleanup_attempt(
    attempt_id: UUID, deadline_seconds: int = 30, provider: object | None = None
) -> CleanupReport:
    """Quarantine the attempt when context cleanup has no proof. The record survives an engine error."""

    if isinstance(deadline_seconds, bool) or type(deadline_seconds) is not int or deadline_seconds < 0:
        raise ValueError("cleanup deadline is invalid")
    proofs: list[str] = []
    reasons: list[str] = []
    try:
        proofs.extend(close_guest_context(provider))
    except Exception:
        reasons.append("engine_exception")
    finally:
        if not proofs:
            reasons.append("proof_missing")
        _CLEANUP[attempt_id] = "quarantined" if not proofs else "released"
    return CleanupReport(
        released=bool(proofs),
        quarantined=not proofs,
        reasons=tuple(reasons),
        proof_refs=tuple(proofs),
    )
