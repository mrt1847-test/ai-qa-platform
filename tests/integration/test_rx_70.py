"""RX-70: TrustedWebDriver requires execution port; local page mutates real DOM."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from aiqa.adapters.cuawright_web import local_web_fixture
from aiqa.replay.driver import ApprovedWebPackage, TrustedWebDriver, WebDispatchError
from aiqa.replay.ipc import TypedAction, parse_ipc_message
from aiqa.worker.local_page import LocalPageRejected, local_page_from_fixture_html
from aiqa.worker.web_jobs import (
    assemble_web_worker_from_entry_binding,
    build_fixture_web_gate,
    fixture_web_observation,
)
from aiqa.worker.web_vm_transport import WebGuestEntryBinding

ORIGIN = "https://app.example.test"
ENDPOINT = "guest-ipc://web-rx70"
PEER = "rx70-peer-token-ok"
SECRET = b"rx70-fixture-proof!!!!"
DIGEST = "sha256:" + ("ab" * 32)


def _gate_proof(now: datetime):
    gate = build_fixture_web_gate(approved_origin=ORIGIN, proof_secret=SECRET)
    return gate, gate.issue_proof(now=now)


def test_rx_70_local_page_mutates_dom_and_blocks_without_port(tmp_path: Path) -> None:
    now = datetime(2026, 11, 6, 10, 0, tzinfo=timezone.utc)
    gate, proof = _gate_proof(now)
    approved = ApprovedWebPackage(DIGEST, "lock-1", ORIGIN)
    fixture = local_web_fixture(origin=ORIGIN)
    page = local_page_from_fixture_html(origin=ORIGIN, html=fixture.page_html)
    assert "cdp" not in page.public_view()
    assert page.public_view().get("owns_cdp") is False

    before = page.capture()
    assert 'id="go"' in before.dom
    assert 'value=""' in before.dom or "value=''" in before.dom or 'value=""' in before.dom.replace("'", '"')

    driver = TrustedWebDriver(
        "ws://127.0.0.1:0/devtools/browser/private",
        approved=approved,
        gate=gate,
        proof=proof,
        spool=tmp_path / "spool",
        runner=page.as_runner(),
        now=now,
    )
    # Generated/public surface must not expose the CDP endpoint.
    assert "9222" not in str(driver.public_view())
    assert "devtools" not in str(driver.public_view())

    click = driver.run(
        before=before,
        action={"type": "click", "selector": "#go"},
        presented_digest=DIGEST,
        presented_revision="lock-1",
        page_origin=ORIGIN,
        after=page.capture(),
    )
    assert click.native_calls == 1
    assert click.ai_calls == 0
    assert "data-clicked=" in page.capture().dom

    fill = driver.run(
        before=page.capture(),
        action={"type": "fill", "selector": "#name", "value": "ada"},
        presented_digest=DIGEST,
        presented_revision="lock-1",
        page_origin=ORIGIN,
        after=page.capture(),
    )
    assert fill.native_calls == 1
    after_fill = page.capture()
    assert 'value="ada"' in after_fill.dom
    assert after_fill.png != before.png

    scroll = driver.run(
        before=after_fill,
        action={"type": "scroll", "selector": "#page", "value": "120"},
        presented_digest=DIGEST,
        presented_revision="lock-1",
        page_origin=ORIGIN,
        after=page.capture(),
    )
    assert scroll.native_calls == 1
    assert "data-scroll-y=" in page.capture().dom
    assert page.action_log == ["click:#go", "fill:#name", "scroll"]

    blocked = TrustedWebDriver(
        "ws://127.0.0.1:0/devtools/browser/private",
        approved=approved,
        gate=gate,
        proof=proof,
        spool=tmp_path / "blocked",
        runner=None,
        now=now,
    )
    with pytest.raises(WebDispatchError, match="execution port"):
        blocked.run(
            before=fixture_web_observation(),
            action={"type": "click", "selector": "#go"},
            presented_digest=DIGEST,
            presented_revision="lock-1",
            page_origin=ORIGIN,
        )
    assert blocked.native_calls == 0


def test_rx_70_worker_entry_wires_local_execution_port(tmp_path: Path) -> None:
    now = datetime(2026, 11, 6, 10, 30, tzinfo=timezone.utc)
    binding = WebGuestEntryBinding(ENDPOINT, PEER, ORIGIN)
    assembled = assemble_web_worker_from_entry_binding(
        binding,
        runtime_root=tmp_path / "entry",
        proof_secret=SECRET,
        now=now,
        spawn_guest=True,
        connect_deadline_seconds=2.0,
        request_deadline_seconds=2.0,
    )
    try:
        assert assembled.replay is not None
        assert assembled.replay.context.runner is not None
        # Runner must accept TypedAction without returning browser handles.
        runner = assembled.replay.context.runner
        runner(parse_ipc_message({"type": "click", "selector": "#go"}))
        assert callable(runner)
        result = runner(TypedAction(type="fill", selector="#name", value="bee"))
        assert result is None
    finally:
        assembled.close()


def test_rx_70_local_page_rejects_foreign_selector() -> None:
    page = local_page_from_fixture_html(origin=ORIGIN)
    with pytest.raises(LocalPageRejected, match="allowlist|not found"):
        page.apply(TypedAction(type="click", selector="document.body", value=""))
