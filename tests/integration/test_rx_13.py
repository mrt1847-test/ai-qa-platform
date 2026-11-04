"""RX-13: Web isolation gate, proof TTL, and guest IPC bypass refusal."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aiqa.replay.ipc import parse_ipc_message
from aiqa.worker.isolated_web import require_web_ready
from aiqa.worker.web_isolation_backend import (
    DEFAULT_PROOF_TTL_SECONDS,
    IsolationConfig,
    IsolationProof,
    IsolationRejected,
    WebIsolationGate,
    admit_guest_channel,
    fixture_backend,
)


def _gate(*, ttl: int = DEFAULT_PROOF_TTL_SECONDS) -> WebIsolationGate:
    return WebIsolationGate(
        IsolationConfig(
            backend=fixture_backend(ttl_seconds=ttl),
            proof_secret=b"rx13-fixture-secret!!",
        )
    )


def test_missing_forged_expired_proof_keeps_execution_zero() -> None:
    now = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
    gate = _gate(ttl=60)
    assert require_web_ready(None) is False
    assert gate.web_ready(None, now=now) is None
    assert gate.execution_count == 0

    with pytest.raises(IsolationRejected, match="not ready|missing"):
        gate.run_guest_ipc(None, {"type": "click", "selector": "#go"}, now=now)
    assert gate.execution_count == 0

    proof = gate.issue_proof(now=now)
    forged = IsolationProof(
        backend=proof.backend,
        issued_at=proof.issued_at,
        expires_at=proof.expires_at,
        scope_hash=proof.scope_hash,
        nonce=proof.nonce,
        token="sha256:" + ("0" * 64),
    )
    with pytest.raises(IsolationRejected, match="forged"):
        gate.verify_proof(forged, now=now)
    with pytest.raises(IsolationRejected):
        gate.run_guest_ipc(forged, {"type": "click", "selector": "#go"}, now=now)
    assert gate.execution_count == 0

    expired_at = now + timedelta(seconds=61)
    with pytest.raises(IsolationRejected, match="expired"):
        gate.verify_proof(proof, now=expired_at)
    with pytest.raises(IsolationRejected):
        gate.run_guest_ipc(proof, {"type": "click", "selector": "#go"}, now=expired_at)
    assert gate.execution_count == 0

    # Wrong scope (config change) looks like a forged/mismatched proof
    other = WebIsolationGate(
        IsolationConfig(
            backend=fixture_backend(allowed_origins=("https://other.example.test",)),
            proof_secret=b"rx13-fixture-secret!!",
        )
    )
    with pytest.raises(IsolationRejected, match="scope"):
        other.verify_proof(proof, now=now)
    assert other.execution_count == 0


def test_fixture_admits_ipc_and_refuses_bypass_kinds() -> None:
    now = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
    gate = _gate()
    proof = gate.issue_proof(now=now)
    ready = gate.web_ready(proof, now=now)
    assert ready is not None
    assert require_web_ready(ready) is True
    assert ready.backend == "fixture"
    assert gate.config.backend.proof_ttl_seconds == DEFAULT_PROOF_TTL_SECONDS

    action = gate.run_guest_ipc(
        proof,
        {"kind": "ipc", "payload": {"type": "click", "selector": "#submit"}},
        now=now,
    )
    assert action.type == "click"
    assert gate.execution_count == 1

    # Direct typed payload without kind still goes through IPC admit
    gate.run_guest_ipc(proof, {"type": "fill", "selector": "#q", "value": "ok"}, now=now)
    assert gate.execution_count == 2

    for kind in (
        "host_filesystem",
        "host_process",
        "adb",
        "cdp",
        "direct_provider",
        "arbitrary_network",
    ):
        before = gate.execution_count
        with pytest.raises(IsolationRejected, match="bypass"):
            gate.run_guest_ipc(proof, {"kind": kind, "path": "C:/secret"}, now=now)
        assert gate.execution_count == before

    with pytest.raises(IsolationRejected, match="bypass|cdp"):
        admit_guest_channel(
            {"type": "click", "selector": "#x", "cdp_url": "ws://127.0.0.1:9222"},
            allowed_actions=gate.config.backend.allowed_actions,
        )
    with pytest.raises(ValueError):
        parse_ipc_message({"type": "click", "cdp_url": "ws://127.0.0.1:9222/devtools/browser"})

    # IsolationConfig itself cannot be constructed without backend/secret
    with pytest.raises(IsolationRejected):
        IsolationConfig(backend=fixture_backend(), proof_secret=b"short")
