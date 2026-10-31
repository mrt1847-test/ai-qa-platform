"""Typed action proposals. Importing this module does not open a device or a shell."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

WEB_ACTIONS = frozenset({"click", "fill", "scroll", "select"})
ANDROID_ACTIONS = frozenset({"tap", "type", "swipe", "back"})
RAW_ACTIONS = frozenset({"shell", "raw", "code", "exec", "raw_command", "script", "adb"})


@dataclass(frozen=True, slots=True)
class LiteralInput:
    text: str


@dataclass(frozen=True, slots=True)
class ActionProposal:
    step_id: str
    action_id: str
    type: str
    intent: str
    approved_path_ref: str
    source: str = "typed"
    target_binding: str | None = None
    coordinates: tuple[int, int] | None = None
    input: LiteralInput | tuple[UUID, UUID, int] | None = None
    navigation_url: str | None = None
    target_package: str | None = None
    helper_command: str | None = None


@dataclass(frozen=True, slots=True)
class StepContext:
    platform: str
    allowed_origins: tuple[str, ...]
    allowed_packages: tuple[str, ...]
    approved_literals: tuple[str, ...]
    approved_secrets: tuple[tuple[UUID, UUID, int], ...]
    required_steps: tuple[str, ...]
    approved_path_ref: str
    screen_text: str
    content_bounds: tuple[int, int, int, int] | None


@dataclass(frozen=True, slots=True)
class ActionDecision:
    allowed: bool
    in_scope: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CaptureGeometry:
    physical_width: int
    physical_height: int
    model_width: int
    model_height: int
    transform: str
    rotation: int
    content_bounds: tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class Observation:
    """In-memory capture. Raw fields stay here until redaction removes them."""

    observation_id: str
    captured_at: str
    geometry: CaptureGeometry | None
    png: bytes
    dom: str
    stdout: str
    messages: tuple[str, ...]
    reasoning: str
    capture_ok: bool
    platform: str


@dataclass(frozen=True, slots=True)
class PreparedAction:
    proposal: ActionProposal
    observation_id: str
    before_ref: str | None
    command_allowed: bool
    attempt_id: str | None = None


@dataclass(frozen=True, slots=True)
class DispatchReceipt:
    observation_id: str
    states: tuple[str, ...]
    native_calls: int
