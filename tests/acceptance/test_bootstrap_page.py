"""W00-03: the product server renders the bootstrap page and CSS outside the repo."""

from __future__ import annotations

import asyncio
import os
import socket
import struct
import subprocess
import sys
import time
import zlib
from pathlib import Path
from unittest.mock import patch

import httpx

from aiqa.api.app import create_app
from aiqa.config import load_settings
from aiqa.web.routes import render_bootstrap

REPO = Path(__file__).resolve().parents[2]
PAGE_TITLE = "AI QA 기본 실행 환경"
CONNECTION_ERROR = "API에 연결할 수 없습니다."
BODY_COLOR = (244, 241, 234)
MARK_COLOR = (15, 110, 86)
_FAKE_MARKERS = (
    "localStorage",
    "sessionStorage",
    "PASS",
    "<button",
    "승인됨",
    "승인 완료",
    "녹화 완료",
    "dashboard",
    "prototype",
)
_BROWSERS = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
)


def _fake_count(text: str) -> int:
    return sum(text.count(marker) for marker in _FAKE_MARKERS)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _browser() -> Path | None:
    return next((path for path in _BROWSERS if path.is_file()), None)


def _paeth(left: int, up: int, up_left: int) -> int:
    estimate = left + up - up_left
    left_dist = abs(estimate - left)
    up_dist = abs(estimate - up)
    up_left_dist = abs(estimate - up_left)
    if left_dist <= up_dist and left_dist <= up_left_dist:
        return left
    if up_dist <= up_left_dist:
        return up
    return up_left


def _png_has_colors(path: Path, colors: set[tuple[int, int, int]]) -> bool:
    data = path.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return False
    pos = 8
    width = height = bit_depth = color_type = interlace = None
    idat = bytearray()
    while pos + 8 <= len(data):
        length = int.from_bytes(data[pos : pos + 4], "big")
        kind = data[pos + 4 : pos + 8]
        chunk = data[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            width, height, bit_depth, color_type, _comp, _filt, interlace = struct.unpack(
                ">IIBBBBB", chunk[:13]
            )
        elif kind == b"IDAT":
            idat.extend(chunk)
        elif kind == b"IEND":
            break
    if (
        width is None
        or height is None
        or bit_depth != 8
        or color_type not in (2, 6)
        or interlace != 0
    ):
        return False
    channels = 3 if color_type == 2 else 4
    raw = zlib.decompress(bytes(idat))
    stride = width * channels
    found: set[tuple[int, int, int]] = set()
    previous = bytearray(stride)
    index = 0
    for _row in range(height):
        filter_type = raw[index]
        index += 1
        scan = bytearray(raw[index : index + stride])
        index += stride
        recon = bytearray(stride)
        for column in range(stride):
            left = recon[column - channels] if column >= channels else 0
            up = previous[column]
            up_left = previous[column - channels] if column >= channels else 0
            if filter_type == 0:
                value = scan[column]
            elif filter_type == 1:
                value = (scan[column] + left) & 255
            elif filter_type == 2:
                value = (scan[column] + up) & 255
            elif filter_type == 3:
                value = (scan[column] + ((left + up) // 2)) & 255
            elif filter_type == 4:
                value = (scan[column] + _paeth(left, up, up_left)) & 255
            else:
                return False
            recon[column] = value
        previous = recon
        for column in range(0, stride, channels):
            pixel = (recon[column], recon[column + 1], recon[column + 2])
            if pixel in colors:
                found.add(pixel)
            if found == colors:
                return True
    return found == colors


def _wait_for_health(port: int, proc: subprocess.Popen[str]) -> bool:
    deadline = time.monotonic() + 20
    url = f"http://127.0.0.1:{port}/api/v1/health"
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return False
        try:
            response = httpx.get(url, timeout=0.5)
        except httpx.HTTPError:
            time.sleep(0.1)
            continue
        if response.status_code == 200 and response.json() == {"status": "ok", "component": "api"}:
            return True
        time.sleep(0.1)
    return False


def _screenshot(browser: Path, url: str, work: Path) -> Path:
    shot = work / "bootstrap.png"
    profile = work / "browser-profile"
    profile.mkdir()
    subprocess.run(
        [
            str(browser),
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            f"--user-data-dir={profile}",
            "--force-device-scale-factor=1",
            "--window-size=1280,720",
            f"--screenshot={shot}",
            "--default-background-color=FFFFFFFF",
            url,
        ],
        cwd=work,
        check=False,
        capture_output=True,
        text=True,
        timeout=40,
    )
    return shot


def test_w00_03(tmp_path: Path) -> None:
    assert callable(render_bootstrap)
    outside = tmp_path / "cwd"
    outside.mkdir()
    assert outside != REPO and REPO not in outside.parents
    runtime = tmp_path / "runtime"
    port = _free_port()
    env = os.environ.copy()
    env["AIQA_HOST"] = "127.0.0.1"
    env["AIQA_PORT"] = "8000"
    env["AIQA_RUNTIME_ROOT"] = str(runtime)
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
    try:
        ready = _wait_for_health(port, proc)
        page = css = projects = None
        if ready:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=5) as client:
                page = client.get("/")
                css = client.get("/static/app.css")
                liveness_did_not_open_store = not runtime.exists()
                projects = client.get("/api/v1/projects")
        browser = _browser()
        shot = None
        if ready and browser is not None and page is not None and page.status_code == 200:
            shot = _screenshot(browser, f"http://127.0.0.1:{port}/", tmp_path)
        browser_page_verified = bool(
            shot is not None and shot.is_file() and _png_has_colors(shot, {BODY_COLOR, MARK_COLOR})
        )
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

    assert ready
    assert page is not None and css is not None and projects is not None
    assert projects.status_code == 200 and projects.json() == {'items': []}
    assert "text/html" in page.headers.get("content-type", "")
    assert f"<title>{PAGE_TITLE}</title>" in page.text
    assert 'id="liveness" class="liveness"' in page.text
    assert "API liveness: status ok, component api." in page.text
    assert css.headers.get("content-type", "").startswith("text/css")
    assert liveness_did_not_open_store
    assert (runtime / 'db' / 'aiqa.sqlite').is_file()

    from aiqa.api import app as api_app

    broken = create_app(
        load_settings({"LOCALAPPDATA": str(tmp_path / "local"), "AIQA_RUNTIME_ROOT": str(runtime)})
    )

    def fail_health() -> dict[str, str]:
        raise RuntimeError("down")

    with patch.object(api_app, "health", fail_health):
        transport = httpx.ASGITransport(app=broken)

        async def read_error() -> httpx.Response:
            async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
                return await client.get("/")

        error_page = asyncio.run(read_error())
    assert error_page.status_code == 200
    assert f">{CONNECTION_ERROR}</p>" in error_page.text
    assert "API liveness: status ok, component api." not in error_page.text
    assert _fake_count(error_page.text) == 0

    observed = {
        "page_status": page.status_code,
        "css_status": css.status_code,
        "templates_work_outside_repo": (
            page.status_code == 200
            and f"<title>{PAGE_TITLE}</title>" in page.text
            and css.status_code == 200
            and css.headers.get("content-type", "").startswith("text/css")
            and "#f4f1ea" in css.text
            and "#0f6e56" in css.text
        ),
        "fake_business_results": _fake_count(page.text) + _fake_count(css.text),
        "browser_page_verified": browser_page_verified,
    }
    assert observed == {
        "page_status": 200,
        "css_status": 200,
        "templates_work_outside_repo": True,
        "fake_business_results": 0,
        "browser_page_verified": True,
    }
