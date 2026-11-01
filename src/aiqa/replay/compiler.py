"""Compile the proven web action subset into qa_runtime calls.

A static AST check does not replace a sandbox. The source is not executed.
"""

from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import dataclass
from uuid import uuid4

from aiqa.contracts.replay import ReplayPackageBody, StepMapping
from aiqa.replay.ipc import parse_ipc_message, runtime_call
from aiqa.replay.packages import _mapping_hash, validate_package_body
from aiqa.store.models import RecordingManifest


class CompileRejected(Exception):
    """The source is outside the proven click, fill, scroll, and select subset."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class CompilerRef:
    """The pinned compiler and the raw web source. This object does not run the source."""

    compiler_id: str
    lock_hash: str
    raw_source: str


@dataclass(frozen=True, slots=True)
class CompiledStep:
    """One mapped action. The call is qa_runtime and the input text is unchanged."""

    step_id: str
    action_id: str
    line: int
    call: str
    selector: str
    value: str


@dataclass(frozen=True, slots=True)
class CompiledPackage:
    """A compiled plan. Produced version and compiled hash stay outside the body."""

    body: ReplayPackageBody
    body_hash: str
    ready_artifact_ids: tuple[str, ...]
    steps: tuple[CompiledStep, ...]
    expectations: tuple[str, ...]


def compile_replay_package(source: RecordingManifest, compiler: CompilerRef) -> CompiledPackage:
    """Map each allowed action to qa_runtime. Unsupported syntax is rejected before any call runs."""

    if compiler.compiler_id != "web-ipc-subset" or compiler.lock_hash.strip() == "":
        raise CompileRejected("compiler is not the web subset")
    raw_hash = hashlib.sha256(compiler.raw_source.encode("utf-8")).hexdigest()
    try:
        hashes = json.loads(source.source_artifact_hashes)
    except json.JSONDecodeError as exc:
        raise CompileRejected("source does not match") from exc
    if type(hashes) is not list or raw_hash not in hashes:
        raise CompileRejected("source does not match")
    expectations, steps = _translate(compiler.raw_source)
    plan = "\n".join(step.call for step in steps)
    mappings = tuple(StepMapping(step.step_id, step.action_id, step.line) for step in steps)
    body = ReplayPackageBody(
        schema_version="replay-package-v1",
        source_manifest_id=source.manifest_id,
        source_manifest_hash=source.body_hash,
        raw_source_hash=raw_hash,
        approved_code_or_plan_hash=hashlib.sha256(plan.encode("utf-8")).hexdigest(),
        runtime_ref="web",
        compiler_ref=compiler.compiler_id,
        lock_hash=compiler.lock_hash,
        step_mapping_hash=_mapping_hash(mappings),
        mappings=mappings,
    )
    checked = validate_package_body(body, source)
    if not checked.ready:
        raise CompileRejected(checked.reasons[0] if checked.reasons else "package is not ready")
    return CompiledPackage(body, checked.body_hash, (), steps, expectations)


def _translate(raw_source: str) -> tuple[tuple[str, ...], tuple[CompiledStep, ...]]:
    try:
        tree = ast.parse(raw_source)
    except SyntaxError as exc:
        raise CompileRejected("unsupported syntax") from exc
    expectations: list[str] = []
    steps: list[CompiledStep] = []
    for statement in tree.body:
        if type(statement) is not ast.Expr:
            raise CompileRejected("unsupported statement")
        value = statement.value
        if type(value) is ast.Constant and type(value.value) is str:
            expectations.append(value.value)
            continue
        if type(value) is not ast.Call:
            raise CompileRejected("unsupported statement")
        action = _action(value)
        rendered = runtime_call(action)
        steps.append(
            CompiledStep(
                f"step-{len(steps) + 1}",
                str(uuid4()),
                statement.lineno,
                rendered,
                action.selector,
                action.value,
            )
        )
    if not steps:
        raise CompileRejected("action is missing")
    return tuple(expectations), tuple(steps)


def _action(call: ast.Call):
    if call.keywords or type(call.func) is not ast.Attribute or type(call.func.value) is not ast.Name:
        raise CompileRejected("unsupported call")
    if call.func.value.id != "qa_runtime":
        raise CompileRejected("raw browser or helper call is rejected")
    if any(type(arg) is not ast.Constant or type(arg.value) is not str or arg.value.strip() == "" for arg in call.args):
        raise CompileRejected("compound action is rejected")
    needed = 2 if call.func.attr in {"fill", "select"} else 1
    if call.func.attr not in {"click", "fill", "scroll", "select"} or len(call.args) != needed:
        raise CompileRejected("unsupported call")
    selector = str(call.args[0].value)
    entered = str(call.args[1].value) if needed == 2 else ""
    try:
        return parse_ipc_message({"type": call.func.attr, "selector": selector, "value": entered})
    except ValueError as exc:
        raise CompileRejected("unsupported call") from exc
