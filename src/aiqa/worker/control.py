"""Cancel checkpoints. A stored flag blocks the next model, lookup, and dispatch."""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone
from collections.abc import Callable
from collections import OrderedDict
from threading import Lock
from uuid import UUID

from aiqa.contracts.jobs import ControlDecision, LeaseView
from aiqa.worker.presence import HEARTBEAT_SECONDS, get_presence
from aiqa.worker.runner import (
    LEASE_MARGIN_SECONDS,
    WATCHDOG_SECONDS,
    AttemptRunner,
    MonotonicInstant,
)

_PHASES = ("before_model", "after_model", "before_lookup", "before_dispatch")
_BLOCKED = frozenset({"cancel_requested", "finalizing", "completed", "error", "cancelled", "lost"})
_ATTEMPT_CONTROLS: OrderedDict[str, tuple[AttemptRunner, float]] = OrderedDict()
_CONTROLS_LOCK = Lock()
LEASE_SECONDS = 45
POLL_SECONDS = 2


class RemoteLeaseGuard:
    """Gate one action with the local monotonic clock and the server's remaining lease."""

    heartbeat_seconds = HEARTBEAT_SECONDS
    lease_seconds = LEASE_SECONDS
    watchdog_seconds = WATCHDOG_SECONDS
    action_margin_seconds = LEASE_MARGIN_SECONDS
    poll_seconds = POLL_SECONDS

    def __init__(self, runner: AttemptRunner | None = None) -> None:
        self._runner = AttemptRunner() if runner is None else runner

    def note_heartbeat(self, now: MonotonicInstant) -> None:
        self._runner.note_heartbeat(now)

    def authorize(
        self,
        now: MonotonicInstant,
        server_remaining_seconds: float,
        *,
        phase: str = "before_dispatch",
    ) -> ControlDecision:
        if type(server_remaining_seconds) is not float and type(server_remaining_seconds) is not int:
            raise ValueError("server remaining seconds are invalid")
        remaining = float(server_remaining_seconds)
        if remaining < self.action_margin_seconds:
            return ControlDecision(False, "lease_margin")
        lease = LeaseView(
            UUID(int=0),
            UUID(int=1),
            1,
            str(now.seconds + remaining),
            self.lease_seconds,
            self.heartbeat_seconds,
            self.poll_seconds,
        )
        return self._runner.authorize(now, lease, phase)


class RunControl:
    """One attempt phase. checkpoint reads the cancel flag and does not dispatch."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        project_id: UUID,
        job_id: UUID,
        phase: str,
        runner: AttemptRunner | None = None,
        *,
        generation: int | None = None,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        if phase not in _PHASES:
            raise ValueError("checkpoint phase is invalid")
        self._connection = connection
        self._project_id = project_id
        self._job_id = job_id
        self._phase = phase
        self._runner = AttemptRunner() if runner is None else runner
        self._clock = clock
        self._wall_clock = wall_clock
        self._clock_start = clock()
        binding = connection.execute(
            """SELECT attempts.attempt_id, leases.generation, leases.worker_id
               FROM leases JOIN attempts USING (project_id, job_id, generation)
               WHERE leases.project_id=? AND leases.job_id=? ORDER BY leases.generation DESC LIMIT 1""",
            (str(project_id), str(job_id)),
        ).fetchone()
        self.attempt_id = None if binding is None else str(binding[0])
        self._generation = generation if generation is not None else (None if binding is None else int(binding[1]))
        self._worker_id = None if binding is None else str(binding[2])
        if self.attempt_id is not None:
            # One runner owns counters/time across phase objects and API
            # connections. Active concurrency is one; bound retained history.
            with _CONTROLS_LOCK:
                state = _ATTEMPT_CONTROLS.get(self.attempt_id)
                if state is None:
                    state = (self._runner, self._clock_start)
                    _ATTEMPT_CONTROLS[self.attempt_id] = state
                _ATTEMPT_CONTROLS.move_to_end(self.attempt_id)
                while len(_ATTEMPT_CONTROLS) > 1024:
                    _ATTEMPT_CONTROLS.popitem(last=False)
                self._runner, self._clock_start = state

    def checkpoint(self) -> ControlDecision:
        """Allow the phase only while this job is still preparing or running."""

        project_id = str(self._project_id)
        job_id = str(self._job_id)
        cancel = self._connection.execute(
            "SELECT 1 FROM job_cancellations WHERE project_id = ? AND job_id = ?",
            (project_id, job_id),
        ).fetchone()
        row = self._connection.execute(
            "SELECT status FROM jobs WHERE project_id = ? AND job_id = ?",
            (project_id, job_id),
        ).fetchone()
        if row is None:
            return ControlDecision(allowed=False, reason="missing")
        status = str(row[0])
        if cancel is not None or status in _BLOCKED:
            reason = "cancel_requested" if cancel is not None or status == "cancel_requested" else "terminal"
            return ControlDecision(allowed=False, reason=reason)
        if status not in {"preparing", "running"}:
            return ControlDecision(allowed=False, reason="inactive")
        return ControlDecision(allowed=True, reason=self._phase)

    def authorize_next_action(self, now: MonotonicInstant, lease: LeaseView) -> ControlDecision:
        """Allow one real action or model call only inside the attempt budget."""

        blocked = self.checkpoint()
        if not blocked.allowed:
            return blocked
        return self._runner.authorize(now, lease, self._phase)

    def authorize_dispatch(self) -> ControlDecision:
        """Validate the bound live lease and charge the actual dispatch boundary."""
        return self._dispatch_decision(charge=True)

    def dispatch_checkpoint(self) -> ControlDecision:
        """Recheck after journal I/O without charging the same action twice."""
        return self._dispatch_decision(charge=False)

    def _dispatch_decision(self, *, charge: bool) -> ControlDecision:
        decision = self.checkpoint()
        if not decision.allowed:
            return decision
        row = self._connection.execute(
            """SELECT leases.expires_at, leases.worker_id, attempts.attempt_id, session.session_id
               FROM leases JOIN attempts USING (project_id, job_id, generation)
               LEFT JOIN job_worker_sessions AS session
                 ON session.project_id = leases.project_id AND session.job_id = leases.job_id
                AND session.worker_id = leases.worker_id
               WHERE leases.project_id=? AND leases.job_id=? AND leases.generation=?
                 AND leases.generation=(SELECT MAX(generation) FROM attempts WHERE project_id=leases.project_id AND job_id=leases.job_id)""",
            (str(self._project_id), str(self._job_id), self._generation),
        ).fetchone()
        if row is None or str(row[1]) != self._worker_id or str(row[2]) != self.attempt_id:
            return ControlDecision(False, 'stale_generation')
        now = self._wall_clock()
        if row[3] is not None:
            presence = get_presence(self._connection, row[1], now, project_id=self._project_id)
            if presence.state != "online" or presence.session_id != row[3]:
                return ControlDecision(False, "stale_worker_session")
        expires = datetime.fromisoformat(str(row[0]))
        if expires.tzinfo is None:
            return ControlDecision(False, 'lease_margin')
        receipt = self._connection.execute(
            """
            SELECT expires_at FROM claim_receipts
            WHERE project_id = ? AND attempt_id = ?
            """,
            (str(self._project_id), self.attempt_id),
        ).fetchone()
        if receipt is not None:
            receipt_expires = datetime.fromisoformat(str(receipt[0]))
            if receipt_expires.tzinfo is None or now >= receipt_expires.astimezone(timezone.utc):
                return ControlDecision(False, "expired_claim_receipt")
        age = self._clock() - self._clock_start
        instant = MonotonicInstant(self._runner.started_at + age)
        remaining = (expires - now).total_seconds()
        lease = LeaseView(self._project_id, self._job_id, int(self._generation), str(instant.seconds + remaining), 45, 10, 2)
        return self._runner.authorize(instant, lease, 'before_dispatch' if charge else 'before_lookup')

    def note_heartbeat(self, now: MonotonicInstant) -> None:
        """Refresh the watchdog without counting an action."""

        self._runner.note_heartbeat(now)

    def record_transport_retry(self) -> None:
        """Record a transport retry. The attempt counter stays unchanged."""

        self._runner.record_transport_retry()

    def allow_model_action(self, *, late: bool) -> ControlDecision:
        """A late or cancelled model response cannot start the next action."""

        if late:
            return ControlDecision(False, "late")
        return self.checkpoint()

    def record_model_retry(self) -> None:
        """Record a model retry. The attempt counter stays unchanged."""

        self._runner.record_model_retry()

    @property
    def attempt_retries(self) -> int:
        return self._runner.attempt_retries
