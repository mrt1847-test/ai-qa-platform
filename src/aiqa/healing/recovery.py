"""One bounded redispath after a locator failure. This does not change the original QA result."""
from __future__ import annotations

from dataclasses import dataclass

from aiqa.healing.targets import validate_healing_proposal

_LOCATOR = frozenset({"target_not_found", "layout_shift"})


@dataclass(frozen=True, slots=True)
class RecoveryDecision:
    dispatch_once: bool
    healer_calls: int
    reason: str
    changes_original_result: bool = False


def plan_bounded_recovery(*, reason, product_violation, dispatch_sent, proposal, observation, checkpoint, reserved_calls, already_used):
    """Allow one native repeat only for a proven same-target locator or layout failure."""

    if product_violation or reason not in _LOCATOR:
        return RecoveryDecision(False, 0, "not_a_locator_failure")
    if dispatch_sent or already_used:
        return RecoveryDecision(False, 0, "already_sent")
    if type(reserved_calls) is not int or reserved_calls < 1:
        return RecoveryDecision(False, 0, "episode_exhausted")
    try:
        allowed = checkpoint() is True
    except Exception:
        allowed = False
    if not allowed:
        return RecoveryDecision(False, 0, "control_blocked")
    if proposal is None:
        return RecoveryDecision(False, 0, "proposal_missing")
    decision = validate_healing_proposal(proposal, observation)
    if not decision.accepted or not decision.same_target:
        return RecoveryDecision(False, 0, "target_not_proven")
    return RecoveryDecision(True, 1, "same_target")
