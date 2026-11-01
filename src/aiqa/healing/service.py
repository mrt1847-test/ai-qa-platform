"""Reserve one read-only healing lookup. This module does not call a model."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from aiqa.contracts.healing import HealingEpisodeReceipt, HealingTrigger
from aiqa.healing.policy import reserve_window
from aiqa.store.healing import (
    HealingRejected,
    dispatch_started,
    insert_reservation,
    lease_remaining_seconds,
    read_reservation,
)
from aiqa.worker.control import RunControl

_REASONS = frozenset({"target_not_found", "ambiguous", "layout_shift"})


def reserve_healing_episode(trigger: HealingTrigger, control: RunControl) -> HealingEpisodeReceipt:
    """Reserve one episode, or return the episode this item already holds."""

    decision = control.checkpoint()
    if not decision.allowed:
        raise HealingRejected("run control refused the lookup")
    if trigger.reason not in _REASONS:
        raise HealingRejected("lookup reason is invalid")
    if trigger.product_violation:
        raise HealingRejected("product violation blocks healing")
    connection = control._connection
    project_id = control._project_id
    if dispatch_started(connection, project_id, trigger.attempt_id):
        return HealingEpisodeReceipt(None, trigger.case_run_id, 0, 0, False, False)
    if trigger.policy.effective_enabled is not True:
        return HealingEpisodeReceipt(None, trigger.case_run_id, 0, 0, False, False)
    if trigger.binding_revision != trigger.policy.binding_revision:
        raise HealingRejected("binding revision changed")
    now = datetime.now(timezone.utc)
    remaining = min(trigger.lease_seconds, lease_remaining_seconds(connection, project_id, control._job_id, now))
    window = reserve_window(trigger.policy, trigger.job_seconds, remaining)
    if window is None:
        return HealingEpisodeReceipt(None, trigger.case_run_id, 0, 0, False, False)
    calls, seconds = window
    owns_transaction = not connection.in_transaction
    if owns_transaction:
        connection.execute("BEGIN IMMEDIATE")
    try:
        existing = read_reservation(connection, project_id, trigger.case_run_id)
        if existing is not None:
            if owns_transaction:
                connection.execute("COMMIT")
            return HealingEpisodeReceipt(existing[0], trigger.case_run_id, existing[1], existing[2], True, True)
        episode_id = insert_reservation(
            connection,
            project_id,
            trigger.case_run_id,
            trigger.attempt_id,
            trigger.package_id,
            trigger.request_key,
            trigger.reason,
            calls,
            seconds,
            now,
        )
    except sqlite3.IntegrityError:
        if owns_transaction:
            connection.execute("ROLLBACK")
        existing = read_reservation(connection, project_id, trigger.case_run_id)
        if existing is None:
            raise HealingRejected("episode is already reserved") from None
        return HealingEpisodeReceipt(existing[0], trigger.case_run_id, existing[1], existing[2], True, True)
    except Exception:
        if owns_transaction and connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
    if owns_transaction:
        connection.execute("COMMIT")
    return HealingEpisodeReceipt(episode_id, trigger.case_run_id, calls, seconds, True, False)


class HealingService:
    """Ask for one typed target. Acceptance stays in the trusted proof."""

    def __init__(self, broker: object) -> None:
        self._broker = broker

    def propose(self, context: object) -> object:
        from aiqa.contracts.models import ModelRequest
        from aiqa.healing.targets import HealingContext, HealingProposal, TargetCandidate

        if not isinstance(context, HealingContext) or not isinstance(context.request, ModelRequest):
            raise ValueError("healing context is invalid")
        admit = getattr(self._broker, "admit")
        parse = getattr(self._broker, "parse_healer_target")
        admission = admit(context.request)
        payload = parse(context.payload) if admission.allowed else None
        candidate = None if payload is None else _candidate(payload)
        return HealingProposal(
            context.approved_role,
            context.approved_name,
            context.approved_container,
            context.approved_resource_id,
            context.approved_text,
            context.approved_context,
            context.approved_locator,
            context.approved_action,
            context.approved_input,
            context.approved_path,
            candidate,
            candidate is not None,
        )


@dataclass(frozen=True, slots=True)
class AcceptedHealingProposal:
    item_id: str
    accepted: bool
    prepared: object
    journal: object
    command: object
    checks: tuple[object, ...]
    observation: object
    lookup_error: str
    prior_decision: str
    rejection: str
    usage: int
    required_violation: bool = False


@dataclass(frozen=True, slots=True)
class ItemOverride:
    item_id: str
    result: str
    dispatches: int
    healing_used: bool
    lookup_error: str
    prior_decision: str
    rejection: str
    usage: int


_OVERRIDES: list[ItemOverride] = []


def item_overrides(item_id: str) -> tuple[ItemOverride, ...]:
    return tuple(item for item in _OVERRIDES if item.item_id == item_id)


def apply_runtime_override(proposal: AcceptedHealingProposal, control: object) -> object:
    """Append one accepted override and dispatch the original action once."""

    from aiqa.contracts.evidence import ActionObservation
    from aiqa.domain.verdicts import FailureLatch, item_result
    from aiqa.replay.action_executor import ReplayActionExecutor
    from aiqa.validation.web import Validator

    stored = item_overrides(proposal.item_id)
    if stored:
        return _observation(proposal, stored[0].result)
    if not proposal.accepted:
        return _observation(proposal, "")
    executor = ReplayActionExecutor(proposal.journal, proposal.command)
    allowed = getattr(control, "authorize_dispatch", control.checkpoint)().allowed
    receipt = None
    dispatches = 0
    if proposal.prepared.command_allowed and allowed:
        receipt = executor.dispatch_action(proposal.prepared, control)
        dispatches = int(receipt.native_calls)
    observed = executor.observe_action(receipt, control) if receipt is not None else _observation(proposal, "")
    validator = Validator()
    results = tuple(validator.evaluate(check, proposal.observation) for check in proposal.checks)
    latch = FailureLatch()
    for check, result in zip(proposal.checks, results, strict=True):
        latch.note(bool(getattr(check, "required", False)), result.status)
    if proposal.required_violation:
        latch.note(True, "violated")
    satisfied = results != () and all(result.status == "satisfied" for result in results)
    code = item_result(latch.value, satisfied, None)
    _OVERRIDES.append(
        ItemOverride(
            proposal.item_id,
            code,
            dispatches,
            True,
            proposal.lookup_error,
            proposal.prior_decision,
            proposal.rejection,
            proposal.usage,
        )
    )
    if isinstance(observed, ActionObservation):
        return observed
    return _observation(proposal, code)


def _observation(proposal: AcceptedHealingProposal, result: str) -> object:
    from aiqa.contracts.evidence import ActionObservation

    action_id = str(getattr(proposal.prepared, "observation_id", proposal.item_id))
    return ActionObservation(action_id, None, None, None, None, result, None, (), "immediate", "unknown", False)


def _candidate(payload: dict[str, object]) -> object:
    from aiqa.healing.targets import TargetCandidate

    point = payload.get("coordinates")
    coordinates = None if type(point) is not list else (int(point[0]), int(point[1]))
    return TargetCandidate(
        str(payload.get("role", "")),
        str(payload.get("name", "")),
        str(payload.get("container", "")),
        str(payload.get("resource_id", "")),
        str(payload.get("text", "")),
        str(payload.get("context", "")),
        str(payload["locator"]),
        str(payload["action"]),
        str(payload["input"]),
        str(payload["path"]),
        coordinates,
        "typed",
    )
