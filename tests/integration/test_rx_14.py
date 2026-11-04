"""RX-14: TrustedWebDriver approval digest, origin, IPC allowlist, no AI."""

from __future__ import annotations

import binascii
import struct
import zlib
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from aiqa.contracts.actions import CaptureGeometry, Observation
from aiqa.recording.action_executor import ActionExecutor, run_web_deterministic
from aiqa.replay.driver import ApprovedWebPackage, TrustedWebDriver, WebDispatchError
from aiqa.replay.ipc import parse_ipc_message
from aiqa.worker.web_isolation_backend import (
    IsolationConfig,
    WebIsolationGate,
    fixture_backend,
)


def _png(width: int = 24, height: int = 48) -> bytes:
    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body))
            + kind
            + body
            + struct.pack(">I", binascii.crc32(kind + body) & 0xFFFFFFFF)
        )

    row = b"\x00" + b"\x00" * width * 3
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(row * height))
        + chunk(b"IEND", b"")
    )


def _observation(*, stamp: str | None = None) -> Observation:
    return Observation(
        str(uuid4()),
        stamp or datetime.now(timezone.utc).isoformat(),
        CaptureGeometry(24, 48, 24, 48, "identity", 0, (0, 0, 24, 48)),
        _png(),
        "<button id='go'>Go</button>",
        "",
        (),
        "",
        True,
        "web",
    )


def _gate_and_proof(origin: str = "https://app.example.test"):
    now = datetime(2026, 11, 3, 16, 0, tzinfo=timezone.utc)
    gate = WebIsolationGate(
        IsolationConfig(
            backend=fixture_backend(allowed_origins=(origin,)),
            proof_secret=b"rx14-fixture-secret!!",
        )
    )
    proof = gate.issue_proof(now=now)
    return gate, proof, now


def test_trusted_driver_rejects_forbidden_and_runs_allowlisted(tmp_path: Path) -> None:
    origin = "https://app.example.test"
    gate, proof, now = _gate_and_proof(origin)
    approved = ApprovedWebPackage(
        digest="sha256:" + ("a" * 64),
        revision="lock-1",
        origin=origin,
    )
    seen: list[str] = []

    def runner(action):
        seen.append(action.type)

    driver = TrustedWebDriver(
        "ws://127.0.0.1:9222/devtools/browser/private",
        approved=approved,
        gate=gate,
        proof=proof,
        spool=tmp_path / "spool",
        runner=runner,
        now=now,
    )
    assert driver.public_view()["owns_cdp"] is True
    assert "9222" not in str(driver.dispatch({"type": "click", "selector": "#go"}))

    with pytest.raises(WebDispatchError, match="forbidden|cdp"):
        driver.dispatch({"type": "click", "selector": "#go", "cdp_url": "ws://x"})
    with pytest.raises(WebDispatchError, match="forbidden|python"):
        driver.dispatch({"type": "click", "selector": "#go", "python": "print(1)"})
    with pytest.raises(ValueError):
        parse_ipc_message({"type": "click", "selector": "#go", "cdp_url": "ws://x"})

    before = _observation()
    after = _observation()
    result = driver.run(
        before=before,
        action={"type": "click", "selector": "#go"},
        presented_digest=approved.digest,
        presented_revision=approved.revision,
        page_origin=origin,
        after=after,
    )
    assert result.native_calls == 1
    assert result.retries == 0
    assert result.ai_calls == 0
    assert result.before_ref and result.after_ref
    assert seen == ["click"]

    with pytest.raises(WebDispatchError, match="digest"):
        driver.run(
            before=_observation(),
            action={"type": "fill", "selector": "#q", "value": "x"},
            presented_digest="sha256:" + ("b" * 64),
            presented_revision=approved.revision,
            page_origin=origin,
        )
    with pytest.raises(WebDispatchError, match="revision"):
        driver.run(
            before=_observation(),
            action={"type": "scroll", "selector": "body"},
            presented_digest=approved.digest,
            presented_revision="other-lock",
            page_origin=origin,
        )
    with pytest.raises(WebDispatchError, match="cross-origin"):
        driver.run(
            before=_observation(),
            action={"type": "click", "selector": "#go"},
            presented_digest=approved.digest,
            presented_revision=approved.revision,
            page_origin="https://evil.example.test",
        )
    with pytest.raises(WebDispatchError, match="selector|unsupported|ipc"):
        driver.run(
            before=_observation(),
            action={"type": "click", "selector": ""},
            presented_digest=approved.digest,
            presented_revision=approved.revision,
            page_origin=origin,
        )
    with pytest.raises(WebDispatchError, match="forbidden|shell"):
        driver.run(
            before=_observation(),
            action={"type": "click", "selector": "#go", "shell": "rm -rf /"},
            presented_digest=approved.digest,
            presented_revision=approved.revision,
            page_origin=origin,
        )

    forged = proof.__class__(
        backend=proof.backend,
        issued_at=proof.issued_at,
        expires_at=proof.expires_at,
        scope_hash=proof.scope_hash,
        nonce=proof.nonce,
        token="sha256:" + ("0" * 64),
    )
    bad = TrustedWebDriver(
        "ws://127.0.0.1:9222/devtools/browser/private",
        approved=approved,
        gate=gate,
        proof=forged,
        spool=tmp_path / "spool3",
        now=now,
    )
    with pytest.raises(WebDispatchError):
        bad.run(
            before=_observation(),
            action={"type": "click", "selector": "#go"},
            presented_digest=approved.digest,
            presented_revision=approved.revision,
            page_origin=origin,
        )

    executor = ActionExecutor(tmp_path / "exec-spool", ())
    bridged = run_web_deterministic(
        executor,
        driver=driver,
        before=_observation(),
        action={"type": "select", "selector": "#pick", "value": "1"},
        presented_digest=approved.digest,
        presented_revision=approved.revision,
        page_origin=origin,
        after=_observation(),
    )
    assert bridged.ai_calls == 0
    assert bridged.native_calls == 1
    assert executor.post_dispatch_retries == 0
