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


@dataclass(frozen=True, slots=True)
class SeparateVerifyHealRecord:
    """Original failure stays distinct from any healing proposal or attempt."""

    original_failure: str
    original_check_id: str
    proposal_admitted: bool
    proposal_accepted: bool
    attempt_result: str
    healer_calls: int
    verifier_calls: int
    approved_package_digest: str
    package_digest_after: str


@dataclass(frozen=True, slots=True)
class ReplayVerifyHealResult:
    check_results: tuple[object, ...]
    record: SeparateVerifyHealRecord
    success: bool


def run_replay_verify_and_heal(
    *,
    checks: tuple[object, ...],
    observation: object,
    control: object,
    broker: object,
    transport: object,
    healing_enabled: bool,
    heal_budget_remaining: int,
    approved_failure_reason: str | None,
    healable_check_id: str | None,
    approved_package_digest: str,
    healing_context: object | None = None,
    heal_observation: object | None = None,
    worker_model_call: object | None = None,
) -> ReplayVerifyHealResult:
    """Run deterministic checks first, AI checks only when admitted, heal only when ON.

    Healing proposals never mutate the approved package digest. Model timeout is not success.
    """

    from aiqa.contracts.checks import CheckResult, CheckSpec
    from aiqa.domain.verdicts import FailureLatch
    from aiqa.healing.targets import HealingContext, validate_healing_proposal
    from aiqa.models.broker import ModelBroker, ModelTransport
    from aiqa.validation.visual import evaluate_check_policy

    if not isinstance(broker, ModelBroker) or not isinstance(transport, ModelTransport):
        raise ValueError("broker and transport are required")
    latch = FailureLatch()
    results: list[CheckResult] = []
    before = int(getattr(transport, "calls", 0))
    for raw in checks:
        if not isinstance(raw, CheckSpec):
            raise ValueError("check is invalid")
        results.append(
            evaluate_check_policy(
                raw,
                observation,  # type: ignore[arg-type]
                control,  # type: ignore[arg-type]
                broker=broker,
                transport=transport,
                latch=latch,
            )
        )
    verifier_calls = int(getattr(transport, "calls", 0)) - before

    timed_out = any(item.reason == "timed out" for item in results)
    violated = [item for item in results if item.status == "violated"]
    success = not timed_out and violated == [] and all(item.status == "satisfied" for item in results)

    original_failure = ""
    original_check_id = ""
    if violated:
        first = violated[0]
        original_check_id = first.check_id
        original_failure = approved_failure_reason if approved_failure_reason else first.reason
    elif timed_out:
        timed = next(item for item in results if item.reason == "timed out")
        original_check_id = timed.check_id
        original_failure = "timed out"

    healer_calls = 0
    proposal_admitted = False
    proposal_accepted = False
    attempt_result = "not_run"
    digest_after = approved_package_digest

    needs_heal = violated != [] and original_failure != "timed out"
    if needs_heal:
        attempt_result = "rejected_policy"
        allowed_reason = original_failure in _REASONS
        allowed_check = healable_check_id is None or healable_check_id == original_check_id
        if (
            healing_enabled
            and heal_budget_remaining >= 1
            and allowed_reason
            and allowed_check
            and isinstance(healing_context, HealingContext)
        ):
            try:
                if worker_model_call is not None:
                    complete = getattr(worker_model_call, "complete_role", None)
                    if complete is None:
                        raise TypeError("worker model call is invalid")
                    complete("healing", episode_id=getattr(healing_context.request, "episode_id", None))
                    healer_calls += 1
                proposal = HealingService(broker).propose(healing_context)
                proposal_admitted = bool(proposal.admitted)
                screen = heal_observation if heal_observation is not None else observation
                decision = validate_healing_proposal(proposal, screen)  # type: ignore[arg-type]
                proposal_accepted = bool(decision.accepted)
                attempt_result = "accepted" if proposal_accepted else ("proposed" if proposal_admitted else "rejected_policy")
                if worker_model_call is None and proposal_admitted:
                    healer_calls = 1
            except TimeoutError:
                attempt_result = "timed_out"
                success = False
                if healer_calls == 0:
                    healer_calls = 1
            except Exception as exc:
                from aiqa.models.broker import ModelRequestDenied

                if isinstance(exc, ModelRequestDenied):
                    attempt_result = "rejected_policy"
                else:
                    raise
        # Approved package digest is never rewritten by a healing proposal.
        digest_after = approved_package_digest

    if timed_out:
        success = False

    record = SeparateVerifyHealRecord(
        original_failure,
        original_check_id,
        proposal_admitted,
        proposal_accepted,
        attempt_result,
        healer_calls,
        verifier_calls,
        approved_package_digest,
        digest_after,
    )
    return ReplayVerifyHealResult(tuple(results), record, success)
