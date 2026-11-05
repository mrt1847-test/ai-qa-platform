"""Web recording/replay job handlers for the independent worker runtime.

Importing this module does not open a browser, CDP, or a real VM.
"""

from __future__ import annotations

import binascii
import struct
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import UUID, uuid4

from aiqa.adapters.cuawright_web import (
    CuawrightRejected,
    CuawrightWebAdapter,
    WebContractPackage,
    build_web_contract_package,
    load_web_contract_package,
    make_recording_manifest,
    persist_web_contract_package,
)
from aiqa.contracts.actions import CaptureGeometry, Observation
from aiqa.contracts.evidence import EvidenceEnvelope
from aiqa.replay.driver import ApprovedWebPackage
from aiqa.worker.android_jobs import (
    ClaimReplayPin,
    PurposeRoutedHandler,
    android_evidence_artifacts,
    android_evidence_events,
    resolve_claim_replay_pin,
)
from aiqa.worker.control import RemoteLeaseGuard
from aiqa.worker.dispatch_journal import DispatchJournal, JournalWriteError
from aiqa.worker.isolated_web import (
    admit_recording_channel,
    bind_web_vm_transport,
    require_web_ready,
)
from aiqa.worker.runner import MonotonicInstant
from aiqa.worker.runtime import HandlerResult, InertHandler, JobHandler
from aiqa.worker.spool import EvidenceSpool
from aiqa.worker.web_isolation_backend import (
    IsolationConfig,
    IsolationProof,
    IsolationRejected,
    WebIsolationGate,
    fixture_backend,
)
from aiqa.worker.web_vm_transport import (
    GuestIpcLimits,
    LocalGuestProcess,
    WebGuestEntryBinding,
    WebVmTransport,
    spawn_local_guest_process,
)

_DEFAULT_PROOF_SECRET = b"fixture-web-proof-secret!!"
_DEFAULT_FIXTURE_TRAJECTORY: dict[str, object] = {
    "complete": True,
    "steps": [
        {
            "hook": "hook.web.code_output.step_script",
            "code": "qa_runtime.click('#go')",
            "summary": {"type": "click", "selector": "#go"},
        }
    ],
}

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


def resolve_web_claim_replay_pin(snapshot: dict[str, Any]) -> ClaimReplayPin:
    """Prefer claim-fixed Web package references over handler context defaults."""

    return resolve_claim_replay_pin(snapshot)


def trajectory_from_claim_intent(
    snapshot: dict[str, Any],
    fallback: dict[str, object],
) -> dict[str, object]:
    """Prefer server-frozen intent steps when the claim carries a recording intent."""

    intent = snapshot.get("intent")
    if type(intent) is not dict:
        return fallback
    steps = intent.get("steps")
    if type(steps) is not list or not steps:
        return fallback
    converted: list[dict[str, object]] = []
    for item in steps:
        if type(item) is not dict:
            continue
        if "hook" in item and "code" in item:
            converted.append(dict(item))
            continue
        # Intent steps may be structured objectives; keep fallback when unusable.
        return fallback
    if not converted:
        return fallback
    return {"complete": True, "steps": converted}


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
    package_root: Path | None = None
    package_id: str | None = None
    revision: str = "lock-1"


@dataclass
class WebRecordingHandler:
    """Claim snapshot → ready/lease/journal → CUAWright extract + guest IPC recording steps."""

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
    persisted_packages: list[WebContractPackage] = field(default_factory=list)

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

        trajectory = trajectory_from_claim_intent(snapshot, self.context.trajectory)
        try:
            bundle = self.adapter.extract_trajectory(trajectory)
        except CuawrightRejected:
            self.journal.mark_started_only_unknown(attempt_id, action_id)
            return _fail_closed("trajectory_rejected", evidence_complete=False, ambiguous=True)

        self.raw_sources_held = len(bundle.raw_sources)
        if not bundle.package_ready:
            return _fail_closed("package_not_ready", evidence_complete=False)

        for summary in bundle.summaries:
            body: dict[str, object] = {"type": summary.action_type, "selector": summary.selector}
            if summary.value:
                body["value"] = summary.value
            try:
                self.transport.dispatch_ipc({"kind": "ipc", "payload": body}, now=self.context.now)
            except IsolationRejected:
                self.journal.mark_started_only_unknown(attempt_id, action_id)
                return _fail_closed("ipc_rejected", evidence_complete=False, ambiguous=True)
            self.authoring_dispatches += 1

        revision = str(snapshot.get("revision") or self.context.revision or "lock-1")
        attempt_uuid = _attempt_uuid(attempt_id)
        before_receipt = self.spool.append(
            EvidenceEnvelope(attempt_uuid, 1, self.context.before.png, "before", self.context.before.captured_at)
        )
        after_receipt = self.spool.append(
            EvidenceEnvelope(attempt_uuid, 2, after.png, "after", after.captured_at)
        )
        draft = self.adapter.build_approval_package(
            bundle,
            origin=self.context.approved_origin,
            revision=revision,
            manifest=make_recording_manifest(raw_source=bundle.reviewable_source),
            lock_hash=revision,
            evidence_before=(before_receipt.payload_hash,),
            evidence_after=(after_receipt.payload_hash,),
        )
        self.approval_digests.append(draft.digest)

        package = build_web_contract_package(
            self.adapter,
            trajectory,
            origin=self.context.approved_origin,
            revision=revision,
            evidence_before=(before_receipt.payload_hash,),
            evidence_after=(after_receipt.payload_hash,),
            package_id=self.context.package_id or str(uuid4()),
        )
        # Keep digest identical to the approval draft used for claim pins.
        package = WebContractPackage(
            package_id=package.package_id,
            digest=draft.digest,
            revision=draft.revision,
            origin=draft.origin,
            trajectory=trajectory,
            step_code_digests=package.step_code_digests,
            evidence_before=draft.evidence_before,
            evidence_after=draft.evidence_after,
            reviewable_source=bundle.reviewable_source,
        )
        if self.context.package_root is not None:
            persist_web_contract_package(self.context.package_root, package)
        self.persisted_packages.append(package)

        try:
            self.journal.append(attempt_id, action_id, "acknowledged")
            self.journal.append(attempt_id, action_id, "observed")
        except JournalWriteError:
            return _fail_closed("journal_observe_failed", evidence_complete=False, ambiguous=True)

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
                "package_id": package.package_id,
                "step_code_digests": list(package.step_code_digests),
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
        source_hashes = (
            *package.step_code_digests,
            before_receipt.payload_hash,
            after_receipt.payload_hash,
        )
        return HandlerResult(
            actions=self.authoring_dispatches,
            outcome="completed",
            evidence_complete=True,
            ambiguous_dispatch=False,
            final_seq=len(events),
            last_ack_seq=0,
            last_ack_hash="",
            evidence_events=events,
            evidence_artifacts=artifacts,
            source_artifact_hashes=source_hashes,
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
    healing_enabled: bool = False
    heal_budget_remaining: int = 0
    checks: tuple[object, ...] = ()
    verify_broker: object | None = None
    verify_transport: object | None = None
    verify_control: object | None = None
    healable_check_id: str | None = None
    approved_failure_reason: str | None = None
    healing_context: object | None = None
    heal_observation: Observation | None = None
    worker_model_call: object | None = None
    package_root: Path | None = None


@dataclass
class WebReplayHandler:
    """Replay approved Web package through TrustedWebDriver. Actor AI 0; shared verify/heal port."""

    adapter: CuawrightWebAdapter
    gate: WebIsolationGate
    guard: RemoteLeaseGuard
    journal: DispatchJournal
    spool: EvidenceSpool
    context: WebReplayContext
    dispatch_count: int = 0
    actor_ai_calls: int = 0
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

        pin = resolve_web_claim_replay_pin(snapshot)
        approved = self.context.approved
        bundle_source = self.context.bundle_source
        if pin.package_id is not None and self.context.package_root is not None:
            try:
                loaded = load_web_contract_package(self.context.package_root, pin.package_id)
            except CuawrightRejected:
                return _fail_closed("package_missing", evidence_complete=False)
            if pin.package_hash is not None and loaded.digest != pin.package_hash:
                return _fail_closed("digest_changed", evidence_complete=False)
            approved = ApprovedWebPackage(loaded.digest, loaded.revision, loaded.origin)
            bundle_source = loaded.trajectory
        elif pin.package_hash is not None:
            approved = ApprovedWebPackage(pin.package_hash, approved.revision, approved.origin)

        healing_enabled = self.context.healing_enabled
        if pin.healing_enabled is not None:
            healing_enabled = pin.healing_enabled

        origin = str(snapshot.get("origin") or "")
        if origin == "" or origin != approved.origin:
            return _fail_closed("origin_mismatch", evidence_complete=False)

        presented = str(
            pin.package_hash
            or snapshot.get("digest")
            or snapshot.get("approved_digest")
            or ""
        )
        if presented != approved.digest:
            return _fail_closed("digest_changed", evidence_complete=False)

        revision = str(snapshot.get("revision") or "")
        if revision and revision != approved.revision:
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
            bundle = self.adapter.extract_trajectory(bundle_source)
            live = str(snapshot.get("live_source") or bundle.reviewable_source)
            self.adapter.assert_replay_source_unchanged(bundle, live)
            results = self.adapter.run_allowlisted_steps(
                bundle,
                approved=approved,
                gate=self.gate,
                proof=self.context.proof,
                before=self.context.before,
                after=after,
                spool=self.spool.root,
                now=self.context.now,
                presented_digest=presented,
                presented_revision=revision or approved.revision,
                page_origin=origin,
                runner=self.context.runner,
            )
        except CuawrightRejected as exc:
            self.journal.mark_started_only_unknown(attempt_id, action_id)
            self.original_failure = str(exc.reason)
            return _fail_closed("replay_rejected", evidence_complete=False, ambiguous=True)

        self.dispatch_count += len(results)
        self.actor_ai_calls = sum(item.ai_calls for item in results)
        self.package_digest_after = approved.digest
        if self.actor_ai_calls != 0:
            return _fail_closed("actor_ai_forbidden", evidence_complete=False)

        try:
            self.journal.append(attempt_id, action_id, "acknowledged")
            self.journal.append(attempt_id, action_id, "observed")
        except JournalWriteError:
            return _fail_closed("journal_observe_failed", evidence_complete=False, ambiguous=True)

        if purpose == "trial":
            healing_enabled = False
        verify_ok = True
        if self.context.checks:
            verify = self._verify_and_heal(after, healing_enabled=healing_enabled)
            self.package_digest_after = str(verify.record.package_digest_after)
            self.healer_calls = int(verify.record.healer_calls)
            self.verifier_calls = int(verify.record.verifier_calls)
            if verify.record.original_failure:
                self.original_failure = str(verify.record.original_failure)
            verify_ok = bool(verify.success)

        events = web_evidence_events(
            attempt_id=attempt_id,
            before=self.context.before,
            after=after,
            action_id=action_id,
        )
        hashes = tuple(str(event["payload_hash"]) for event in events)
        if not verify_ok:
            return HandlerResult(
                actions=len(results),
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

    def _verify_and_heal(self, observation: Observation, *, healing_enabled: bool) -> object:
        from aiqa.worker.runner import verify_and_heal_after_replay

        broker = self.context.verify_broker
        if broker is None:
            raise ValueError("verify broker is required when checks are set")
        return verify_and_heal_after_replay(
            checks=self.context.checks,
            observation=observation,
            control=self.context.verify_control or _AllowVerify(),
            broker=broker,
            transport=self.context.verify_transport or _NoTransport(),
            healing_enabled=healing_enabled,
            heal_budget_remaining=self.context.heal_budget_remaining,
            approved_failure_reason=self.context.approved_failure_reason,
            healable_check_id=self.context.healable_check_id,
            approved_package_digest=self.context.approved.digest,
            healing_context=self.context.healing_context,
            heal_observation=self.context.heal_observation
            if self.context.heal_observation is not None
            else observation,
            worker_model_call=self.context.worker_model_call,
        )


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


@dataclass
class AssembledWebWorker:
    """Worker-entry Web stack: handlers stay inert until proof and origin gates pass."""

    handler: PurposeRoutedHandler
    gate: WebIsolationGate
    transport: WebVmTransport
    proof: IsolationProof
    approved_origin: str
    endpoint_id: str
    guest: LocalGuestProcess | None = None
    recording: WebRecordingHandler | None = None
    replay: WebReplayHandler | None = None

    def close(self) -> None:
        close = getattr(self.transport, "close", None)
        if close is not None:
            close()
        if self.guest is not None:
            self.guest.terminate()


def fixture_web_observation(*, platform: str = "web") -> Observation:
    """Minimal capture used when assembling fixture Web handlers without a live page."""

    return Observation(
        str(uuid4()),
        datetime.now(timezone.utc).isoformat(),
        CaptureGeometry(24, 48, 24, 48, "identity", 0, (0, 0, 24, 48)),
        _fixture_png(),
        "<button id='go'>Go</button>",
        "",
        (),
        "",
        True,
        platform,
    )


def build_fixture_web_gate(
    *,
    approved_origin: str,
    proof_secret: bytes | None = None,
) -> WebIsolationGate:
    """Fixture isolation gate bound to the dedicated approved origin from execution settings."""

    secret = proof_secret if proof_secret is not None else _DEFAULT_PROOF_SECRET
    if len(secret) < 16:
        raise ValueError("web proof secret must be at least 16 bytes")
    if type(approved_origin) is not str or not approved_origin.startswith("https://"):
        raise ValueError("approved origin must be https")
    return WebIsolationGate(
        IsolationConfig(
            backend=fixture_backend(allowed_origins=(approved_origin,)),
            proof_secret=secret,
        )
    )


def assemble_web_worker_from_entry_binding(
    binding: WebGuestEntryBinding,
    *,
    runtime_root: Path,
    proof_secret: bytes | None = None,
    now: datetime | None = None,
    spawn_guest: bool = True,
    connect_deadline_seconds: float = 2.0,
    request_deadline_seconds: float = 2.0,
    approved_digest: str = "",
    approved_revision: str = "lock-1",
    trajectory: dict[str, object] | None = None,
    proof: IsolationProof | None = None,
    before: Observation | None = None,
    after: Observation | None = None,
) -> AssembledWebWorker:
    """Read approved guest endpoint + origin and assemble recording/replay handlers.

    Guest IPC stays fail-closed until a verified proof admits web_ready. Real VM
    security acceptance remains RX-22.
    """

    instant = now if now is not None else datetime.now(timezone.utc)
    gate = build_fixture_web_gate(
        approved_origin=binding.approved_origin,
        proof_secret=proof_secret,
    )
    issued = proof if proof is not None else gate.issue_proof(now=instant)
    guest: LocalGuestProcess | None = None
    bindings: tuple[object, ...] = ()
    if spawn_guest:
        guest = spawn_local_guest_process(
            endpoint_id=binding.endpoint_id,
            peer_token=binding.peer_token,
        )
        bindings = (guest.binding,)
    transport = bind_web_vm_transport(
        gate,
        approved_endpoints=(binding.endpoint_id,),
        limits=GuestIpcLimits(
            connect_deadline_seconds=connect_deadline_seconds,
            request_deadline_seconds=request_deadline_seconds,
        ),
        bindings=bindings,
    )
    assert isinstance(transport, WebVmTransport)

    spool = EvidenceSpool(runtime_root / "spool")
    journal = DispatchJournal(runtime_root / "journal.jsonl")
    adapter = CuawrightWebAdapter()
    obs_before = before if before is not None else fixture_web_observation()
    obs_after = after if after is not None else fixture_web_observation()
    traj = trajectory if trajectory is not None else dict(_DEFAULT_FIXTURE_TRAJECTORY)

    recording = WebRecordingHandler(
        adapter=adapter,
        transport=transport,
        gate=gate,
        guard=RemoteLeaseGuard(),
        journal=journal,
        spool=spool,
        context=WebRecordingContext(
            approved_origin=binding.approved_origin,
            trajectory=traj,
            before=obs_before,
            after=obs_after,
            proof=issued,
            now=instant,
            guest_process=guest,
            endpoint_id=binding.endpoint_id,
        ),
    )

    digest = approved_digest.strip()
    if digest == "":
        try:
            bundle = adapter.extract_trajectory(traj)
            draft = adapter.build_approval_package(
                bundle,
                origin=binding.approved_origin,
                revision=approved_revision,
                manifest=make_recording_manifest(raw_source=bundle.reviewable_source),
                lock_hash=approved_revision,
            )
            digest = draft.digest
        except CuawrightRejected:
            digest = "sha256:" + ("0" * 64)

    replay = WebReplayHandler(
        adapter=adapter,
        gate=gate,
        guard=RemoteLeaseGuard(),
        journal=DispatchJournal(runtime_root / "journal-replay.jsonl"),
        spool=EvidenceSpool(runtime_root / "spool-replay"),
        context=WebReplayContext(
            approved=ApprovedWebPackage(
                digest=digest,
                revision=approved_revision,
                origin=binding.approved_origin,
            ),
            bundle_source=traj,
            before=obs_before,
            after=obs_after,
            proof=issued,
            now=instant,
        ),
    )
    handler = assemble_web_worker_handlers(recording=recording, replay=replay)
    return AssembledWebWorker(
        handler=handler,
        gate=gate,
        transport=transport,
        proof=issued,
        approved_origin=binding.approved_origin,
        endpoint_id=binding.endpoint_id,
        guest=guest,
        recording=recording,
        replay=replay,
    )


def _fixture_png(width: int = 24, height: int = 48) -> bytes:
    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body))
            + kind
            + body
            + struct.pack(">I", binascii.crc32(kind + body) & 0xFFFFFFFF)
        )

    row = b"\x00" + b"\x00" * width * 3
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(row * height))
        + chunk(b"IEND", b"")
    )


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
