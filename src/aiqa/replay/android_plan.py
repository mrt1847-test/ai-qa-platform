"""Turn a Mobile-Agent trace into an immutable Android plan. The model loop is not replayed."""

from __future__ import annotations

import ast
import hashlib
import json
import re
from dataclasses import dataclass

from aiqa.contracts.actions import CaptureGeometry
from aiqa.contracts.replay import AndroidPlanStep, ReplayPackageBody, StepMapping
from aiqa.replay.compiler import CompiledPackage, CompiledStep
from aiqa.replay.packages import _mapping_hash, android_trace_reasons, validate_package_body
from aiqa.store.models import RecordingManifest

_COMPILER = "android-plan-v1"
_LOCK = "android-plan-lock"
_ACTIONS = frozenset({"tap", "swipe", "key", "text", "back"})
_TEXT_SAFE = re.compile(r"^[A-Za-z0-9._:@%+\-/=]*$")
_ACTION_LINE = re.compile(
    r"^(?:Action:\s*)?(?P<name>click|tap|swipe|type|text|back|key|system_button|shell|adb|open_app)\s*\((?P<args>.*)\)\s*$",
    re.IGNORECASE | re.DOTALL,
)


class PlanRejected(Exception):
    """The trace cannot become a ready plan. The reason does not repeat a secret literal."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class TypedAndroidAction:
    """One verified Android input. Coordinates are display pixels on the locked geometry."""

    kind: str
    x: int | None = None
    y: int | None = None
    x2: int | None = None
    y2: int | None = None
    keycode: int | None = None
    text: str | None = None
    duration_ms: int = 300


@dataclass(frozen=True, slots=True)
class ParsedUpstreamAction:
    """Pure parser output in model coordinate space before rescaling."""

    kind: str
    x: float | None = None
    y: float | None = None
    x2: float | None = None
    y2: float | None = None
    keycode: int | None = None
    text: str | None = None
    duration_ms: int = 300


def build_typed_android_action(
    kind: str,
    *,
    width: int,
    height: int,
    rotation: int,
    x: int | None = None,
    y: int | None = None,
    x2: int | None = None,
    y2: int | None = None,
    keycode: int | None = None,
    text: str | None = None,
    duration_ms: int = 300,
    secrets: tuple[str, ...] = (),
) -> TypedAndroidAction:
    """Reject out-of-bounds and sensitive literals before any ADB argv is built."""

    if kind not in _ACTIONS:
        raise PlanRejected("action is unsupported")
    if type(width) is not int or type(height) is not int or width < 1 or height < 1:
        raise PlanRejected("geometry is invalid")
    if type(rotation) is not int or rotation not in {0, 90, 180, 270}:
        raise PlanRejected("rotation is invalid")
    if kind == "tap":
        _require_point(x, y, width, height)
        return TypedAndroidAction("tap", x=x, y=y)
    if kind == "swipe":
        _require_point(x, y, width, height)
        _require_point(x2, y2, width, height)
        if type(duration_ms) is not int or not 1 <= duration_ms <= 5000:
            raise PlanRejected("swipe duration is invalid")
        return TypedAndroidAction("swipe", x=x, y=y, x2=x2, y2=y2, duration_ms=duration_ms)
    if kind == "key":
        if type(keycode) is not int or not 0 <= keycode <= 999:
            raise PlanRejected("keycode is invalid")
        return TypedAndroidAction("key", keycode=keycode)
    if kind == "back":
        return TypedAndroidAction("key", keycode=4)
    if kind == "text":
        if type(text) is not str or text == "" or len(text) > 256:
            raise PlanRejected("text is invalid")
        if any(secret and secret in text for secret in secrets):
            raise PlanRejected("sensitive text is refused")
        if _TEXT_SAFE.fullmatch(text) is None:
            raise PlanRejected("text contains unsupported characters")
        return TypedAndroidAction("text", text=text)
    raise PlanRejected("action is unsupported")


def _require_point(x: int | None, y: int | None, width: int, height: int) -> None:
    if type(x) is not int or type(y) is not int:
        raise PlanRejected("coordinate is required")
    if x < 0 or y < 0 or x >= width or y >= height:
        raise PlanRejected("coordinate is outside")


def parse_mobile_agent_action(response: str) -> ParsedUpstreamAction:
    """Parse a fixed Mobile-Agent style action line. Shell and unknown verbs are refused."""

    if type(response) is not str or response.strip() == "":
        raise PlanRejected("action is missing")
    line = response.strip().splitlines()[-1].strip()
    matched = _ACTION_LINE.match(line)
    if matched is None:
        raise PlanRejected("action is unsupported")
    name = matched.group("name").lower()
    if name in {"shell", "adb"}:
        raise PlanRejected("shell payload is refused")
    if name == "open_app":
        raise PlanRejected("action is unsupported")
    args = _parse_args(matched.group("args"))
    if name in {"click", "tap"}:
        if len(args) != 2 or any(type(item) not in {int, float} for item in args):
            raise PlanRejected("coordinate is required")
        return ParsedUpstreamAction("tap", x=float(args[0]), y=float(args[1]))
    if name == "swipe":
        if len(args) not in {4, 5} or any(type(item) not in {int, float} for item in args[:4]):
            raise PlanRejected("coordinate is required")
        duration = 300
        if len(args) == 5:
            if type(args[4]) not in {int, float}:
                raise PlanRejected("swipe duration is invalid")
            duration = int(args[4])
        return ParsedUpstreamAction(
            "swipe",
            x=float(args[0]),
            y=float(args[1]),
            x2=float(args[2]),
            y2=float(args[3]),
            duration_ms=duration,
        )
    if name in {"type", "text"}:
        text = _text_arg(args)
        return ParsedUpstreamAction("text", text=text)
    if name == "back":
        if args:
            raise PlanRejected("action is unsupported")
        return ParsedUpstreamAction("back")
    if name == "system_button":
        button = _text_arg(args).lower()
        if button != "back":
            raise PlanRejected("action is unsupported")
        return ParsedUpstreamAction("back")
    if name == "key":
        if len(args) != 1 or type(args[0]) is not int:
            raise PlanRejected("keycode is invalid")
        return ParsedUpstreamAction("key", keycode=int(args[0]))
    raise PlanRejected("action is unsupported")


def rescale_coordinates(
    x: float,
    y: float,
    geometry: CaptureGeometry,
) -> tuple[int, int]:
    """Map model-space coordinates onto physical display pixels."""

    if geometry.model_width < 1 or geometry.model_height < 1:
        raise PlanRejected("geometry is invalid")
    if geometry.physical_width < 1 or geometry.physical_height < 1:
        raise PlanRejected("geometry is invalid")
    if float(x) < 0 or float(y) < 0:
        raise PlanRejected("coordinate is outside")
    if float(x) > geometry.model_width or float(y) > geometry.model_height:
        raise PlanRejected("coordinate is outside")
    px = int(round(float(x) * geometry.physical_width / geometry.model_width))
    py = int(round(float(y) * geometry.physical_height / geometry.model_height))
    # Clamp the inclusive edge of exact model max onto the last physical pixel.
    if px == geometry.physical_width:
        px = geometry.physical_width - 1
    if py == geometry.physical_height:
        py = geometry.physical_height - 1
    if px < 0 or py < 0 or px >= geometry.physical_width or py >= geometry.physical_height:
        raise PlanRejected("coordinate is outside")
    return px, py


def typed_from_upstream(
    parsed: ParsedUpstreamAction,
    geometry: CaptureGeometry,
    *,
    secrets: tuple[str, ...] = (),
) -> TypedAndroidAction:
    """Rescale parsed model action into a typed Android driver action."""

    if geometry.rotation not in {0, 90, 180, 270}:
        raise PlanRejected("rotation is invalid")
    if parsed.kind == "tap":
        assert parsed.x is not None and parsed.y is not None
        x, y = rescale_coordinates(parsed.x, parsed.y, geometry)
        return build_typed_android_action(
            "tap",
            width=geometry.physical_width,
            height=geometry.physical_height,
            rotation=geometry.rotation,
            x=x,
            y=y,
        )
    if parsed.kind == "swipe":
        assert parsed.x is not None and parsed.y is not None
        assert parsed.x2 is not None and parsed.y2 is not None
        x, y = rescale_coordinates(parsed.x, parsed.y, geometry)
        x2, y2 = rescale_coordinates(parsed.x2, parsed.y2, geometry)
        return build_typed_android_action(
            "swipe",
            width=geometry.physical_width,
            height=geometry.physical_height,
            rotation=geometry.rotation,
            x=x,
            y=y,
            x2=x2,
            y2=y2,
            duration_ms=parsed.duration_ms,
        )
    if parsed.kind == "text":
        return build_typed_android_action(
            "text",
            width=geometry.physical_width,
            height=geometry.physical_height,
            rotation=geometry.rotation,
            text=parsed.text,
            secrets=secrets,
        )
    if parsed.kind == "back":
        return build_typed_android_action(
            "back",
            width=geometry.physical_width,
            height=geometry.physical_height,
            rotation=geometry.rotation,
        )
    if parsed.kind == "key":
        return build_typed_android_action(
            "key",
            width=geometry.physical_width,
            height=geometry.physical_height,
            rotation=geometry.rotation,
            keycode=parsed.keycode,
        )
    raise PlanRejected("action is unsupported")


def _parse_args(source: str) -> list[object]:
    text = source.strip()
    if text == "":
        return []
    try:
        node = ast.parse(f"f({text})", mode="eval")
    except SyntaxError as exc:
        raise PlanRejected("action is unsupported") from exc
    if type(node.body) is not ast.Call:
        raise PlanRejected("action is unsupported")
    call = node.body
    if call.args and call.keywords:
        raise PlanRejected("action is unsupported")
    if call.keywords:
        values: list[object] = []
        for keyword in call.keywords:
            if keyword.arg not in {"content", "text", "button"}:
                raise PlanRejected("action is unsupported")
            values.append(_const(keyword.value))
        return values
    return [_const(arg) for arg in call.args]


def _const(node: object) -> object:
    if type(node) is not ast.Constant:
        raise PlanRejected("action is unsupported")
    value = node.value
    if type(value) not in {int, float, str}:
        raise PlanRejected("action is unsupported")
    return value


def _text_arg(args: list[object]) -> str:
    if len(args) != 1 or type(args[0]) is not str:
        raise PlanRejected("text is invalid")
    return str(args[0])


def compile_android_plan(source: RecordingManifest) -> CompiledPackage:
    """Keep tap, type, swipe, and back. Drop model prompts and refuse a secret literal."""

    try:
        parsed = json.loads(source.action_mapping)
    except json.JSONDecodeError as exc:
        raise PlanRejected("trace is missing") from exc
    if type(parsed) is not dict or type(parsed.get("events")) is not list:
        raise PlanRejected("trace is missing")
    events = parsed["events"]
    reasons = android_trace_reasons(events)
    if reasons:
        raise PlanRejected(reasons[0])
    raw_hash = hashlib.sha256(source.action_mapping.encode("utf-8")).hexdigest()
    if raw_hash not in _source_hashes(source):
        raise PlanRejected("source does not match")
    planned = tuple(_step(item) for item in events if type(item) is dict and item.get("kind") != "model")
    compiled = tuple(_compiled(item) for item in planned)
    plan = "\n".join(step.call for step in compiled)
    mappings = tuple(StepMapping(step.step_id, step.action_id, step.line) for step in compiled)
    body = ReplayPackageBody(
        schema_version="replay-package-v1",
        source_manifest_id=source.manifest_id,
        source_manifest_hash=source.body_hash,
        raw_source_hash=raw_hash,
        approved_code_or_plan_hash=hashlib.sha256(plan.encode("utf-8")).hexdigest(),
        runtime_ref="android",
        compiler_ref=_COMPILER,
        lock_hash=_LOCK,
        step_mapping_hash=_mapping_hash(mappings),
        mappings=mappings,
    )
    checked = validate_package_body(body, source)
    if not checked.ready:
        raise PlanRejected(checked.reasons[0] if checked.reasons else "package is not ready")
    return CompiledPackage(body, checked.body_hash, (), compiled, ())


def _step(item: dict[str, object]) -> AndroidPlanStep:
    kind = str(item["kind"])
    geometry = item["geometry"]
    assert type(geometry) is dict
    bounds = geometry["content_bounds"]
    assert type(bounds) is list
    secret = item.get("secret_ref")
    maps_to = item.get("maps_to")
    expected = item.get("expected")
    return AndroidPlanStep(
        kind,
        "wait" if kind == "wait" else "check" if kind == "check" else str(item["action"]),
        str(item.get("intent", "")),
        str(item.get("target", "")),
        str(item["action_id"]),
        int(str(item["line"])),
        int(str(geometry["rotation"])),
        (int(str(bounds[0])), int(str(bounds[1])), int(str(bounds[2])), int(str(bounds[3]))),
        None if secret in {None, ""} else str(secret),
        None if maps_to in {None, ""} else str(maps_to),
        None if expected in {None, ""} else str(expected),
    )


def _compiled(step: AndroidPlanStep) -> CompiledStep:
    secret = "" if step.secret_ref is None else f",secret_ref={step.secret_ref!r}"
    mapped = "" if step.maps_to is None else f",maps_to={step.maps_to!r}"
    expected = "" if step.expected is None else f",expected={step.expected!r}"
    bounds = ",".join(str(item) for item in step.content_bounds)
    call = (
        f"android.{step.action}(intent={step.intent!r},target={step.target!r}{secret}"
        f",rotation={step.rotation},bounds={bounds}{mapped}{expected})"
    )
    return CompiledStep(step.action_id, step.action_id, step.line, call, step.target, step.secret_ref or "")


def _source_hashes(source: RecordingManifest) -> set[str]:
    try:
        parsed = json.loads(source.source_artifact_hashes)
    except json.JSONDecodeError:
        return set()
    if type(parsed) is not list:
        return set()
    return {item for item in parsed if type(item) is str}
