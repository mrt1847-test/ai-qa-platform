"""CUAWright Web recording adapter. Fixed hooks only; generated code never runs on host."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from aiqa.contracts.actions import ActionProposal, Observation
from aiqa.replay.compiler import CompiledPackage, CompilerRef, compile_replay_package
from aiqa.replay.driver import ApprovedWebPackage, TrustedWebDriver, WebDispatchError, WebDispatchResult
from aiqa.replay.ipc import WEB_ACTION_TYPES, parse_ipc_message
from aiqa.store.models import RecordingManifest
from aiqa.worker.isolated_web import require_web_ready
from aiqa.worker.web_isolation_backend import IsolationProof, WebIsolationGate

# Pinned CUAWright hook ids from probes/cuawright_source.py (commit 35dbcf3...).
STEP_SOURCE_HOOKS = frozenset(
    {
        "hook.web.code_output.step_script",
        "hook.web.code_output.script_py",
    }
)
SHELL_HOOKS = frozenset(
    {
        "hook.web.code_output.shell",
        "hook.web.code_output.shell_step",
        "hook.web.code_output.shell_history",
        "hook.web.source.shell",
    }
)
DIRECT_CDP_HOOKS = frozenset(
    {
        "hook.web.playwright.cdp",
        "hook.web.playwright.cdp_process",
        "hook.web.code_output.page_exec",
    }
)
_HOST_ESCAPE = re.compile(
    r"(?:\bsubprocess\b|\bPopen\b|\bos\.system\b|\bopen\s*\(|\bPath\s*\(|"
    r"\bconnect_over_cdp\b|\bcdp_url\b|\bchromium\.connect\b|"
    r"\bread_text\b|\bwrite_text\b|\bPath\.home\b|/etc/passwd|C:\\\\Users)",
    re.IGNORECASE,
)
_ALLOWED_RUNTIME = re.compile(
    r"^qa_runtime\.(click|fill|scroll|select)\((.*)\)$",
    re.DOTALL,
)


class CuawrightRejected(Exception):
    """CUAWright hook, host escape, or approval package was refused."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class StepRawSource:
    step_index: int
    hook: str
    code: str
    code_digest: str


@dataclass(frozen=True, slots=True)
class StepSummary:
    step_index: int
    action_type: str
    selector: str
    value: str
    accepted: bool
    reject_reason: str


@dataclass(frozen=True, slots=True)
class RecordingBundle:
    """Separated raw sources and allowlisted summaries for one trajectory."""

    trajectory_complete: bool
    raw_sources: tuple[StepRawSource, ...]
    summaries: tuple[StepSummary, ...]
    reviewable_source: str
    source_digest: str
    package_ready: bool
    reject_reason: str


@dataclass(frozen=True, slots=True)
class ApprovalPackageDraft:
    digest: str
    revision: str
    origin: str
    body_hash: str
    compiled: CompiledPackage
    evidence_before: tuple[str, ...]
    evidence_after: tuple[str, ...]


class CuawrightWebAdapter:
    """Capture fixture plus fixed-hook extraction. Upstream CUAWright is never imported."""

    def before_capture(self, proposal: ActionProposal, observation: Observation) -> Observation:
        if observation.platform != "web" or not observation.capture_ok:
            return replace(observation, capture_ok=False, png=b"")
        return observation

    def extract_trajectory(self, trajectory: Mapping[str, object]) -> RecordingBundle:
        """Split step raw source from summary. Truncated runs cannot approve."""

        if type(trajectory) is not dict:
            raise CuawrightRejected("trajectory must be an object")
        complete = trajectory.get("complete") is True
        steps = trajectory.get("steps")
        if type(steps) is not list:
            raise CuawrightRejected("trajectory steps are required")
        raws: list[StepRawSource] = []
        summaries: list[StepSummary] = []
        accepted_lines: list[str] = []
        reject = ""
        for index, item in enumerate(steps):
            if type(item) is not dict:
                raise CuawrightRejected("step must be an object")
            hook = item.get("hook")
            code = item.get("code")
            if type(hook) is not str or hook.strip() == "":
                raise CuawrightRejected("step hook is required")
            if type(code) is not str:
                raise CuawrightRejected("step code is required")
            if hook in SHELL_HOOKS:
                raise CuawrightRejected("workspace shell is forbidden")
            if hook in DIRECT_CDP_HOOKS:
                raise CuawrightRejected("direct CDP is forbidden")
            if hook not in STEP_SOURCE_HOOKS:
                raise CuawrightRejected("unsupported hook")
            if _HOST_ESCAPE.search(code):
                raise CuawrightRejected("generated code host read is forbidden")
            digest = "sha256:" + hashlib.sha256(code.encode("utf-8")).hexdigest()
            raws.append(StepRawSource(index, hook, code, digest))
            summary = self._summarize(index, code, item.get("summary"))
            summaries.append(summary)
            if summary.accepted:
                accepted_lines.append(_runtime_line(summary))
            elif reject == "":
                reject = summary.reject_reason
        reviewable = "\n".join(accepted_lines)
        source_digest = "sha256:" + hashlib.sha256(reviewable.encode("utf-8")).hexdigest()
        package_ready = complete and bool(accepted_lines) and all(item.accepted for item in summaries)
        if not complete:
            reject = reject or "trajectory is truncated"
            package_ready = False
        return RecordingBundle(
            complete,
            tuple(raws),
            tuple(summaries),
            reviewable,
            source_digest,
            package_ready,
            "" if package_ready else reject or "package is not ready",
        )

    def assert_replay_source_unchanged(self, bundle: RecordingBundle, live_source: str) -> None:
        """Refuse unauthorized code edits during replay."""

        live = "sha256:" + hashlib.sha256(live_source.encode("utf-8")).hexdigest()
        if live != bundle.source_digest:
            raise CuawrightRejected("unauthorized code modification during replay")

    def build_approval_package(
        self,
        bundle: RecordingBundle,
        *,
        origin: str,
        revision: str,
        manifest: RecordingManifest,
        lock_hash: str,
    ) -> ApprovalPackageDraft:
        if not bundle.package_ready:
            raise CuawrightRejected(bundle.reject_reason or "package is not ready")
        if not require_web_ready(True):
            raise CuawrightRejected("web ready is missing")
        compiler = CompilerRef("web-ipc-subset", lock_hash, bundle.reviewable_source)
        compiled = compile_replay_package(manifest, compiler)
        plan_hash = compiled.body.approved_code_or_plan_hash
        digest = plan_hash if plan_hash.startswith("sha256:") else "sha256:" + plan_hash
        return ApprovalPackageDraft(
            digest=digest,
            revision=revision,
            origin=origin,
            body_hash=compiled.body_hash,
            compiled=compiled,
            evidence_before=(),
            evidence_after=(),
        )

    def run_allowlisted_steps(
        self,
        bundle: RecordingBundle,
        *,
        approved: ApprovedWebPackage,
        gate: WebIsolationGate,
        proof: IsolationProof,
        before: Observation,
        after: Observation,
        spool: Path,
        now: datetime | None = None,
        presented_digest: str | None = None,
        presented_revision: str | None = None,
        page_origin: str | None = None,
        runner=None,
    ) -> tuple[WebDispatchResult, ...]:
        """Execute only allowlisted summaries through TrustedWebDriver."""

        if not bundle.package_ready:
            raise CuawrightRejected(bundle.reject_reason or "package is not ready")
        if not gate.web_ready(proof, now=now):
            raise CuawrightRejected("web ready is missing")
        clock = now or datetime.now(timezone.utc)
        driver = TrustedWebDriver(
            "ws://127.0.0.1:0/devtools/browser/private",
            approved=approved,
            gate=gate,
            proof=proof,
            spool=spool,
            runner=runner,
            now=clock,
        )
        results: list[WebDispatchResult] = []
        for summary in bundle.summaries:
            if not summary.accepted:
                raise CuawrightRejected(summary.reject_reason)
            payload: dict[str, object] = {"type": summary.action_type, "selector": summary.selector}
            if summary.value:
                payload["value"] = summary.value
            try:
                result = driver.run(
                    before=before,
                    action=payload,
                    presented_digest=presented_digest or approved.digest,
                    presented_revision=presented_revision or approved.revision,
                    page_origin=page_origin or approved.origin,
                    after=after,
                )
            except WebDispatchError as exc:
                raise CuawrightRejected(str(exc)) from exc
            results.append(result)
        if driver.ai_calls != 0:
            raise CuawrightRejected("replay actor AI is forbidden")
        return tuple(results)

    def _summarize(self, index: int, code: str, declared: object) -> StepSummary:
        stripped = code.strip()
        if "\n" in stripped or ";" in stripped:
            return StepSummary(index, "", "", "", False, "compound step is rejected")
        match = _ALLOWED_RUNTIME.match(stripped)
        if match is None:
            return StepSummary(index, "", "", "", False, "step is outside allowlist")
        action_type = match.group(1)
        if action_type not in WEB_ACTION_TYPES:
            return StepSummary(index, "", "", "", False, "unsupported action")
        try:
            args = ast_strings(match.group(2))
        except ValueError:
            return StepSummary(index, "", "", "", False, "step arguments are invalid")
        needed = 2 if action_type in {"fill", "select"} else 1
        if len(args) != needed:
            return StepSummary(index, "", "", "", False, "step arity mismatch")
        selector = args[0]
        value = args[1] if needed == 2 else ""
        if declared is not None:
            if type(declared) is not dict:
                return StepSummary(index, "", "", "", False, "summary mismatch")
            if declared.get("type") != action_type or declared.get("selector") != selector:
                return StepSummary(index, "", "", "", False, "summary mismatch")
            if needed == 2 and declared.get("value") != value:
                return StepSummary(index, "", "", "", False, "summary mismatch")
        try:
            parse_ipc_message({"type": action_type, "selector": selector, "value": value})
        except ValueError:
            return StepSummary(index, "", "", "", False, "ipc allowlist rejected step")
        return StepSummary(index, action_type, selector, value, True, "")


def ast_strings(argument_source: str) -> tuple[str, ...]:
    """Parse only string literal arguments. No evaluation."""

    import ast

    try:
        node = ast.parse(f"f({argument_source})", mode="eval")
    except SyntaxError as exc:
        raise ValueError("arguments") from exc
    if type(node.body) is not ast.Call:
        raise ValueError("arguments")
    values: list[str] = []
    for arg in node.body.args:
        if type(arg) is not ast.Constant or type(arg.value) is not str or arg.value.strip() == "":
            raise ValueError("arguments")
        values.append(arg.value)
    if node.body.keywords:
        raise ValueError("arguments")
    return tuple(values)


def _runtime_line(summary: StepSummary) -> str:
    if summary.action_type in {"fill", "select"}:
        return f"qa_runtime.{summary.action_type}({summary.selector!r}, {summary.value!r})"
    return f"qa_runtime.{summary.action_type}({summary.selector!r})"


def make_recording_manifest(*, raw_source: str, project_id: UUID | None = None) -> RecordingManifest:
    """Minimal manifest whose source hash matches the reviewable source."""

    digest = hashlib.sha256(raw_source.encode("utf-8")).hexdigest()
    return RecordingManifest(
        project_id=project_id or uuid4(),
        case_id=uuid4(),
        recording_id=uuid4(),
        manifest_id=uuid4(),
        revision=1,
        kind="original",
        prior_manifest_id=None,
        input_version_hash="input-hash",
        source_artifact_hashes=json.dumps([digest]),
        action_mapping="{}",
        evidence_completeness="complete",
        request_key="rx15",
        body_hash="manifest-hash",
    )
