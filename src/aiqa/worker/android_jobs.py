"""Android recording/replay job handlers for the independent worker runtime.

Importing this module does not open ADB, a model provider, or the management DB.
"""

from __future__ import annotations

import base64
import hashlib
import json
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
from aiqa.models.broker import ModelBroker
from aiqa.replay.android_runner import AndroidDeterministicDriver, require_approved_digest
from aiqa.worker.control import RemoteLeaseGuard
from aiqa.worker.dispatch_journal import DispatchJournal, JournalWriteError
from aiqa.worker.runner import MonotonicInstant
from aiqa.worker.runtime import HandlerResult, InertHandler, JobHandler
from aiqa.worker.spool import EvidenceSpool

_REPLAY_PURPOSES = frozenset({"trial", "regression"})


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
) -> tuple[dict[str, Any], ...]:
    """Build sanitized evidence events for server commit. No raw-handle fields."""

    events: list[dict[str, Any]] = []
    for seq, phase, obs in ((1, "before", before), (2, "after", after)):
        detail = json.dumps(
            {
                "phase": phase,
                "action_id": action_id,
                "sanitized": True,
                "review_pending": True,
                "png_sha256": "sha256:" + hashlib.sha256(obs.png).hexdigest(),
            },
            separators=(",", ":"),
            sort_keys=True,
        )
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
) -> tuple[dict[str, Any], ...]:
    """Build sanitized before/after PNG and action log bodies for evidence commit."""

    parts: list[dict[str, Any]] = []
    for phase, obs in (("before", before), ("after", after)):
        digest = "sha256:" + hashlib.sha256(obs.png).hexdigest()
        parts.append(
            {
                "filename": f"{phase}.png",
                "media_type": "image/png",
                "declared_hash": digest,
                "declared_length": len(obs.png),
                "body_b64": base64.b64encode(obs.png).decode("ascii"),
                "role": phase,
                "owner_kind": "REC",
                "attempt_id": attempt_id,
                "action_id": action_id,
            }
        )
    log_text = "\n".join(
        item
        for item in (
            f"action_id={action_id}",
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
            "filename": "action.log",
            "media_type": "text/plain",
            "declared_hash": "sha256:" + hashlib.sha256(log_body).hexdigest(),
            "declared_length": len(log_body),
            "body_b64": base64.b64encode(log_body).decode("ascii"),
            "role": "log",
            "owner_kind": "REC",
            "attempt_id": attempt_id,
            "action_id": action_id,
        }
    )
    return tuple(parts)


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


@dataclass
class AndroidRecordingHandler:
    """Claim snapshot → lease/journal gates → one Mobile-Agent recording step."""

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
    _mono_origin: float | None = field(default=None, init=False, repr=False)

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

        # Live workers use a process-relative clock so AttemptRunner limits stay meaningful.
        if self.context.mono_seconds is None:
            if self._mono_origin is None:
                self._mono_origin = time.monotonic()
            mono_value = max(0.0, time.monotonic() - self._mono_origin)
        else:
            mono_value = float(self.context.mono_seconds)
        now = MonotonicInstant(mono_value)
        # Runtime heartbeats refresh the same guard; standalone tests must too.
        self.guard.note_heartbeat(now)
        decision = self.guard.authorize(
            now,
            self.context.lease_remaining_seconds,
            phase="before_dispatch",
        )
        if not decision.allowed:
            return _fail_closed("lease_expired", evidence_complete=False)

        action_id = str(snapshot.get("action_id") or f"rec-{attempt_id}")
        if self.journal.is_ambiguous(attempt_id, action_id):
            return HandlerResult(
                actions=0,
                outcome="error",
                evidence_complete=False,
                ambiguous_dispatch=True,
            )

        try:
            self.journal.append(attempt_id, action_id, "planned")
            self.journal.append(attempt_id, action_id, "dispatch_started")
        except JournalWriteError:
            return _fail_closed("journal_blocked", evidence_complete=False)

        before_authoring = self.broker.authoring_calls
        try:
            before, after, before_ref, after_ref = self._run_recording_step()
        except MobileAgentRejected:
            self.journal.mark_started_only_unknown(attempt_id, action_id)
            return _fail_closed("recording_rejected", evidence_complete=False, ambiguous=True)
        except _CaptureFailed as exc:
            return _fail_closed(exc.reason, evidence_complete=False)

        self.tap_count += 1
        self.authoring_calls_seen = self.broker.authoring_calls - before_authoring
        if self.authoring_calls_seen < 1:
            return _fail_closed("authoring_missing", evidence_complete=False)

        try:
            self.journal.append(attempt_id, action_id, "acknowledged")
            self.journal.append(attempt_id, action_id, "observed")
        except JournalWriteError:
            return _fail_closed("journal_observe_failed", evidence_complete=False, ambiguous=True)

        events = android_evidence_events(
            attempt_id=attempt_id,
            before=before,
            after=after,
            action_id=action_id,
        )
        artifacts = android_evidence_artifacts(
            attempt_id=attempt_id,
            action_id=action_id,
            before=before,
            after=after,
        )
        commit = {
            "attempt_id": attempt_id,
            "action_id": action_id,
            "before_ref": before_ref,
            "after_ref": after_ref,
            "sanitized": True,
            "review_pending": True,
        }
        self.evidence_commits.append(commit)
        # Finish outcome is completed with evidence; server approval stays off the worker path.
        return HandlerResult(
            actions=1,
            outcome="completed",
            evidence_complete=True,
            ambiguous_dispatch=False,
            final_seq=len(events),
            last_ack_seq=0,
            last_ack_hash="",
            evidence_events=events,
            evidence_artifacts=artifacts,
            source_artifact_hashes=(),
            review_pending=True,
        )

    def _run_recording_step(self) -> tuple[Observation, Observation, str | None, str | None]:
        live = self.context.live_capture
        if live is None:
            before = self.context.before
            after = self.context.after
            if before is None or after is None or not after.capture_ok or after.png == b"":
                raise _CaptureFailed("after_evidence_missing")
            recorded = self.adapter.record_step(
                observation=before,
                after=after,
                fixture_response=self.context.fixture_response,
                broker=self.broker,
                control=self.control,
                driver=self.driver,
            )
            return before, after, recorded.before_ref, recorded.after_ref

        if self.context.prepare_device is not None:
            try:
                self.context.prepare_device()
            except Exception as exc:
                raise _CaptureFailed("device_prepare_failed") from exc
        try:
            before = live()
        except Exception as exc:
            raise _CaptureFailed("before_capture_failed") from exc
        if not before.capture_ok or before.png == b"":
            raise _CaptureFailed("before_capture_failed")
        authored = self.adapter.author(
            broker=self.broker,
            control=self.control,
            fixture_response=self.context.fixture_response,
        )
        action = self.adapter.parse_to_typed(authored.content, before)
        dispatch = self.adapter._dispatch(self.driver, before, before, action)
        # Re-capture after the native action so evidence is the real device surface.
        try:
            after = live()
        except Exception as exc:
            raise _CaptureFailed("after_evidence_missing") from exc
        if after is None or not after.capture_ok or after.png == b"":
            raise _CaptureFailed("after_evidence_missing")
        after_ref = self.driver._sanitize_to_spool(after, phase="after")
        return before, after, dispatch.before_ref, after_ref


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


@dataclass
class AndroidReplayContext:
    """Approved immutable plan inputs for trial/regression. Actor authoring stays 0."""

    expected_serial: str
    approved_digest: str
    approved_plan: str
    before: Observation
    after: Observation | None
    lease_remaining_seconds: float = 60.0
    mono_seconds: float = 100.0
    cancelled: bool = False
    healing_enabled: bool = False
    heal_budget_remaining: int = 0
    checks: tuple[object, ...] = ()
    verify_broker: object | None = None
    verify_transport: object | None = None
    verify_control: object | None = None
    healable_check_id: str | None = None
    approved_failure_reason: str | None = None
    healing_context: object | None = None


@dataclass
class AndroidReplayHandler:
    """Replay an approved plan: digest/geometry/lease gates, actor AI 0, limited healing."""

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

    def handle(self, claim: dict[str, Any]) -> HandlerResult:
        snapshot = claim.get("snapshot")
        if type(snapshot) is not dict:
            return _fail_closed("snapshot_missing")
        purpose = str(snapshot.get("purpose", ""))
        if purpose not in _REPLAY_PURPOSES:
            return _fail_closed("wrong_purpose")
        if self.context.cancelled or snapshot.get("cancel_requested") is True:
            return _fail_closed("cancelled", evidence_complete=False)

        serial = str(snapshot.get("serial") or snapshot.get("native_id") or "")
        if serial == "" or serial != self.context.expected_serial:
            return _fail_closed("serial_mismatch")

        presented = str(snapshot.get("digest") or snapshot.get("approved_digest") or "")
        try:
            require_approved_digest(presented, self.context.approved_digest)
        except Exception:
            return _fail_closed("digest_changed", evidence_complete=False)

        attempt_id = str(claim.get("attempt_id") or "")
        if attempt_id == "":
            return _fail_closed("attempt_missing")
        try:
            self.driver.bind_attempt(UUID(attempt_id))
        except (TypeError, ValueError):
            return _fail_closed("attempt_missing")

        now = MonotonicInstant(self.context.mono_seconds)
        self.guard.note_heartbeat(now)
        decision = self.guard.authorize(
            now,
            self.context.lease_remaining_seconds,
            phase="before_dispatch",
        )
        if not decision.allowed:
            return _fail_closed("lease_expired", evidence_complete=False)

        after = self.context.after
        if after is None or not after.capture_ok:
            self.original_failure = "after_evidence_missing"
            return _fail_closed("after_evidence_missing", evidence_complete=False)

        action_id = str(snapshot.get("action_id") or f"replay-{attempt_id}")
        if self.journal.is_ambiguous(attempt_id, action_id):
            # Disconnect/STARTED-only: never retransmit the physical action.
            return HandlerResult(
                actions=0,
                outcome="error",
                evidence_complete=False,
                ambiguous_dispatch=True,
            )

        try:
            self.journal.append(attempt_id, action_id, "planned")
            self.journal.append(attempt_id, action_id, "dispatch_started")
        except JournalWriteError:
            return _fail_closed("journal_blocked", evidence_complete=False)

        before_authoring = self.broker.authoring_calls
        try:
            recorded = self.adapter.replay_step(
                plan_response=self.context.approved_plan,
                observation=self.context.before,
                after=after,
                driver=self.driver,
                broker=self.broker,
            )
        except MobileAgentRejected as exc:
            self.journal.mark_started_only_unknown(attempt_id, action_id)
            self.original_failure = str(exc.reason)
            return _fail_closed("replay_rejected", evidence_complete=False, ambiguous=True)

        self.dispatch_count += 1
        self.authoring_calls_seen = self.broker.authoring_calls - before_authoring
        if self.authoring_calls_seen != 0 or recorded.authoring_calls != 0:
            return _fail_closed("actor_ai_forbidden", evidence_complete=False)

        try:
            self.journal.append(attempt_id, action_id, "acknowledged")
            self.journal.append(attempt_id, action_id, "observed")
        except JournalWriteError:
            return _fail_closed("journal_observe_failed", evidence_complete=False, ambiguous=True)

        verify = self._verify_and_heal(after)
        self.package_digest_after = verify.record.package_digest_after
        self.healer_calls = verify.record.healer_calls
        self.verifier_calls = verify.record.verifier_calls
        if verify.record.original_failure:
            self.original_failure = verify.record.original_failure
        events = android_evidence_events(
            attempt_id=attempt_id,
            before=self.context.before,
            after=after,
            action_id=action_id,
        )
        hashes = tuple(str(event["payload_hash"]) for event in events)
        if not verify.success:
            return HandlerResult(
                actions=1,
                outcome="error",
                evidence_complete=True,
                ambiguous_dispatch=False,
                final_seq=len(events),
                last_ack_seq=0,
                last_ack_hash="",
                evidence_events=events,
                source_artifact_hashes=hashes,
            )
        return HandlerResult(
            actions=1,
            outcome="completed",
            evidence_complete=True,
            ambiguous_dispatch=False,
            final_seq=len(events),
            last_ack_seq=0,
            last_ack_hash="",
            evidence_events=events,
            source_artifact_hashes=hashes,
        )

    def _verify_and_heal(self, observation: Observation) -> object:
        from aiqa.worker.runner import verify_and_heal_after_replay

        broker = self.context.verify_broker if self.context.verify_broker is not None else self.broker
        return verify_and_heal_after_replay(
            checks=self.context.checks,
            observation=observation,
            control=self.context.verify_control or _AllowVerify(),
            broker=broker,
            transport=self.context.verify_transport or _NoTransport(),
            healing_enabled=self.context.healing_enabled,
            heal_budget_remaining=self.context.heal_budget_remaining,
            approved_failure_reason=self.context.approved_failure_reason,
            healable_check_id=self.context.healable_check_id,
            approved_package_digest=self.context.approved_digest,
            healing_context=self.context.healing_context,
            heal_observation=observation,
        )


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
    other: dict[str, JobHandler] | None = None,
) -> PurposeRoutedHandler:
    """Register prepared Android handlers for the worker process entry."""

    if replay is None:
        return register_android_recording_handler(recording, other=other)
    return register_android_replay_handler(replay, recording=recording, other=other)


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
    from aiqa.environments.android_observation import AndroidObservationProvider
    import subprocess

    observer = AndroidObservationProvider(adb_path, serial, expected_avd=expected_avd)
    spool = EvidenceSpool(runtime_root / "spool")
    journal = DispatchJournal(runtime_root / "journal.jsonl")
    driver = AndroidDeterministicDriver(adb_path, serial, spool=spool)

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


def _fail_closed(
    _reason: str,
    *,
    evidence_complete: bool = True,
    ambiguous: bool = False,
) -> HandlerResult:
    return HandlerResult(
        actions=0,
        outcome="error",
        evidence_complete=evidence_complete,
        ambiguous_dispatch=ambiguous,
    )
