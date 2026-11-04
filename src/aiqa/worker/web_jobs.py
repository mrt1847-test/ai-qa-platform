"""Web recording/replay job handlers for the independent worker runtime.

Importing this module does not open a browser, CDP, or a real VM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable
from uuid import UUID, uuid4

from aiqa.adapters.cuawright_web import (
    CuawrightRejected,
    CuawrightWebAdapter,
    make_recording_manifest,
)
from aiqa.contracts.actions import Observation
from aiqa.contracts.evidence import EvidenceEnvelope
from aiqa.replay.driver import ApprovedWebPackage
from aiqa.worker.android_jobs import (
    PurposeRoutedHandler,
    android_evidence_artifacts,
    android_evidence_events,
)
from aiqa.worker.control import RemoteLeaseGuard
from aiqa.worker.dispatch_journal import DispatchJournal, JournalWriteError
from aiqa.worker.isolated_web import admit_recording_channel, require_web_ready
from aiqa.worker.runner import MonotonicInstant
from aiqa.worker.runtime import HandlerResult, InertHandler, JobHandler
from aiqa.worker.spool import EvidenceSpool
from aiqa.worker.web_isolation_backend import IsolationProof, IsolationRejected, WebIsolationGate
from aiqa.worker.web_vm_transport import LocalGuestProcess, WebVmTransport

# Sanitized before/after events/files for WorkerRuntime server commit (same wire as Android).
web_evidence_events = android_evidence_events
web_evidence_artifacts = android_evidence_artifacts


def resolve_web_claim_origin(
    claim: dict[str, Any],
    *,
    approved_origin: str,
) -> dict[str, Any]:
    """Attach the worker's approved HTTPS origin when the claim snapshot omits it."""

    if type(approved_origin) is not str or not approved_origin.startswith("https://"):
        return claim
    snapshot = claim.get("snapshot")
    if type(snapshot) is not dict:
        return claim
    present = str(snapshot.get("origin") or "")
    if present == approved_origin:
        return claim
    if present != "":
        return claim
    enriched = dict(snapshot)
    enriched["origin"] = approved_origin
    return {**claim, "snapshot": enriched}

_REPLAY_PURPOSES = frozenset({"trial", "regression"})
BrowserRunner = Callable[[object], None]


@dataclass
class WebRecordingContext:
    """Per-attempt Web recording inputs. Authoring/IPC runs only after ACK gates."""

    approved_origin: str
    trajectory: dict[str, object]
    before: Observation
    after: Observation | None
    proof: IsolationProof
    now: datetime
    lease_remaining_seconds: float = 60.0
    mono_seconds: float = 100.0
    guest_process: LocalGuestProcess | None = None
    channel: str = "ipc"
    endpoint_id: str = ""


@dataclass
class WebRecordingHandler:
    """Claim snapshot → ready/lease/journal → CUAWright extract + guest IPC recording step."""

    adapter: CuawrightWebAdapter
    transport: WebVmTransport
    gate: WebIsolationGate
    guard: RemoteLeaseGuard
    journal: DispatchJournal
    spool: EvidenceSpool
    context: WebRecordingContext
    evidence_commits: list[dict[str, object]] = field(default_factory=list)
    authoring_dispatches: int = 0
    raw_sources_held: int = 0
    approval_digests: list[str] = field(default_factory=list)

    def handle(self, claim: dict[str, Any]) -> HandlerResult:
        snapshot = claim.get("snapshot")
        if type(snapshot) is not dict:
            return _fail_closed("snapshot_missing")
        if str(snapshot.get("purpose", "")) != "recording":
            return _fail_closed("wrong_purpose")

        origin = str(snapshot.get("origin") or "")
        if origin == "" or origin != self.context.approved_origin:
            return _fail_closed("origin_mismatch")

        attempt_id = str(claim.get("attempt_id") or "")
        if attempt_id == "":
            return _fail_closed("attempt_missing")

        try:
            admit_recording_channel(self.context.channel)
        except ValueError:
            return _fail_closed("channel_refused", evidence_complete=False)

        if self.context.channel != "ipc":
            return _fail_closed("direct_cdp_refused", evidence_complete=False)

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
            return _fail_closed("after_evidence_missing", evidence_complete=False)

        if self.transport.session is None or not self.transport.session.alive:
            endpoint = self.context.endpoint_id or str(
                snapshot.get("endpoint_id") or next(iter(self.transport.config.approved_endpoints))
            )
            try:
                self.transport.connect(
                    endpoint,
                    self.context.proof,
                    now=self.context.now,
                    guest_process=self.context.guest_process,
                    open_channel=self.context.guest_process is not None,
                )
            except IsolationRejected:
                return _fail_closed("web_not_ready", evidence_complete=False)
        if not self.transport.web_ready(now=self.context.now):
            return _fail_closed("web_not_ready", evidence_complete=False)
        if not require_web_ready(self.gate.web_ready(self.context.proof, now=self.context.now)):
            return _fail_closed("proof_unverified", evidence_complete=False)

        action_id = str(snapshot.get("action_id") or f"web-rec-{attempt_id}")
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

        try:
            bundle = self.adapter.extract_trajectory(self.context.trajectory)
        except CuawrightRejected:
            self.journal.mark_started_only_unknown(attempt_id, action_id)
            return _fail_closed("trajectory_rejected", evidence_complete=False, ambiguous=True)

        self.raw_sources_held = len(bundle.raw_sources)
        if not bundle.package_ready:
            return _fail_closed("package_not_ready", evidence_complete=False)

        first = bundle.summaries[0]
        body: dict[str, object] = {"type": first.action_type, "selector": first.selector}
        if first.value:
            body["value"] = first.value
        try:
            self.transport.dispatch_ipc({"kind": "ipc", "payload": body}, now=self.context.now)
        except IsolationRejected:
            self.journal.mark_started_only_unknown(attempt_id, action_id)
            return _fail_closed("ipc_rejected", evidence_complete=False, ambiguous=True)
        self.authoring_dispatches += 1

        draft = self.adapter.build_approval_package(
            bundle,
            origin=self.context.approved_origin,
            revision=str(snapshot.get("revision") or "lock-1"),
            manifest=make_recording_manifest(raw_source=bundle.reviewable_source),
            lock_hash=str(snapshot.get("revision") or "lock-1"),
        )
        self.approval_digests.append(draft.digest)

        try:
            self.journal.append(attempt_id, action_id, "acknowledged")
            self.journal.append(attempt_id, action_id, "observed")
        except JournalWriteError:
            return _fail_closed("journal_observe_failed", evidence_complete=False, ambiguous=True)

        attempt_uuid = _attempt_uuid(attempt_id)
        before_receipt = self.spool.append(
            EvidenceEnvelope(attempt_uuid, 1, self.context.before.png, "before", self.context.before.captured_at)
        )
        after_receipt = self.spool.append(
            EvidenceEnvelope(attempt_uuid, 2, after.png, "after", after.captured_at)
        )
        self.evidence_commits.append(
            {
                "attempt_id": attempt_id,
                "action_id": action_id,
                "before_ref": before_receipt.payload_hash,
                "after_ref": after_receipt.payload_hash,
                "sanitized": True,
                "review_pending": True,
                "raw_source_digest": bundle.source_digest,
                "approval_digest": draft.digest,
            }
        )
        events = web_evidence_events(
            attempt_id=attempt_id,
            before=self.context.before,
            after=after,
            action_id=action_id,
        )
        artifacts = web_evidence_artifacts(
            attempt_id=attempt_id,
            action_id=action_id,
            before=self.context.before,
            after=after,
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
            evidence_artifacts=artifacts,
            source_artifact_hashes=(),
            review_pending=True,
        )


@dataclass
class WebReplayContext:
    """Approved immutable Web package for trial/regression. Replay actor AI stays 0."""

    approved: ApprovedWebPackage
    bundle_source: dict[str, object]
    before: Observation
    after: Observation | None
    proof: IsolationProof
    now: datetime
    lease_remaining_seconds: float = 60.0
    mono_seconds: float = 100.0
    cancelled: bool = False
    runner: BrowserRunner | None = None


@dataclass
class WebReplayHandler:
    """Replay approved Web package through TrustedWebDriver. Actor AI 0."""

    adapter: CuawrightWebAdapter
    gate: WebIsolationGate
    guard: RemoteLeaseGuard
    journal: DispatchJournal
    spool: EvidenceSpool
    context: WebReplayContext
    dispatch_count: int = 0
    actor_ai_calls: int = 0
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

        origin = str(snapshot.get("origin") or "")
        if origin == "" or origin != self.context.approved.origin:
            return _fail_closed("origin_mismatch", evidence_complete=False)

        presented = str(snapshot.get("digest") or snapshot.get("approved_digest") or "")
        if presented != self.context.approved.digest:
            return _fail_closed("digest_changed", evidence_complete=False)

        revision = str(snapshot.get("revision") or "")
        if revision and revision != self.context.approved.revision:
            return _fail_closed("revision_changed", evidence_complete=False)

        if snapshot.get("channel") == "cdp" or snapshot.get("direct_cdp") is True:
            return _fail_closed("direct_cdp_refused", evidence_complete=False)

        if not require_web_ready(self.gate.web_ready(self.context.proof, now=self.context.now)):
            return _fail_closed("proof_unverified", evidence_complete=False)

        attempt_id = str(claim.get("attempt_id") or "")
        if attempt_id == "":
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

        action_id = str(snapshot.get("action_id") or f"web-replay-{attempt_id}")
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

        try:
            bundle = self.adapter.extract_trajectory(self.context.bundle_source)
            live = str(snapshot.get("live_source") or bundle.reviewable_source)
            self.adapter.assert_replay_source_unchanged(bundle, live)
            results = self.adapter.run_allowlisted_steps(
                bundle,
                approved=self.context.approved,
                gate=self.gate,
                proof=self.context.proof,
                before=self.context.before,
                after=after,
                spool=self.spool.root,
                now=self.context.now,
                presented_digest=presented,
                presented_revision=revision or self.context.approved.revision,
                page_origin=origin,
                runner=self.context.runner,
            )
        except CuawrightRejected as exc:
            self.journal.mark_started_only_unknown(attempt_id, action_id)
            self.original_failure = str(exc.reason)
            return _fail_closed("replay_rejected", evidence_complete=False, ambiguous=True)

        self.dispatch_count += len(results)
        self.actor_ai_calls = sum(item.ai_calls for item in results)
        self.package_digest_after = self.context.approved.digest
        if self.actor_ai_calls != 0:
            return _fail_closed("actor_ai_forbidden", evidence_complete=False)

        try:
            self.journal.append(attempt_id, action_id, "acknowledged")
            self.journal.append(attempt_id, action_id, "observed")
        except JournalWriteError:
            return _fail_closed("journal_observe_failed", evidence_complete=False, ambiguous=True)

        events = web_evidence_events(
            attempt_id=attempt_id,
            before=self.context.before,
            after=after,
            action_id=action_id,
        )
        hashes = tuple(str(event["payload_hash"]) for event in events)
        return HandlerResult(
            actions=len(results),
            outcome="completed",
            evidence_complete=True,
            ambiguous_dispatch=False,
            final_seq=len(events),
            last_ack_seq=0,
            last_ack_hash="",
            evidence_events=events,
            source_artifact_hashes=hashes,
        )


def register_web_handlers(
    *,
    recording: WebRecordingHandler | None = None,
    replay: WebReplayHandler | None = None,
    other: dict[str, JobHandler] | None = None,
) -> PurposeRoutedHandler:
    """Attach Web recording and/or trial/regression handlers for prepared adapters."""

    routes: dict[str, JobHandler] = {}
    if recording is not None:
        routes["recording"] = recording
    if replay is not None:
        routes["trial"] = replay
        routes["regression"] = replay
    if other:
        routes.update(other)
    return PurposeRoutedHandler(routes, default=InertHandler())


def assemble_web_worker_handlers(
    *,
    recording: WebRecordingHandler | None = None,
    replay: WebReplayHandler | None = None,
    other: dict[str, JobHandler] | None = None,
) -> PurposeRoutedHandler:
    """Register prepared Web handlers for the worker process entry."""

    return register_web_handlers(recording=recording, replay=replay, other=other)


def _attempt_uuid(attempt_id: str) -> UUID:
    try:
        return UUID(attempt_id)
    except ValueError:
        return uuid4()


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
