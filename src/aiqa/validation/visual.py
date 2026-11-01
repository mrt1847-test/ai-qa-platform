"""Apply a declared verifier policy. A violated check is not sent to a model."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from aiqa.contracts.actions import Observation
from aiqa.contracts.checks import CheckResult, CheckSpec
from aiqa.domain.verdicts import FailureLatch
from aiqa.models.broker import ModelBroker, ModelTransport
from aiqa.validation.web import Validator

if TYPE_CHECKING:
    from aiqa.worker.control import RunControl

_METHODS = frozenset({"deterministic", "ai_visual", "deterministic_then_ai_unknown"})
_STATUSES = frozenset({"satisfied", "violated", "unknown"})


def evaluate_check_policy(
    check: CheckSpec,
    observation: Observation | None,
    control: RunControl,
    *,
    broker: ModelBroker,
    transport: ModelTransport,
    latch: FailureLatch | None = None,
) -> CheckResult:
    """Evaluate one declared method. Unknown supplement never runs after a violation."""

    held = FailureLatch() if latch is None else latch
    if check.method not in _METHODS:
        return _finish(check, "unknown", "", "method is not declared", _when(observation), held)
    if _occluded(observation):
        return _finish(check, "unknown", "occluded", "observation is occluded", observation.captured_at, held)
    if check.method == "deterministic":
        base = Validator().evaluate(check, observation)
        return _finish(check, base.status, base.sanitized_observed, base.reason, base.observed_at, held)
    if check.method == "deterministic_then_ai_unknown":
        base = Validator().evaluate(check, observation)
        if base.status != "unknown" or not check.allow_unknown_supplement:
            return _finish(check, base.status, base.sanitized_observed, base.reason, base.observed_at, held)
    if observation is None or not observation.capture_ok:
        return _finish(check, "unknown", "", "evidence is missing", _when(observation), held)
    decision = control.checkpoint()
    if not decision.allowed:
        reason = "budget is missing" if decision.reason == "budget" else decision.reason
        return _finish(check, "unknown", "", reason, observation.captured_at, held)
    admission = broker.admit_verifier(check.id, check.method)
    if not admission.allowed:
        return _finish(check, "unknown", "", admission.reason, observation.captured_at, held)
    try:
        text = transport.complete(check.id)
    except TimeoutError:
        return _finish(check, "unknown", "", "timed out", observation.captured_at, held)
    parsed = _parse(text)
    if parsed is None:
        return _finish(check, "unknown", text[:80], "parse failed", observation.captured_at, held)
    status, reason = parsed
    return _finish(check, status, text[:80], reason, observation.captured_at, held)


def _occluded(observation: Observation | None) -> bool:
    return observation is not None and "occluded" in observation.messages


def _when(observation: Observation | None) -> str:
    return "" if observation is None else observation.captured_at


def _parse(text: str) -> tuple[str, str] | None:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    if type(parsed) is not dict:
        return None
    status = parsed.get("status")
    reason = parsed.get("reason")
    if status not in _STATUSES or type(reason) is not str or reason.strip() == "":
        return None
    return str(status), reason[:80]


def _finish(
    check: CheckSpec,
    status: str,
    observed: str,
    reason: str,
    observed_at: str,
    latch: FailureLatch,
) -> CheckResult:
    return CheckResult(
        check.id,
        status,
        check.method,
        check.expected,
        observed,
        reason,
        observed_at,
        latch.note(check.required, status),
    )
