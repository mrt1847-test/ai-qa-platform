"""Trusted web driver. CDP stays private; guest code only sees typed IPC."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from aiqa.contracts.actions import Observation
from aiqa.contracts.evidence import EvidenceEnvelope
from aiqa.replay.ipc import WEB_ACTION_TYPES, TypedAction, parse_ipc_message
from aiqa.security.redaction import RedactionError, filter_capture
from aiqa.worker.spool import EvidenceSpool
from aiqa.worker.web_isolation_backend import IsolationProof, IsolationRejected, WebIsolationGate

_FORBIDDEN_PAYLOAD = frozenset(
    {
        "python",
        "shell",
        "eval",
        "exec",
        "subprocess",
        "playwright",
        "page",
        "browser",
        "context",
        "cdp",
        "cdp_url",
        "websocket",
    }
)


class WebDispatchError(Exception):
    """Approved digest, origin, isolation, or sanitization refused the step."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class ApprovedWebPackage:
    """Pinned approval surface for replay. Digest/revision/origin must match live."""

    digest: str
    revision: str
    origin: str


@dataclass(frozen=True, slots=True)
class WebDispatchResult:
    action: TypedAction
    native_calls: int
    retries: int
    ai_calls: int
    before_ref: str | None
    after_ref: str | None
    outcome: str
    reason: str


BrowserRunner = Callable[[TypedAction], None]


class TrustedWebDriver:
    """Translate allowlisted IPC into one isolated browser call. Replay actor AI stays 0."""

    def __init__(
        self,
        cdp_endpoint: str,
        *,
        approved: ApprovedWebPackage,
        gate: WebIsolationGate,
        proof: IsolationProof,
        spool: Path | EvidenceSpool | None = None,
        runner: BrowserRunner | None = None,
        now: datetime | None = None,
        secrets: tuple[str, ...] = (),
        attempt_id: UUID | None = None,
        observe: Callable[[], Observation] | None = None,
    ) -> None:
        if not isinstance(cdp_endpoint, str) or not cdp_endpoint:
            raise ValueError("driver requires a CDP endpoint")
        if approved.origin not in gate.config.backend.allowed_origins:
            raise WebDispatchError("approved origin is outside isolation allowlist")
        self._cdp_endpoint = cdp_endpoint
        self._approved = approved
        self._gate = gate
        self._proof = proof
        if isinstance(spool, EvidenceSpool):
            self._spool = spool
        elif spool is None:
            self._spool = None
        else:
            self._spool = EvidenceSpool(Path(spool))
        self._runner = runner
        self._observe = observe
        self._now = now
        self._secrets = secrets
        self._attempt_id = attempt_id or uuid4()
        self._seq = 0
        self.ai_calls = 0
        self.auto_retries = 0
        self.native_calls = 0
        self.retries = 0

    def public_view(self) -> dict[str, object]:
        return {"owns_cdp": True, "origin": self._approved.origin, "digest": self._approved.digest}

    def execution_allowed(self, *, now: datetime | None = None) -> bool:
        """Replay stays blocked until the isolation proof verifies for this driver."""

        return self._gate.web_ready(self._proof, now=now if now is not None else self._now) is not None

    def dispatch(self, payload: dict) -> TypedAction:
        """Parse only. Does not touch the browser or leak the CDP endpoint."""

        _refuse_forbidden(payload)
        return parse_ipc_message(payload)

    def run(
        self,
        *,
        before: Observation,
        action: TypedAction | dict[str, object],
        presented_digest: str,
        presented_revision: str,
        page_origin: str,
        after: Observation | None = None,
    ) -> WebDispatchResult:
        """Verify approval → sanitize before → one guest IPC → optional after. Never retries/AI."""

        if self.ai_calls != 0:
            raise WebDispatchError("replay actor AI is forbidden")
        if not self.execution_allowed():
            raise WebDispatchError("web is not ready without isolation confirmation")
        if presented_digest != self._approved.digest:
            raise WebDispatchError("approval digest mismatch")
        if presented_revision != self._approved.revision:
            raise WebDispatchError("approval revision mismatch")
        if page_origin != self._approved.origin:
            raise WebDispatchError("cross-origin was refused")

        if isinstance(action, dict):
            _refuse_forbidden(action)
            typed = parse_ipc_message(action)
        else:
            typed = action
        if typed.type not in WEB_ACTION_TYPES:
            raise WebDispatchError("unsupported action")
        if typed.type in {"click", "fill", "select"} and typed.selector.strip() == "":
            raise WebDispatchError("selector is required")

        before_ref = self._sanitize_to_spool(before, phase="before")
        try:
            admitted = self._gate.run_guest_ipc(
                self._proof,
                {
                    "kind": "ipc",
                    "payload": {
                        "type": typed.type,
                        "selector": typed.selector,
                        "value": typed.value,
                    },
                },
                now=self._now,
            )
        except IsolationRejected as exc:
            raise WebDispatchError(str(exc)) from exc
        if (
            admitted.type != typed.type
            or admitted.selector != typed.selector
            or admitted.value != typed.value
        ):
            raise WebDispatchError("ipc translation mismatch")

        # Execution port is mandatory. Without a runner, do not invent native success.
        if self._runner is None:
            raise WebDispatchError("execution port is not configured")
        try:
            self._runner(typed)
        except WebDispatchError:
            raise
        except Exception as exc:
            raise WebDispatchError(str(exc) or "execution failed") from exc
        # Keep CDP on this object only; guest IPC and generated code never receive it.
        _ = self._cdp_endpoint

        self.native_calls += 1
        self.auto_retries = 0
        self.retries = 0

        if after is None and self._observe is not None:
            # Post-action observation comes from the same owned execution port.
            try:
                after = self._observe()
            except Exception as exc:
                raise WebDispatchError(str(exc) or "post-action observation failed") from exc

        after_ref = None
        if after is not None:
            after_ref = self._sanitize_to_spool(after, phase="after")

        return WebDispatchResult(
            action=typed,
            native_calls=1,
            retries=0,
            ai_calls=0,
            before_ref=before_ref,
            after_ref=after_ref,
            outcome="acknowledged",
            reason="ok",
        )

    def _sanitize_to_spool(self, observation: Observation, *, phase: str) -> str:
        try:
            cleaned = filter_capture(observation, self._secrets)
        except RedactionError as exc:
            raise WebDispatchError("sanitize_failed") from exc
        self._seq += 1
        stamp = observation.captured_at
        try:
            parsed = datetime.fromisoformat(stamp)
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                stamp = datetime.now(timezone.utc).isoformat()
        except ValueError:
            stamp = datetime.now(timezone.utc).isoformat()
        if self._spool is None:
            return f"{phase}:{self._seq}"
        receipt = self._spool.append(
            EvidenceEnvelope(
                self._attempt_id,
                self._seq,
                cleaned.png,
                f"web.{phase}\n{cleaned.dom}\n{cleaned.stdout}",
                stamp,
            )
        )
        return f"{phase}:{receipt.local_seq}:{receipt.payload_hash}"


def _refuse_forbidden(payload: dict[str, object]) -> None:
    leaked = _FORBIDDEN_PAYLOAD.intersection(payload)
    if leaked:
        raise WebDispatchError(f"forbidden field: {sorted(leaked)[0]}")
