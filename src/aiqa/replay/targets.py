"""Resolve a recorded Android target against one fixture hierarchy. This does not open a device."""

from __future__ import annotations

import json
from dataclasses import dataclass

from aiqa.contracts.actions import Observation


@dataclass(frozen=True, slots=True)
class TargetBinding:
    """A recorded resource or an approved fixed point. A scaled point is not a binding."""

    kind: str
    resource_id: str = ""
    text: str = ""
    context: str = ""
    x: int | None = None
    y: int | None = None
    approved: bool = False
    approved_rotation: int | None = None
    approved_width: int | None = None
    approved_height: int | None = None
    approved_bounds: tuple[int, int, int, int] | None = None


@dataclass(frozen=True, slots=True)
class TargetResolution:
    """Whether this target may be dispatched. Blocked means the current geometry is unusable."""

    dispatched: bool
    blocked: bool
    reason: str
    matches: int


def resolve_recorded_target(binding: TargetBinding, observation: Observation) -> TargetResolution:
    """Match resource id, text, and context, or one approved point on the same geometry."""

    if binding.kind == "guess":
        return TargetResolution(False, True, "coordinate guess is not allowed", 0)
    if observation.geometry is None:
        return TargetResolution(False, True, "dimension is unknown", 0)
    if binding.kind == "coordinate":
        return _coordinate(binding, observation)
    if binding.kind != "resource":
        return TargetResolution(False, True, "target is unknown", 0)
    matches = _matches(observation.stdout, binding)
    if matches > 1:
        return TargetResolution(False, False, "target is ambiguous", matches)
    if matches == 0:
        return TargetResolution(False, False, "target is missing", 0)
    return TargetResolution(True, False, "target matched", 1)


def _coordinate(binding: TargetBinding, observation: Observation) -> TargetResolution:
    geometry = observation.geometry
    assert geometry is not None
    if not binding.approved or binding.x is None or binding.y is None:
        return TargetResolution(False, True, "coordinate is not approved", 0)
    if (
        binding.approved_width != geometry.physical_width
        or binding.approved_height != geometry.physical_height
        or binding.approved_rotation != geometry.rotation
        or binding.approved_bounds != geometry.content_bounds
    ):
        return TargetResolution(False, True, "dimension changed", 0)
    if geometry.transform != "identity":
        return TargetResolution(False, True, "coordinate guess is not allowed", 0)
    left, top, right, bottom = geometry.content_bounds
    if binding.x < left or binding.x > right or binding.y < top or binding.y > bottom:
        return TargetResolution(False, True, "coordinate is outside", 0)
    return TargetResolution(True, False, "coordinate matched", 1)


def _matches(raw: str, binding: TargetBinding) -> int:
    try:
        parsed = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        return 0
    if type(parsed) is not dict or type(parsed.get("nodes")) is not list:
        return 0
    count = 0
    for item in parsed["nodes"]:
        if type(item) is not dict:
            continue
        if item.get("resource_id") == binding.resource_id and item.get("text") == binding.text and item.get("context") == binding.context:
            count += 1
    return count
