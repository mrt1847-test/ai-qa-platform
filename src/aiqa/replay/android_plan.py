"""Turn a Mobile-Agent trace into an immutable Android plan. The model loop is not replayed."""

from __future__ import annotations

import hashlib
import json

from aiqa.contracts.replay import AndroidPlanStep, ReplayPackageBody, StepMapping
from aiqa.replay.compiler import CompiledPackage, CompiledStep
from aiqa.replay.packages import _mapping_hash, android_trace_reasons, validate_package_body
from aiqa.store.models import RecordingManifest

_COMPILER = "android-plan-v1"
_LOCK = "android-plan-lock"


class PlanRejected(Exception):
    """The trace cannot become a ready plan. The reason does not repeat a secret literal."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


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
