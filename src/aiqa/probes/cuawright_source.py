"""Read the pinned CUAWright tree and list output, write, and action boundaries.

This module never imports CUAWright and never runs generated code.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from aiqa.contracts.common import EngineRef

PINNED_SOURCE_SHA = "35dbcf389ce2d9a77eb22f539c79a1274ea53559"
LICENSE_SPDX = "MIT AND Apache-2.0"
WRITER_KINDS = frozenset({"code_output", "direct_playwright", "llm_helper", "png_debug"})

_REPO = Path(__file__).resolve().parents[3]
_VENDOR = _REPO / "third_party" / "cuawright"
_TREE = _VENDOR / "upstream"
_COMMIT = _VENDOR / "COMMIT"
_MANIFEST = _VENDOR / "TREE_MANIFEST.sha256"


@dataclass(frozen=True)
class SourceLocation:
    path: str
    line: int
    symbol: str
    anchor: str
    kind: str
    hook: str


@dataclass(frozen=True)
class SourceInventory:
    files: tuple[SourceLocation, ...]
    code_outputs: tuple[SourceLocation, ...]
    writers: tuple[SourceLocation, ...]
    action_calls: tuple[SourceLocation, ...]
    source_sha: str
    executes_generated_code: bool
    license_spdx: str
    license_sha256: str
    notice_sha256: str


def _loc(path: str, line: int, symbol: str, anchor: str, kind: str, hook: str) -> SourceLocation:
    return SourceLocation(path, line, symbol, anchor, kind, hook)


_FILES = (
    _loc("LICENSE", 1, "LICENSE", "MIT License", "source_file", "hook.web.source.license"),
    _loc("NOTICE", 1, "NOTICE", "CUAWright includes the Webwright browser runtime", "source_file", "hook.web.source.notice"),
    _loc("pyproject.toml", 10, "project.license", 'license = "MIT AND Apache-2.0"', "source_file", "hook.web.source.license"),
    _loc("licenses/OSWorld-runtime-APACHE-2.0.txt", 1, "OSWorld-runtime", "Apache License", "source_file", "hook.web.source.license"),
    _loc("src/cuawright/webwright/config/base.yaml", 54, "environment_class", "environment_class: local_workspace", "source_file", "hook.web.source.workspace_config"),
    _loc("src/cuawright/webwright/config/base.yaml", 58, "shell", "shell: /bin/bash", "source_file", "hook.web.source.shell"),
    _loc("src/cuawright/webwright/config/base.yaml", 65, "browser_mode", "browser_mode: local", "source_file", "hook.web.source.browser_mode"),
    _loc("src/cuawright/webwright/run/cli.py", 32, "run_one", "def run_one(", "source_file", "hook.web.source.run_one"),
    _loc("src/cuawright/webwright/run/cli.py", 83, "trajectory_output", '"output_path": str(resolved_output_dir / "trajectory.json")', "source_file", "hook.web.writer.trajectory"),
)

_CODE_OUTPUTS = (
    _loc("src/cuawright/webwright/environments/local_browser.py", 424, "_persist_step_code", "step_path.write_text(python_code, encoding=\"utf-8\")", "code_output", "hook.web.code_output.step_script"),
    _loc("src/cuawright/webwright/environments/local_browser.py", 427, "_persist_step_code", "with script_path.open(\"a\", encoding=\"utf-8\") as handle:", "code_output", "hook.web.code_output.script_py"),
    _loc("src/cuawright/webwright/environments/local_browser.py", 442, "_run_python_code", "exec(wrapped, globals_dict, locals_dict)", "code_output", "hook.web.code_output.page_exec"),
    _loc("src/cuawright/webwright/environments/local_workspace.py", 175, "_persist_step_command", "step_path.write_text(command.rstrip() + \"\\n\", encoding=\"utf-8\")", "code_output", "hook.web.code_output.shell_step"),
    _loc("src/cuawright/webwright/environments/local_workspace.py", 178, "_persist_step_command", "with history_path.open(\"a\", encoding=\"utf-8\") as handle:", "code_output", "hook.web.code_output.shell_history"),
    _loc("src/cuawright/webwright/environments/local_workspace.py", 232, "execute", "result = subprocess.run(", "code_output", "hook.web.code_output.shell"),
    _loc("src/cuawright/webwright/tools/browser_session.py", 732, "_run_step_code", "exec(wrapped, {\"__builtins__\": __builtins__}, namespace)", "code_output", "hook.web.code_output.page_exec"),
    _loc("src/cuawright/webwright/tools/browser_session.py", 823, "_cmd_step", "code_path.write_text(code.rstrip() + \"\\n\", encoding=\"utf-8\")", "code_output", "hook.web.code_output.step_script"),
    _loc("extensions/skill-factory/src/cuawright/webwright/skill_factory/library.py", 55, "Library.add", "(d / \"skill.py\").write_text(skill.code, encoding=\"utf-8\")", "code_output", "hook.web.code_output.skill_py"),
    _loc("extensions/skill-factory/src/cuawright/webwright/skill_factory/update.py", 103, "_replay", "(tdp / \"skill.py\").write_text(code, encoding=\"utf-8\")", "code_output", "hook.web.code_output.skill_py"),
    _loc("extensions/skill-factory/src/cuawright/webwright/skill_factory/update.py", 110, "_replay", "proc = subprocess.run([sys.executable, \"skill.py\", \"taskspec.json\"], cwd=td,", "code_output", "hook.web.code_output.run_skill"),
    _loc("extensions/skill-factory/src/cuawright/webwright/skill_factory/execute.py", 40, "run_skill", "(tdp / \"taskspec.json\").write_text(json.dumps(", "code_output", "hook.web.code_output.taskspec"),
    _loc("extensions/skill-factory/src/cuawright/webwright/skill_factory/execute.py", 44, "run_skill", "proc = subprocess.run(", "code_output", "hook.web.code_output.run_skill"),
)

_WRITERS = (
    _CODE_OUTPUTS[0],
    _CODE_OUTPUTS[1],
    _CODE_OUTPUTS[3],
    _CODE_OUTPUTS[4],
    _CODE_OUTPUTS[7],
    _CODE_OUTPUTS[8],
    _CODE_OUTPUTS[9],
    _CODE_OUTPUTS[11],
    _loc("src/cuawright/webwright/environments/local_browser.py", 247, "prepare", "(self.config.output_dir / \"task.json\").write_text(", "png_debug", "hook.web.writer.task_metadata"),
    _loc("src/cuawright/webwright/environments/local_browser.py", 487, "_capture_observation", "await page.screenshot(path=str(screenshot_path), full_page=False)", "png_debug", "hook.web.writer.screenshot"),
    _loc("src/cuawright/webwright/environments/local_workspace.py", 189, "_write_step_log", "log_path.write_text(output, encoding=\"utf-8\")", "png_debug", "hook.web.writer.step_log"),
    _loc("src/cuawright/webwright/environments/local_workspace.py", 204, "prepare", "self._task_metadata_path().write_text(json.dumps(kwargs, indent=2), encoding=\"utf-8\")", "png_debug", "hook.web.writer.task_metadata"),
    _loc("src/cuawright/webwright/agents/default.py", 145, "_write_debug_step_artifact", "(steps_dir / f\"step_{step_index:04d}.json\").write_text(json.dumps(payload, indent=2))", "png_debug", "hook.web.writer.debug_step"),
    _loc("src/cuawright/webwright/agents/default.py", 148, "_write_debug_step_artifact", "with summary_path.open(\"a\", encoding=\"utf-8\") as handle:", "png_debug", "hook.web.writer.debug_markdown"),
    _loc("src/cuawright/webwright/agents/default.py", 519, "save", "path.write_text(json.dumps(data, indent=2))", "png_debug", "hook.web.writer.trajectory"),
    _loc("src/cuawright/webwright/utils/logging.py", 19, "append_runtime_log", "with path.open(\"a\", encoding=\"utf-8\") as handle:", "png_debug", "hook.web.writer.runtime_log"),
    _loc("src/cuawright/webwright/config/__init__.py", 103, "snapshot_config_specs", "saved_copy.write_text(", "png_debug", "hook.web.writer.config_snapshot"),
    _loc("src/cuawright/webwright/config/__init__.py", 116, "snapshot_config_specs", "(snapshot_dir / \"config_spec_manifest.json\").write_text(", "png_debug", "hook.web.writer.config_snapshot"),
    _loc("src/cuawright/webwright/config/__init__.py", 121, "snapshot_config_specs", "(snapshot_dir / \"merged_config.yaml\").write_text(", "png_debug", "hook.web.writer.config_snapshot"),
    _loc("src/cuawright/webwright/tools/browser_session.py", 343, "_atomic_write_private_json", "json.dump(payload, handle, indent=2, ensure_ascii=False, sort_keys=True)", "png_debug", "hook.web.writer.session_state"),
    _loc("src/cuawright/webwright/tools/browser_session.py", 913, "_cmd_step", "await page.screenshot(", "png_debug", "hook.web.writer.screenshot"),
    _loc("src/cuawright/webwright/tools/self_reflection.py", 642, "main", "Path(args.output).write_text(serialized, encoding=\"utf-8\")", "png_debug", "hook.web.writer.reflection_result"),
    _loc("src/cuawright/webwright/tools/persistent_local_browser.py", 163, "_cmd_create", "out_path.write_text(json.dumps(session, indent=2) + \"\\n\", encoding=\"utf-8\")", "png_debug", "hook.web.writer.session_state"),
    _loc("src/cuawright/webwright/run/doctor.py", 60, "check_screenshot", "page.screenshot(path=str(screenshot_path))", "png_debug", "hook.web.writer.doctor_screenshot"),
)

_ACTIONS = (
    _loc("src/cuawright/webwright/environments/local_browser.py", 289, "_ensure_local_cdp_browser", "self._local_cdp_process = subprocess.Popen(", "direct_playwright", "hook.web.playwright.cdp_process"),
    _loc("src/cuawright/webwright/environments/local_browser.py", 316, "_prepare_async", "self._playwright = await async_playwright().start()", "direct_playwright", "hook.web.playwright.launch"),
    _loc("src/cuawright/webwright/environments/local_browser.py", 330, "_prepare_async", "self._browser = await chromium.connect_over_cdp(self.config.local_cdp_url)", "direct_playwright", "hook.web.playwright.cdp"),
    _loc("src/cuawright/webwright/environments/local_browser.py", 344, "_prepare_async", "self._context = await chromium.launch_persistent_context(", "direct_playwright", "hook.web.playwright.launch"),
    _loc("src/cuawright/webwright/environments/local_browser.py", 355, "_prepare_async", "self._browser = await chromium.launch(**launch_kwargs)", "direct_playwright", "hook.web.playwright.launch"),
    _loc("src/cuawright/webwright/environments/local_browser.py", 368, "_prepare_async", "await self._page.goto(self.config.start_url, wait_until=\"domcontentloaded\")", "direct_playwright", "hook.web.playwright.navigate"),
    _CODE_OUTPUTS[2],
    _loc("src/cuawright/webwright/environments/local_browser.py", 487, "_capture_observation", "await page.screenshot(path=str(screenshot_path), full_page=False)", "direct_playwright", "hook.web.playwright.screenshot"),
    _CODE_OUTPUTS[5],
    _loc("src/cuawright/webwright/tools/browser_session.py", 223, "open_browser_session", "return await playwright.chromium.connect_over_cdp(connect_url)", "direct_playwright", "hook.web.playwright.cdp"),
    _CODE_OUTPUTS[6],
    _loc("src/cuawright/webwright/tools/browser_session.py", 913, "_cmd_step", "await page.screenshot(", "direct_playwright", "hook.web.playwright.screenshot"),
    _loc("src/cuawright/webwright/tools/persistent_local_browser.py", 144, "_cmd_create", "proc = subprocess.Popen(chromium_args, **popen_kwargs)  # noqa: S603", "direct_playwright", "hook.web.playwright.cdp_process"),
    _loc("src/cuawright/webwright/run/doctor.py", 54, "check_screenshot", "browser = p.chromium.launch(headless=True)", "direct_playwright", "hook.web.playwright.launch"),
    _loc("src/cuawright/webwright/run/doctor.py", 60, "check_screenshot", "page.screenshot(path=str(screenshot_path))", "direct_playwright", "hook.web.playwright.screenshot"),
    _loc("src/cuawright/webwright/agents/default.py", 478, "execute_actions", "outputs = [self.env.execute(action) for action in extra.get(\"actions\", [])]", "code_output", "hook.web.action.dispatch"),
    _CODE_OUTPUTS[10],
    _CODE_OUTPUTS[12],
    _loc("src/cuawright/webwright/models/base.py", 688, "query", "def query(self, messages: list[dict[str, Any]], **kwargs) -> dict[str, Any]:", "llm_helper", "hook.web.llm.query"),
    _loc("src/cuawright/webwright/models/openai_model.py", 172, "_usage_metrics_from_response_payload", "def _usage_metrics_from_response_payload(payload: dict[str, Any]) -> dict[str, int]:", "llm_helper", "hook.web.llm.usage"),
    _loc("src/cuawright/webwright/tools/image_qa.py", 71, "run_image_qa", "def run_image_qa(", "llm_helper", "hook.web.llm.image_qa"),
    _loc("src/cuawright/webwright/tools/self_reflection.py", 403, "run_self_reflection_async", "async def run_self_reflection_async(", "llm_helper", "hook.web.llm.self_reflection"),
    _loc("extensions/skill-factory/src/cuawright/webwright/skill_factory/llm.py", 83, "llm_json", "def llm_json(system: str, user: str, **kw: Any) -> dict:", "llm_helper", "hook.web.llm.skill_factory"),
    _loc("extensions/skill-factory/src/cuawright/webwright/skill_factory/retrieve.py", 47, "_retrieve_llm", "out = llm_json(sys, user)", "llm_helper", "hook.web.llm.skill_factory"),
    _loc("extensions/skill-factory/src/cuawright/webwright/skill_factory/decide.py", 39, "_decide_llm", "out = llm_json(sys, user)", "llm_helper", "hook.web.llm.skill_factory"),
    _loc("extensions/skill-factory/src/cuawright/webwright/skill_factory/fill.py", 55, "fill_params", "out = llm_json(_SYS, user)", "llm_helper", "hook.web.llm.skill_factory"),
    _loc("extensions/skill-factory/src/cuawright/webwright/skill_factory/learn.py", 72, "canonicalize_answers", "out = llm_json(_CANON_SYS, f\"## Template\\n{template}\\n\\n## Answers\\n{listing}\")", "llm_helper", "hook.web.llm.skill_factory"),
    _loc("extensions/skill-factory/src/cuawright/webwright/tools/skill_use.py", 58, "recommend", "def recommend(task: str, library_root: str) -> dict:", "llm_helper", "hook.web.llm.recommend"),
    _loc("extensions/skill-factory/src/cuawright/webwright/skill_factory/route.py", 127, "route", "def route(task: str, library: str, *, recommend_fn=None, run_skill_fn=run_skill,", "llm_helper", "hook.web.llm.route"),
    _loc("src/cuawright/webwright/agents/default.py", 439, "query", "def query(self) -> dict[str, Any]:", "llm_helper", "hook.web.llm.query"),
    _loc("src/cuawright/webwright/agents/default.py", 448, "query", "message = self.model.query(self.messages)", "llm_helper", "hook.web.llm.query"),
    _loc("src/cuawright/webwright/utils/browser_evidence.py", 97, "task_screenshot_paths", "def task_screenshot_paths(workspace_dir: str | Path) -> list[Path]:", "png_debug", "hook.web.writer.screenshot_index"),
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_manifest(path: Path) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, rel = line.split("  ", 1)
        rows.append((digest, rel))
    return rows


def _require_tree_integrity() -> None:
    if not _TREE.is_dir():
        raise ValueError(f"CUAWright tree is missing: {_TREE}")
    commit = _COMMIT.read_text(encoding="utf-8").strip()
    if commit != PINNED_SOURCE_SHA:
        raise ValueError("vendored COMMIT does not match the pinned CUAWright SHA")
    for digest, rel in _read_manifest(_MANIFEST):
        file_path = _TREE / rel
        if not file_path.is_file() or _sha256(file_path) != digest:
            raise ValueError(f"vendored file does not match the pinned tree manifest: {rel}")


def _require_anchors() -> None:
    for loc in (*_FILES, *_CODE_OUTPUTS, *_WRITERS, *_ACTIONS):
        file_path = _TREE / loc.path
        if not file_path.is_file():
            raise ValueError(f"inventory file is missing: {loc.path}")
        lines = file_path.read_text(encoding="utf-8").splitlines()
        if loc.line < 1 or loc.line > len(lines) or loc.anchor not in lines[loc.line - 1]:
            raise ValueError(f"inventory anchor mismatch: {loc.path}:{loc.line} {loc.symbol}")
        if loc.kind not in WRITER_KINDS and loc.kind != "source_file":
            raise ValueError(f"inventory kind is not classified: {loc.path}:{loc.line}")


def inspect_cuawright_source(source: EngineRef) -> SourceInventory:
    """Return the pinned source boundary list. Does not run generated code."""
    if source.source_sha != PINNED_SOURCE_SHA:
        raise ValueError("source_sha is not the pinned CUAWright revision")
    _require_tree_integrity()
    _require_anchors()
    license_path = _TREE / "LICENSE"
    notice_path = _TREE / "NOTICE"
    license_text = license_path.read_text(encoding="utf-8")
    notice_text = notice_path.read_text(encoding="utf-8")
    pyproject = (_TREE / "pyproject.toml").read_text(encoding="utf-8")
    if "MIT License" not in license_text or "Apache-2.0" not in notice_text:
        raise ValueError("LICENSE or NOTICE does not match the recorded dual-license boundary")
    if f'license = "{LICENSE_SPDX}"' not in pyproject:
        raise ValueError("pyproject license is not MIT AND Apache-2.0")
    return SourceInventory(
        files=_FILES,
        code_outputs=_CODE_OUTPUTS,
        writers=_WRITERS,
        action_calls=_ACTIONS,
        source_sha=source.source_sha,
        executes_generated_code=False,
        license_spdx=LICENSE_SPDX,
        license_sha256=_sha256(license_path),
        notice_sha256=_sha256(notice_path),
    )


def inventory_document(inventory: SourceInventory) -> dict:
    """Serializable boundary list. Secret values are not part of this document."""
    def rows(items: tuple[SourceLocation, ...]) -> list[dict[str, object]]:
        return [asdict(item) for item in items]

    return {
        "sha": inventory.source_sha,
        "license_spdx": inventory.license_spdx,
        "license_sha256": inventory.license_sha256,
        "notice_sha256": inventory.notice_sha256,
        "executes_generated_code": inventory.executes_generated_code,
        "patch_status": "none",
        "excluded": [
            {
                "path_prefix": "release/",
                "reason": "Imported desktop OSWorld runtime is outside the Web authoring boundary.",
            },
            {
                "path_prefix": "extensions/skill-factory/src/cuawright/webwright/skill_factory/examples/",
                "reason": "Sample final_script and skill outputs are not the generator.",
            },
            {
                "path_prefix": "assets/",
                "reason": "Demo mp4 and png files are not execution boundaries and are omitted from the text snapshot.",
            },
        ],
        "files": rows(inventory.files),
        "code_outputs": rows(inventory.code_outputs),
        "writers": rows(inventory.writers),
        "action_calls": rows(inventory.action_calls),
    }


def write_source_json(inventory: SourceInventory, path: Path) -> None:
    path.write_text(
        json.dumps(inventory_document(inventory), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
