"""RX-60: execution settings → Web handler assembly; local guest connect/timeout/origin/proof."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from aiqa.replay.driver import TrustedWebDriver, WebDispatchError
from aiqa.worker.http_client import WorkerHttpClient
from aiqa.worker.isolated_web import (
    bind_web_vm_transport,
    require_web_ready,
    web_handlers_blocked_without_proof,
)
from aiqa.worker.runtime import run_worker_process, web_worker_prepared_adapters
from aiqa.worker.web_isolation_backend import IsolationProof
from aiqa.worker.web_jobs import (
    assemble_web_worker_from_entry_binding,
    build_fixture_web_gate,
)
from aiqa.worker.web_vm_transport import (
    GuestIpcLimits,
    WebGuestEntryBinding,
    load_web_guest_entry_binding,
    spawn_local_guest_process,
)

ORIGIN = "https://app.example.test"
OTHER_ORIGIN = "https://evil.example.test"
ENDPOINT = "guest-ipc://web-rx60"
PEER = "rx60-peer-token-ok"
SECRET = b"rx60-fixture-proof!!!!"


def _binding() -> WebGuestEntryBinding:
    return WebGuestEntryBinding(ENDPOINT, PEER, ORIGIN)


def _recording_claim(*, origin: str = ORIGIN, purpose: str = "recording") -> dict[str, object]:
    return {
        "attempt_id": str(uuid4()),
        "snapshot": {
            "purpose": purpose,
            "origin": origin,
            "action_id": "web-rx60",
            "endpoint_id": ENDPOINT,
            "revision": "lock-1",
        },
    }


def test_rx_60_entry_binding_and_local_guest_connect_timeout_origin_proof(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)
    env = {
        "AIQA_WEB_GUEST_ENDPOINT": ENDPOINT,
        "AIQA_WEB_GUEST_PEER_TOKEN": PEER,
        "AIQA_WEB_APPROVED_ORIGIN": ORIGIN,
    }
    loaded = load_web_guest_entry_binding(env)
    assert loaded is not None
    assert loaded.endpoint_id == ENDPOINT
    assert loaded.approved_origin == ORIGIN
    assert "recording" in web_worker_prepared_adapters()
    assert web_handlers_blocked_without_proof(None) is True
    assert require_web_ready(None) is False

    assembled = assemble_web_worker_from_entry_binding(
        _binding(),
        runtime_root=tmp_path / "ok",
        proof_secret=SECRET,
        now=now,
        connect_deadline_seconds=2.0,
        request_deadline_seconds=2.0,
    )
    try:
        assert assembled.guest is not None
        assert assembled.transport.web_ready(now=now) is False
        assert web_handlers_blocked_without_proof(
            assembled.gate.web_ready(assembled.proof, now=now)
        ) is False

        happy = assembled.handler.handle(_recording_claim())
        assert happy.actions == 1
        assert happy.outcome == "completed"
        assert assembled.recording is not None
        assert assembled.recording.authoring_dispatches == 1
        assert assembled.transport.dispatch_count == 1

        # Wrong origin stays at zero actions.
        other = assembled.handler.handle(_recording_claim(origin=OTHER_ORIGIN))
        assert other.actions == 0
    finally:
        assembled.close()

    # Connect timeout against a port that never accepts.
    gate = build_fixture_web_gate(approved_origin=ORIGIN, proof_secret=SECRET)
    proof = gate.issue_proof(now=now)
    from aiqa.worker.web_vm_transport import GuestEndpointBinding

    dead = GuestEndpointBinding(ENDPOINT, "127.0.0.1", 1, PEER)
    timed = bind_web_vm_transport(
        gate,
        approved_endpoints=(ENDPOINT,),
        limits=GuestIpcLimits(connect_deadline_seconds=0.2, request_deadline_seconds=0.2),
        bindings=(dead,),
    )
    with pytest.raises(Exception):
        timed.connect(ENDPOINT, proof, now=now, open_channel=True)
    assert any("connect" in item or "failed" in item for item in timed.cleanup_proofs) or (
        timed.connect_attempts >= 1
    )
    timed.close()

    # Bad / forged proof → zero actions, no IPC.
    good_gate = build_fixture_web_gate(approved_origin=ORIGIN, proof_secret=SECRET)
    forged = IsolationProof(
        backend="fixture",
        issued_at=now.isoformat(),
        expires_at=now.isoformat(),
        scope_hash=good_gate.config.scope_hash,
        nonce="forged-nonce",
        token="sha256:" + ("0" * 64),
    )
    bad = assemble_web_worker_from_entry_binding(
        _binding(),
        runtime_root=tmp_path / "bad-proof",
        proof_secret=SECRET,
        now=now,
        proof=forged,
    )
    try:
        denied = bad.handler.handle(_recording_claim())
        assert denied.actions == 0
        assert bad.recording is not None
        assert bad.recording.authoring_dispatches == 0
        assert bad.transport.dispatch_count == 0
    finally:
        bad.close()

    # Guest disconnect / terminate → not ready.
    guest = spawn_local_guest_process(endpoint_id=ENDPOINT, peer_token=PEER)
    transport = bind_web_vm_transport(
        gate,
        approved_endpoints=(ENDPOINT,),
        bindings=(guest.binding,),
    )
    try:
        transport.connect(ENDPOINT, proof, now=now, guest_process=guest, open_channel=True)
        assert transport.web_ready(now=now) is True
        guest.terminate()
        assert transport.web_ready(now=now) is False
    finally:
        transport.close()
        guest.terminate()


def test_rx_60_driver_blocks_without_proof_and_wrong_origin(tmp_path: Path) -> None:
    now = datetime(2026, 11, 5, 12, 30, tzinfo=timezone.utc)
    gate = build_fixture_web_gate(approved_origin=ORIGIN, proof_secret=SECRET)
    proof = gate.issue_proof(now=now)
    from aiqa.replay.driver import ApprovedWebPackage
    from aiqa.worker.web_jobs import fixture_web_observation

    approved = ApprovedWebPackage("sha256:" + ("ab" * 32), "lock-1", ORIGIN)
    driver = TrustedWebDriver(
        "http://127.0.0.1:9222",
        approved=approved,
        gate=gate,
        proof=proof,
        spool=tmp_path / "spool",
        now=now,
    )
    assert driver.execution_allowed(now=now) is True
    before = fixture_web_observation()
    with pytest.raises(WebDispatchError, match="cross-origin|refused"):
        driver.run(
            before=before,
            action={"kind": "ipc", "payload": {"type": "click", "selector": "#go"}},
            presented_digest=approved.digest,
            presented_revision=approved.revision,
            page_origin=OTHER_ORIGIN,
        )

    forged = IsolationProof(
        backend="fixture",
        issued_at=now.isoformat(),
        expires_at=now.isoformat(),
        scope_hash=gate.config.scope_hash,
        nonce="x",
        token="sha256:" + ("f" * 64),
    )
    blocked = TrustedWebDriver(
        "http://127.0.0.1:9222",
        approved=approved,
        gate=gate,
        proof=forged,
        spool=tmp_path / "spool2",
        now=now,
    )
    assert blocked.execution_allowed(now=now) is False
    with pytest.raises(WebDispatchError, match="not ready|isolation"):
        blocked.run(
            before=before,
            action={"kind": "ipc", "payload": {"type": "click", "selector": "#go"}},
            presented_digest=approved.digest,
            presented_revision=approved.revision,
            page_origin=ORIGIN,
        )


def test_rx_60_run_worker_process_assembles_web_handlers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env = {
        "AIQA_MANAGEMENT_BASE_URL": "https://manage.example",
        "AIQA_WORKER_TOKEN": "tok-rx60",
        "AIQA_WORKER_BOOT_ID": "boot-rx60",
        "AIQA_WORKER_PROJECT_ID": str(uuid4()),
        "AIQA_WORKER_RUNTIME_ROOT": str(tmp_path / "runtime"),
        "AIQA_WORKER_MAX_CYCLES": "1",
        "AIQA_WORKER_MODEL_MODE": "fixture",
        "AIQA_WEB_GUEST_ENDPOINT": ENDPOINT,
        "AIQA_WEB_GUEST_PEER_TOKEN": PEER,
        "AIQA_WEB_APPROVED_ORIGIN": ORIGIN,
        "AIQA_WEB_GUEST_PROOF_SECRET": SECRET.decode("utf-8"),
    }
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        seen.append(path.rsplit("/", 1)[-1])
        if path.endswith("/heartbeats"):
            return httpx.Response(200, json={"state": "online"})
        if path.endswith("/inventory"):
            return httpx.Response(200, json={"state": "ready"})
        if path.endswith("/claims"):
            # Idle claim — assembly must still spawn guest then exit cleanly.
            return httpx.Response(204)
        return httpx.Response(404)

    original = WorkerHttpClient.__init__

    def patched(self, settings, *, transport=None, **kwargs):
        return original(self, settings, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(WorkerHttpClient, "__init__", patched)
    code = run_worker_process(env, max_cycles=1)
    assert code == 0
    assert "heartbeats" in seen or "claims" in seen
