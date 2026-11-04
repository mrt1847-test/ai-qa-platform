"""Apply the action policy and prepare sanitized before-captures. No shell is started."""

from __future__ import annotations

from pathlib import Path

from aiqa.adapters.cuawright_web import CuawrightWebAdapter
from aiqa.adapters.mobile_agent_android import MobileAgentAndroidAdapter
from aiqa.contracts.actions import (
    ActionDecision,
    ActionProposal,
    DispatchReceipt,
    Observation,
    PreparedAction,
    StepContext,
)
from aiqa.contracts.evidence import ActionObservation
from aiqa.security.action_policy import PolicyGate
from aiqa.security.redaction import RedactionError, SanitizedCapture, filter_capture
from aiqa.validation.observations import store_action_observation
from aiqa.worker.control import RunControl
from aiqa.worker.dispatch_journal import DispatchJournal, JournalWriteError


class ActionExecutor:
    """Count decisions and store only sanitized before-captures. Native dispatch is later."""

    def __init__(
        self,
        spool: Path | None = None,
        secrets: tuple[str, ...] = (),
        context: StepContext | None = None,
        journal: DispatchJournal | None = None,
        command: object | None = None,
        observer: object | None = None,
        attempt_id: str | None = None,
    ) -> None:
        self.out_of_scope_dispatches = 0
        self.raw_shell_allowed = False
        self.screen_instruction_authoritative = False
        self.pre_capture_failure_dispatches = 0
        self.journal_failure_dispatches = 0
        self.post_dispatch_retries = 0
        self.timeout_reclassified_lookup = False
        self.missing_after_redispatches = 0
        self.delayed_as_immediate = False
        self._immediate_after = 0
        self._spool = spool
        self._secrets = secrets
        self._context = context
        self._journal = journal
        self._command = command
        self._observer = observer
        self._attempt_id = attempt_id
        self._by_observation: dict[str, PreparedAction] = {}
        self._gate = PolicyGate()
        self._web = CuawrightWebAdapter()
        self._android = MobileAgentAndroidAdapter()
        self._prepared: list[PreparedAction] = []

    def submit(self, proposal: ActionProposal, context: StepContext) -> ActionDecision:
        decision = self._gate.authorize(proposal, context)
        if decision.allowed and proposal.helper_command is not None:
            self.raw_shell_allowed = True
        if decision.allowed and proposal.source != "typed":
            self.screen_instruction_authoritative = True
        if decision.allowed and not decision.in_scope:
            self.out_of_scope_dispatches += 1
        return decision

    def prepare_action(self, proposal: ActionProposal, observation: Observation) -> PreparedAction:
        """Filter one actual action and keep the command when the before-capture is stored."""

        adapter = self._web if observation.platform == "web" else self._android
        captured = adapter.before_capture(proposal, observation)
        decision = self._authorize(proposal)
        try:
            cleaned = filter_capture(captured, self._secrets)
        except RedactionError:
            return self._blocked(proposal, observation.observation_id)
        if not decision.allowed or self._spool is None:
            return self._blocked(proposal, observation.observation_id)
        ref = _write_sanitized(self._spool, observation.observation_id, cleaned)
        prepared = PreparedAction(proposal, observation.observation_id, ref, True, self._attempt_id)
        self._prepared.append(prepared)
        self._by_observation[observation.observation_id] = prepared
        return prepared

    def prepare_actions(
        self, proposals: tuple[ActionProposal, ...], observations: tuple[Observation, ...]
    ) -> tuple[PreparedAction, ...]:
        """Split a compound step into one prepared action per proposal."""

        pairs = zip(proposals, observations, strict=True)
        return tuple(self.prepare_action(proposal, observation) for proposal, observation in pairs)

    @property
    def actions(self) -> int:
        return len(self._prepared)

    @property
    def before_artifacts(self) -> int:
        return sum(1 for item in self._prepared if item.before_ref is not None)

    @property
    def normal_before_after_png(self) -> int:
        return self.before_artifacts + self._immediate_after

    def _authorize(self, proposal: ActionProposal) -> ActionDecision:
        if self._context is None:
            return ActionDecision(False, False, ("context_missing",))
        return self._gate.authorize(proposal, self._context)

    def _blocked(self, proposal: ActionProposal, observation_id: str) -> PreparedAction:
        return PreparedAction(proposal, observation_id, None, False)

    def dispatch_action(self, prepared: PreparedAction, control: RunControl) -> DispatchReceipt:
        """Flush dispatch_started before one command. A missing ACK stays unknown."""

        if not prepared.command_allowed or self._journal is None or self._command is None:
            return DispatchReceipt(prepared.observation_id, (), 0)
        if not control.checkpoint().allowed:
            return DispatchReceipt(prepared.observation_id, (), 0)
        action_id = prepared.proposal.action_id
        attempt_id = prepared.attempt_id or getattr(control, 'attempt_id', None)
        if attempt_id is None or (prepared.attempt_id is not None and prepared.attempt_id != getattr(control, 'attempt_id', None)):
            return DispatchReceipt(prepared.observation_id, (), 0)
        def states():
            return self._journal.states(action_id, str(attempt_id))
        try:
            if 'dispatch_started' in states():
                return DispatchReceipt(prepared.observation_id, states(), 0)
            self._journal.append(attempt_id, action_id, "planned")
        except JournalWriteError:
            return DispatchReceipt(prepared.observation_id, (), 0)
        try:
            located = bool(self._command.lookup(prepared))
        except Exception:
            located = False
        if not located:
            try:
                self._journal.append(attempt_id, action_id, "lookup_failed")
            except JournalWriteError:
                pass
            return DispatchReceipt(prepared.observation_id, states(), 0)
        authorize = getattr(control, 'authorize_dispatch', None)
        if authorize is None or not authorize().allowed:
            return DispatchReceipt(prepared.observation_id, states(), 0)
        try:
            self._journal.append(attempt_id, action_id, "dispatch_started")
        except JournalWriteError:
            return DispatchReceipt(prepared.observation_id, states(), 0)
        final_guard = getattr(control, 'dispatch_checkpoint', control.checkpoint)
        if not final_guard().allowed:
            try:
                self._journal.append(attempt_id, action_id, 'unknown')
            except JournalWriteError:
                pass
            return DispatchReceipt(prepared.observation_id, states(), 0)
        try:
            result = str(self._command.execute(prepared))
            calls = 1
            outcome = "acknowledged" if result == "acknowledged" else "unknown"
        except Exception:
            calls = 1
            outcome = "unknown"
        if calls > 1:
            self.post_dispatch_retries += calls - 1
        try:
            self._journal.append(attempt_id, action_id, outcome)
        except JournalWriteError:
            return DispatchReceipt(prepared.observation_id, states(), calls)
        return DispatchReceipt(prepared.observation_id, states(), calls)

    def observe_action(self, receipt: DispatchReceipt, control: RunControl) -> ActionObservation:
        """Link one sanitized after-capture. A missing after does not dispatch again."""

        prepared = self._by_observation.get(receipt.observation_id)
        before_ref = None if prepared is None else prepared.before_ref
        action_id = receipt.observation_id if prepared is None else prepared.proposal.action_id
        if self._spool is None or self._observer is None or not control.checkpoint().allowed:
            return self._unknown_after(action_id, before_ref, "control")
        view = self._observer.after_capture(receipt)
        captured = None if view is None else view.captured
        timing = "immediate" if view is None else str(view.timing)
        record = store_action_observation(
            self._spool,
            action_id,
            before_ref,
            captured,
            timing=timing,
            command_result="" if view is None else str(view.command_result),
            error_ref=None if view is None else view.error_ref,
            check_refs=() if view is None else tuple(view.check_refs),
            secrets=self._secrets,
            before_rotation=None if view is None else view.before_rotation,
        )
        if timing == "delayed" and record.timing == "immediate":
            self.delayed_as_immediate = True
        if record.timing == "immediate" and record.outcome == "complete" and record.after_ref is not None:
            self._immediate_after += 1
        return record

    def _unknown_after(self, action_id: str, before_ref: str | None, command_result: str) -> ActionObservation:
        if self._spool is None:
            return ActionObservation(
                action_id, before_ref, None, None, None, command_result, None, (), "immediate", "unknown", False
            )
        return store_action_observation(
            self._spool,
            action_id,
            before_ref,
            None,
            timing="immediate",
            command_result=command_result,
            error_ref=None,
            check_refs=(),
            secrets=self._secrets,
            before_rotation=None,
        )


def run_android_deterministic(
    executor: ActionExecutor,
    *,
    driver,
    preflight,
    binding,
    before,
    action,
    after=None,
) -> object:
    """Bridge recording executor evidence to the Android fixed-argv driver. No AI."""

    if getattr(driver, "ai_calls", 0) != 0:
        raise ValueError("replay actor AI is forbidden")
    result = driver.run(
        preflight=preflight,
        binding=binding,
        before=before,
        action=action,
        after=after,
    )
    if result.retries or result.native_calls > 1:
        executor.post_dispatch_retries += max(0, result.native_calls - 1)
    if result.after_ref is not None:
        executor._immediate_after += 1
    return result


def run_web_deterministic(
    executor: ActionExecutor,
    *,
    driver,
    before,
    action,
    presented_digest: str,
    presented_revision: str,
    page_origin: str,
    after=None,
) -> object:
    """Bridge recording executor evidence to TrustedWebDriver. Replay actor AI stays 0."""

    if getattr(driver, "ai_calls", 0) != 0:
        raise ValueError("replay actor AI is forbidden")
    result = driver.run(
        before=before,
        action=action,
        presented_digest=presented_digest,
        presented_revision=presented_revision,
        page_origin=page_origin,
        after=after,
    )
    if result.retries or result.native_calls > 1:
        executor.post_dispatch_retries += max(0, result.native_calls - 1)
    if result.after_ref is not None:
        executor._immediate_after += 1
    return result


def _write_sanitized(spool: Path, observation_id: str, cleaned: SanitizedCapture) -> str:
    folder = spool / "before"
    folder.mkdir(parents=True, exist_ok=True)
    png = cleaned.png
    text = "\n".join((cleaned.dom, cleaned.stdout, *cleaned.messages))
    (folder / f"{observation_id}.png").write_bytes(png)
    (folder / f"{observation_id}.txt").write_text(text, encoding="utf-8")
    return f"before/{observation_id}"
