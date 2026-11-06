"""RX-76: owned browser execution port (TrustedBrowserSession) behind TrustedWebDriver."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from aiqa.environments.web_browser import (
    BrowserSessionRejected,
    FakeCdpTransport,
    TrustedBrowserSession,
    chrome_available,
    default_fixture_html,
)
from aiqa.replay.driver import ApprovedWebPackage, TrustedWebDriver, WebDispatchError
from aiqa.replay.ipc import TypedAction
from aiqa.worker.local_page import LocalPageSession, local_page_from_fixture_html
from aiqa.worker.web_isolation_backend import IsolationProof
from aiqa.worker.web_jobs import assemble_web_worker_from_entry_binding, build_fixture_web_gate
from aiqa.worker.web_vm_transport import WebGuestEntryBinding

ORIGIN = "https://app.example.test"
OTHER = "https://evil.example.test"
ENDPOINT = "guest-ipc://web-rx76"
PEER = "rx76-peer-token-ok"
SECRET = b"rx76-fixture-proof!!!!"
DIGEST = "sha256:" + ("cd" * 32)
NOW = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)

PAGE = (
    "<!DOCTYPE html><html><body id='page'>"
    "<button id='go'>Go</button>"
    "<input id='name' value=''/>"
    "<select id='pick'><option value='a'>a</option><option value='b'>b</option></select>"
    f"<a id='leave' href='{OTHER}/x'>leave</a>"
    "</body></html>"
)


def _driver(tmp_path: Path, session, *, proof=None, runner="session", name="spool", observe=True):
    gate = build_fixture_web_gate(approved_origin=ORIGIN, proof_secret=SECRET)
    issued = proof if proof is not None else gate.issue_proof(now=NOW)
    return TrustedWebDriver(
        "ws://127.0.0.1:0/devtools/browser/private",
        approved=ApprovedWebPackage(DIGEST, "lock-1", ORIGIN),
        gate=gate,
        proof=issued,
        spool=tmp_path / name,
        runner=session.as_runner() if runner == "session" else None,
        now=NOW,
        observe=session.capture if observe else None,
    )


def _run(driver, session, action: dict):
    return driver.run(
        before=session.capture(),
        action=action,
        presented_digest=DIGEST,
        presented_revision="lock-1",
        page_origin=ORIGIN,
    )


def test_rx_76_fake_session_click_fill_scroll_select_change_dom_and_pixels(tmp_path: Path) -> None:
    session = TrustedBrowserSession.open(origin=ORIGIN, html=PAGE)
    driver = _driver(tmp_path, session)
    before = session.capture()
    assert 'value=""' in before.dom
    assert before.capture_ok is True and before.platform == "web"

    click = _run(driver, session, {"type": "click", "selector": "#go"})
    assert click.native_calls == 1 and click.ai_calls == 0
    assert click.after_ref is not None  # observed right after the action, no caller-supplied after
    assert 'data-clicked="1"' in session.capture().dom

    fill = _run(driver, session, {"type": "fill", "selector": "#name", "value": "ada"})
    assert fill.native_calls == 1
    filled = session.capture()
    assert 'value="ada"' in filled.dom
    assert filled.png != before.png

    pick = _run(driver, session, {"type": "select", "selector": "#pick", "value": "b"})
    assert pick.native_calls == 1
    assert 'id="pick"' in session.capture().dom and 'value="b"' in session.capture().dom

    scroll = _run(driver, session, {"type": "scroll", "selector": "#page", "value": "120"})
    assert scroll.native_calls == 1
    assert 'data-scroll-y="120"' in session.capture().dom

    assert driver.native_calls == 4
    assert session.action_log == ["click:#go", "fill:#name", "select:#pick", "scroll"]
    assert isinstance(session._transport, FakeCdpTransport)
    assert session._transport.calls.count("Page.captureScreenshot") >= 4
    session.close()


def test_rx_76_fail_closed_without_port_unsupported_action_cross_origin_and_proof(
    tmp_path: Path,
) -> None:
    session = TrustedBrowserSession.open(origin=ORIGIN, html=PAGE)

    no_runner = _driver(tmp_path, session, runner=None, name="no-runner")
    with pytest.raises(WebDispatchError, match="execution port"):
        _run(no_runner, session, {"type": "click", "selector": "#go"})
    assert no_runner.native_calls == 0

    for bad in (
        TypedAction(type="navigate", selector="", value=OTHER),
        TypedAction(type="click", selector="document.body", value=""),
        TypedAction(type="click", selector="#missing", value=""),
    ):
        with pytest.raises(BrowserSessionRejected):
            session.apply(bad)
    assert session.action_log == []

    # Forged proof: driver never reaches the browser.
    gate = build_fixture_web_gate(approved_origin=ORIGIN, proof_secret=SECRET)
    forged = IsolationProof(
        backend="fixture",
        issued_at=NOW.isoformat(),
        expires_at=NOW.isoformat(),
        scope_hash=gate.config.scope_hash,
        nonce="forged",
        token="sha256:" + ("0" * 64),
    )
    forged_driver = _driver(tmp_path, session, proof=forged, name="forged")
    with pytest.raises(WebDispatchError):
        _run(forged_driver, session, {"type": "click", "selector": "#go"})
    assert forged_driver.native_calls == 0 and session.action_log == []

    # Cross-origin page_origin is refused before the browser is touched.
    live = _driver(tmp_path, session, name="live")
    with pytest.raises(WebDispatchError, match="cross-origin"):
        live.run(
            before=session.capture(),
            action={"type": "click", "selector": "#go"},
            presented_digest=DIGEST,
            presented_revision="lock-1",
            page_origin=OTHER,
        )
    assert live.native_calls == 0

    # A click that leaves the approved origin is rejected and the session is closed.
    with pytest.raises(WebDispatchError, match="cross-origin"):
        _run(live, session, {"type": "click", "selector": "#leave"})
    assert session.public_view()["closed"] is True
    with pytest.raises(BrowserSessionRejected, match="closed"):
        session.capture()

    # Opening on a transport that serves another origin never becomes ready.
    with pytest.raises(BrowserSessionRejected):
        TrustedBrowserSession.open(
            origin=ORIGIN, transport=FakeCdpTransport(html=PAGE, origin=OTHER)
        )
    with pytest.raises(BrowserSessionRejected, match="https"):
        TrustedBrowserSession.open(origin="http://app.example.test", html=PAGE)


def test_rx_76_fake_transport_rejects_unknown_methods_and_expressions() -> None:
    transport = FakeCdpTransport(html=PAGE, origin=ORIGIN)
    with pytest.raises(BrowserSessionRejected, match="unknown cdp method"):
        transport.call("Network.getAllCookies", {})
    with pytest.raises(BrowserSessionRejected, match="unknown cdp method"):
        transport.call("Browser.close", {})
    transport.call("Page.navigate", {"url": ORIGIN + "/"})
    with pytest.raises(BrowserSessionRejected, match="unknown expression"):
        transport.call("Runtime.evaluate", {"expression": "fetch('https://evil.example.test')"})
    shot = transport.call("Page.captureScreenshot", {"format": "png"})
    assert isinstance(shot["data"], str) and shot["data"] != ""


def test_rx_76_public_view_never_exposes_cdp_endpoint() -> None:
    session = TrustedBrowserSession.open(origin=ORIGIN, html=PAGE)
    view = session.public_view()
    assert view["owns_cdp"] is True
    assert view["execution_port"] == "trusted_browser"
    assert view["origin"] == ORIGIN
    text = str(view).lower()
    for leaked in ("9222", "devtools", "ws://", "wss://", "endpoint", "websocket"):
        assert leaked not in text
    assert not any(key in view for key in ("cdp", "endpoint", "cdp_url", "websocket"))
    session.close()
    assert session.public_view()["closed"] is True


def test_rx_76_default_assembly_uses_trusted_browser_and_replays_with_post_action_observe(
    tmp_path: Path,
) -> None:
    binding = WebGuestEntryBinding(ENDPOINT, PEER, ORIGIN)
    trajectory = {
        "complete": True,
        "steps": [
            {
                "hook": "hook.web.code_output.step_script",
                "code": "qa_runtime.click('#go')",
                "summary": {"type": "click", "selector": "#go"},
            },
            {
                "hook": "hook.web.code_output.script_py",
                "code": "qa_runtime.fill('#name', 'ada')",
                "summary": {"type": "fill", "selector": "#name", "value": "ada"},
            },
        ],
    }
    assembled = assemble_web_worker_from_entry_binding(
        binding,
        runtime_root=tmp_path / "entry",
        proof_secret=SECRET,
        now=NOW,
        spawn_guest=False,
        trajectory=trajectory,
    )
    try:
        session = assembled.page_session
        assert isinstance(session, TrustedBrowserSession)
        assert not isinstance(session, LocalPageSession)
        assert assembled.owns_page_session is True
        assert session.public_view()["execution_port"] == "trusted_browser"
        assert assembled.replay is not None
        assert assembled.replay.context.runner is not None
        assert assembled.replay.context.after is None
        assert assembled.replay.context.observe is not None

        digest = assembled.replay.context.approved.digest
        result = assembled.handler.handle(
            {
                "attempt_id": str(uuid4()),
                "snapshot": {
                    "purpose": "trial",
                    "origin": ORIGIN,
                    "revision": "lock-1",
                    "digest": digest,
                    "approved_digest": digest,
                },
            }
        )
        assert result.outcome == "completed"
        assert result.actions == 2
        assert assembled.replay.actor_ai_calls == 0
        assert session.action_log == ["click:#go", "fill:#name"]
        dom = session.capture().dom
        assert 'data-clicked="1"' in dom and 'value="ada"' in dom
    finally:
        assembled.close()
    assert session.public_view()["closed"] is True


def test_rx_76_assembly_accepts_injected_local_page_session_and_fake_transport(
    tmp_path: Path,
) -> None:
    binding = WebGuestEntryBinding(ENDPOINT, PEER, ORIGIN)
    local = local_page_from_fixture_html(origin=ORIGIN)
    injected = assemble_web_worker_from_entry_binding(
        binding,
        runtime_root=tmp_path / "local",
        proof_secret=SECRET,
        now=NOW,
        spawn_guest=False,
        page_session=local,
    )
    try:
        assert injected.page_session is local
        assert injected.owns_page_session is False
        assert injected.replay is not None and injected.replay.context.runner is not None
        injected.replay.context.runner(TypedAction(type="click", selector="#go", value=""))
        assert local.action_log == ["click:#go"]
        assert local.public_view()["execution_port"] == "local_page"
    finally:
        injected.close()

    transport = FakeCdpTransport(html=default_fixture_html(ORIGIN), origin=ORIGIN)
    with_transport = assemble_web_worker_from_entry_binding(
        binding,
        runtime_root=tmp_path / "transport",
        proof_secret=SECRET,
        now=NOW,
        spawn_guest=False,
        browser_transport=transport,
    )
    try:
        assert isinstance(with_transport.page_session, TrustedBrowserSession)
        assert with_transport.page_session._transport is transport
    finally:
        with_transport.close()
    assert transport.closed is True

    with pytest.raises(ValueError):
        assemble_web_worker_from_entry_binding(
            binding,
            runtime_root=tmp_path / "both",
            proof_secret=SECRET,
            now=NOW,
            spawn_guest=False,
            browser_session=local,
            browser_transport=transport,
        )


def test_rx_76_replay_without_after_or_observe_stays_fail_closed(tmp_path: Path) -> None:
    binding = WebGuestEntryBinding(ENDPOINT, PEER, ORIGIN)
    assembled = assemble_web_worker_from_entry_binding(
        binding,
        runtime_root=tmp_path / "entry",
        proof_secret=SECRET,
        now=NOW,
        spawn_guest=False,
    )
    try:
        assert assembled.replay is not None
        assembled.replay.context.observe = None
        digest = assembled.replay.context.approved.digest
        result = assembled.handler.handle(
            {
                "attempt_id": str(uuid4()),
                "snapshot": {
                    "purpose": "trial",
                    "origin": ORIGIN,
                    "revision": "lock-1",
                    "digest": digest,
                },
            }
        )
        assert result.outcome == "error" and result.actions == 0
    finally:
        assembled.close()


@pytest.mark.skipif(not chrome_available(), reason="local Chrome/Edge with websockets is not available")
def test_rx_76_live_headless_browser_mutates_real_dom_and_screenshot(tmp_path: Path) -> None:
    session = TrustedBrowserSession.open_chrome(origin=ORIGIN, html=PAGE)
    try:
        view = session.public_view()
        assert view["backend"] == "chrome" and "9222" not in str(view)
        driver = _driver(tmp_path, session)
        before = session.capture()
        assert before.png.startswith(b"\x89PNG") and before.geometry is not None

        _run(driver, session, {"type": "click", "selector": "#go"})
        _run(driver, session, {"type": "fill", "selector": "#name", "value": "ada"})
        _run(driver, session, {"type": "select", "selector": "#pick", "value": "b"})
        _run(driver, session, {"type": "scroll", "selector": "#page", "value": "50"})
        after = session.capture()
        assert 'data-clicked="1"' in after.dom
        assert 'value="ada"' in after.dom
        assert 'data-scroll-y="50"' in after.dom
        assert driver.native_calls == 4
        assert after.dom != before.dom

        with pytest.raises(WebDispatchError):
            _run(driver, session, {"type": "click", "selector": "#leave"})
        assert session.public_view()["closed"] is True
    finally:
        session.close()
