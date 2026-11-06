"""RX-76: owned browser execution port for TrustedWebDriver.

``TrustedBrowserSession`` owns a CDP-like transport. The transport object and any
DevTools endpoint stay private to this module; callers only see ``TypedAction``,
``Observation`` and a sanitized ``public_view``.

The default transport is an in-memory ``FakeCdpTransport`` (no process, no port).
``ChromeCdpTransport.launch`` starts a real headless Chrome/Edge when one is
installed. ``LocalPageSession`` (RX-70) remains available for test injection.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.parse import urlsplit
from uuid import uuid4

from aiqa.contracts.actions import CaptureGeometry, Observation
from aiqa.replay.ipc import TypedAction
from aiqa.worker.local_page import (
    _find_by_id,
    _png_from_digest,
    _render,
    _TreeBuilder,
)

BrowserRunner = Callable[[TypedAction], None]

EXECUTION_PORT = "trusted_browser"
_SESSION_ACTIONS = frozenset({"click", "fill", "scroll", "select"})
_SELECTOR = re.compile(r"#([A-Za-z][\w\-]*)")
_ACTION_MARK = "/*aiqa:action:"
_DOM_EXPR = "/*aiqa:dom*/document.documentElement.outerHTML"
_ORIGIN_EXPR = "/*aiqa:origin*/location.origin"

# Real-browser action script. Arguments arrive only as one JSON array literal.
_ACTION_JS = (
    "(function(a){var t=a[0],s=a[1],v=a[2];"
    "if(t==='scroll'){var n=/^\\d+$/.test(v.trim())?parseInt(v.trim(),10):100;"
    "window.__aiqaScroll=(window.__aiqaScroll||0)+n;window.scrollBy(0,n);"
    "document.body.setAttribute('data-scroll-y',String(window.__aiqaScroll));return 'ok';}"
    "var el=document.querySelector(s);if(!el){return 'element was not found';}"
    "if(t==='click'){var c=parseInt(el.getAttribute('data-clicked')||'0',10)+1;"
    "el.setAttribute('data-clicked',String(c));el.click();return 'ok';}"
    "if(t==='fill'){if(el.tagName!=='INPUT'&&el.tagName!=='TEXTAREA'){return 'fill requires an input';}"
    "el.focus();el.value=v;el.setAttribute('value',v);"
    "el.dispatchEvent(new Event('input',{bubbles:true}));"
    "el.dispatchEvent(new Event('change',{bubbles:true}));return 'ok';}"
    "if(t==='select'){el.value=v;el.setAttribute('value',v);"
    "el.dispatchEvent(new Event('change',{bubbles:true}));return 'ok';}"
    "return 'unsupported action';})"
)

_CHROME_CANDIDATES = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
)
_CHROME_NAMES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome", "msedge")


class BrowserSessionRejected(Exception):
    """The trusted browser session refused an action, navigation, or capture."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class CdpTransport(Protocol):
    """Minimal CDP-like command port. Implementations never leave this module's session."""

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]: ...

    def close(self) -> None: ...


def default_fixture_html(origin: str) -> str:
    return (
        "<!DOCTYPE html><html lang='ko'><body id='page'>"
        f"<p data-origin='{origin}'>local execution page</p>"
        "<button id='go'>Go</button>"
        "<input id='name' value=''/>"
        "</body></html>"
    )


def _origin_of(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme == "" or parts.netloc == "":
        return ""
    return f"{parts.scheme}://{parts.netloc}"


def _png_size(png: bytes) -> tuple[int, int]:
    if not png.startswith(b"\x89PNG\r\n\x1a\n") or len(png) < 33:
        raise BrowserSessionRejected("screenshot is not a PNG")
    width, height = struct.unpack(">II", png[16:24])
    if width < 1 or height < 1:
        raise BrowserSessionRejected("screenshot has no size")
    return width, height


def _action_expression(action_type: str, selector: str, value: str) -> str:
    args = json.dumps([action_type, selector, value], ensure_ascii=True)
    token = base64.b64encode(args.encode("utf-8")).decode("ascii")
    return f"{_ACTION_MARK}{token}*/{_ACTION_JS}({args})"


# --------------------------------------------------------------------------- fake


class FakeCdpTransport:
    """In-memory page state with a tiny CDP-like surface. Unknown methods fail."""

    kind = "fake"

    def __init__(self, html: str | None = None, origin: str | None = None) -> None:
        self._html = html
        self._origin = origin or ""
        self._root = None
        self._location = ""
        self._scroll = 0
        self.calls: list[str] = []
        self.closed = False

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.closed:
            raise BrowserSessionRejected("transport is closed")
        body = params or {}
        self.calls.append(method)
        if method == "Page.navigate":
            return self._navigate(str(body.get("url", "")))
        if method == "Runtime.evaluate":
            return self._evaluate(str(body.get("expression", "")))
        if method == "Page.captureScreenshot":
            if self._root is None:
                raise BrowserSessionRejected("no page is loaded")
            digest = hashlib.sha256(_render(self._root).encode("utf-8")).hexdigest()
            data = base64.b64encode(_png_from_digest(digest)).decode("ascii")
            return {"data": data}
        raise BrowserSessionRejected(f"unknown cdp method: {method}")

    def close(self) -> None:
        self.closed = True

    def _navigate(self, url: str) -> dict[str, Any]:
        target = _origin_of(url)
        if target == "":
            raise BrowserSessionRejected("navigation target is not absolute")
        if self._root is None and target == self._origin and self._html:
            builder = _TreeBuilder()
            builder.feed(self._html)
            builder.close()
            self._root = builder.root
        self._location = url
        return {"frameId": "fake-frame"}

    def _evaluate(self, expression: str) -> dict[str, Any]:
        if self._root is None:
            raise BrowserSessionRejected("no page is loaded")
        if expression == _ORIGIN_EXPR:
            return {"result": {"type": "string", "value": _origin_of(self._location)}}
        if expression == _DOM_EXPR:
            return {"result": {"type": "string", "value": _render(self._root)}}
        if expression.startswith(_ACTION_MARK):
            end = expression.find("*/")
            try:
                raw = base64.b64decode(expression[len(_ACTION_MARK) : end])
                action_type, selector, value = json.loads(raw.decode("utf-8"))
            except (ValueError, TypeError):
                raise BrowserSessionRejected("action expression is invalid") from None
            return {"result": {"type": "string", "value": self._act(action_type, selector, value)}}
        raise BrowserSessionRejected("unknown expression")

    def _act(self, action_type: str, selector: str, value: str) -> str:
        if action_type == "scroll":
            amount = int(value.strip()) if value.strip().isdigit() else 100
            self._scroll += amount
            body = self._body()
            body.attrs["data-scroll-y"] = str(self._scroll)
            body.scroll_y = self._scroll
            return "ok"
        match = _SELECTOR.fullmatch(selector.strip())
        node = _find_by_id(self._root, match.group(1)) if match else None
        if node is None:
            return "element was not found"
        if action_type == "click":
            node.clicked += 1
            node.attrs["data-clicked"] = str(node.clicked)
            href = node.attrs.get("href", "")
            if node.tag == "a" and _origin_of(href):
                self._location = href
            return "ok"
        if action_type == "fill":
            if node.tag not in {"input", "textarea"}:
                return "fill requires an input"
            node.attrs["value"] = value
            return "ok"
        if action_type == "select":
            node.attrs["value"] = value
            return "ok"
        return "unsupported action"

    def _body(self):
        for child in self._root.children:
            if child.tag == "body":
                return child
            for nested in child.children:
                if nested.tag == "body":
                    return nested
        return self._root


# -------------------------------------------------------------------- real chrome


def resolve_chrome_path() -> Path | None:
    """Return an installed Chrome/Edge executable, or None. AIQA_CHROME_PATH wins."""

    override = os.environ.get("AIQA_CHROME_PATH", "").strip()
    if override:
        candidate = Path(override)
        return candidate if candidate.is_file() else None
    for path in _CHROME_CANDIDATES:
        if path.is_file():
            return path
    for name in _CHROME_NAMES:
        found = shutil.which(name)
        if found:
            return Path(found)
    return None


def chrome_available() -> bool:
    if resolve_chrome_path() is None:
        return False
    try:
        import websockets.sync.client  # noqa: F401
    except ImportError:
        return False
    return True


class ChromeCdpTransport:
    """Real headless browser over a private DevTools socket. Page HTML is served via Fetch."""

    kind = "chrome"

    def __init__(self, process: subprocess.Popen, profile: Path, ws: Any, origin: str, html: str) -> None:
        self._process = process
        self._profile = profile
        self._ws = ws
        self._origin = origin
        self._html = html.encode("utf-8")
        self._next_id = 0
        self._loaded = False
        self.closed = False

    @classmethod
    def launch(
        cls,
        *,
        origin: str,
        html: str,
        chrome_path: Path | None = None,
        timeout: float = 20.0,
    ) -> "ChromeCdpTransport":
        path = chrome_path or resolve_chrome_path()
        if path is None or not chrome_available():
            raise BrowserSessionRejected("browser is not available")
        from urllib.request import urlopen

        from websockets.sync.client import connect

        profile = Path(tempfile.mkdtemp(prefix="aiqa-browser-"))
        process = subprocess.Popen(
            [
                str(path),
                "--headless=new",
                "--disable-gpu",
                "--no-first-run",
                "--no-default-browser-check",
                "--remote-debugging-port=0",
                f"--user-data-dir={profile}",
                "--window-size=640,480",
                "--force-device-scale-factor=1",
                "about:blank",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        ws = None
        try:
            deadline = time.monotonic() + timeout
            port_file = profile / "DevToolsActivePort"
            port = ""
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise BrowserSessionRejected("browser exited during launch")
                if port_file.is_file():
                    lines = port_file.read_text(encoding="utf-8").splitlines()
                    if lines and lines[0].isdigit():
                        port = lines[0]
                        break
                time.sleep(0.1)
            if port == "":
                raise BrowserSessionRejected("browser did not open its control port")
            socket_url = ""
            while time.monotonic() < deadline and socket_url == "":
                try:
                    with urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2) as response:
                        targets = json.loads(response.read().decode("utf-8"))
                except OSError:
                    targets = []
                for target in targets:
                    if target.get("type") == "page" and target.get("webSocketDebuggerUrl"):
                        socket_url = str(target["webSocketDebuggerUrl"])
                        break
                if socket_url == "":
                    time.sleep(0.1)
            if socket_url == "":
                raise BrowserSessionRejected("browser page target was not found")
            ws = connect(socket_url, max_size=None, open_timeout=5)
            transport = cls(process, profile, ws, origin, html)
            transport._raw_call("Page.enable")
            transport._raw_call("Runtime.enable")
            transport._raw_call("Fetch.enable", {"patterns": [{"urlPattern": "*"}]})
            return transport
        except BaseException:
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass
            _stop_process(process)
            shutil.rmtree(profile, ignore_errors=True)
            raise

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.closed:
            raise BrowserSessionRejected("transport is closed")
        if method == "Page.navigate":
            self._loaded = False
            result = self._raw_call(method, params)
            self._wait_loaded()
            return result
        if method in {"Runtime.evaluate", "Page.captureScreenshot"}:
            return self._raw_call(method, params)
        raise BrowserSessionRejected(f"unknown cdp method: {method}")

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            self._ws.close()
        except Exception:
            pass
        _stop_process(self._process)
        shutil.rmtree(self._profile, ignore_errors=True)

    def _raw_call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._next_id += 1
        wanted = self._next_id
        self._ws.send(json.dumps({"id": wanted, "method": method, "params": params or {}}))
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            message = self._receive(deadline)
            if message is None:
                continue
            if message.get("id") == wanted:
                if "error" in message:
                    raise BrowserSessionRejected("browser command failed")
                result = message.get("result", {})
                if method == "Runtime.evaluate" and "exceptionDetails" in result:
                    raise BrowserSessionRejected("browser script failed")
                return result
        raise BrowserSessionRejected("browser command timed out")

    def _receive(self, deadline: float) -> dict[str, Any] | None:
        try:
            raw = self._ws.recv(timeout=max(0.05, min(1.0, deadline - time.monotonic())))
        except TimeoutError:
            return None
        except Exception as exc:
            raise BrowserSessionRejected("browser connection was lost") from exc
        message = json.loads(raw)
        method = message.get("method")
        if method == "Page.loadEventFired":
            self._loaded = True
        elif method == "Fetch.requestPaused":
            self._answer_request(message.get("params", {}))
        return message

    def _answer_request(self, params: dict[str, Any]) -> None:
        request_id = params.get("requestId")
        url = str(params.get("request", {}).get("url", ""))
        self._next_id += 1
        if _origin_of(url) == self._origin:
            command = {
                "id": self._next_id,
                "method": "Fetch.fulfillRequest",
                "params": {
                    "requestId": request_id,
                    "responseCode": 200,
                    "responseHeaders": [{"name": "Content-Type", "value": "text/html; charset=utf-8"}],
                    "body": base64.b64encode(self._html).decode("ascii"),
                },
            }
        else:
            command = {
                "id": self._next_id,
                "method": "Fetch.failRequest",
                "params": {"requestId": request_id, "errorReason": "BlockedByClient"},
            }
        self._ws.send(json.dumps(command))

    def _wait_loaded(self) -> None:
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            if self._loaded:
                return
            self._receive(deadline)
        raise BrowserSessionRejected("page did not finish loading")


def _stop_process(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


# ------------------------------------------------------------------------ session


class TrustedBrowserSession:
    """Owns one dedicated browser context. Mutation API is TypedAction-only."""

    def __init__(self, *, origin: str, transport: CdpTransport) -> None:
        self._origin = origin
        self._transport = transport
        self._closed = False
        self.action_log: list[str] = []

    @classmethod
    def open(
        cls,
        *,
        origin: str,
        html: str | None = None,
        transport: CdpTransport | None = None,
    ) -> "TrustedBrowserSession":
        if type(origin) is not str or not origin.startswith("https://"):
            raise BrowserSessionRejected("page origin must be https")
        if html is not None and (type(html) is not str or html.strip() == ""):
            raise BrowserSessionRejected("page html is required")
        owned = transport is None
        active: CdpTransport = (
            FakeCdpTransport(html=html if html is not None else default_fixture_html(origin), origin=origin)
            if transport is None
            else transport
        )
        session = cls(origin=origin, transport=active)
        try:
            session._call("Page.navigate", {"url": origin + "/"})
            session._require_origin()
        except BaseException:
            session._closed = True
            if owned:
                active.close()
            raise
        return session

    @classmethod
    def open_chrome(
        cls,
        *,
        origin: str,
        html: str | None = None,
        chrome_path: Path | None = None,
    ) -> "TrustedBrowserSession":
        """Open a real headless browser context that serves ``html`` for ``origin``."""

        if type(origin) is not str or not origin.startswith("https://"):
            raise BrowserSessionRejected("page origin must be https")
        body = html if html is not None else default_fixture_html(origin)
        transport = ChromeCdpTransport.launch(origin=origin, html=body, chrome_path=chrome_path)
        try:
            return cls.open(origin=origin, html=body, transport=transport)
        except BaseException:
            transport.close()
            raise

    @property
    def origin(self) -> str:
        return self._origin

    def public_view(self) -> dict[str, object]:
        return {
            "origin": self._origin,
            "owns_cdp": True,
            "execution_port": EXECUTION_PORT,
            "backend": str(getattr(self._transport, "kind", "custom")),
            "closed": self._closed,
        }

    def apply(self, action: TypedAction) -> None:
        self._require_open()
        if action.type not in _SESSION_ACTIONS:
            raise BrowserSessionRejected("unsupported action")
        selector = action.selector.strip()
        if action.type != "scroll" and _SELECTOR.fullmatch(selector) is None:
            raise BrowserSessionRejected("selector is outside browser allowlist")
        value = action.value if type(action.value) is str else ""
        result = self._call("Runtime.evaluate", {"expression": _action_expression(action.type, selector, value),
                                                  "returnByValue": True})
        outcome = _value_of(result)
        if outcome != "ok":
            raise BrowserSessionRejected(outcome if isinstance(outcome, str) and outcome else "action failed")
        self._require_origin()
        self.action_log.append(f"{action.type}:{selector}" if action.type != "scroll" else "scroll")

    def capture(self) -> Observation:
        self._require_open()
        self._require_origin()
        dom = _value_of(self._call("Runtime.evaluate", {"expression": _DOM_EXPR, "returnByValue": True}))
        if type(dom) is not str:
            raise BrowserSessionRejected("dom capture failed")
        shot = self._call("Page.captureScreenshot", {"format": "png"})
        try:
            png = base64.b64decode(str(shot.get("data", "")), validate=True)
        except ValueError:
            raise BrowserSessionRejected("screenshot capture failed") from None
        width, height = _png_size(png)
        return Observation(
            str(uuid4()),
            datetime.now(timezone.utc).isoformat(),
            CaptureGeometry(width, height, width, height, "identity", 0, (0, 0, width, height)),
            png,
            dom,
            "",
            (),
            "",
            True,
            "web",
        )

    def as_runner(self) -> BrowserRunner:
        """BrowserRunner for TrustedWebDriver. Returns no browser handles."""

        def runner(action: TypedAction) -> None:
            self.apply(action)

        return runner

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._transport.close()

    def _require_open(self) -> None:
        if self._closed:
            raise BrowserSessionRejected("session is closed")

    def _call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "Page.navigate" and _origin_of(str(params.get("url", ""))) != self._origin:
            raise BrowserSessionRejected("cross-origin was refused")
        return self._transport.call(method, params)

    def _require_origin(self) -> None:
        current = _value_of(self._transport.call("Runtime.evaluate", {"expression": _ORIGIN_EXPR,
                                                                      "returnByValue": True}))
        if current != self._origin:
            # A page that left the approved origin is never trusted again.
            self.close()
            raise BrowserSessionRejected("cross-origin was refused")


def _value_of(result: dict[str, Any]) -> object:
    inner = result.get("result")
    if type(inner) is not dict:
        return None
    return inner.get("value")
