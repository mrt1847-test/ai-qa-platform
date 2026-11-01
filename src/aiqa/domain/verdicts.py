"""Separate terminal QA from cleanup. Recording and management jobs have no QA verdict."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from aiqa.contracts.jobs import MANAGEMENT_JOB_PURPOSES

_ITEM_PURPOSES = frozenset({"trial", "regression"})
_UNCERTAIN = frozenset({"lost", "cancelled", "crash"})


@dataclass(frozen=True, slots=True)
class JobFinishInput:
    project_id: UUID
    job_id: UUID
    finish_reason: str
    required_violation: bool
    dispatched: bool
    cleanup_failed: bool


class FailureLatch:
    """A required violation stays a failure after a later satisfied check."""

    def __init__(self) -> None:
        self._held = ""

    def note(self, required: bool, status: str) -> str:
        if self._held != "FAIL" and required and status == "violated":
            self._held = "FAIL"
        return self._held

    @property
    def value(self) -> str:
        return self._held


def item_result(latch: str, satisfied: bool, prior: str | None) -> str:
    """Keep the first terminal result. A required violation stays a failure."""

    if prior in {"PASS", "FAIL", "INCONCLUSIVE"}:
        return prior
    if latch == "FAIL":
        return "FAIL"
    if satisfied:
        return "PASS"
    return "INCONCLUSIVE"


_SATISFIED = frozenset({"PASS"})


def remaining_disposition(policy: str, result: str, cancelled: bool) -> str | None:
    """Choose the code for items that have not started. A user cancel is not a stop."""

    if cancelled:
        return "CANCELLED"
    if policy == "stop_on_non_pass" and result not in _SATISFIED:
        return "NOT_RUN"
    return None


def decide_verdict(purpose: str, finish: JobFinishInput) -> str | None:
    """Return the item verdict. A required violation stays a failure through cancel and loss."""

    if purpose == "recording" or purpose in MANAGEMENT_JOB_PURPOSES or purpose not in _ITEM_PURPOSES:
        return None
    if finish.required_violation:
        return "FAIL"
    if finish.finish_reason in _UNCERTAIN:
        return "INCONCLUSIVE"
    return None
