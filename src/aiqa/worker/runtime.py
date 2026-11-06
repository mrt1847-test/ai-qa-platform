"""Independent worker consume loop. Opens management HTTP only — never the server DB."""

from __future__ import annotations

import hashlib
import os
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from aiqa.config import load_worker_client_settings
from aiqa.worker.control import RemoteLeaseGuard
from aiqa.worker.http_client import RetryClass, WorkerHttpClient, WorkerHttpError
from aiqa.worker.runner import MonotonicInstant, verify_job_snapshot


def _empty_ack_hash() -> str:
    return "sha256:" + hashlib.sha256(b"").hexdigest()


@dataclass(frozen=True, slots=True)
class HandlerResult:
    """One attempt outcome. Device adapters may raise; inert stays at zero actions."""

    actions: int
    outcome: str
    evidence_complete: bool
    ambiguous_dispatch: bool
    final_seq: int = 0
    last_ack_seq: int = 0
    last_ack_hash: str = field(default_factory=_empty_ack_hash)
    evidence_events: tuple[dict[str, Any], ...] = ()
    evidence_artifacts: tuple[dict[str, Any], ...] = ()
    source_artifact_hashes: tuple[str, ...] = ()
    review_pending: bool = False
    action_mapping: str = "{}"
    cleanup_proof_refs: tuple[str, ...] = ()


# Default proof after a local handler returned and the finish receipt exists. Real device
# cleanup proof (for example ADB state) is supplied by handlers through cleanup_proof_refs.
_DEFAULT_CLEANUP_PROOF = "runtime:attempt-closed"


class JobHandler(Protocol):
    def handle(self, claim: dict[str, Any]) -> HandlerResult:
        """Run one claimed snapshot. Must not open the management SQLite."""


class InertHandler:
    """Verification handler: claim/ACK/finish only, zero target actions."""

    def handle(self, claim: dict[str, Any]) -> HandlerResult:
        return HandlerResult(
            actions=0,
            outcome="completed",
            evidence_complete=True,
            ambiguous_dispatch=False,
            final_seq=0,
            last_ack_seq=0,
            last_ack_hash=_empty_ack_hash(),
            cleanup_proof_refs=("runtime:inert",),
        )


@dataclass(frozen=True, slots=True)
class WorkerRuntimeConfig:
    boot_id: str
    prepared_adapters: frozenset[str]
    poll_seconds: float = 2.0
    max_cycles: int | None = None
    automatic_resume: bool = False

    def __post_init__(self) -> None:
        if type(self.boot_id) is not str or self.boot_id.strip() == "":
            raise ValueError("boot_id is required")
        if self.automatic_resume:
            raise ValueError("automatic resume of past jobs is forbidden")
        if self.poll_seconds <= 0:
            raise ValueError("poll_seconds must be positive")


@dataclass(frozen=True, slots=True)
class CycleReport:
    state: str
    claimed: bool
    actions: int
    finished: bool
    reason: str


class WorkerRuntime:
    """heartbeat → inventory → claim → snapshot → ACK → handler → finish. No DB path."""

    def __init__(
        self,
        client: WorkerHttpClient,
        config: WorkerRuntimeConfig,
        handler: JobHandler,
        *,
        inventory_provider: Callable[[], dict[str, Any] | None] | None = None,
        registered_serial: str | None = None,
        approved_web_origin: str | None = None,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] | None = None,
        mono: Callable[[], float] | None = None,
    ) -> None:
        self._client = client
        self._config = config
        self._handler = handler
        self._registered_serial = None if registered_serial is None else str(registered_serial).strip()
        self._registered_physical_key_id: str | None = None
        origin = None if approved_web_origin is None else str(approved_web_origin).strip()
        self._approved_web_origin = origin if origin and origin.startswith("https://") else None
        self._inventory_provider = inventory_provider
        self._sleep = sleep
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._mono = mono or time.monotonic
        self._stopping = False
        self._guard = RemoteLeaseGuard()
        self._cycles = 0
        self._total_actions = 0
        self._claims = 0
        self._finished = 0
        self._resumed_past = 0
        self._state = "idle"
        self._last_reason = "idle"
        # Restart contract: no durable claimed-job journal.
        self._active_attempt: str | None = None
        self._pending_finish: dict[str, Any] | None = None
        self._pending_cleanup: dict[str, Any] | None = None

    @property
    def state(self) -> str:
        return self._state

    @property
    def pending_finish(self) -> dict[str, Any] | None:
        return self._pending_finish

    @property
    def pending_cleanup(self) -> dict[str, Any] | None:
        return self._pending_cleanup

    @property
    def total_actions(self) -> int:
        return self._total_actions

    @property
    def claims(self) -> int:
        return self._claims

    @property
    def finished(self) -> int:
        return self._finished

    @property
    def resumed_past_jobs(self) -> int:
        return self._resumed_past

    def request_stop(self) -> None:
        """Stop after the current cycle. New claims are not started."""

        self._stopping = True
        self._state = "stopping"

    def run(self) -> str:
        while True:
            if self._config.max_cycles is not None and self._cycles >= self._config.max_cycles:
                self._state = "stopped"
                self._last_reason = "max_cycles"
                return self._last_reason
            if self._stopping and self._active_attempt is None:
                self._state = "stopped"
                self._last_reason = "stopped"
                return self._last_reason
            report = self.run_once()
            self._cycles += 1
            if report.state in {"offline", "unregistered"} and self._stopping:
                self._state = "stopped"
                return report.reason
            if self._config.max_cycles is None and not self._stopping:
                self._sleep(self._config.poll_seconds)
            elif self._stopping and self._active_attempt is None:
                self._state = "stopped"
                return "stopped"

    def run_once(self) -> CycleReport:
        if self._stopping and self._active_attempt is None:
            self._state = "stopped"
            return CycleReport("stopped", False, 0, False, "stopped")

        try:
            self._client.heartbeat(self._config.boot_id)
            self._guard.note_heartbeat(MonotonicInstant(self._mono()))
        except WorkerHttpError as exc:
            if exc.retry_class is RetryClass.auth:
                self._state = "unregistered"
                self._last_reason = "unregistered"
                return CycleReport("unregistered", False, 0, False, "unregistered")
            self._state = "offline"
            self._last_reason = "offline"
            return CycleReport("offline", False, 0, False, "offline")

        if self._inventory_provider is not None:
            payload = self._inventory_provider()
            if payload is not None:
                if not self._config.prepared_adapters and payload.get("state") == "ready":
                    payload = {**payload, "state": "offline"}
                try:
                    inventory = self._client.report_inventory(
                        payload,
                        idempotency_key=f"inv-{self._config.boot_id}-{self._cycles}",
                    )
                    key = inventory.get("physical_key_id")
                    if type(key) is str and key.strip() != "":
                        self._registered_physical_key_id = key.strip()
                    native = payload.get("native_id")
                    if self._registered_serial in {None, ""} and type(native) is str and native.strip() != "":
                        self._registered_serial = native.strip()
                except WorkerHttpError as exc:
                    if exc.retry_class is RetryClass.auth:
                        self._state = "unregistered"
                        return CycleReport("unregistered", False, 0, False, "unregistered")
                    self._state = "offline"
                    return CycleReport("offline", False, 0, False, "offline")

        if self._stopping:
            self._state = "stopped"
            return CycleReport("stopped", False, 0, False, "claim_blocked")

        if not self._config.prepared_adapters:
            self._state = "idle"
            self._last_reason = "no_execution_handler"
            return CycleReport("idle", False, 0, False, self._last_reason)

        if self._pending_cleanup is not None:
            # A lost cleanup response keeps the lease; retry the same key/body before claiming more.
            self.confirm_pending_cleanup()

        claim_key = f"claim-{self._config.boot_id}-{uuid.uuid4()}"
        try:
            claimed = self._client.claim(
                boot_id=self._config.boot_id,
                now=self._now().isoformat(),
                idempotency_key=claim_key,
            )
        except WorkerHttpError as exc:
            if exc.retry_class is RetryClass.auth:
                self._state = "unregistered"
                return CycleReport("unregistered", False, 0, False, "unregistered")
            self._state = "offline"
            return CycleReport("offline", False, 0, False, "offline")

        if claimed is None:
            self._state = "idle"
            self._last_reason = "empty"
            return CycleReport("idle", False, 0, False, "empty")

        self._claims += 1
        snapshot = claimed.get("snapshot")
        if type(snapshot) is not dict:
            self._state = "error"
            return CycleReport("error", True, 0, False, "snapshot_missing")

        checked = verify_job_snapshot(snapshot, self._config.prepared_adapters)
        if not checked.supported:
            # Unsupported target: zero device actions; seal as error without adapter dispatch.
            self._finish_without_dispatch(claimed, outcome="error", reason=checked.reason)
            self._state = "unsupported"
            return CycleReport("unsupported", True, 0, True, checked.reason)

        self._active_attempt = str(claimed["attempt_id"])
        try:
            self._client.acknowledge(
                project_id=str(claimed["project_id"]),
                job_id=str(claimed["job_id"]),
                generation=int(claimed["generation"]),
                runner_nonce=str(uuid.uuid4()),
                now=self._now().isoformat(),
                idempotency_key=f"ack-{claimed['attempt_id']}",
            )
        except WorkerHttpError:
            self._active_attempt = None
            self._state = "offline"
            return CycleReport("offline", True, 0, False, "ack_failed")

        bound = self._bind_claim_targets(claimed)
        self._bind_step_evidence_commit(bound)
        result = self._handler.handle(bound)
        try:
            result = self._commit_evidence(bound, result)
        except WorkerHttpError:
            self._active_attempt = None
            self._state = "offline"
            return CycleReport("offline", True, int(result.actions), False, "evidence_commit_failed")
        self._total_actions += int(result.actions)
        receipt = self._submit_finish(bound, result)
        self._active_attempt = None
        if receipt is None:
            self._state = "finish_pending"
            self._last_reason = "finish_receipt_missing"
            return CycleReport("finish_pending", True, int(result.actions), False, "finish_receipt_missing")
        self._finished += 1
        cleanup = self._submit_cleanup(bound, result)
        if cleanup is None:
            # The attempt is sealed; only the lease release is outstanding.
            self._state = "cleanup_pending"
            self._last_reason = "cleanup_pending"
            return CycleReport("cleanup_pending", True, int(result.actions), True, "cleanup_pending")
        self._state = "running"
        self._last_reason = "finished"
        return CycleReport("running", True, int(result.actions), True, "finished")

    def note_restart(self) -> None:
        """Clear in-memory attempt. Past jobs are never auto-resumed."""

        self._active_attempt = None
        self._pending_finish = None
        self._pending_cleanup = None
        self._resumed_past = 0
        self._state = "restarted"

    def confirm_pending_finish(self) -> dict[str, Any] | None:
        """Confirm a lost finish with the same idempotency key and body. No new dispatch."""

        pending = self._pending_finish
        if pending is None:
            return None
        try:
            receipt = self._client.confirm_finish_attempt(
                payload=pending["payload"],
                idempotency_key=str(pending["idempotency_key"]),
            )
        except WorkerHttpError:
            return None
        self._pending_finish = None
        self._finished += 1
        self._state = "running"
        self._last_reason = "finish_confirmed"
        # The attempt is sealed; release its lease too so the resource is reusable.
        if self._pending_cleanup is not None:
            self.confirm_pending_cleanup()
        else:
            body = pending["payload"]
            self._send_cleanup(
                self._cleanup_payload(
                    body,
                    physical_key_id=body.get("physical_key_id"),
                    proofs=(_DEFAULT_CLEANUP_PROOF,),
                )
            )
        if self._pending_cleanup is not None:
            self._state = "cleanup_pending"
            self._last_reason = "cleanup_pending"
        return receipt

    def confirm_pending_cleanup(self) -> dict[str, Any] | None:
        """Re-post a lost cleanup with the same idempotency key and body. No new dispatch."""

        pending = self._pending_cleanup
        if pending is None:
            return None
        try:
            receipt = self._client.confirm_pending_cleanup(
                payload=pending["payload"],
                idempotency_key=str(pending["idempotency_key"]),
            )
        except WorkerHttpError:
            return None
        self._pending_cleanup = None
        if self._state == "cleanup_pending":
            self._state = "running"
            self._last_reason = "cleanup_confirmed"
        return receipt

    def _cleanup_payload(
        self,
        ids: Mapping[str, Any],
        *,
        physical_key_id: object,
        proofs: tuple[str, ...],
    ) -> dict[str, Any]:
        physical = None if physical_key_id in {None, ""} else str(physical_key_id)
        return {
            "project_id": ids["project_id"],
            "job_id": ids["job_id"],
            "attempt_id": ids["attempt_id"],
            "generation": ids["generation"],
            "physical_key_id": physical,
            "proof_refs": [str(item) for item in proofs],
            "now": self._now().isoformat(),
        }

    def _send_cleanup(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        key = f"cleanup-{payload['attempt_id']}"
        try:
            receipt = self._client.confirm_cleanup(
                project_id=payload["project_id"],
                job_id=payload["job_id"],
                attempt_id=payload["attempt_id"],
                generation=payload["generation"],
                physical_key_id=payload["physical_key_id"],
                proof_refs=list(payload["proof_refs"]),
                now=payload["now"],
                idempotency_key=key,
            )
        except WorkerHttpError:
            # Never invent a release. Keep the exact body for a same-key re-post.
            self._pending_cleanup = {"payload": payload, "idempotency_key": key}
            return None
        self._pending_cleanup = None
        return receipt

    def _submit_cleanup(self, claimed: dict[str, Any], result: HandlerResult) -> dict[str, Any] | None:
        """Confirm cleanup after the finish receipt so the lease frees for the next claim.

        Handlers may pass cleanup_proof_refs. When they do not, the runtime attests with
        `runtime:attempt-closed` because the local handler returned and the server sealed the
        attempt; sending an empty list would quarantine the resource. Real device proof is
        supplied by device handlers later. Quarantine is left to the server when cleanup never
        arrives or the handler reports an explicit failure.
        """

        proofs = tuple(item for item in result.cleanup_proof_refs if str(item).strip() != "")
        if proofs == ():
            proofs = (_DEFAULT_CLEANUP_PROOF,)
        # Same fence value as the finish body: the lease's physical key, never a guessed one.
        physical = claimed.get("physical_key_id")
        return self._send_cleanup(self._cleanup_payload(claimed, physical_key_id=physical, proofs=proofs))

    def _finish_without_dispatch(self, claimed: dict[str, Any], *, outcome: str, reason: str) -> None:
        try:
            self._client.acknowledge(
                project_id=str(claimed["project_id"]),
                job_id=str(claimed["job_id"]),
                generation=int(claimed["generation"]),
                runner_nonce=str(uuid.uuid4()),
                now=self._now().isoformat(),
                idempotency_key=f"ack-{claimed['attempt_id']}-skip",
            )
        except WorkerHttpError:
            return
        result = HandlerResult(
            actions=0,
            outcome=outcome,
            evidence_complete=True,
            ambiguous_dispatch=False,
        )
        receipt = self._submit_finish(claimed, result)
        if receipt is not None:
            self._finished += 1
            # No device was touched; release the lease so the resource is not held.
            self._submit_cleanup(
                claimed,
                replace(result, cleanup_proof_refs=("runtime:unsupported-skip",)),
            )

    def _bind_claim_targets(self, claimed: dict[str, Any]) -> dict[str, Any]:
        bound = claimed
        if self._registered_serial not in {None, ""}:
            from aiqa.worker.android_jobs import resolve_android_claim_target

            bound = resolve_android_claim_target(
                bound,
                registered_serial=str(self._registered_serial),
                registered_physical_key_id=self._registered_physical_key_id,
            )
        if self._approved_web_origin not in {None, ""}:
            from aiqa.worker.web_jobs import resolve_web_claim_origin

            bound = resolve_web_claim_origin(
                bound,
                approved_origin=str(self._approved_web_origin),
            )
        return bound

    def _bind_step_evidence_commit(self, claimed: dict[str, Any]) -> None:
        """Wire per-action evidence commit so the timeline updates before the attempt finishes."""

        from aiqa.worker.android_jobs import bind_step_evidence_commit

        attempt_id = str(claimed.get("attempt_id") or "")
        project_id = str(claimed.get("project_id") or "")
        job_id = str(claimed.get("job_id") or "")
        generation = int(claimed.get("generation") or 0)

        def commit_step(
            *,
            action_seq: int,
            action_id: str,
            events: list[dict[str, Any]],
            artifacts: list[dict[str, Any]],
        ) -> dict[str, Any]:
            del action_id  # identity is carried inside event/artifact payloads
            return self._client.commit_evidence(
                sanitized=True,
                project_id=project_id,
                job_id=job_id,
                generation=generation,
                now=self._now().isoformat(),
                events=events,
                artifacts=artifacts,
                idempotency_key=f"evidence-{attempt_id}-step-{int(action_seq)}",
            )

        bind_step_evidence_commit(self._handler, commit_step)

    def _commit_evidence(self, claimed: dict[str, Any], result: HandlerResult) -> HandlerResult:
        events = list(result.evidence_events)
        artifacts = list(result.evidence_artifacts)
        purpose = ""
        snapshot = claimed.get("snapshot")
        if type(snapshot) is dict:
            purpose = str(snapshot.get("purpose") or "")
        requires_files = (
            result.outcome == "completed"
            and result.evidence_complete
            and purpose == "recording"
        )
        if events == [] and artifacts == []:
            # Steps may already be ACK'd during the handler; trust the prefix.
            if requires_files and result.source_artifact_hashes == ():
                return replace(
                    result,
                    outcome="error",
                    evidence_complete=False,
                    source_artifact_hashes=(),
                )
            return result
        if requires_files and artifacts == []:
            return replace(
                result,
                outcome="error",
                evidence_complete=False,
                source_artifact_hashes=(),
            )
        ack = self._client.commit_evidence(
            sanitized=True,
            project_id=str(claimed["project_id"]),
            job_id=str(claimed["job_id"]),
            generation=int(claimed["generation"]),
            now=self._now().isoformat(),
            events=events,
            artifacts=artifacts,
            idempotency_key=f"evidence-{claimed['attempt_id']}",
        )
        ids = tuple(str(item) for item in (ack.get("artifact_ids") or []) if str(item).strip() != "")
        if requires_files and (ids == () or int(ack.get("artifact_count") or 0) < 1):
            return replace(
                result,
                outcome="error",
                evidence_complete=False,
                last_ack_seq=int(ack["contiguous_seq"]),
                last_ack_hash=str(ack["prefix_hash"]),
                source_artifact_hashes=(),
                final_seq=max(int(result.final_seq), int(ack["contiguous_seq"])),
            )
        hashes = ids if ids else result.source_artifact_hashes
        return replace(
            result,
            last_ack_seq=int(ack["contiguous_seq"]),
            last_ack_hash=str(ack["prefix_hash"]),
            source_artifact_hashes=hashes,
            final_seq=max(int(result.final_seq), int(ack["contiguous_seq"])),
        )

    def _submit_finish(self, claimed: dict[str, Any], result: HandlerResult) -> dict[str, Any] | None:
        payload = {
            "project_id": claimed["project_id"],
            "job_id": claimed["job_id"],
            "attempt_id": claimed["attempt_id"],
            "generation": claimed["generation"],
            "outcome": result.outcome,
            "final_seq": result.final_seq,
            "last_ack_seq": result.last_ack_seq,
            "last_ack_hash": result.last_ack_hash,
            "manifest_digest": claimed["snapshot"]["digest"],
            "evidence_complete": result.evidence_complete,
            "ambiguous_dispatch": result.ambiguous_dispatch,
            "physical_key_id": claimed.get("physical_key_id"),
            "now": self._now().isoformat(),
            "source_artifact_hashes": list(result.source_artifact_hashes),
            "action_mapping": result.action_mapping if result.action_mapping.strip() else "{}",
        }
        key = f"finish-{claimed['attempt_id']}"
        try:
            receipt = self._client.finish_attempt(payload=payload, idempotency_key=key)
        except WorkerHttpError:
            # Keep the exact body for later confirm; never mark complete without a receipt.
            self._pending_finish = {"payload": payload, "idempotency_key": key}
            return None
        self._pending_finish = None
        return receipt


@dataclass(frozen=True, slots=True)
class AndroidInventoryBinding:
    """Registered project and dedicated Android serial for worker inventory."""

    project_id: str
    serial: str
    adb_path: str
    expected_avd: str | None = None


def load_android_inventory_binding(env: Mapping[str, str] | None) -> AndroidInventoryBinding | None:
    """Read inventory wiring. Missing project/serial/adb means no ready inventory."""

    source: Mapping[str, str] = os.environ if env is None else env
    project_id = str(source.get("AIQA_WORKER_PROJECT_ID", "")).strip()
    serial = str(source.get("AIQA_ANDROID_SERIAL", "")).strip()
    adb_path = str(source.get("AIQA_ADB_PATH", "")).strip()
    if project_id == "" or serial == "" or adb_path == "":
        return None
    avd_raw = source.get("AIQA_ANDROID_AVD")
    expected_avd = None if avd_raw is None or str(avd_raw).strip() == "" else str(avd_raw).strip()
    return AndroidInventoryBinding(project_id, serial, adb_path, expected_avd)


def make_android_inventory_provider(
    binding: AndroidInventoryBinding,
    *,
    provider: object | None = None,
) -> Callable[[], dict[str, Any] | None]:
    """Connect AndroidObservationProvider to WorkerRuntime inventory after heartbeat."""

    from aiqa.environments.android_observation import AndroidObservationProvider
    from aiqa.worker.resources import assemble_android_inventory_payload

    obs = provider
    if obs is None:
        obs = AndroidObservationProvider(
            Path(binding.adb_path),
            binding.serial,
            expected_avd=binding.expected_avd,
        )

    def provide() -> dict[str, Any] | None:
        return assemble_android_inventory_payload(
            obs,  # type: ignore[arg-type]
            project_id=binding.project_id,
            expected_serial=binding.serial,
        )

    return provide


def recording_prepared_adapters() -> frozenset[str]:
    """Adapters that may be claimed after Android inventory/recording wiring (RX-32/33)."""

    return frozenset({"resource_probe", "recording", "structure", "app_install"})


def replay_prepared_adapters() -> frozenset[str]:
    """Adapters for Android recording plus approved trial/regression replay (RX-34)."""

    return frozenset({"resource_probe", "recording", "trial", "regression", "structure", "app_install"})


def web_prepared_adapters() -> frozenset[str]:
    """Adapters for Web recording and approved trial/regression replay (RX-36)."""

    return frozenset({"resource_probe", "recording", "trial", "regression", "structure"})


def structure_prepared_adapters() -> frozenset[str]:
    """Management adapter for NL structure jobs completed without device actions."""

    return frozenset({"structure"})


def android_worker_prepared_adapters() -> frozenset[str]:
    """Prepared Android entry adapters: recording plus approved trial/regression."""

    return replay_prepared_adapters()


def web_worker_prepared_adapters() -> frozenset[str]:
    """Prepared Web entry adapters: recording plus approved trial/regression."""

    return web_prepared_adapters()


def run_worker_process(
    env: dict[str, str] | None = None,
    *,
    handler: JobHandler | None = None,
    prepared_adapters: frozenset[str] | None = None,
    inventory_provider: Callable[[], dict[str, Any] | None] | None = None,
    max_cycles: int | None = None,
) -> int:
    """Process entry used by `python -m aiqa.launcher worker`. No server DB."""

    settings = load_worker_client_settings(env)
    source = os.environ if env is None else env
    boot_id = source.get("AIQA_WORKER_BOOT_ID") or str(uuid.uuid4())
    binding = load_android_inventory_binding(env)
    from aiqa.worker.web_vm_transport import load_web_guest_entry_binding

    web_binding = load_web_guest_entry_binding(source)
    resolved_handler = handler
    model_mode = str(source.get("AIQA_WORKER_MODEL_MODE", "")).strip().lower()
    approved_digest = str(source.get("AIQA_WORKER_APPROVED_DIGEST", "")).strip()
    approved_plan = str(source.get("AIQA_WORKER_APPROVED_PLAN", "")).strip()
    cycles = max_cycles
    if cycles is None:
        raw_cycles = str(source.get("AIQA_WORKER_MAX_CYCLES", "")).strip()
        if raw_cycles.isdigit():
            cycles = int(raw_cycles)
    provider = inventory_provider
    if provider is None and binding is not None:
        provider = make_android_inventory_provider(binding)
    assembled_web = None
    with WorkerHttpClient(settings) as client:
        try:
            if resolved_handler is None and binding is not None and model_mode in {"fixture", "operational"}:
                from aiqa.worker.android_jobs import (
                    assemble_android_worker_handlers,
                    build_approved_android_replay_handler,
                    build_fixture_android_recording_handler,
                    build_operational_android_recording_handler,
                )

                runtime_root = Path(
                    str(source.get("AIQA_WORKER_RUNTIME_ROOT") or Path.cwd() / "worker-runtime")
                )
                runtime_root.mkdir(parents=True, exist_ok=True)
                if model_mode == "fixture":
                    fixture_response = str(
                        source.get("AIQA_WORKER_FIXTURE_RESPONSE")
                        or "swipe(360, 1200, 360, 400, 300)"
                    ).strip()
                    recording = build_fixture_android_recording_handler(
                        adb_path=Path(binding.adb_path),
                        serial=binding.serial,
                        expected_avd=binding.expected_avd,
                        runtime_root=runtime_root,
                        fixture_response=fixture_response,
                    )
                else:
                    recording = build_operational_android_recording_handler(
                        adb_path=Path(binding.adb_path),
                        serial=binding.serial,
                        expected_avd=binding.expected_avd,
                        runtime_root=runtime_root,
                        client=client,
                    )
                # Claim carries package id/digest/plan. Env pins stay optional fallbacks only.
                replay = build_approved_android_replay_handler(
                    adb_path=Path(binding.adb_path),
                    serial=binding.serial,
                    expected_avd=binding.expected_avd,
                    runtime_root=runtime_root,
                    approved_digest=approved_digest,
                    approved_plan=approved_plan,
                )
                from aiqa.worker.android_jobs import (
                    build_android_support_handlers,
                    http_apk_provider,
                    http_app_build_fetcher,
                )

                # RX-75: real AdbInstallDriver by default; the APK is pinned and spooled locally.
                probe, install = build_android_support_handlers(
                    adb_path=Path(binding.adb_path),
                    serial=binding.serial,
                    build_fetcher=http_app_build_fetcher(client),
                    apk_provider=http_apk_provider(client, runtime_root / "apk-spool"),
                )
                resolved_handler = assemble_android_worker_handlers(
                    recording=recording,
                    replay=replay,
                    installed_apps=probe,
                    app_install=install,
                )
            elif (
                resolved_handler is None
                and binding is None
                and web_binding is not None
                and model_mode in {"", "fixture"}
            ):
                from aiqa.worker.web_jobs import assemble_web_worker_from_entry_binding

                runtime_root = Path(
                    str(source.get("AIQA_WORKER_RUNTIME_ROOT") or Path.cwd() / "worker-runtime")
                )
                runtime_root.mkdir(parents=True, exist_ok=True)
                secret_raw = str(source.get("AIQA_WEB_GUEST_PROOF_SECRET", "")).strip()
                proof_secret = (
                    secret_raw.encode("utf-8")
                    if len(secret_raw.encode("utf-8")) >= 16
                    else None
                )
                approved_revision = str(
                    source.get("AIQA_WORKER_APPROVED_REVISION", "lock-1")
                ).strip() or "lock-1"
                assembled_web = assemble_web_worker_from_entry_binding(
                    web_binding,
                    runtime_root=runtime_root,
                    proof_secret=proof_secret,
                    approved_digest=approved_digest,
                    approved_revision=approved_revision,
                )
                resolved_handler = assembled_web.handler
            adapters = frozenset()
            if resolved_handler is not None:
                if prepared_adapters is not None:
                    default = prepared_adapters
                elif binding is not None:
                    default = android_worker_prepared_adapters()
                elif web_binding is not None:
                    default = web_worker_prepared_adapters()
                else:
                    default = recording_prepared_adapters()
                adapters = default
            config = WorkerRuntimeConfig(
                boot_id=boot_id,
                prepared_adapters=adapters,
                automatic_resume=False,
                max_cycles=cycles,
            )
            runtime = WorkerRuntime(
                client,
                config,
                resolved_handler or InertHandler(),
                inventory_provider=provider,
                registered_serial=None if binding is None else binding.serial,
                approved_web_origin=None if web_binding is None else web_binding.approved_origin,
            )
            runtime.run()
        finally:
            if assembled_web is not None:
                assembled_web.close()
    return 0
