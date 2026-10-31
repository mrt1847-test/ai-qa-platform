"""W00-01: the package installs from an isolated environment and imports outside the repo."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def test_w00_01():
    outside = Path(tempfile.mkdtemp(prefix="aiqa-w00-"))
    assert REPO not in outside.parents
    imported = _run(
        [
            sys.executable,
            "-c",
            "import aiqa, importlib.metadata; print(importlib.metadata.version('aiqa')); print(aiqa.__file__)",
        ],
        outside,
    )
    imported_ok = imported.returncode == 0 and bool(imported.stdout.strip())
    if imported_ok:
        version, location = imported.stdout.splitlines()[:2]
        imported_ok = bool(version) and location.replace("\\", "/").endswith("aiqa/__init__.py")
    dependency_check = _run([sys.executable, "-m", "pip", "check"], REPO)
    collected = _run([sys.executable, "-m", "pytest", "--collect-only", "-q", "tests"], REPO)
    w01_01 = _run(
        [sys.executable, "-m", "pytest", "tests/integration/test_w01.py::test_w01_01", "-q"],
        REPO,
    )
    observed = {
        "installed_import_outside_repo": imported_ok,
        "dependency_check_ok": dependency_check.returncode == 0 and "No broken requirements" in dependency_check.stdout,
        "pytest_collects": collected.returncode == 0,
        "existing_w01_01_passes": w01_01.returncode == 0,
        "global_environment_required": sys.prefix == sys.base_prefix,
    }
    assert observed == {
        "installed_import_outside_repo": True,
        "dependency_check_ok": True,
        "pytest_collects": True,
        "existing_w01_01_passes": True,
        "global_environment_required": False,
    }
