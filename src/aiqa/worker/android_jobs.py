"""Android recording/replay job handlers for the independent worker runtime.

Importing this module does not open ADB, a model provider, or the management DB.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from aiqa.adapters.mobile_agent_android import (
    AuthoringControl,
    MobileAgentAndroidAdapter,
    MobileAgentRejected,
)
from aiqa.contracts.actions import Observation
from aiqa.environments.app_builds import (
    AdbInstallDriver,
    AppPreparationSpec,
    FixtureInstallDriver,
    prepare_app,
)
from aiqa.environments.usb_android import list_installed_apps
from aiqa.models.broker import ModelBroker
from aiqa.replay.android_runner import AndroidDeterministicDriver, require_approved_digest
from aiqa.worker.control import RemoteLeaseGuard
from aiqa.worker.dispatch_journal import DispatchJournal, JournalWriteError
from aiqa.worker.runner import MonotonicInstant
from aiqa.worker.recording_limits import RecordingLimits, resolve_recording_limits
from aiqa.worker.runtime import HandlerResult, InertHandler, JobHandler
from aiqa.worker.spool import EvidenceSpool

_REPLAY_PURPOSES = frozenset({"trial", "regression"})


@dataclass
class InstalledAppsProbeHandler:
    """Read-only installed_apps listing for a claimed resource_probe. Install/reset stay 0."""

    adb_path: Path
    expected_serial: str
    run: Callable[..., Any] | None = None

    def handle(self, claim: dict[str, Any]) -> HandlerResult:
        snapshot = claim.get("snapshot")
        if type(snapshot) is not dict:
            return _fail_closed("snapshot_missing")
        if str(snapshot.get("purpose", "")) != "resource_probe":
            return _fail_closed("wrong_purpose")
        limits = snapshot.get("limits")
        kind = ""
        if type(limits) is dict:
            kind = str(limits.get("kind", ""))
        elif type(limits) is str:
            try:
                parsed = json.loads(limits)
            except json.JSONDecodeError:
                parsed = {}
            if type(parsed) is dict:
                kind = str(parsed.get("kind", ""))
        if kind != "installed_apps":
            # Other resource_probe kinds stay no-op on this Android entry.
            return HandlerResult(
                actions=0,
                outcome="completed",
                evidence_complete=True,
                ambiguous_dispatch=False,
            )
        serial = str(snapshot.get("serial") or snapshot.get("native_id") or self.expected_serial)
        observation = list_installed_apps(
            self.adb_path,
            serial,
            expected_serial=self.expected_serial,
            run=self.run,
        )
        payload = {
            "kind": "installed_apps",
            "type": "installed_apps",
            "serial": observation.serial,
            "state": observation.state,
            "reason": observation.reason,
            "observed_at": observation.observed_at,
            "install_calls": observation.install_calls,
            "reset_calls": observation.reset_calls,
            "ready": observation.state == "ready",
            "qa": None,
            "apps": [
                {
                    "package": app.package,
                    "version_name": app.version_name,
                    "api_level": app.api_level,
                    "abi": app.abi,
                    "content_hash": app.content_hash,
                }
                for app in observation.apps
            ],
        }
        return HandlerResult(
            actions=0,
            outcome="completed" if observation.state == "ready" else "error",
            evidence_complete=True,
            ambiguous_dispatch=False,
            action_mapping=json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
        )


def register_installed_apps_probe_handler(
    handler: InstalledAppsProbeHandler,
    *,
    other: dict[str, JobHandler] | None = None,
) -> PurposeRoutedHandler:
    """Attach installed_apps resource_probe handling for a prepared Android worker."""

    routes: dict[str, JobHandler] = {"resource_probe": handler}
    if other:
        routes.update(other)
    return PurposeRoutedHandler(routes)


@dataclass
class AppInstallHandler:
    """Explicit app_install/reset under lease and digest gates. Unapproved mutations stay 0."""

    expected_serial: str
    driver: FixtureInstallDriver | AdbInstallDriver
    build: object | None = None
    build_lookup: Callable[[UUID, UUID], object | None] | None = None
    # RX-74: (project_id, build_id, pinned_hash) -> verified build from the management server.
    build_fetcher: Callable[[UUID, UUID, str], object | None] | None = None
    # RX-75: (project_id, build_id, pinned_hash) -> local hash-verified APK path for a real driver.
    apk_provider: Callable[[UUID, UUID, str], Path | None] | None = None
    lease_held: bool = True

    def handle(self, claim: dict[str, Any]) -> HandlerResult:
        snapshot = claim.get("snapshot")
        if type(snapshot) is not dict:
            return _fail_closed("snapshot_missing")
        if str(snapshot.get("purpose", "")) != "app_install":
            return _fail_closed("wrong_purpose")
        limits = snapshot.get("limits")
        if type(limits) is str:
            try:
                limits = json.loads(limits)
            except json.JSONDecodeError:
                limits = {}
        if type(limits) is not dict:
            return _fail_closed("limits_missing")
        try:
            build_id = UUID(str(limits.get("build_id", "")))
            project_id = UUID(str(claim.get("project_id") or snapshot.get("project_id") or ""))
            resource_id = UUID(str(limits.get("resource_id") or snapshot.get("resource_id") or ""))
        except ValueError:
            return _fail_closed("invalid_ids")
        build = self.build
        if build is None and self.build_lookup is not None:
            build = self.build_lookup(project_id, build_id)
        if build is None:
            from aiqa.environments.app_builds import get_app_build

            build = get_app_build(project_id, build_id)
        pinned = str(limits.get("content_hash", ""))
        claim_build_hash = str(limits.get("build_hash") or pinned)
        if build is None and self.build_fetcher is not None:
            if pinned == "" or claim_build_hash != pinned:
                return _fail_closed("digest_mismatch")
            try:
                build = self.build_fetcher(project_id, build_id, pinned)
            except Exception:
                return _fail_closed("build_fetch_failed")
            if build is not None and (
                getattr(build, "content_hash", None) != pinned
                or getattr(build, "build_id", None) != build_id
            ):
                return _fail_closed("digest_mismatch")
        if build is None:
            return _fail_closed("build_missing")
        serial = str(limits.get("serial") or snapshot.get("serial") or self.expected_serial)
        policy = str(limits.get("policy", "use_installed"))
        apk_path: Path | None = None
        if (
            self.apk_provider is not None
            and policy in {"install_if_needed", "force_reinstall"}
            and bool(limits.get("confirmed", False))
            and self.lease_held
            and serial == self.expected_serial
            and getattr(build, "ready", False) is True
            and pinned != ""
            and getattr(build, "content_hash", None) == pinned
            and not snapshot.get("cancel_requested")
        ):
            try:
                apk_path = self.apk_provider(project_id, build_id, pinned)
            except Exception:
                return _fail_closed("apk_fetch_failed")
        result = prepare_app(
            AppPreparationSpec(
                project_id,
                resource_id,
                build_id,
                str(limits.get("content_hash", "")),
                serial,
                policy,
                bool(limits.get("confirmed", False)),
                apk_path,
            ),
            build=build,  # type: ignore[arg-type]
            driver=self.driver,
            enrolled_serial=self.expected_serial,
            lease_held=self.lease_held,
            cancel_requested=bool(snapshot.get("cancel_requested")),
        )
        payload = {
            "kind": "app_install",
            "type": "app_install",
            "ready": result.ready,
            "state": result.state,
            "reason": result.reason,
            "install_calls": result.install_calls,
            "reset_calls": result.reset_calls,
            "unapproved_mutations": self.driver.unapproved_mutations,
            "observed_at": result.observed_at,
            "package": result.package,
            "result_hash": result.content_hash,
            "qa": None,
            "build_id": str(build_id),
            "content_hash": str(limits.get("content_hash", "")),
            "policy": str(limits.get("policy", "use_installed")),
            "serial": serial,
            "confirmed": bool(limits.get("confirmed", False)),
            "resource_id": str(resource_id),
        }
        return HandlerResult(
            actions=result.install_calls + result.reset_calls,
            outcome="completed" if result.ready else "error",
            evidence_complete=True,
            ambiguous_dispatch=False,
            action_mapping=json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
        )


def register_app_install_handler(
    handler: AppInstallHandler,
    *,
    other: dict[str, JobHandler] | None = None,
) -> PurposeRoutedHandler:
    """Attach app_install handling for a prepared Android worker."""

    routes: dict[str, JobHandler] = {"app_install": handler}
    if other:
        routes.update(other)
    return PurposeRoutedHandler(routes)


@dataclass(frozen=True, slots=True)
class ClaimReplayPin:
    """Package digest/plan/healing taken from the server claim, not worker env."""

    package_id: str | None
    package_hash: str | None
    approved_plan: str | None
    healing_enabled: bool | None


def resolve_claim_replay_pin(snapshot: dict[str, Any]) -> ClaimReplayPin:
    """Prefer claim-fixed package references over global worker environment pins."""

    package_id = snapshot.get("replay_package_id")
    package_hash = snapshot.get("replay_package_hash")
    plan = snapshot.get("approved_plan")
    healing = snapshot.get("self_healing_enabled")
    return ClaimReplayPin(
        None if type(package_id) is not str or package_id.strip() == "" else package_id,
        None if type(package_hash) is not str or package_hash.strip() == "" else package_hash,
        None if type(plan) is not str or plan.strip() == "" else plan,
        None if type(healing) is not bool else healing,
    )


def resolve_android_claim_target(
    claim: dict[str, Any],
    *,
    registered_serial: str,
    registered_physical_key_id: str | None = None,
) -> dict[str, Any]:
    """Map server target_ref / physical_key_id onto the registered device serial."""

    if type(registered_serial) is not str or registered_serial.strip() == "":
        return claim
    serial = registered_serial.strip()
    snapshot = claim.get("snapshot")
    if type(snapshot) is not dict:
        return claim
    present = str(snapshot.get("serial") or snapshot.get("native_id") or "")
    if present == serial:
        return claim
    target = snapshot.get("target_ref")
    physical = claim.get("physical_key_id")
    matched = False
    if registered_physical_key_id is not None:
        key = str(registered_physical_key_id)
        if str(target or "") == key or str(physical or "") == key:
            matched = True
    if not matched and str(target or "") == serial:
        matched = True
    if not matched and present == "" and physical is not None:
        # Claim already fenced to a physical key; entry serial is the only registered device.
        matched = True
    if not matched:
        return claim
    enriched = dict(snapshot)
    enriched["serial"] = serial
    enriched["native_id"] = serial
    return {**claim, "snapshot": enriched}


def android_evidence_events(
    *,
    attempt_id: str,
    before: Observation,
    after: Observation,
    action_id: str,
    seq_base: int = 0,
    action_seq: int | None = None,
) -> tuple[dict[str, Any], ...]:
    """Build sanitized evidence events for server commit. No raw-handle fields."""

    events: list[dict[str, Any]] = []
    for offset, phase, obs in ((1, "before", before), (2, "after", after)):
        seq = seq_base + offset
        detail_body: dict[str, object] = {
            "phase": phase,
            "action_id": action_id,
            "sanitized": True,
            "review_pending": True,
            "png_sha256": "sha256:" + hashlib.sha256(obs.png).hexdigest(),
        }
        if action_seq is not None:
            detail_body["action_seq"] = action_seq
        detail = json.dumps(detail_body, separators=(",", ":"), sort_keys=True)
        body = detail.encode("utf-8")
        payload = f"{seq}\n".encode("utf-8") + body
        events.append(
            {
                "event_id": str(uuid4()),
                "attempt_id": attempt_id,
                "local_seq": seq,
                "captured_at": obs.captured_at,
                "event_type": "action.observed",
                "minimum_facts": "{}",
                "payload_hash": "sha256:" + hashlib.sha256(payload).hexdigest(),
                "body_hash": "sha256:" + hashlib.sha256(body).hexdigest(),
                "detail_payload": detail,
            }
        )
    return tuple(events)


def android_evidence_artifacts(
    *,
    attempt_id: str,
    action_id: str,
    before: Observation,
    after: Observation,
    action_seq: int | None = None,
    owner_kind: str = "REC",
) -> tuple[dict[str, Any], ...]:
    """Build sanitized before/after PNG and action log bodies for evidence commit.

    Recording evidence is owned by the recording (``REC``); replay evidence by the case run (``ITEM``).
    """

    parts: list[dict[str, Any]] = []
    prefix = "" if action_seq is None else f"a{action_seq}-"
    for phase, obs in (("before", before), ("after", after)):
        digest = "sha256:" + hashlib.sha256(obs.png).hexdigest()
        parts.append(
            {
                "filename": f"{prefix}{phase}.png",
                "media_type": "image/png",
                "declared_hash": digest,
                "declared_length": len(obs.png),
                "body_b64": base64.b64encode(obs.png).decode("ascii"),
                "role": phase,
                "owner_kind": owner_kind,
                "attempt_id": attempt_id,
                "action_id": action_id,
            }
        )
    log_text = "\n".join(
        item
        for item in (
            f"action_id={action_id}",
            None if action_seq is None else f"action_seq={action_seq}",
            f"before={before.captured_at}",
            f"after={after.captured_at}",
            before.stdout or "",
            after.stdout or "",
        )
        if item
    )
    log_body = log_text.encode("utf-8")
    parts.append(
        {
            "filename": f"{prefix}action.log",
            "media_type": "text/plain",
            "declared_hash": "sha256:" + hashlib.sha256(log_body).hexdigest(),
            "declared_length": len(log_body),
            "body_b64": base64.b64encode(log_body).decode("ascii"),
            "role": "log",
            "owner_kind": owner_kind,
            "attempt_id": attempt_id,
            "action_id": action_id,
        }
    )
    return tuple(parts)


def android_source_artifact(*, attempt_id: str, action_mapping: str) -> dict[str, Any]:
    """Recording `source` evidence: the sealed action mapping that the replay package compiles from."""

    body = action_mapping.encode("utf-8")
    return {
        "filename": "source-mapping.log",
        "media_type": "text/plain",
        "declared_hash": "sha256:" + hashlib.sha256(body).hexdigest(),
        "declared_length": len(body),
        "body_b64": base64.b64encode(body).decode("ascii"),
        "role": "source",
        "owner_kind": "REC",
        "attempt_id": attempt_id,
    }


# Per-step server commit. Returns the evidence-commit ACK dict (contiguous_seq, prefix_hash, …).
StepEvidenceCommit = Callable[..., dict[str, Any]]


@dataclass
class AndroidRecordingContext:
    """Per-attempt inputs. Authoring runs only inside the handler (after ACK)."""

    expected_serial: str
    fixture_response: str
    before: Observation | None = None
    after: Observation | None = None
    lease_remaining_seconds: float = 60.0
    mono_seconds: float | None = 100.0
    live_capture: Callable[[], Observation] | None = None
    prepare_device: Callable[[], None] | None = None
    plan_provider: Callable[[dict[str, Any]], str] | None = None
    fixture_responses: tuple[str, ...] = ()
    step_observations: tuple[tuple[Observation, Observation], ...] = ()
    max_actions: int = 50
    max_seconds: float | None = None
    cancelled: bool | Callable[[], bool] = False
    step_evidence_commit: StepEvidenceCommit | None = None
    remote_checkpoint: Callable[[str], object] | None = None


@dataclass
class AndroidRecordingHandler:
    """Claim snapshot → lease/journal gates → one or more Mobile-Agent recording steps."""

    adapter: MobileAgentAndroidAdapter
    driver: AndroidDeterministicDriver
    broker: ModelBroker
    control: AuthoringControl
    guard: RemoteLeaseGuard
    journal: DispatchJournal
    spool: EvidenceSpool
    context: AndroidRecordingContext
    evidence_commits: list[dict[str, object]] = field(default_factory=list)
    tap_count: int = 0
    authoring_calls_seen: int = 0
    finished_by_model: bool = False
    stopped_reason: str = ""
    _mono_origin: float | None = field(default=None, init=False, repr=False)
    _limits: RecordingLimits | None = field(default=None, init=False, repr=False)
    _plan_index: int = field(default=0, init=False, repr=False)
    _device_prepared: bool = field(default=False, init=False, repr=False)
    _previous_result: str = field(default="", init=False, repr=False)
    _seal_events: list[dict[str, Any]] = field(default_factory=list, init=False, repr=False)

    def handle(self, claim: dict[str, Any]) -> HandlerResult:
        snapshot = claim.get("snapshot")
        if type(snapshot) is not dict:
            return _fail_closed("snapshot_missing")
        if str(snapshot.get("purpose", "")) != "recording":
            return _fail_closed("wrong_purpose")

        serial = str(snapshot.get("serial") or snapshot.get("native_id") or "")
        if serial == "" or serial != self.context.expected_serial:
            return _fail_closed("serial_mismatch")

        attempt_id = str(claim.get("attempt_id") or "")
        if attempt_id == "":
            return _fail_closed("attempt_missing")
        try:
            self.driver.bind_attempt(UUID(attempt_id))
        except (TypeError, ValueError):
            return _fail_closed("attempt_missing")

        try:
            self._limits = resolve_recording_limits(snapshot,
                worker_actions=self.context.max_actions, worker_seconds=self.context.max_seconds)
        except ValueError:
            return _fail_closed("authoring_pin_invalid")
        multi = self.context.plan_provider is not None or len(self.context.fixture_responses) > 0
        max_actions = int(self.context.max_actions) if multi else 1
        if self._limits is not None:
            max_actions = min(max_actions, self._limits.max_actions)

        self.guard.begin_attempt(attempt_id)
        # Each claim/attempt starts clean so a reused handler cannot accumulate taps or clocks.
        all_events: list[dict[str, Any]] = []
        all_artifacts: list[dict[str, Any]] = []
        before_authoring = self.broker.authoring_calls
        self._plan_index = 0
        self.finished_by_model = False
        self.stopped_reason = ""
        self.tap_count = 0
        self.authoring_calls_seen = 0
        self.evidence_commits.clear()
        self._mono_origin = None
        self._device_prepared = False
        self._previous_result = ""
        self._seal_events = []
        last_ack_seq = 0
        last_ack_hash = ""
        acked_artifact_ids: list[str] = []
        step_commit = self.context.step_evidence_commit
        if max_actions < 1:
            self.stopped_reason = "action_budget"
            return _fail_closed("action_budget")

        for action_seq in range(1, max_actions + 1):
            if self._is_cancelled():
                self.stopped_reason = "cancelled"
                break
            now = self._mono_now()
            self.guard.note_heartbeat(now)
            decision = self.guard.authorize(
                now,
                self.context.lease_remaining_seconds,
                phase="before_lookup",
            )
            if not decision.allowed:
                self.stopped_reason = str(decision.reason or "lease_expired")
                if self.tap_count == 0:
                    return _fail_closed(self.stopped_reason, evidence_complete=False)
                break
            if self._limits is None and self.context.max_seconds is not None and now.seconds >= float(self.context.max_seconds):
                self.stopped_reason = "time_budget"
                if self.tap_count == 0:
                    return _fail_closed("time_budget", evidence_complete=False)
                break

            action_id = str(snapshot.get("action_id") or f"rec-{attempt_id}-{action_seq}")
            if action_seq == 1 and snapshot.get("action_id") and not multi:
                action_id = str(snapshot.get("action_id"))
            if self.journal.is_ambiguous(attempt_id, action_id):
                if self.tap_count == 0:
                    return HandlerResult(
                        actions=0,
                        outcome="error",
                        evidence_complete=False,
                        ambiguous_dispatch=True,
                    )
                self.stopped_reason = "ambiguous_dispatch"
                break

            try:
                self.journal.append(attempt_id, action_id, "planned")
            except JournalWriteError:
                if self.tap_count == 0:
                    return _fail_closed("journal_blocked", evidence_complete=False)
                self.stopped_reason = "journal_blocked"
                break

            try:
                step = self._run_recording_step(claim, action_seq=action_seq)
            except _RecordingFinished:
                self.finished_by_model = True
                self.stopped_reason = "model_finish"
                # Model finish is not a device dispatch and has no dispatch ACK.
                break
            except _PlanExhausted:
                self.stopped_reason = "plan_exhausted"
                break
            except MobileAgentRejected:
                ambiguous = self.journal.mark_started_only_unknown(attempt_id, action_id) == "unknown"
                self.stopped_reason = "ambiguous_dispatch" if ambiguous else "recording_rejected"
                if self.tap_count == 0:
                    return _fail_closed(self.stopped_reason, evidence_complete=False, ambiguous=ambiguous)
                break
            except _CaptureFailed as exc:
                uncertain = self.journal.is_ambiguous(attempt_id, action_id)
                self.stopped_reason = "ambiguous_dispatch" if uncertain else exc.reason
                if self.tap_count == 0:
                    return _fail_closed(exc.reason, evidence_complete=False, ambiguous=uncertain)
                break

            before, after, before_ref, after_ref, typed_action = step
            self.tap_count += 1
            try:
                self.journal.append(attempt_id, action_id, "acknowledged")
                self.journal.append(attempt_id, action_id, "observed")
            except JournalWriteError:
                if self.tap_count == 1:
                    return _fail_closed("journal_observe_failed", evidence_complete=False, ambiguous=True)
                self.stopped_reason = "journal_observe_failed"
                # Keep already committed steps; do not append this step's evidence.
                self.tap_count -= 1
                break

            seal_event = _seal_event_for_action(
                typed_action, before, action_id=action_id, line=action_seq
            )
            if seal_event is not None:
                self._seal_events.append(seal_event)
            seq_base = last_ack_seq if step_commit is not None else len(all_events)
            events = android_evidence_events(
                attempt_id=attempt_id,
                before=before,
                after=after,
                action_id=action_id,
                seq_base=seq_base,
                action_seq=action_seq,
            )
            artifacts = android_evidence_artifacts(
                attempt_id=attempt_id,
                action_id=action_id,
                before=before,
                after=after,
                action_seq=action_seq,
            )
            if step_commit is not None:
                try:
                    ack = step_commit(
                        action_seq=action_seq,
                        action_id=action_id,
                        events=list(events),
                        artifacts=list(artifacts),
                    )
                except Exception:
                    self.stopped_reason = "evidence_commit_failed"
                    break
                if type(ack) is not dict:
                    self.stopped_reason = "evidence_commit_failed"
                    break
                last_ack_seq = int(ack.get("contiguous_seq") or last_ack_seq)
                last_ack_hash = str(ack.get("prefix_hash") or last_ack_hash)
                for item in ack.get("artifact_ids") or ():
                    text = str(item).strip()
                    if text != "":
                        acked_artifact_ids.append(text)
                self.evidence_commits.append(
                    {
                        "attempt_id": attempt_id,
                        "action_id": action_id,
                        "action_seq": action_seq,
                        "before_ref": before_ref,
                        "after_ref": after_ref,
                        "sanitized": True,
                        "review_pending": True,
                        "acked": True,
                        "contiguous_seq": last_ack_seq,
                    }
                )
            else:
                all_events.extend(events)
                all_artifacts.extend(artifacts)
                self.evidence_commits.append(
                    {
                        "attempt_id": attempt_id,
                        "action_id": action_id,
                        "action_seq": action_seq,
                        "before_ref": before_ref,
                        "after_ref": after_ref,
                        "sanitized": True,
                        "review_pending": True,
                    }
                )
            if self._is_cancelled():
                self.stopped_reason = "cancelled"
                break

        self.authoring_calls_seen = self.broker.authoring_calls - before_authoring
        if self.tap_count < 1 and not self.finished_by_model:
            if self.stopped_reason:
                return _fail_closed(self.stopped_reason, evidence_complete=False)
            return _fail_closed("authoring_missing", evidence_complete=False)
        if self.tap_count >= 1 and self.authoring_calls_seen < 1:
            return _fail_closed("authoring_missing", evidence_complete=False)
        if (
            multi
            and self.tap_count >= max_actions
            and not self.finished_by_model
            and self.stopped_reason == ""
        ):
            self.stopped_reason = "action_budget"

        outcome = _recording_attempt_outcome(self.stopped_reason)
        # Only a completed recording carries a compile-ready mapping; cancelled/error stay "{}".
        action_mapping = "{}"
        if outcome == "completed" and self._seal_events:
            action_mapping = json.dumps(
                {"events": list(self._seal_events)},
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        if action_mapping != "{}":
            source_part = android_source_artifact(attempt_id=attempt_id, action_mapping=action_mapping)
            if step_commit is None:
                all_artifacts.append(source_part)
            else:
                try:
                    source_ack = step_commit(
                        action_seq=self.tap_count + 1,
                        action_id="source",
                        events=[],
                        artifacts=[source_part],
                    )
                    if type(source_ack) is not dict:
                        raise ValueError("source ack is invalid")
                    for item in source_ack.get("artifact_ids") or ():
                        text = str(item).strip()
                        if text != "":
                            acked_artifact_ids.append(text)
                except Exception:
                    # No source evidence means no compile-ready mapping and no approval-ready outcome.
                    self.stopped_reason = "evidence_commit_failed"
                    outcome = _recording_attempt_outcome(self.stopped_reason)
                    action_mapping = "{}"
        if step_commit is not None:
            return HandlerResult(
                actions=self.tap_count,
                outcome=outcome,
                evidence_complete=True,
                ambiguous_dispatch=self.stopped_reason == "ambiguous_dispatch",
                final_seq=max(last_ack_seq, self.tap_count * 2),
                last_ack_seq=last_ack_seq,
                last_ack_hash=last_ack_hash,
                evidence_events=(),
                evidence_artifacts=(),
                source_artifact_hashes=tuple(acked_artifact_ids),
                review_pending=outcome == "completed",
                action_mapping=action_mapping,
            )
        return HandlerResult(
            actions=self.tap_count,
            outcome=outcome,
            evidence_complete=True,
            ambiguous_dispatch=self.stopped_reason == "ambiguous_dispatch",
            final_seq=len(all_events),
            last_ack_seq=0,
            last_ack_hash="",
            evidence_events=tuple(all_events),
            evidence_artifacts=tuple(all_artifacts),
            source_artifact_hashes=(),
            review_pending=outcome == "completed",
            action_mapping=action_mapping,
        )

    def _is_cancelled(self) -> bool:
        flag = self.context.cancelled
        if callable(flag):
            return bool(flag())
        return bool(flag)

    def _mono_now(self) -> MonotonicInstant:
        if self.context.mono_seconds is None:
            if self._mono_origin is None:
                self._mono_origin = time.monotonic()
            mono_value = max(0.0, time.monotonic() - self._mono_origin)
        else:
            # Tests may bump mono_seconds between steps to exercise budgets.
            mono_value = float(self.context.mono_seconds)
            if self._limits is not None:
                if self._mono_origin is None:
                    self._mono_origin = mono_value
                mono_value = max(0.0, mono_value - self._mono_origin)
        return MonotonicInstant(mono_value)

    def _authoring_content(
        self,
        claim: dict[str, Any],
        *,
        observation: Observation,
        previous_result: str = "",
    ) -> str:
        self._recording_gate(claim, phase="before_model")
        if self._limits is not None and self._plan_index >= self._limits.max_model_calls:
            raise _CaptureFailed("model_budget")
        provider = self.context.plan_provider
        if provider is not None:
            step_claim = dict(claim)
            step_claim["action_seq"] = self._plan_index + 1
            step_claim["observation"] = observation
            step_claim["previous_result"] = previous_result
            from aiqa.worker.http_client import WorkerHttpError
            try:
                content = provider(step_claim)
            except WorkerHttpError as exc:
                # A model transport failure does not imply a device command was sent.
                raise _CaptureFailed("model_request_failed") from exc
            if type(content) is not str or content.strip() == "":
                raise MobileAgentRejected("authoring content missing")
            self._plan_index += 1
            return content
        responses = self.context.fixture_responses
        if responses:
            if self._plan_index >= len(responses):
                raise _PlanExhausted()
            content = responses[self._plan_index]
            self._plan_index += 1
            if type(content) is not str or content.strip() == "":
                raise MobileAgentRejected("authoring content missing")
            return content
        text = self.context.fixture_response
        if type(text) is not str or text.strip() == "":
            raise MobileAgentRejected("authoring content missing")
        self._plan_index += 1
        return text

    def _recording_gate(self, claim: dict[str, Any], *, phase: str) -> None:
        if self._is_cancelled() or claim["snapshot"].get("cancel_requested") is True:
            raise _CaptureFailed("cancelled")
        remote = self.context.remote_checkpoint
        if remote is not None and phase in {"before_model", "before_dispatch"}:
            decision = remote(phase)
            if getattr(decision, "allowed", None) is not True:
                raise _CaptureFailed("remote_checkpoint_blocked")
            if self._is_cancelled():
                raise _CaptureFailed("cancelled")
            # A fresh authenticated server fence also proves the current worker incarnation.
            self.guard.note_heartbeat(self._mono_now())
        now = self._mono_now()
        seconds = self._limits.timeout_seconds if self._limits is not None else self.context.max_seconds
        if seconds is not None and now.seconds >= seconds:
            raise _CaptureFailed("time_budget")
        decision = self.guard.authorize(now, self.context.lease_remaining_seconds, phase=phase)
        if not decision.allowed:
            raise _CaptureFailed(str(decision.reason or "lease_expired"))

    def _before_native_recording_send(self, claim: dict[str, Any], action_seq: int) -> None:
        # Driver has completed preflight, argv validation and sanitized spool I/O.
        self._recording_gate(claim, phase="before_lookup")
        snapshot = claim["snapshot"]
        attempt_id = str(claim["attempt_id"])
        action_id = str(snapshot.get("action_id") or f"rec-{attempt_id}-{action_seq}")
        try:
            self.journal.append(attempt_id, action_id, "dispatch_started")
            try:
                # Charge once after blocking journal I/O, immediately before native send.
                self._recording_gate(claim, phase="before_dispatch")
            except _CaptureFailed:
                self.journal.append(attempt_id, action_id, "not_sent")
                raise
        except JournalWriteError as exc:
            raise _CaptureFailed("journal_blocked") from exc

    def _observations_for_step(self, action_seq: int) -> tuple[Observation, Observation]:
        steps = self.context.step_observations
        if steps:
            index = action_seq - 1
            if index < 0 or index >= len(steps):
                raise _CaptureFailed("after_evidence_missing")
            before, after = steps[index]
            if before is None or after is None or not after.capture_ok or after.png == b"":
                raise _CaptureFailed("after_evidence_missing")
            return before, after
        before = self.context.before
        after = self.context.after
        if before is None or after is None or not after.capture_ok or after.png == b"":
            raise _CaptureFailed("after_evidence_missing")
        return before, after

    def _sanitize_before(self, observation: Observation) -> Observation:
        try:
            return self.adapter.sanitize(observation)
        except MobileAgentRejected as exc:
            raise _CaptureFailed("sanitize_failed") from exc

    def _run_recording_step(
        self, claim: dict[str, Any], *, action_seq: int
    ) -> tuple[Observation, Observation, str | None, str | None, Any]:
        """Observe → sanitize → model plan → parse → dispatch. Capture failure skips the model."""

        live = self.context.live_capture
        if live is None:
            before, after = self._observations_for_step(action_seq)
            if not before.capture_ok or before.png == b"":
                raise _CaptureFailed("before_capture_failed")
            before = self._sanitize_before(before)
            plan_text = self._authoring_content(
                claim, observation=before, previous_result=self._previous_result
            )
            authored = self.adapter.author(
                broker=self.broker,
                control=self.control,
                fixture_response=plan_text,
            )
            action = self.adapter.parse_to_typed(authored.content, before)
            if action.kind == "finish":
                self._previous_result = "finish"
                raise _RecordingFinished()
            dispatch = self.adapter._dispatch(self.driver, before, after, action,
                before_native_send=lambda: self._before_native_recording_send(claim, action_seq))
            self._previous_result = _action_result_token(action)
            return before, after, dispatch.before_ref, dispatch.after_ref, action

        if self.context.prepare_device is not None and not self._device_prepared:
            try:
                self.context.prepare_device()
            except Exception as exc:
                raise _CaptureFailed("device_prepare_failed") from exc
            self._device_prepared = True
        try:
            before = live()
        except Exception as exc:
            raise _CaptureFailed("before_capture_failed") from exc
        if not before.capture_ok or before.png == b"":
            raise _CaptureFailed("before_capture_failed")
        before = self._sanitize_before(before)
        plan_text = self._authoring_content(
            claim, observation=before, previous_result=self._previous_result
        )
        authored = self.adapter.author(
            broker=self.broker,
            control=self.control,
            fixture_response=plan_text,
        )
        action = self.adapter.parse_to_typed(authored.content, before)
        if action.kind == "finish":
            self._previous_result = "finish"
            raise _RecordingFinished()
        dispatch = self.adapter._dispatch(self.driver, before, before, action,
            before_native_send=lambda: self._before_native_recording_send(claim, action_seq))
        self._previous_result = _action_result_token(action)
        try:
            after = live()
        except Exception as exc:
            raise _CaptureFailed("after_evidence_missing") from exc
        if after is None or not after.capture_ok or after.png == b"":
            raise _CaptureFailed("after_evidence_missing")
        after_ref = self.driver._sanitize_to_spool(after, phase="after")
        return before, after, dispatch.before_ref, after_ref, action


def _seal_event_for_action(
    action: Any, before: Observation, *, action_id: str, line: int
) -> dict[str, Any] | None:
    """One RX-50 style seal event for a dispatched step. Unsupported kinds are skipped."""

    kind = str(getattr(action, "kind", "") or "")
    x = getattr(action, "x", None)
    y = getattr(action, "y", None)
    if kind == "tap" and type(x) is int and type(y) is int:
        name = "tap"
        bounds = [x, y, x + 1, y + 1]
        target: Any = f"{x},{y}"
    elif kind == "swipe" and type(x) is int and type(y) is int:
        x2, y2 = getattr(action, "x2", None), getattr(action, "y2", None)
        if type(x2) is not int or type(y2) is not int:
            return None
        name = "swipe"
        bounds = [min(x, x2), min(y, y2), max(x, x2) + 1, max(y, y2) + 1]
        target = f"{x},{y}->{x2},{y2}"
    elif kind == "text":
        name = "type"
        bounds = [0, 0, 1, 1]
        target = "text"
    elif kind == "key" and getattr(action, "keycode", None) == 4:
        name = "back"
        bounds = [0, 0, 1, 1]
        target = "back"
    else:
        return None
    return {
        "kind": "action",
        "action": name,
        "intent": "open",
        "target": target,
        "action_id": action_id,
        "line": line,
        "geometry": {
            "rotation": int(before.geometry.rotation),
            "content_bounds": bounds,
        },
    }


def _action_result_token(action: object) -> str:
    kind = str(getattr(action, "kind", "") or "")
    x = getattr(action, "x", None)
    y = getattr(action, "y", None)
    if x is None or y is None:
        return kind
    return f"{kind}:{x},{y}"


class _RecordingFinished(Exception):
    """Model returned an explicit finish/done/terminate with no further dispatch."""


class _PlanExhausted(Exception):
    """Fixture/plan sequence ended without an explicit finish verb."""


class _CaptureFailed(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class PurposeRoutedHandler:
    """Dispatch claim snapshots to purpose-specific handlers."""

    routes: dict[str, JobHandler]
    default: JobHandler = field(default_factory=InertHandler)

    def handle(self, claim: dict[str, Any]) -> HandlerResult:
        snapshot = claim.get("snapshot")
        purpose = "" if type(snapshot) is not dict else str(snapshot.get("purpose", ""))
        handler = self.routes.get(purpose, self.default)
        return handler.handle(claim)


def bind_step_evidence_commit(handler: object, committer: StepEvidenceCommit | None) -> None:
    """Attach a per-step evidence committer to recording handlers under a router."""

    if isinstance(handler, AndroidRecordingHandler):
        handler.context.step_evidence_commit = committer
        return
    routes = getattr(handler, "routes", None)
    if type(routes) is not dict:
        return
    for route in routes.values():
        if isinstance(route, AndroidRecordingHandler):
            route.context.step_evidence_commit = committer


def bind_attempt_checkpoint(handler: object, checkpoint: Callable[[str], object]) -> None:
    """Bind the current HTTPS claim fence without sharing a previous attempt's callback."""
    if isinstance(handler, AndroidRecordingHandler):
        handler.context.remote_checkpoint = checkpoint
        return
    routes = getattr(handler, "routes", None)
    if type(routes) is dict:
        for route in routes.values():
            bind_attempt_checkpoint(route, checkpoint)


@dataclass
class AndroidReplayContext:
    """Approved immutable plan inputs for trial/regression. Actor authoring stays 0."""

    expected_serial: str
    approved_digest: str
    approved_plan: str
    before: Observation | None = None
    after: Observation | None = None
    lease_remaining_seconds: float = 60.0
    mono_seconds: float = 100.0
    cancelled: bool | Callable[[], bool] = False
    healing_enabled: bool = False
    heal_budget_remaining: int = 0
    checks: tuple[object, ...] = ()
    verify_broker: object | None = None
    verify_transport: object | None = None
    verify_control: object | None = None
    healable_check_id: str | None = None
    approved_failure_reason: str | None = None
    healing_context: object | None = None
    step_observations: tuple[tuple[Observation, Observation], ...] = ()
    live_capture: Callable[[], Observation] | None = None
    max_seconds: float | None = None


@dataclass
class AndroidReplayHandler:
    """Replay each sealed plan line: observe → dispatch → observe → Check. Actor AI 0."""

    adapter: MobileAgentAndroidAdapter
    driver: AndroidDeterministicDriver
    broker: ModelBroker
    guard: RemoteLeaseGuard
    journal: DispatchJournal
    spool: EvidenceSpool
    context: AndroidReplayContext
    dispatch_count: int = 0
    authoring_calls_seen: int = 0
    healer_calls: int = 0
    verifier_calls: int = 0
    original_failure: str = ""
    package_digest_after: str = ""
    stopped_reason: str = ""

    def handle(self, claim: dict[str, Any]) -> HandlerResult:
        snapshot = claim.get("snapshot")
        if type(snapshot) is not dict:
            return _fail_closed("snapshot_missing")
        purpose = str(snapshot.get("purpose", ""))
        if purpose not in _REPLAY_PURPOSES:
            return _fail_closed("wrong_purpose")
        if self._is_cancelled() or snapshot.get("cancel_requested") is True:
            return _fail_closed("cancelled", evidence_complete=False)

        serial = str(snapshot.get("serial") or snapshot.get("native_id") or "")
        if serial == "" or serial != self.context.expected_serial:
            return _fail_closed("serial_mismatch")

        pin = resolve_claim_replay_pin(snapshot)
        approved_digest = pin.package_hash or self.context.approved_digest
        approved_plan = pin.approved_plan or self.context.approved_plan
        healing_enabled = pin.healing_enabled
        if healing_enabled is None:
            healing_enabled = self.context.healing_enabled
        if purpose == "trial":
            healing_enabled = False
        presented = pin.package_hash or str(snapshot.get("approved_digest") or snapshot.get("digest") or "")
        if pin.package_hash is not None and snapshot.get("approved_digest") not in {None, ""}:
            if str(snapshot.get("approved_digest")) != pin.package_hash:
                return _fail_closed("digest_changed", evidence_complete=False)
        try:
            require_approved_digest(presented, approved_digest)
        except Exception:
            return _fail_closed("digest_changed", evidence_complete=False)

        attempt_id = str(claim.get("attempt_id") or "")
        if attempt_id == "":
            return _fail_closed("attempt_missing")
        try:
            self.driver.bind_attempt(UUID(attempt_id))
        except (TypeError, ValueError):
            return _fail_closed("attempt_missing")

        plan_lines = _replay_plan_lines(approved_plan)
        if not plan_lines:
            return _fail_closed("plan_missing", evidence_complete=False)

        self.dispatch_count = 0
        self.authoring_calls_seen = 0
        self.healer_calls = 0
        self.verifier_calls = 0
        self.original_failure = ""
        self.package_digest_after = approved_digest
        self.stopped_reason = ""
        before_authoring = self.broker.authoring_calls
        all_events: list[dict[str, Any]] = []
        all_artifacts: list[dict[str, Any]] = []
        previous_after: Observation | None = None
        base_action_id = str(snapshot.get("action_id") or f"replay-{attempt_id}")

        for step_index, plan_line in enumerate(plan_lines):
            if self._is_cancelled():
                self.stopped_reason = "cancelled"
                break
            now = MonotonicInstant(float(self.context.mono_seconds))
            self.guard.note_heartbeat(now)
            decision = self.guard.authorize(
                now,
                self.context.lease_remaining_seconds,
                phase="before_dispatch",
            )
            if not decision.allowed:
                self.stopped_reason = str(decision.reason or "lease_expired")
                if self.dispatch_count == 0:
                    return _fail_closed(self.stopped_reason, evidence_complete=False)
                break
            if self.context.max_seconds is not None and now.seconds >= float(self.context.max_seconds):
                self.stopped_reason = "time_budget"
                if self.dispatch_count == 0:
                    return _fail_closed("time_budget", evidence_complete=False)
                break

            try:
                before, after = self._observations_for_step(step_index, previous_after)
            except _ReplayCaptureFailed as exc:
                self.original_failure = exc.reason
                self.stopped_reason = exc.reason
                if self.dispatch_count == 0:
                    return _fail_closed(exc.reason, evidence_complete=False)
                break

            action_id = (
                base_action_id if len(plan_lines) == 1 else f"{base_action_id}-{step_index + 1}"
            )
            if self.journal.is_ambiguous(attempt_id, action_id):
                if self.dispatch_count == 0:
                    return HandlerResult(
                        actions=0,
                        outcome="error",
                        evidence_complete=False,
                        ambiguous_dispatch=True,
                    )
                self.stopped_reason = "ambiguous_dispatch"
                break

            try:
                self.journal.append(attempt_id, action_id, "planned")
                self.journal.append(attempt_id, action_id, "dispatch_started")
            except JournalWriteError:
                if self.dispatch_count == 0:
                    return _fail_closed("journal_blocked", evidence_complete=False)
                self.stopped_reason = "journal_blocked"
                break

            try:
                recorded = self.adapter.replay_step(
                    plan_response=plan_line,
                    observation=before,
                    after=after if after is not None else before,
                    driver=self.driver,
                    broker=self.broker,
                )
            except MobileAgentRejected as exc:
                self.journal.mark_started_only_unknown(attempt_id, action_id)
                self.original_failure = str(exc.reason)
                if self.dispatch_count == 0:
                    return _fail_closed("replay_rejected", evidence_complete=False, ambiguous=True)
                self.stopped_reason = "replay_rejected"
                break

            if after is None:
                live = self.context.live_capture
                if live is None:
                    self.original_failure = "after_evidence_missing"
                    if self.dispatch_count == 0:
                        return _fail_closed("after_evidence_missing", evidence_complete=False)
                    self.stopped_reason = "after_evidence_missing"
                    break
                try:
                    after = live()
                except Exception:
                    self.original_failure = "after_evidence_missing"
                    if self.dispatch_count == 0:
                        return _fail_closed("after_evidence_missing", evidence_complete=False)
                    self.stopped_reason = "after_evidence_missing"
                    break
                if after is None or not after.capture_ok or after.png == b"":
                    self.original_failure = "after_evidence_missing"
                    if self.dispatch_count == 0:
                        return _fail_closed("after_evidence_missing", evidence_complete=False)
                    self.stopped_reason = "after_evidence_missing"
                    break

            self.dispatch_count += 1
            step_authoring = self.broker.authoring_calls - before_authoring
            self.authoring_calls_seen = step_authoring
            if step_authoring != 0 or recorded.authoring_calls != 0:
                return _fail_closed("actor_ai_forbidden", evidence_complete=False)

            try:
                self.journal.append(attempt_id, action_id, "acknowledged")
                self.journal.append(attempt_id, action_id, "observed")
            except JournalWriteError:
                if self.dispatch_count == 1:
                    return _fail_closed("journal_observe_failed", evidence_complete=False, ambiguous=True)
                self.stopped_reason = "journal_observe_failed"
                self.dispatch_count -= 1
                break

            verify = self._verify_and_heal(
                after,
                healing_enabled=healing_enabled,
                approved_digest=approved_digest,
            )
            self.package_digest_after = verify.record.package_digest_after
            self.healer_calls += int(verify.record.healer_calls)
            self.verifier_calls += int(verify.record.verifier_calls)
            if verify.record.original_failure:
                self.original_failure = verify.record.original_failure
            events = android_evidence_events(
                attempt_id=attempt_id,
                before=before,
                after=after,
                action_id=action_id,
                seq_base=len(all_events),
                action_seq=step_index + 1,
            )
            all_events.extend(events)
            all_artifacts.extend(
                android_evidence_artifacts(
                    attempt_id=attempt_id,
                    action_id=action_id,
                    before=before,
                    after=after,
                    action_seq=step_index + 1,
                    owner_kind="ITEM",
                )
            )
            previous_after = after
            if not verify.success:
                self.stopped_reason = "check_failed"
                hashes = tuple(str(event["payload_hash"]) for event in all_events)
                return HandlerResult(
                    actions=self.dispatch_count,
                    outcome="error",
                    evidence_complete=True,
                    ambiguous_dispatch=False,
                    final_seq=len(all_events),
                    last_ack_seq=0,
                    last_ack_hash="",
                    evidence_events=tuple(all_events),
                    evidence_artifacts=tuple(all_artifacts),
                    source_artifact_hashes=hashes,
                )

        if self.dispatch_count < 1:
            if self.stopped_reason:
                return _fail_closed(self.stopped_reason, evidence_complete=False)
            return _fail_closed("replay_rejected", evidence_complete=False)

        hashes = tuple(str(event["payload_hash"]) for event in all_events)
        if self.stopped_reason == "cancelled":
            return HandlerResult(
                actions=self.dispatch_count,
                outcome="cancelled",
                evidence_complete=True,
                ambiguous_dispatch=False,
                final_seq=len(all_events),
                last_ack_seq=0,
                last_ack_hash="",
                evidence_events=tuple(all_events),
                evidence_artifacts=tuple(all_artifacts),
                source_artifact_hashes=hashes,
            )
        if self.stopped_reason:
            return HandlerResult(
                actions=self.dispatch_count,
                outcome="error",
                evidence_complete=True,
                ambiguous_dispatch=self.stopped_reason == "ambiguous_dispatch",
                final_seq=len(all_events),
                last_ack_seq=0,
                last_ack_hash="",
                evidence_events=tuple(all_events),
                evidence_artifacts=tuple(all_artifacts),
                source_artifact_hashes=hashes,
            )
        return HandlerResult(
            actions=self.dispatch_count,
            outcome="completed",
            evidence_complete=True,
            ambiguous_dispatch=False,
            final_seq=len(all_events),
            last_ack_seq=0,
            last_ack_hash="",
            evidence_events=tuple(all_events),
            evidence_artifacts=tuple(all_artifacts),
            source_artifact_hashes=hashes,
        )

    def _is_cancelled(self) -> bool:
        flag = self.context.cancelled
        if callable(flag):
            return bool(flag())
        return bool(flag)

    def _observations_for_step(
        self, step_index: int, previous_after: Observation | None
    ) -> tuple[Observation, Observation | None]:
        """Resolve before/after for one sealed plan line. Live after is captured post-dispatch."""

        steps = self.context.step_observations
        if steps:
            if step_index < 0 or step_index >= len(steps):
                raise _ReplayCaptureFailed("after_evidence_missing")
            before, after = steps[step_index]
            if before is None or not before.capture_ok or before.png == b"":
                raise _ReplayCaptureFailed("before_capture_failed")
            if after is None or not after.capture_ok or after.png == b"":
                raise _ReplayCaptureFailed("after_evidence_missing")
            return before, after

        live = self.context.live_capture
        if live is not None:
            if previous_after is not None:
                before = previous_after
            else:
                try:
                    before = live()
                except Exception as exc:
                    raise _ReplayCaptureFailed("before_capture_failed") from exc
            if before is None or not before.capture_ok or before.png == b"":
                raise _ReplayCaptureFailed("before_capture_failed")
            return before, None

        if step_index > 0:
            raise _ReplayCaptureFailed("after_evidence_missing")
        before = self.context.before
        after = self.context.after
        if before is None or not before.capture_ok or before.png == b"":
            raise _ReplayCaptureFailed("before_capture_failed")
        if after is None or not after.capture_ok or after.png == b"":
            raise _ReplayCaptureFailed("after_evidence_missing")
        return before, after

    def _verify_and_heal(
        self,
        observation: Observation,
        *,
        healing_enabled: bool | None = None,
        approved_digest: str | None = None,
    ) -> object:
        from aiqa.worker.runner import verify_and_heal_after_replay

        broker = self.context.verify_broker if self.context.verify_broker is not None else self.broker
        return verify_and_heal_after_replay(
            checks=self.context.checks,
            observation=observation,
            control=self.context.verify_control or _AllowVerify(),
            broker=broker,
            transport=self.context.verify_transport or _NoTransport(),
            healing_enabled=self.context.healing_enabled if healing_enabled is None else healing_enabled,
            heal_budget_remaining=self.context.heal_budget_remaining,
            approved_failure_reason=self.context.approved_failure_reason,
            healable_check_id=self.context.healable_check_id,
            approved_package_digest=self.context.approved_digest if approved_digest is None else approved_digest,
            healing_context=self.context.healing_context,
            heal_observation=observation,
        )


def _replay_plan_lines(plan: str) -> tuple[str, ...]:
    """Split a sealed multi-line Mobile-Agent plan into one action per step."""

    if type(plan) is not str:
        return ()
    return tuple(line.strip() for line in plan.splitlines() if line.strip() != "")


class _ReplayCaptureFailed(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class _AllowAuthoring:
    def checkpoint(self) -> object:
        from aiqa.contracts.jobs import ControlDecision

        return ControlDecision(True, "before_model")


class _AllowVerify:
    def checkpoint(self) -> object:
        from aiqa.contracts.jobs import ControlDecision

        return ControlDecision(True, "before_model")

    def allow_model_action(self, *, late: bool) -> object:
        from aiqa.contracts.jobs import ControlDecision

        return ControlDecision(not late, "before_model")


class _NoTransport:
    calls = 0

    def complete(self, check_id: str) -> str:
        raise TimeoutError("provider is not connected")


def register_android_recording_handler(
    recording: AndroidRecordingHandler,
    *,
    other: dict[str, JobHandler] | None = None,
) -> PurposeRoutedHandler:
    """Attach the recording handler for worker prepared_adapters including recording."""

    routes: dict[str, JobHandler] = {"recording": recording}
    if other:
        routes.update(other)
    return PurposeRoutedHandler(routes)


def register_android_replay_handler(
    replay: AndroidReplayHandler,
    *,
    recording: AndroidRecordingHandler | None = None,
    other: dict[str, JobHandler] | None = None,
) -> PurposeRoutedHandler:
    """Attach trial/regression replay (and optional recording) handlers."""

    routes: dict[str, JobHandler] = {
        "trial": replay,
        "regression": replay,
    }
    if recording is not None:
        routes["recording"] = recording
    if other:
        routes.update(other)
    return PurposeRoutedHandler(routes)


def assemble_android_worker_handlers(
    *,
    recording: AndroidRecordingHandler,
    replay: AndroidReplayHandler | None = None,
    installed_apps: InstalledAppsProbeHandler | None = None,
    app_install: AppInstallHandler | None = None,
    other: dict[str, JobHandler] | None = None,
) -> PurposeRoutedHandler:
    """Register prepared Android handlers for the worker process entry."""

    routes: dict[str, JobHandler] = {}
    if installed_apps is not None:
        routes["resource_probe"] = installed_apps
    if app_install is not None:
        routes["app_install"] = app_install
    if other:
        routes.update(other)
    if replay is None:
        return register_android_recording_handler(recording, other=routes or None)
    return register_android_replay_handler(replay, recording=recording, other=routes or None)


def build_android_support_handlers(
    *,
    adb_path: Path,
    serial: str,
    run: Callable[..., Any] | None = None,
    install_driver: FixtureInstallDriver | AdbInstallDriver | None = None,
    build_fetcher: Callable[[UUID, UUID, str], object | None] | None = None,
    apk_provider: Callable[[UUID, UUID, str], Path | None] | None = None,
) -> tuple[InstalledAppsProbeHandler, AppInstallHandler]:
    """Helpers for installed_apps probe and explicit app_install claims.

    Without an explicit ``install_driver`` the real ``AdbInstallDriver`` is used (RX-75);
    fixtures are injected by tests only.
    """

    driver = (
        install_driver
        if install_driver is not None
        else AdbInstallDriver(adb_path=adb_path, expected_serial=serial, run=run)
    )
    probe = InstalledAppsProbeHandler(adb_path=adb_path, expected_serial=serial, run=run)
    install = AppInstallHandler(
        expected_serial=serial,
        driver=driver,
        build_fetcher=build_fetcher,
        apk_provider=apk_provider,
        lease_held=True,
    )
    return probe, install


_DIGEST_FORM = re.compile(r"^sha256:[0-9a-f]{64}$")


def http_apk_provider(client: object, spool_dir: Path) -> Callable[[UUID, UUID, str], Path | None]:
    """Download the pinned APK over the worker HTTP client into ``spool_dir`` (RX-75).

    The bytes are hash-verified by the client and again here; the file name is derived only from
    the validated digest. A bad or missing hash raises, so the handler fails closed.
    """

    root = Path(spool_dir)

    def provide(project_id: UUID, build_id: UUID, pinned_hash: str) -> Path | None:
        if type(pinned_hash) is not str or _DIGEST_FORM.fullmatch(pinned_hash) is None:
            raise ValueError("pinned hash is invalid")
        body, digest = getattr(client, "fetch_app_build_content")(
            str(project_id), str(build_id), expected_hash=pinned_hash
        )
        actual = "sha256:" + hashlib.sha256(body).hexdigest()
        if digest != pinned_hash or actual != pinned_hash:
            raise ValueError("apk bytes do not match the pinned hash")
        root.mkdir(parents=True, exist_ok=True)
        target = root / f"{pinned_hash.split(':', 1)[1]}.apk"
        temp = root / f".{uuid4().hex}.tmp"
        try:
            temp.write_bytes(body)
            temp.replace(target)
        finally:
            if temp.exists():
                temp.unlink()
        return target

    return provide


def http_app_build_fetcher(client: object) -> Callable[[UUID, UUID, str], object | None]:
    """Fetch a pinned build over the authenticated worker HTTP client (RX-74).

    Downloads the APK bytes, verifies their sha256 against the claim-pinned hash, and returns
    an ``AppBuildView`` whose hash comes from the verified bytes. A 404 returns None; any
    hash problem raises so the handler fails closed.
    """

    from aiqa.environments.app_builds import AppBuildView
    from aiqa.worker.http_client import WorkerHttpError

    def fetch(project_id: UUID, build_id: UUID, pinned_hash: str) -> object | None:
        try:
            meta = getattr(client, "get_app_build")(str(project_id), str(build_id))
        except WorkerHttpError as exc:
            if exc.status_code == 404:
                return None
            raise
        _, digest = getattr(client, "fetch_app_build_content")(
            str(project_id), str(build_id), expected_hash=pinned_hash
        )

        def text(name: str) -> str | None:
            value = meta.get(name)
            return None if value is None or str(value) == "" else str(value)

        return AppBuildView(
            build_id,
            str(meta.get("filename") or ""),
            text("package_name"),
            text("version_name"),
            text("min_sdk"),
            text("abi"),
            str(meta.get("signature_status") or "unknown"),
            meta.get("ready") is True,
            digest,
            int(meta.get("byte_length") or 0),
            str(meta.get("created_at") or ""),
        )

    return fetch


def _live_android_capture_pair(
    *,
    adb_path: Path,
    serial: str,
    expected_avd: str | None,
) -> tuple[Callable[[], Observation], Callable[[], None]]:
    from aiqa.environments.android_observation import AndroidObservationProvider
    import subprocess

    observer = AndroidObservationProvider(adb_path, serial, expected_avd=expected_avd)

    def capture() -> Observation:
        result = observer.observe(capture=True)
        if result.observation is None or not result.observation.capture_ok:
            raise RuntimeError(result.reason or "capture_failed")
        return result.observation

    def prepare() -> None:
        completed = subprocess.run(
            [
                str(adb_path),
                "-s",
                serial,
                "shell",
                "am",
                "start",
                "-a",
                "android.settings.SETTINGS",
            ],
            capture_output=True,
            timeout=20,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError("settings_launch_failed")
        time.sleep(1.5)

    return capture, prepare


def observation_authoring_inputs(
    observation: Observation,
    *,
    previous_result: str = "",
) -> tuple[str, ...]:
    """Digest-level observation context for model requests. Never includes raw PNG bytes."""

    geo = observation.geometry
    if geo is None:
        raise MobileAgentRejected("geometry is invalid")
    screen = "sha256:" + hashlib.sha256(observation.png).hexdigest()
    hierarchy_raw = observation.stdout if observation.stdout.strip() != "" else observation.dom
    hierarchy = "sha256:" + hashlib.sha256(hierarchy_raw.encode("utf-8")).hexdigest()
    parts = [
        f"observation_id:{observation.observation_id}",
        f"geometry:{geo.physical_width}x{geo.physical_height}:rot{geo.rotation}",
        f"screen_digest:{screen}",
        f"hierarchy_digest:{hierarchy}",
    ]
    if previous_result.strip() != "":
        parts.append(f"previous_result:{previous_result.strip()}")
    return tuple(parts)


def server_model_plan_provider(
    client: object,
    *,
    binding_revision: int = 1,
    token_output_limit: int = 64,
) -> Callable[[dict[str, Any]], str]:
    """Fetch authoring plan text via worker model-requests. Secrets stay on the server."""

    def provide(claim: dict[str, Any]) -> str:
        project_id = str(claim.get("project_id") or "").strip()
        attempt_id = str(claim.get("attempt_id") or "").strip()
        if project_id == "" or attempt_id == "":
            raise MobileAgentRejected("model request context missing")
        call_id = str(uuid4())
        snapshot = claim.get("snapshot") if type(claim.get("snapshot")) is dict else {}
        from aiqa.contracts.authoring import validate_authoring_pin
        pin = validate_authoring_pin(snapshot)
        revision = pin["authoring_binding"]["revision"] if pin is not None else binding_revision
        intent_hash = str(snapshot.get("intent_hash") or "").strip()
        observation = claim.get("observation")
        previous_result = str(claim.get("previous_result") or "")
        if isinstance(observation, Observation):
            sanitized_inputs = list(
                observation_authoring_inputs(observation, previous_result=previous_result)
            )
        else:
            sanitized_inputs = ["sanitized"]
        payload: dict[str, Any] = {
            "call_id": call_id,
            "purpose": "recording",
            "role": "authoring",
            "owner_kind": "authoring",
            "owner_id": attempt_id,
            "binding_revision": revision,
            "sanitized_inputs": sanitized_inputs,
            "token_output_limit": token_output_limit,
            "deadline": "2099-01-01T00:00:00+00:00",
        }
        if pin is not None:
            payload["generation"] = claim.get("generation")
        if intent_hash != "":
            payload["intent_hash"] = intent_hash
        if pin is not None:
            from aiqa.worker.model_observations import upload_authoring_observation
            frame = upload_authoring_observation(client, claim, observation, payload)
            payload["model_observation_id"] = frame["observation_id"]
            payload["sanitized_inputs"] = frame["sanitized_inputs"]
        request = getattr(client, "request_model")
        receipt = request(
            project_id=project_id,
            item_id=attempt_id,
            payload=payload,
            idempotency_key=f"author-{attempt_id}-{call_id}",
        )
        if type(receipt) is not dict or receipt.get("allowed") is not True:
            raise MobileAgentRejected("authoring refused")
        if pin is not None and receipt.get("action_allowed") is not True:
            raise MobileAgentRejected("authoring response is not executable")
        content = receipt.get("content")
        if type(content) is not str or content.strip() == "":
            raise MobileAgentRejected("authoring content missing")
        return content

    return provide


def build_fixture_android_recording_handler(
    *,
    adb_path: Path,
    serial: str,
    expected_avd: str | None,
    runtime_root: Path,
    fixture_response: str,
) -> AndroidRecordingHandler:
    """Wire a live ADB capture path that uses only an explicit fixture model response."""

    from aiqa.adapters.mobile_agent_android import MobileAgentAndroidAdapter, recording_broker

    capture, prepare = _live_android_capture_pair(
        adb_path=adb_path, serial=serial, expected_avd=expected_avd
    )
    spool = EvidenceSpool(runtime_root / "spool")
    journal = DispatchJournal(runtime_root / "journal.jsonl")
    driver = AndroidDeterministicDriver(adb_path, serial, spool=spool)

    return AndroidRecordingHandler(
        adapter=MobileAgentAndroidAdapter(),
        driver=driver,
        broker=recording_broker(),
        control=_AllowAuthoring(),
        guard=RemoteLeaseGuard(),
        journal=journal,
        spool=spool,
        context=AndroidRecordingContext(
            expected_serial=serial,
            fixture_response=fixture_response,
            before=None,
            after=None,
            lease_remaining_seconds=120.0,
            mono_seconds=None,
            live_capture=capture,
            prepare_device=prepare,
        ),
    )


def build_operational_android_recording_handler(
    *,
    adb_path: Path,
    serial: str,
    expected_avd: str | None,
    runtime_root: Path,
    client: object,
) -> AndroidRecordingHandler:
    """Live ADB recording that uses management-server operational model responses."""

    from aiqa.adapters.mobile_agent_android import MobileAgentAndroidAdapter, recording_broker

    capture, prepare = _live_android_capture_pair(
        adb_path=adb_path, serial=serial, expected_avd=expected_avd
    )
    spool = EvidenceSpool(runtime_root / "spool")
    journal = DispatchJournal(runtime_root / "journal.jsonl")
    driver = AndroidDeterministicDriver(adb_path, serial, spool=spool)

    return AndroidRecordingHandler(
        adapter=MobileAgentAndroidAdapter(),
        driver=driver,
        broker=recording_broker(),
        control=_AllowAuthoring(),
        guard=RemoteLeaseGuard(),
        journal=journal,
        spool=spool,
        context=AndroidRecordingContext(
            expected_serial=serial,
            fixture_response="",
            before=None,
            after=None,
            lease_remaining_seconds=120.0,
            mono_seconds=None,
            live_capture=capture,
            prepare_device=prepare,
            plan_provider=server_model_plan_provider(client),
        ),
    )


def build_approved_android_replay_handler(
    *,
    adb_path: Path,
    serial: str,
    expected_avd: str | None,
    runtime_root: Path,
    approved_digest: str,
    approved_plan: str,
    checks: tuple[object, ...] = (),
    healing_enabled: bool = False,
) -> AndroidReplayHandler:
    """Replay each sealed plan line on a live device. Capture after every dispatch."""

    from aiqa.adapters.mobile_agent_android import MobileAgentAndroidAdapter, recording_broker
    from aiqa.contracts.models import OwnedCheck, RoleBinding

    capture, prepare = _live_android_capture_pair(
        adb_path=adb_path, serial=serial, expected_avd=expected_avd
    )
    prepare()
    spool = EvidenceSpool(runtime_root / "spool-replay")
    journal = DispatchJournal(runtime_root / "journal-replay.jsonl")
    driver = AndroidDeterministicDriver(adb_path, serial, spool=spool)
    verify_broker = ModelBroker(
        "replay-item",
        (
            RoleBinding("verification", 1, "fixture-v", "ref"),
            RoleBinding("healing", 1, "fixture-h", "ref"),
        ),
        (OwnedCheck("check-1", "replay-item"),),
        (),
    )
    return AndroidReplayHandler(
        adapter=MobileAgentAndroidAdapter(),
        driver=driver,
        broker=recording_broker("replay-item"),
        guard=RemoteLeaseGuard(),
        journal=journal,
        spool=spool,
        context=AndroidReplayContext(
            expected_serial=serial,
            approved_digest=approved_digest,
            approved_plan=approved_plan,
            lease_remaining_seconds=120.0,
            mono_seconds=100.0,
            healing_enabled=healing_enabled,
            heal_budget_remaining=0,
            checks=checks,
            verify_broker=verify_broker,
            verify_transport=_NoTransport(),
            verify_control=_AllowVerify(),
            live_capture=capture,
        ),
    )


_RECORDING_SUCCESS_STOPS = frozenset({"", "model_finish"})
_RECORDING_CANCEL_STOPS = frozenset({"cancelled"})


def _recording_attempt_outcome(stopped_reason: str) -> str:
    """Map stop cause to attempt outcome. Only clean finish is approval-ready completed."""

    if stopped_reason in _RECORDING_SUCCESS_STOPS:
        return "completed"
    if stopped_reason in _RECORDING_CANCEL_STOPS:
        return "cancelled"
    return "error"


def _fail_closed(
    _reason: str,
    *,
    evidence_complete: bool = True,
    ambiguous: bool = False,
) -> HandlerResult:
    outcome = "cancelled" if _reason == "cancelled" else "error"
    return HandlerResult(
        actions=0,
        outcome=outcome,
        evidence_complete=evidence_complete,
        ambiguous_dispatch=ambiguous,
        review_pending=False,
    )
