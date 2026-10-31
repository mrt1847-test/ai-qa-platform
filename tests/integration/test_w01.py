"""W01-01: pinned CUAWright source boundaries are read from the tree."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import pytest

from aiqa.contracts.common import EngineRef
from aiqa.probes.cuawright_source import (
    PINNED_SOURCE_SHA,
    WRITER_KINDS,
    inspect_cuawright_source,
    inventory_document,
)

REPO = Path(__file__).resolve().parents[2]
TREE = REPO / "third_party" / "cuawright" / "upstream"
PROBE = REPO / "src" / "aiqa" / "probes" / "cuawright_source.py"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _locations_exist(inventory) -> bool:
    groups = (
        inventory.files,
        inventory.code_outputs,
        inventory.writers,
        inventory.action_calls,
    )
    if not any(groups):
        return False
    for group in groups:
        for loc in group:
            file_path = TREE / loc.path
            if not file_path.is_file():
                return False
            lines = file_path.read_text(encoding="utf-8").splitlines()
            if loc.line < 1 or loc.line > len(lines):
                return False
            if loc.anchor not in lines[loc.line - 1]:
                return False
    return True


def _probe_does_not_execute_generated_code() -> bool:
    parsed = ast.parse(PROBE.read_text(encoding="utf-8"))
    for node in ast.walk(parsed):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "subprocess" or alias.name.startswith("cuawright"):
                    return False
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "subprocess" or module.startswith("cuawright"):
                return False
        elif isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else ""
            if name in {"exec", "eval", "compile"}:
                return False
    return True


def test_w01_01():
    license_text = (TREE / "LICENSE").read_text(encoding="utf-8")
    notice_text = (TREE / "NOTICE").read_text(encoding="utf-8")
    pyproject = (TREE / "pyproject.toml").read_text(encoding="utf-8")
    commit = (REPO / "third_party" / "cuawright" / "COMMIT").read_text(encoding="utf-8").strip()
    assert "MIT License" in license_text
    assert "Apache-2.0" in notice_text
    assert 'license = "MIT AND Apache-2.0"' in pyproject
    assert commit == PINNED_SOURCE_SHA

    inventory = inspect_cuawright_source(
        EngineRef(
            source_sha=commit,
            patch_hash="",
            dependency_lock_hash="",
            adapter_version="",
        )
    )
    with pytest.raises(ValueError):
        inspect_cuawright_source(
            EngineRef(
                source_sha="0" * 40,
                patch_hash="",
                dependency_lock_hash="",
                adapter_version="",
            )
        )

    unclassified = sum(1 for writer in inventory.writers if writer.kind not in WRITER_KINDS)
    kinds = {loc.kind for loc in (*inventory.writers, *inventory.action_calls, *inventory.code_outputs)}
    observed = {
        "sha": inventory.source_sha if inventory.source_sha == commit else "",
        "all_locations_exist": _locations_exist(inventory),
        "unclassified_writers": unclassified,
    }
    assert inventory.executes_generated_code is False
    assert _probe_does_not_execute_generated_code()
    assert inventory.license_sha256 == _sha256(TREE / "LICENSE")
    assert inventory.notice_sha256 == _sha256(TREE / "NOTICE")
    assert {"code_output", "direct_playwright", "llm_helper", "png_debug"} <= kinds
    assert inventory.code_outputs
    assert inventory.writers
    assert all(writer.hook for writer in inventory.writers)
    published = json.loads((REPO / "third_party" / "cuawright" / "SOURCE.json").read_text(encoding="utf-8"))
    assert published == inventory_document(inventory)
    assert observed == {
        "sha": "35dbcf389ce2d9a77eb22f539c79a1274ea53559",
        "all_locations_exist": True,
        "unclassified_writers": 0,
    }


def test_w01_02():
    from aiqa.replay.ipc import parse_ipc_message
    from aiqa.worker.isolated_web import VmProbeConfig, probe_web_isolation

    with pytest.raises(ValueError):
        parse_ipc_message({"type": "click", "cdp_url": "ws://127.0.0.1:9222/devtools/browser"})

    report = probe_web_isolation(VmProbeConfig(backend="hyper-v", destroy_after=True))
    script_rows = [item for item in report.evidence if item.kind == "synthetic_script"]
    if len(script_rows) != 1:
        observed = {
            "driver_ipc": None,
            "direct_cdp": None,
            "script_model_network": None,
            "host_secret_access": None,
        }
    else:
        payload = json.loads(script_rows[0].detail)
        observed = {
            "driver_ipc": payload["driver_ipc"],
            "direct_cdp": payload["direct_cdp"],
            "script_model_network": payload["script_model_network"],
            "host_secret_access": payload["host_secret_access"],
        }
    assert observed == {
        "driver_ipc": True,
        "direct_cdp": False,
        "script_model_network": False,
        "host_secret_access": False,
    }
