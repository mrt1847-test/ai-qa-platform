"""Android traces become immutable plans. A model loop is not a replay command."""

from __future__ import annotations

import hashlib
import json
from uuid import UUID

from aiqa.replay.android_plan import PlanRejected, compile_android_plan
from aiqa.store.models import RecordingManifest

_SECRET = "trace-secret-literal"
_PROMPT = "model-loop-prompt"
_GEOMETRY = {"rotation": 0, "content_bounds": [0, 0, 1080, 1920]}


def test_w30_01() -> None:
    package = compile_android_plan(_manifest(_supported()))
    plan = "\n".join(step.call for step in package.steps)
    actions = [step.call.split(".", 1)[1].split("(", 1)[0] for step in package.steps]
    secret_saved = True
    try:
        compile_android_plan(_manifest([_action("type", "a2", 2, secret_literal=_SECRET)]))
    except PlanRejected as exc:
        secret_saved = _SECRET in exc.reason
    geometry_ready = True
    try:
        compile_android_plan(_manifest([_action("tap", "a1", 1, geometry=None)]))
    except PlanRejected as exc:
        geometry_ready = exc.reason != "geometry is missing"
    for bad in (
        [_action("shell", "a1", 1)],
        [_action("pinch", "a1", 1)],
        [_action("tap", "a1", 1), {"kind": "wait", "intent": "settle", "action_id": "w1", "line": 2, "maps_to": "missing", "geometry": _GEOMETRY}],
    ):
        try:
            compile_android_plan(_manifest(bad))
        except PlanRejected:
            continue
        raise AssertionError(bad[0])
    observed = {
        "supported_actions": [name for name in actions if name in {"tap", "type", "swipe", "back"}],
        "raw_model_loop_in_plan": _PROMPT in plan,
        "secret_literal_saved": secret_saved,
        "missing_geometry_ready": geometry_ready,
    }
    assert "ref-1" in plan and _PROMPT not in plan
    assert observed == {
        "supported_actions": ["tap", "type", "swipe", "back"],
        "raw_model_loop_in_plan": False,
        "secret_literal_saved": False,
        "missing_geometry_ready": False,
    }


def _supported() -> list[object]:
    return [
        {"kind": "model", "prompt": _PROMPT, "loop": "think"},
        _action("tap", "a1", 1, intent="open", target="resource_id=login"),
        _action("type", "a2", 2, intent="enter", target="resource_id=field", secret_ref="ref-1"),
        _action("swipe", "a3", 3, intent="scroll", target="resource_id=list"),
        _action("back", "a4", 4, intent="return", target="system"),
        {"kind": "wait", "intent": "settle", "action_id": "w1", "line": 5, "maps_to": "a1", "target": "resource_id=login", "geometry": _GEOMETRY},
        {"kind": "check", "intent": "visible", "expected": "로그인됨", "action_id": "c1", "line": 6, "maps_to": "a1", "target": "resource_id=login", "geometry": _GEOMETRY},
    ]


def _action(action: str, action_id: str, line: int, **extra: object) -> dict[str, object]:
    event: dict[str, object] = {
        "kind": "action",
        "action": action,
        "intent": "open",
        "target": "resource_id=login",
        "action_id": action_id,
        "line": line,
        "geometry": _GEOMETRY,
    }
    event.update(extra)
    return event


def _manifest(events: list[object]) -> RecordingManifest:
    raw = json.dumps({"events": events}, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return RecordingManifest(
        UUID("00000000-0000-4000-8000-000000000030"),
        UUID("00000000-0000-4000-8000-000000000031"),
        UUID("00000000-0000-4000-8000-000000000032"),
        UUID("00000000-0000-4000-8000-000000000033"),
        1,
        "recorded",
        None,
        "a" * 64,
        json.dumps([digest]),
        raw,
        "complete",
        "w30-01",
        "b" * 64,
    )


def test_w30_02() -> None:
    from aiqa.contracts.actions import CaptureGeometry, Observation
    from aiqa.replay.android_runner import AndroidPreflight
    from aiqa.replay.targets import TargetBinding

    runner = AndroidPreflight()
    same = runner.dispatch(_resource(), _screen([_node("로그인")], 1080, 1920, 0))
    ambiguous = runner.dispatch(_resource(), _screen([_node("로그인"), _node("로그인")], 1080, 1920, 0))
    changed = runner.dispatch(_resource(), _screen([_node("다른문구")], 1080, 1920, 0))
    resized = runner.dispatch(_point(1080, 1920), _screen([_node("로그인")], 720, 1280, 0))
    rotated = runner.dispatch(_point(1080, 1920), _screen([_node("로그인")], 1080, 1920, 90))
    outside = runner.dispatch(_point(1080, 1920, x=2000, y=10), _screen([_node("로그인")], 1080, 1920, 0))
    guessed = runner.dispatch(TargetBinding("guess", x=10, y=10), _screen([_node("로그인")], 720, 1280, 0))
    approved = runner.dispatch(_point(1080, 1920), _screen([_node("로그인")], 1080, 1920, 0))
    observed = {
        "ambiguous_not_dispatched": ambiguous.dispatched is False and ambiguous.reason == "target is ambiguous",
        "dimension_change_blocked": resized.blocked is True and resized.dispatched is False,
        "guessed_coordinate_dispatches": runner.guessed_coordinate_dispatches,
    }
    assert same.dispatched is True and changed.dispatched is False
    assert rotated.blocked is True and outside.reason == "coordinate is outside"
    assert guessed.dispatched is False and approved.dispatched is True
    assert observed == {
        "ambiguous_not_dispatched": True,
        "dimension_change_blocked": True,
        "guessed_coordinate_dispatches": 0,
    }


def _resource() -> TargetBinding:
    from aiqa.replay.targets import TargetBinding

    return TargetBinding("resource", resource_id="login", text="로그인", context="main")


def _point(width: int, height: int, x: int = 40, y: int = 40) -> TargetBinding:
    from aiqa.replay.targets import TargetBinding

    return TargetBinding(
        "coordinate",
        x=x,
        y=y,
        approved=True,
        approved_rotation=0,
        approved_width=width,
        approved_height=height,
        approved_bounds=(0, 0, width, height),
    )


def _node(text: str) -> dict[str, str]:
    return {"resource_id": "login", "text": text, "context": "main"}


def _screen(nodes: list[dict[str, str]], width: int, height: int, rotation: int) -> Observation:
    from aiqa.contracts.actions import CaptureGeometry, Observation

    geometry = CaptureGeometry(width, height, width, height, "identity", rotation, (0, 0, width, height))
    return Observation(
        "obs-1",
        "2026-11-01T00:00:00+00:00",
        geometry,
        b"",
        "",
        json.dumps({"nodes": nodes}, ensure_ascii=False),
        (),
        "",
        True,
        "android",
    )
