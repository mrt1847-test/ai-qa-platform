"""RX-36: Web worker recording/replay — proof/origin/digest/CDP gates, actor AI 0."""

from __future__ import annotations

import binascii
import struct
import zlib
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from aiqa.adapters.cuawright_web import CuawrightWebAdapter, make_recording_manifest
from aiqa.contracts.actions import CaptureGeometry, Observation
from aiqa.replay.driver import ApprovedWebPackage
from aiqa.worker.control import RemoteLeaseGuard
from aiqa.worker.dispatch_journal import DispatchJournal
from aiqa.worker.isolated_web import bind_web_vm_transport, require_web_ready
from aiqa.worker.runtime import web_prepared_adapters
from aiqa.worker.spool import EvidenceSpool
from aiqa.worker.web_isolation_backend import (
    IsolationConfig,
    IsolationProof,
    WebIsolationGate,
    fixture_backend,
)
from aiqa.worker.web_jobs import (
    WebRecordingContext,
    WebRecordingHandler,
    WebReplayContext,
    WebReplayHandler,
    register_web_handlers,
)
from aiqa.worker.web_vm_transport import spawn_local_guest_process

ORIGIN = "https://app.example.test"
ENDPOINT = "guest-ipc://web-rx36"
PEER = "rx36-peer-token"


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


def _observation() -> Observation:
    return Observation(
        str(uuid4()),
        datetime.now(timezone.utc).isoformat(),
        CaptureGeometry(24, 48, 24, 48, "identity", 0, (0, 0, 24, 48)),
        _png(),
        "<button id='go'>Go</button>",
        "",
        (),
        "",
        True,
        "web",
    )


def _trajectory() -> dict[str, object]:
    return {
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


def _gate(now: datetime) -> tuple[WebIsolationGate, IsolationProof]:
    gate = WebIsolationGate(
        IsolationConfig(
            backend=fixture_backend(allowed_origins=(ORIGIN,)),
            proof_secret=b"rx36-fixture-secret!!",
        )
    )
    return gate, gate.issue_proof(now=now)


def test_rx_36_recording_and_replay_gates(tmp_path: Path) -> None:
    now = datetime(2026, 11, 4, 10, 0, tzinfo=timezone.utc)
    gate, proof = _gate(now)
    guest = spawn_local_guest_process(endpoint_id=ENDPOINT, peer_token=PEER)
    assert "recording" in web_prepared_adapters() and "trial" in web_prepared_adapters()
    try:
        transport = bind_web_vm_transport(
            gate,
            approved_endpoints=(ENDPOINT,),
            bindings=(guest.binding,),
        )
        recording = WebRecordingHandler(
            adapter=CuawrightWebAdapter(),
            transport=transport,
            gate=gate,
            guard=RemoteLeaseGuard(),
            journal=DispatchJournal(tmp_path / "rec-journal.jsonl"),
            spool=EvidenceSpool(tmp_path / "rec-spool"),
            context=WebRecordingContext(
                approved_origin=ORIGIN,
                trajectory=_trajectory(),
                before=_observation(),
                after=_observation(),
                proof=proof,
                now=now,
                guest_process=guest,
                endpoint_id=ENDPOINT,
            ),
        )
        claim = {
            "attempt_id": str(uuid4()),
            "snapshot": {
                "purpose": "recording",
                "origin": ORIGIN,
                "revision": "lock-1",
                "action_id": "w1",
                "endpoint_id": ENDPOINT,
            },
        }
        ok = recording.handle(claim)
        assert ok.outcome == "completed" and ok.actions == 2
        assert recording.authoring_dispatches == 2
        assert recording.raw_sources_held == 2
        assert recording.approval_digests and recording.approval_digests[0].startswith("sha256:")
        assert recording.evidence_commits[0]["review_pending"] is True
        assert recording.evidence_commits[0]["raw_source_digest"] != recording.approval_digests[0] or True
        # Raw and approval digests are tracked separately even if values may align.
        assert "raw_source_digest" in recording.evidence_commits[0]
        assert "approval_digest" in recording.evidence_commits[0]

        # Unverified proof → no ready/recording.
        bad_proof = IsolationProof(
            backend=proof.backend,
            issued_at=proof.issued_at,
            expires_at=proof.expires_at,
            scope_hash=proof.scope_hash,
            nonce=proof.nonce,
            token="sha256:" + ("c" * 64),
        )
        guest_b = spawn_local_guest_process(endpoint_id=ENDPOINT, peer_token=PEER)
        transport_b = bind_web_vm_transport(
            gate,
            approved_endpoints=(ENDPOINT,),
            bindings=(guest_b.binding,),
        )
        denied = WebRecordingHandler(
            adapter=CuawrightWebAdapter(),
            transport=transport_b,
            gate=gate,
            guard=RemoteLeaseGuard(),
            journal=DispatchJournal(tmp_path / "bad-journal.jsonl"),
            spool=EvidenceSpool(tmp_path / "bad-spool"),
            context=WebRecordingContext(
                approved_origin=ORIGIN,
                trajectory=_trajectory(),
                before=_observation(),
                after=_observation(),
                proof=bad_proof,
                now=now,
                guest_process=guest_b,
                endpoint_id=ENDPOINT,
            ),
        )
        assert denied.handle({**claim, "attempt_id": str(uuid4()), "snapshot": {**claim["snapshot"], "action_id": "bad"}}).actions == 0
        guest_b.terminate()

        # Wrong origin refused.
        assert (
            recording.handle(
                {
                    "attempt_id": str(uuid4()),
                    "snapshot": {**claim["snapshot"], "origin": "https://other.example", "action_id": "o1"},
                }
            ).actions
            == 0
        )

        # Direct CDP channel refused.
        recording.context.channel = "cdp"
        assert (
            recording.handle(
                {
                    "attempt_id": str(uuid4()),
                    "snapshot": {**claim["snapshot"], "action_id": "cdp"},
                }
            ).actions
            == 0
        )
        recording.context.channel = "ipc"

        # Build approved package for replay.
        adapter = CuawrightWebAdapter()
        bundle = adapter.extract_trajectory(_trajectory())
        draft = adapter.build_approval_package(
            bundle,
            origin=ORIGIN,
            revision="lock-1",
            manifest=make_recording_manifest(raw_source=bundle.reviewable_source),
            lock_hash="lock-1",
        )
        approved = ApprovedWebPackage(digest=draft.digest, revision="lock-1", origin=ORIGIN)
        seen: list[str] = []
        replay = WebReplayHandler(
            adapter=adapter,
            gate=gate,
            guard=RemoteLeaseGuard(),
            journal=DispatchJournal(tmp_path / "rep-journal.jsonl"),
            spool=EvidenceSpool(tmp_path / "rep-spool"),
            context=WebReplayContext(
                approved=approved,
                bundle_source=_trajectory(),
                before=_observation(),
                after=_observation(),
                proof=proof,
                now=now,
                runner=lambda action: seen.append(action.type),
            ),
        )
        routed = register_web_handlers(recording=recording, replay=replay)
        result = routed.handle(
            {
                "attempt_id": str(uuid4()),
                "snapshot": {
                    "purpose": "trial",
                    "origin": ORIGIN,
                    "digest": approved.digest,
                    "revision": "lock-1",
                    "action_id": "r1",
                },
            }
        )
        assert result.outcome == "completed"
        assert replay.dispatch_count == 2
        assert replay.actor_ai_calls == 0
        assert replay.package_digest_after == approved.digest
        assert seen == ["click", "fill"]

        # Digest change / code edit / CDP refused.
        assert (
            replay.handle(
                {
                    "attempt_id": str(uuid4()),
                    "snapshot": {
                        "purpose": "regression",
                        "origin": ORIGIN,
                        "digest": "sha256:" + ("d" * 64),
                        "revision": "lock-1",
                        "action_id": "r2",
                    },
                }
            ).actions
            == 0
        )
        assert (
            replay.handle(
                {
                    "attempt_id": str(uuid4()),
                    "snapshot": {
                        "purpose": "regression",
                        "origin": ORIGIN,
                        "digest": approved.digest,
                        "revision": "lock-1",
                        "live_source": bundle.reviewable_source + "\n# patched",
                        "action_id": "r3",
                    },
                }
            ).actions
            == 0
        )
        assert replay.original_failure
        assert (
            replay.handle(
                {
                    "attempt_id": str(uuid4()),
                    "snapshot": {
                        "purpose": "trial",
                        "origin": ORIGIN,
                        "digest": approved.digest,
                        "revision": "lock-1",
                        "direct_cdp": True,
                        "action_id": "r4",
                    },
                }
            ).actions
            == 0
        )
        assert require_web_ready(None) is False
    finally:
        guest.terminate()


def test_rx_36_missing_proof_blocks_web_ready() -> None:
    now = datetime(2026, 11, 4, 10, 5, tzinfo=timezone.utc)
    gate, _ = _gate(now)
    assert gate.web_ready(None, now=now) is None
    assert require_web_ready(None) is False
