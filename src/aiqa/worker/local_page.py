"""Local-only page execution port for TrustedWebDriver.

Holds an in-process DOM for allowlisted click/fill/scroll. CDP and Playwright
handles never leave this module; callers only see TypedAction and Observation.
"""

from __future__ import annotations

import binascii
import hashlib
import re
import struct
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from uuid import uuid4

from aiqa.contracts.actions import CaptureGeometry, Observation
from aiqa.replay.ipc import TypedAction


class LocalPageRejected(Exception):
    """The local page session refused an action or capture."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class _Node:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    text: str = ""
    children: list[_Node] = field(default_factory=list)
    parent: _Node | None = None
    clicked: int = 0
    scroll_y: int = 0


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("document")
        self._stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _Node(tag=tag.lower(), attrs={key: ("" if value is None else value) for key, value in attrs})
        node.parent = self._stack[-1]
        self._stack[-1].children.append(node)
        void = {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        }
        if tag.lower() not in void:
            self._stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        lower = tag.lower()
        while len(self._stack) > 1:
            current = self._stack.pop()
            if current.tag == lower:
                break

    def handle_data(self, data: str) -> None:
        if self._stack:
            self._stack[-1].text += data


def _find_by_id(node: _Node, element_id: str) -> _Node | None:
    if node.attrs.get("id") == element_id:
        return node
    for child in node.children:
        found = _find_by_id(child, element_id)
        if found is not None:
            return found
    return None


def _render(node: _Node) -> str:
    if node.tag == "document":
        return "".join(_render(child) for child in node.children)
    attrs = "".join(f' {key}="{value}"' for key, value in sorted(node.attrs.items()))
    if node.tag in {"input"}:
        return f"<{node.tag}{attrs}/>"
    inner = "".join(_render(child) for child in node.children) + node.text
    return f"<{node.tag}{attrs}>{inner}</{node.tag}>"


def _png_from_digest(digest: str, *, width: int = 24, height: int = 48) -> bytes:
    tone = int(digest[:2], 16)

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body))
            + kind
            + body
            + struct.pack(">I", binascii.crc32(kind + body) & 0xFFFFFFFF)
        )

    row = b"\x00" + bytes([tone, (tone * 3) % 256, (tone * 7) % 256]) * width
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(row * height))
        + chunk(b"IEND", b"")
    )


@dataclass
class LocalPageSession:
    """Dedicated local page. Mutation API is TypedAction-only."""

    origin: str
    _root: _Node
    _scroll_y: int = 0
    action_log: list[str] = field(default_factory=list)

    @classmethod
    def open_html(cls, html: str, *, origin: str) -> "LocalPageSession":
        if type(html) is not str or html.strip() == "":
            raise LocalPageRejected("page html is required")
        if type(origin) is not str or not origin.startswith("https://"):
            raise LocalPageRejected("page origin must be https")
        builder = _TreeBuilder()
        builder.feed(html)
        builder.close()
        return cls(origin=origin, _root=builder.root)

    def public_view(self) -> dict[str, object]:
        return {"origin": self.origin, "owns_cdp": False, "execution_port": "local_page"}

    def apply(self, action: TypedAction) -> None:
        if action.type == "click":
            node = self._require(action.selector)
            node.clicked += 1
            node.attrs["data-clicked"] = str(node.clicked)
            self.action_log.append(f"click:{action.selector}")
            return
        if action.type == "fill":
            node = self._require(action.selector)
            if node.tag != "input" and node.tag != "textarea":
                raise LocalPageRejected("fill requires an input")
            node.attrs["value"] = action.value
            self.action_log.append(f"fill:{action.selector}")
            return
        if action.type == "select":
            node = self._require(action.selector)
            node.attrs["value"] = action.value
            self.action_log.append(f"select:{action.selector}")
            return
        if action.type == "scroll":
            amount = 100
            if action.value.strip().isdigit():
                amount = int(action.value.strip())
            self._scroll_y += amount
            body = _find_by_id(self._root, "page")
            if body is None:
                for child in self._root.children:
                    if child.tag in {"html", "body"}:
                        body = child
                        if child.tag == "html":
                            for nested in child.children:
                                if nested.tag == "body":
                                    body = nested
                                    break
                        break
            if body is None:
                body = self._root
            body.scroll_y = self._scroll_y
            body.attrs["data-scroll-y"] = str(self._scroll_y)
            self.action_log.append("scroll")
            return
        raise LocalPageRejected("unsupported action")

    def capture(self) -> Observation:
        dom = _render(self._root)
        digest = hashlib.sha256(dom.encode("utf-8")).hexdigest()
        return Observation(
            str(uuid4()),
            datetime.now(timezone.utc).isoformat(),
            CaptureGeometry(24, 48, 24, 48, "identity", 0, (0, 0, 24, 48)),
            _png_from_digest(digest),
            dom,
            "",
            (),
            "",
            True,
            "web",
        )

    def as_runner(self):
        """BrowserRunner for TrustedWebDriver. Returns no browser handles."""

        def runner(action: TypedAction) -> None:
            self.apply(action)

        return runner

    def _require(self, selector: str) -> _Node:
        match = re.fullmatch(r"#([A-Za-z][\w\-]*)", selector.strip())
        if match is None:
            raise LocalPageRejected("selector is outside local allowlist")
        node = _find_by_id(self._root, match.group(1))
        if node is None:
            raise LocalPageRejected("element was not found")
        return node


def local_page_from_fixture_html(*, origin: str, html: str | None = None) -> LocalPageSession:
    """Open the RX local fixture page with click/fill/scroll targets."""

    body = html
    if body is None:
        body = (
            "<!DOCTYPE html><html lang='ko'><body id='page'>"
            f"<p data-origin='{origin}'>local execution page</p>"
            "<button id='go'>Go</button>"
            "<input id='name' value=''/>"
            "</body></html>"
        )
    return LocalPageSession.open_html(body, origin=origin)
