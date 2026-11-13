"""Preflight and deterministic Android input. Replay never calls an authoring model."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from aiqa.contracts.actions import Observation
from aiqa.contracts.evidence import EvidenceEnvelope
from aiqa.environments.usb_android import allow_dispatch, require_dedicated_serial
from aiqa.replay.android_plan import TypedAndroidAction
from aiqa.replay.targets import TargetBinding, TargetResolution, resolve_recorded_target
from aiqa.security.redaction import RedactionError, filter_capture
from aiqa.worker.spool import EvidenceSpool


class AndroidDispatchError(Exception):
    """ADB failed, geometry drifted, or sanitization refused the capture."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def require_approved_digest(presented: str, approved: str) -> None:
    """Refuse replay when the live package digest diverges from the approved pin."""

    if type(presented) is not str or type(approved) is not str or presented.strip() == "" or approved.strip() == "":
        raise AndroidDispatchError("approved digest is missing")
    if presented != approved:
        raise AndroidDispatchError("approved digest changed")


@dataclass(frozen=True, slots=True)
class GeometryLock:
    serial: str
    width: int
    height: int
    rotation: int

    @classmethod
    def from_observation(cls, serial: str, observation: Observation) -> GeometryLock:
        if observation.geometry is None:
            raise AndroidDispatchError("geometry is missing")
        geo = observation.geometry
        return cls(serial, geo.physical_width, geo.physical_height, geo.rotation)

    def matches(self, observation: Observation) -> bool:
        if observation.geometry is None:
            return False
        geo = observation.geometry
        return (
            geo.physical_width == self.width
            and geo.physical_height == self.height
            and geo.rotation == self.rotation
        )


@dataclass(frozen=True, slots=True)
class AndroidDispatchResult:
    argv: tuple[str, ...]
    native_calls: int
    retries: int
    ai_calls: int
    before_ref: str | None
    after_ref: str | None
    outcome: str
    reason: str


AdbRunner = Callable[[Sequence[str], float], subprocess.CompletedProcess]


class AndroidPreflight:
    """Count only a resolved dispatch. A guessed coordinate never increments."""

    def __init__(self) -> None:
        self.dispatches = 0
        self.guessed_coordinate_dispatches = 0

    def dispatch(self, binding: TargetBinding, observation: Observation) -> TargetResolution:
        resolution = resolve_recorded_target(binding, observation)
        if binding.kind == "guess":
            self.guessed_coordinate_dispatches += 1
        if allow_dispatch(resolution):
            self.dispatches += 1
        return resolution


class AndroidDeterministicDriver:
    """Run one typed input on a fixed serial with locked geometry. No auto-retry, no AI."""

    def __init__(
        self,
        adb_path: Path,
        serial: str,
        *,
        command_timeout: float = 10.0,
        runner: AdbRunner | None = None,
        spool: EvidenceSpool | None = None,
        secrets: tuple[str, ...] = (),
        attempt_id: UUID | None = None,
    ) -> None:
        path = Path(adb_path)
        if path.name.lower() not in {"adb", "adb.exe"}:
            raise ValueError("an explicit ADB executable is required")
        if type(serial) is not str or serial.strip() == "":
            raise ValueError("serial is required")
        if type(command_timeout) not in {int, float} or not 0 < float(command_timeout) <= 90:
            raise ValueError("command timeout is invalid")
        self.adb_path = path
        self.serial = serial
        self.command_timeout = float(command_timeout)
        self._runner = runner or _default_runner
        self._spool = spool
        self._secrets = secrets
        self._attempt_id = attempt_id or uuid4()
        self._seq = 0
        self.native_calls = 0
        self.retries = 0
        self.ai_calls = 0
        self.auto_retries = 0

    def bind_attempt(self, attempt_id: UUID) -> None:
        """Align spool sequences with the claimed attempt. Resets the local seq."""

        self._attempt_id = attempt_id
        self._seq = 0

    def build_argv(self, action: TypedAndroidAction) -> tuple[str, ...]:
        """Fixed argv list. Consumers must pass this tuple with shell=False."""

        base = (str(self.adb_path), "-s", self.serial, "shell", "input")
        if action.kind == "tap":
            assert action.x is not None and action.y is not None
            return (*base, "tap", str(action.x), str(action.y))
        if action.kind == "swipe":
            assert action.x is not None and action.y is not None
            assert action.x2 is not None and action.y2 is not None
            return (
                *base,
                "swipe",
                str(action.x),
                str(action.y),
                str(action.x2),
                str(action.y2),
                str(action.duration_ms),
            )
        if action.kind == "key":
            assert action.keycode is not None
            return (*base, "keyevent", str(action.keycode))
        if action.kind == "text":
            assert action.text is not None
            return (*base, "text", action.text)
        raise AndroidDispatchError("action is unsupported")

    def run(
        self,
        *,
        preflight: AndroidPreflight,
        binding: TargetBinding,
        before: Observation,
        action: TypedAndroidAction,
        after: Observation | None = None,
        observed_serial: str | None = None,
        before_native_send: Callable[[], None] | None = None,
    ) -> AndroidDispatchResult:
        """Preflight → sanitize before → one native call → optional after. Never retries."""

        if self.ai_calls != 0:
            raise AndroidDispatchError("replay actor AI is forbidden")
        serial = self.serial if observed_serial is None else observed_serial
        if not require_dedicated_serial(self.serial, serial):
            raise AndroidDispatchError("serial mismatch")
        resolution = preflight.dispatch(binding, before)
        if resolution.reason == "target is ambiguous":
            return AndroidDispatchResult((), 0, 0, 0, None, None, "blocked", "ambiguous")
        if not allow_dispatch(resolution):
            return AndroidDispatchResult((), 0, 0, 0, None, None, "blocked", resolution.reason)
        lock = GeometryLock.from_observation(self.serial, before)
        if binding.kind == "coordinate" and (
            binding.approved_width != lock.width
            or binding.approved_height != lock.height
            or binding.approved_rotation != lock.rotation
        ):
            raise AndroidDispatchError("geometry changed")

        before_ref = self._sanitize_to_spool(before, phase="before")
        argv = self.build_argv(action)
        if before_native_send is not None:
            before_native_send()
        try:
            completed = self._runner(argv, self.command_timeout)
        except subprocess.TimeoutExpired as exc:
            raise AndroidDispatchError("timeout") from exc
        except OSError as exc:
            raise AndroidDispatchError("adb_failed") from exc
        self.native_calls += 1
        self.auto_retries = 0
        self.retries = 0
        if completed.returncode != 0:
            raise AndroidDispatchError("adb_failed")

        after_ref = None
        if after is not None:
            if not lock.matches(after):
                raise AndroidDispatchError("geometry changed")
            after_ref = self._sanitize_to_spool(after, phase="after")
        return AndroidDispatchResult(
            argv,
            1,
            0,
            self.ai_calls,
            before_ref,
            after_ref,
            "acknowledged",
            "ok",
        )

    def _sanitize_to_spool(self, observation: Observation, *, phase: str) -> str:
        try:
            cleaned = filter_capture(observation, self._secrets)
        except RedactionError as exc:
            raise AndroidDispatchError("sanitize_failed") from exc
        self._seq += 1
        stamp = observation.captured_at
        if not _has_tz(stamp):
            stamp = datetime.now(timezone.utc).isoformat()
        if self._spool is None:
            return f"{phase}:{self._seq}"
        receipt = self._spool.append(
            EvidenceEnvelope(
                self._attempt_id,
                self._seq,
                cleaned.png,
                f"android.{phase}\n{cleaned.dom}\n{cleaned.stdout}",
                stamp,
            )
        )
        return f"{phase}:{receipt.local_seq}:{receipt.payload_hash}"


def _has_tz(value: str) -> bool:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _default_runner(argv: Sequence[str], timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(argv),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        shell=False,
        timeout=timeout,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
