"""Replay dispatch uses the same journal-before-call rule. No device is opened."""

from __future__ import annotations

from aiqa.contracts.actions import DispatchReceipt, PreparedAction
from aiqa.recording.action_executor import ActionExecutor
from aiqa.worker.control import RunControl
from aiqa.worker.dispatch_journal import DispatchJournal


class ReplayActionExecutor:
    """One replay command after a durable dispatch_started record."""

    def __init__(self, journal: DispatchJournal, command: object) -> None:
        self._inner = ActionExecutor(journal=journal, command=command)

    def dispatch_action(self, prepared: PreparedAction, control: RunControl) -> DispatchReceipt:
        return self._inner.dispatch_action(prepared, control)

    @property
    def journal_failure_dispatches(self) -> int:
        return self._inner.journal_failure_dispatches

    @property
    def post_dispatch_retries(self) -> int:
        return self._inner.post_dispatch_retries

    @property
    def timeout_reclassified_lookup(self) -> bool:
        return self._inner.timeout_reclassified_lookup
