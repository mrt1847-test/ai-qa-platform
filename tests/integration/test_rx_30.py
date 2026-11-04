"""RX-30: Web VM transport — connect/fail/exit/forged IPC/proof swap + no real VM ready."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aiqa.worker.isolated_web import (
    bind_web_vm_transport,
    close_guest_context,
    require_web_ready,
    transport_as_cleanup_provider,
)
from aiqa.worker.web_isolation_backend import (
    IsolationConfig,
    IsolationProof,
    IsolationRejected,
    WebIsolationGate,
    fixture_backend,
    unsupported_vm_backend,
)
from aiqa.worker.web_vm_transport import open_web_vm_transport


def _gate(backend=None) -> WebIsolationGate:
    return WebIsolationGate(
        IsolationConfig(
            backend=backend or fixture_backend(),
            proof_secret=b"rx30-fixture-secret!!",
        )
    )


def test_rx_30_connection_guest_exit_forged_ipc_and_proof_swap_cleanup() -> None:
    now = datetime(2026, 11, 4, 6, 0, tzinfo=timezone.utc)
    gate = _gate()
    proof = gate.issue_proof(now=now)
    transport = open_web_vm_transport(gate, approved_endpoints=("guest-ipc://approved",))

    assert transport.web_ready(now=now) is False
    assert require_web_ready(None) is False

    failing = open_web_vm_transport(
        gate,
        approved_endpoints=("guest-ipc://approved",),
        fail_connect=True,
    )
    with pytest.raises(IsolationRejected, match="connection failed"):
        failing.connect("guest-ipc://approved", proof, now=now)
    assert any("connect_failed" in item for item in failing.cleanup_proofs)
    assert failing.web_ready(now=now) is False

    with pytest.raises(IsolationRejected, match="not approved"):
        transport.connect("guest-ipc://other", proof, now=now)
    assert any("endpoint_refused" in item for item in transport.cleanup_proofs)

    session = transport.connect("guest-ipc://approved", proof, now=now)
    assert session.alive is True
    assert transport.web_ready(now=now) is True
    assert require_web_ready(transport.gate.web_ready(session.proof, now=now)) is True

    action = transport.dispatch_ipc(
        {"kind": "ipc", "payload": {"type": "click", "selector": "#go"}},
        now=now,
    )
    assert action.type == "click"
    assert transport.dispatch_count == 1

    with pytest.raises(IsolationRejected, match="secret|cdp|model"):
        transport.dispatch_ipc(
            {"kind": "ipc", "payload": {"type": "click", "selector": "#go", "model_key": "sk-live"}},
            now=now,
        )
    # previous cleanup killed session — reconnect
    transport.connect("guest-ipc://approved", proof, now=now)
    transport.inject_forged_ipc({"kind": "cdp", "cdp_url": "ws://127.0.0.1:9222"}, now=now)
    assert transport.session is not None and transport.session.alive is False
    assert any("ipc_rejected" in item for item in transport.cleanup_proofs)

    transport.connect("guest-ipc://approved", proof, now=now)
    forged = IsolationProof(
        backend=proof.backend,
        issued_at=proof.issued_at,
        expires_at=proof.expires_at,
        scope_hash=proof.scope_hash,
        nonce=proof.nonce,
        token="sha256:" + ("a" * 64),
    )
    with pytest.raises(IsolationRejected, match="replaced"):
        transport.dispatch_ipc(
            {"type": "click", "selector": "#go"},
            now=now,
            presented_proof=forged,
        )
    assert any("guest_proof_replaced" in item for item in transport.cleanup_proofs)

    transport.connect("guest-ipc://approved", proof, now=now)
    transport.note_guest_exit()
    assert transport.web_ready(now=now) is False
    with pytest.raises(IsolationRejected, match="not alive"):
        transport.dispatch_ipc({"type": "click", "selector": "#go"}, now=now)
    assert any("guest_exited" in item for item in transport.cleanup_proofs)

    proofs = close_guest_context(transport_as_cleanup_provider(transport))
    assert proofs
    assert any(item.startswith("guest-cleanup:") for item in proofs)


def test_rx_30_real_vm_without_admission_is_not_ready() -> None:
    now = datetime(2026, 11, 4, 6, 0, tzinfo=timezone.utc)
    gate = _gate(unsupported_vm_backend())
    proof = gate.issue_proof(now=now)
    transport = bind_web_vm_transport(
        gate,
        approved_endpoints=("guest-ipc://approved",),
        allow_real_vm=False,
    )
    with pytest.raises(IsolationRejected, match="real VM is not ready"):
        transport.connect("guest-ipc://approved", proof, now=now)
    assert transport.web_ready(now=now) is False
    assert gate.execution_count == 0
