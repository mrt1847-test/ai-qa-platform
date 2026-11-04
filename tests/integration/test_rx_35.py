"""RX-35: local guest process IPC — send/recv, exit, timeout, size, forged endpoint, proof swap."""

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
)
from aiqa.worker.web_vm_transport import (
    GuestIpcLimits,
    spawn_local_guest_process,
)


ENDPOINT = "guest-ipc://local-fixture"
PEER = "rx35-peer-token"


def _gate() -> WebIsolationGate:
    return WebIsolationGate(
        IsolationConfig(
            backend=fixture_backend(),
            proof_secret=b"rx35-fixture-secret!!",
        )
    )


def test_rx_35_local_process_send_recv_exit_timeout_size_and_forged_endpoint() -> None:
    now = datetime(2026, 11, 4, 9, 0, tzinfo=timezone.utc)
    gate = _gate()
    proof = gate.issue_proof(now=now)
    guest = spawn_local_guest_process(
        endpoint_id=ENDPOINT,
        peer_token=PEER,
        max_message_bytes=4096,
    )
    try:
        transport = bind_web_vm_transport(
            gate,
            approved_endpoints=(ENDPOINT,),
            limits=GuestIpcLimits(
                connect_deadline_seconds=2.0,
                request_deadline_seconds=2.0,
                max_message_bytes=4096,
            ),
            bindings=(guest.binding,),
        )
        assert require_web_ready(None) is False
        assert transport.web_ready(now=now) is False

        session = transport.connect(ENDPOINT, proof, now=now, guest_process=guest, open_channel=True)
        assert session.alive is True
        assert transport.web_ready(now=now) is True

        action = transport.dispatch_ipc(
            {"kind": "ipc", "payload": {"type": "click", "selector": "#go"}},
            now=now,
        )
        assert action.type == "click"
        assert transport.dispatch_count == 1
        assert transport.channel_exchanges == 1

        # Forged / unapproved endpoint.
        with pytest.raises(IsolationRejected, match="not approved"):
            transport.connect("guest-ipc://forged", proof, now=now, open_channel=True)
        assert any("endpoint_refused" in item for item in transport.cleanup_proofs)

        # Reconnect after cleanup killed the prior session/link; guest already terminated on cleanup.
        guest2 = spawn_local_guest_process(endpoint_id=ENDPOINT, peer_token=PEER, max_message_bytes=4096)
        transport = bind_web_vm_transport(
            gate,
            approved_endpoints=(ENDPOINT,),
            limits=GuestIpcLimits(max_message_bytes=4096),
            bindings=(guest2.binding,),
        )
        transport.connect(ENDPOINT, proof, now=now, guest_process=guest2, open_channel=True)

        # Oversized outbound message → refuse at channel after typed parse.
        huge = {"kind": "ipc", "payload": {"type": "click", "selector": "#" + ("a" * 5000)}}
        with pytest.raises(IsolationRejected, match="size|exceeds|rejected"):
            transport.dispatch_ipc(huge, now=now)
        assert any("ipc_rejected" in item for item in transport.cleanup_proofs)

        # Early guest exit → cleanup, no further ready.
        guest3 = spawn_local_guest_process(endpoint_id=ENDPOINT, peer_token=PEER)
        transport = bind_web_vm_transport(
            gate,
            approved_endpoints=(ENDPOINT,),
            bindings=(guest3.binding,),
        )
        transport.connect(ENDPOINT, proof, now=now, guest_process=guest3, open_channel=True)
        guest3.terminate()
        with pytest.raises(IsolationRejected, match="exited|closed|alive"):
            transport.dispatch_ipc(
                {"kind": "ipc", "payload": {"type": "click", "selector": "#a"}},
                now=now,
            )
        assert transport.web_ready(now=now) is False
        assert any("guest_exited" in item or "ipc_rejected" in item for item in transport.cleanup_proofs)

        # Request timeout: connect without a listening peer after binding a dead port.
        limits = GuestIpcLimits(connect_deadline_seconds=0.2, request_deadline_seconds=0.2)
        dead = bind_web_vm_transport(
            gate,
            approved_endpoints=(ENDPOINT,),
            limits=limits,
            bindings=(guest3.binding,),  # port no longer listening
        )
        with pytest.raises(IsolationRejected, match="connection failed|timed out|closed"):
            dead.connect(ENDPOINT, proof, now=now, open_channel=True)
        assert any("connect_failed" in item for item in dead.cleanup_proofs)

        # Proof replacement still fail-closed.
        guest4 = spawn_local_guest_process(endpoint_id=ENDPOINT, peer_token=PEER)
        transport = bind_web_vm_transport(
            gate,
            approved_endpoints=(ENDPOINT,),
            bindings=(guest4.binding,),
        )
        transport.connect(ENDPOINT, proof, now=now, guest_process=guest4, open_channel=True)
        forged = IsolationProof(
            backend=proof.backend,
            issued_at=proof.issued_at,
            expires_at=proof.expires_at,
            scope_hash=proof.scope_hash,
            nonce=proof.nonce,
            token="sha256:" + ("b" * 64),
        )
        with pytest.raises(IsolationRejected, match="replaced"):
            transport.dispatch_ipc(
                {"kind": "ipc", "payload": {"type": "click", "selector": "#z"}},
                now=now,
                presented_proof=forged,
            )
        assert any("guest_proof_replaced" in item for item in transport.cleanup_proofs)
        assert require_web_ready(gate.web_ready(None, now=now)) is False

        receipts = close_guest_context(transport_as_cleanup_provider(transport))
        assert any(item.startswith("guest-cleanup:") for item in receipts)
    finally:
        if guest.poll_alive():
            guest.terminate()


def test_rx_35_web_ready_still_requires_verified_proof() -> None:
    now = datetime(2026, 11, 4, 9, 5, tzinfo=timezone.utc)
    gate = _gate()
    guest = spawn_local_guest_process(endpoint_id=ENDPOINT, peer_token=PEER)
    try:
        transport = bind_web_vm_transport(
            gate,
            approved_endpoints=(ENDPOINT,),
            bindings=(guest.binding,),
        )
        # Channel alone cannot make Web ready without connect+proof.
        assert transport.web_ready(now=now) is False
        proof = gate.issue_proof(now=now)
        transport.connect(ENDPOINT, proof, now=now, guest_process=guest, open_channel=True)
        assert transport.web_ready(now=now) is True
        expired = IsolationProof(
            backend=proof.backend,
            issued_at=proof.issued_at,
            expires_at="2020-01-01T00:00:00+00:00",
            scope_hash=proof.scope_hash,
            nonce=proof.nonce,
            token=proof.token,
        )
        # Swapping session proof to expired token path: verify via gate directly.
        assert gate.web_ready(expired, now=now) is None
    finally:
        guest.terminate()
