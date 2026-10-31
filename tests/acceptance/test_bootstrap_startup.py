"""W00-04: one owned server process serves health, page, and CSS, then releases its port."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[2]
PAGE_TITLE = "AI QA 기본 실행 환경"
_MODEL_KEYS = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "AIQA_MODEL_KEY",
)
_BROWSERS = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
)


@dataclass(frozen=True)
class BootstrapSmokeReport:
    real_http_health: bool
    real_page_and_css: bool
    owned_process_stopped: bool
    port_released: bool
    vm_or_api_key_required: bool
    existing_block_preserved: bool


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _browser() -> Path | None:
    return next((path for path in _BROWSERS if path.is_file()), None)


def _port_is_free(port: int) -> bool:
    deadline = time.monotonic() + 5
    while True:
        try:
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.1)


def _process_stopped(proc: subprocess.Popen[str]) -> bool:
    if proc.poll() is None:
        return False
    if sys.platform != "win32":
        return True
    import ctypes

    still_active = 259
    query = 0x1000
    handle = ctypes.windll.kernel32.OpenProcess(query, False, proc.pid)
    if not handle:
        return True
    try:
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        return code.value != still_active
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def _wait_for_health(port: int, proc: subprocess.Popen[str]) -> httpx.Response | None:
    deadline = time.monotonic() + 20
    url = f"http://127.0.0.1:{port}/api/v1/health"
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return None
        try:
            response = httpx.get(url, timeout=0.5)
        except httpx.HTTPError:
            time.sleep(0.1)
            continue
        if response.status_code == 200:
            return response
        time.sleep(0.1)
    return None


def _browser_dom(browser: Path, url: str, work: Path) -> str:
    profile = work / "browser-profile"
    profile.mkdir()
    chrome = subprocess.Popen(
        [
            str(browser),
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            f"--user-data-dir={profile}",
            "--virtual-time-budget=5000",
            "--dump-dom",
            url,
        ],
        cwd=work,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        stdout, _stderr = chrome.communicate(timeout=40)
    except subprocess.TimeoutExpired:
        chrome.kill()
        chrome.wait(timeout=5)
        return ""
    return stdout.decode("utf-8", errors="replace")


def _block_preserved() -> bool:
    source = (REPO / "tests" / "integration" / "test_w01.py").read_text(encoding="utf-8")
    handoff = (REPO / "docs" / "validation" / "tasks" / "W01-02.md").read_text(encoding="utf-8")
    index = json.loads((REPO / "docs" / "execution" / "TASK_INDEX.json").read_text(encoding="utf-8"))
    task = next(item for item in index["tasks"] if item["id"] == "W01-02")
    return (
        "def test_w01_02():" in source
        and "pytest.skip" not in source
        and "pytest.mark.skip" not in source
        and '"driver_ipc": None' in source
        and '"driver_ipc": True' in source
        and handoff.startswith("# W01-02")
        and "- 상태: blocked" in handoff
        and task["status"] == "blocked"
    )


def _guides_present() -> bool:
    readme = REPO / "README.md"
    guide = REPO / "docs" / "validation" / "bootstrap.md"
    if not readme.is_file() or not guide.is_file():
        return False
    text = readme.read_text(encoding="utf-8")
    report = guide.read_text(encoding="utf-8")
    required = (
        'python -m pip install -e ".[dev]" -c requirements.lock',
        "python -m uvicorn aiqa.api.app:create_app --factory --host 127.0.0.1 --port 8000",
        "/api/v1/health",
        "W01-02",
        "Ctrl+C",
    )
    fields = (
        "BootstrapSmokeReport",
        "real_http_health",
        "real_page_and_css",
        "owned_process_stopped",
        "port_released",
        "vm_or_api_key_required",
        "existing_block_preserved",
    )
    return all(item in text for item in required) and all(item in report for item in fields)


def test_w00_04(tmp_path: Path) -> None:
    assert _guides_present()
    outside = tmp_path / "cwd"
    outside.mkdir()
    assert outside != REPO and REPO not in outside.parents
    runtime = tmp_path / "runtime"
    port = _free_port()
    env = os.environ.copy()
    env["AIQA_HOST"] = "127.0.0.1"
    env["AIQA_PORT"] = "8000"
    env["AIQA_RUNTIME_ROOT"] = str(runtime)
    for name in _MODEL_KEYS:
        env.pop(name, None)
    stdout = (tmp_path / "uvicorn-out.txt").open("w", encoding="utf-8")
    stderr = (tmp_path / "uvicorn-err.txt").open("w", encoding="utf-8")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "aiqa.api.app:create_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=outside,
        env=env,
        stdout=stdout,
        stderr=stderr,
    )
    health = page = css = None
    browser_dom = ""
    try:
        health = _wait_for_health(port, proc)
        if health is not None:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=5) as client:
                page = client.get("/")
                css = client.get("/static/app.css")
            browser = _browser()
            if browser is not None and page is not None and page.status_code == 200:
                browser_dom = _browser_dom(browser, f"http://127.0.0.1:{port}/", tmp_path)
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        stdout.close()
        stderr.close()

    real_http_health = (
        health is not None
        and health.status_code == 200
        and health.json() == {"status": "ok", "component": "api"}
    )
    real_page_and_css = (
        page is not None
        and css is not None
        and page.status_code == 200
        and f"<title>{PAGE_TITLE}</title>" in page.text
        and css.status_code == 200
        and css.headers.get("content-type", "").startswith("text/css")
        and PAGE_TITLE in browser_dom
    )
    report = BootstrapSmokeReport(
        real_http_health=real_http_health,
        real_page_and_css=real_page_and_css,
        owned_process_stopped=_process_stopped(proc),
        port_released=_port_is_free(port),
        vm_or_api_key_required=any(env.get(name) for name in _MODEL_KEYS),
        existing_block_preserved=_block_preserved(),
    )
    assert not runtime.exists()
    observed = asdict(report)
    assert observed == {
        "real_http_health": True,
        "real_page_and_css": True,
        "owned_process_stopped": True,
        "port_released": True,
        "vm_or_api_key_required": False,
        "existing_block_preserved": True,
    }
