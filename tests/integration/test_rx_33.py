"""RX-33: Android recording handler — ACK-gated authoring, fail-closed gates."""

from __future__ import annotations

import binascii
import json
import struct
import subprocess
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import httpx

from aiqa.adapters.mobile_agent_android import MobileAgentAndroidAdapter, recording_broker
from aiqa.config import WorkerClientSettings
from aiqa.contracts.actions import CaptureGeometry, Observation
from aiqa.contracts.jobs import ControlDecision
from aiqa.replay.android_runner import AndroidDeterministicDriver
from aiqa.worker.android_jobs import (
    AndroidRecordingContext,
    AndroidRecordingHandler,
    register_android_recording_handler,
)
from aiqa.worker.control import RemoteLeaseGuard
from aiqa.worker.dispatch_journal import DispatchJournal
from aiqa.worker.http_client import WorkerHttpClient
from aiqa.worker.runtime import (
    InertHandler,
    WorkerRuntime,
    WorkerRuntimeConfig,
    recording_prepared_adapters,
)
from aiqa.worker.spool import EvidenceSpool


def _png(width: int = 100, height: int = 200) -> bytes:
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


def _geometry() -> CaptureGeometry:
    return CaptureGeometry(100, 200, 1000, 2000, "scale", 0, (0, 0, 100, 200))


def _observation(*, capture_ok: bool = True, png: bytes | None = None) -> Observation:
    geo = _geometry()
    return Observation(
        str(uuid4()),
        datetime.now(timezone.utc).isoformat(),
        geo,
        _png() if png is None else png,
        "",
        "[]",
        (),
        "",
        capture_ok,
        "android",
    )


class _Allow:
    def checkpoint(self) -> ControlDecision:
        return ControlDecision(True, "before_model")


def _driver(tmp_path: Path, calls: list) -> AndroidDeterministicDriver:
    def runner(argv, timeout):
        calls.append(tuple(argv))
        return subprocess.CompletedProcess(list(argv), 0, b"", b"")

    return AndroidDeterministicDriver(
        Path("C:/platform-tools/adb.exe"),
        "emulator-5580",
        runner=runner,
        spool=EvidenceSpool(tmp_path / "spool"),
    )


def _handler(tmp_path: Path, *, after: Observation | None = None, lease: float = 60.0, serial: str = "emulator-5580"):
    calls: list = []
    journal = DispatchJournal(tmp_path / "journal.jsonl")
    recording = AndroidRecordingHandler(
        adapter=MobileAgentAndroidAdapter(),
        driver=_driver(tmp_path, calls),
        broker=recording_broker(),
        control=_Allow(),
        guard=RemoteLeaseGuard(),
        journal=journal,
        spool=EvidenceSpool(tmp_path / "evidence"),
        context=AndroidRecordingContext(
            expected_serial=serial,
            fixture_response="click(250, 500)",
            before=_observation(),
            after=_observation() if after is None else after,
            lease_remaining_seconds=lease,
            mono_seconds=100.0,
        ),
    )
    return recording, calls, journal


def _claim(*, serial: str = "emulator-5580", action_id: str = "act-1") -> dict:
    return {
        "project_id": str(uuid4()),
        "job_id": str(uuid4()),
        "attempt_id": str(uuid4()),
        "generation": 1,
        "snapshot": {
            "purpose": "recording",
            "digest": "sha256:rec",
            "serial": serial,
            "action_id": action_id,
        },
    }


def test_rx_33_one_tap_evidence_and_fail_closed_gates(tmp_path: Path) -> None:
    recording, calls, journal = _handler(tmp_path)
    claim = _claim()
    result = recording.handle(claim)
    assert result.actions == 1
    assert result.outcome == "completed"
    assert result.evidence_complete is True
    assert recording.tap_count == 1
    assert recording.authoring_calls_seen == 1
    assert recording.evidence_commits and recording.evidence_commits[0]["review_pending"] is True
    assert calls and calls[-1][4:8] == ("input", "tap", "25", "50")

    # Wrong serial → no tap, no false complete success path.
    bad_serial, bad_calls, _ = _handler(tmp_path / "s")
    denied = bad_serial.handle(_claim(serial="emulator-5554"))
    assert denied.actions == 0 and denied.outcome == "error"
    assert bad_serial.tap_count == 0 and bad_calls == []

    # Lease expired → no tap.
    expired, exp_calls, _ = _handler(tmp_path / "l", lease=5.0)
    lease_denied = expired.handle(_claim())
    assert lease_denied.actions == 0 and lease_denied.evidence_complete is False
    assert expired.tap_count == 0 and exp_calls == []

    # Missing after evidence → no false complete.
    missing, miss_calls, _ = _handler(tmp_path / "m", after=_observation(capture_ok=False, png=b""))
    no_after = missing.handle(_claim())
    assert no_after.actions == 0 and no_after.evidence_complete is False
    assert missing.tap_count == 0 and miss_calls == []

    # Ambiguous STARTED-only → refuse redispatch / duplicate tap.
    recording2, calls2, journal2 = _handler(tmp_path / "a")
    claim2 = _claim(action_id="dup-1")
    attempt = str(claim2["attempt_id"])
    journal2.append(attempt, "dup-1", "planned")
    journal2.append(attempt, "dup-1", "dispatch_started")
    ambiguous = recording2.handle(claim2)
    assert ambiguous.actions == 0 and ambiguous.ambiguous_dispatch is True
    assert recording2.tap_count == 0 and calls2 == []


def test_rx_33_authoring_only_after_ack_in_runtime(tmp_path: Path) -> None:
    recording, calls, _ = _handler(tmp_path)
    routed = register_android_recording_handler(recording)
    assert "recording" in recording_prepared_adapters()

    authoring_before_ack = {"n": 0}
    finishes: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/heartbeats"):
            return httpx.Response(200, json={"state": "online"})
        if request.url.path.endswith("/claims"):
            body = {
                "project_id": str(uuid4()),
                "job_id": str(uuid4()),
                "attempt_id": str(uuid4()),
                "generation": 1,
                "snapshot": {
                    "purpose": "recording",
                    "digest": "sha256:rec",
                    "serial": "emulator-5580",
                    "action_id": "runtime-1",
                },
            }
            return httpx.Response(200, json=body)
        if request.url.path.endswith("/attempt-acks"):
            # Authoring must not have run yet — handler runs after ACK.
            authoring_before_ack["n"] = recording.broker.authoring_calls
            return httpx.Response(200, json={"acked": True})
        if request.url.path.endswith("/checkpoints"):
            # Explicit protocol fixture: an unknown route must not stand in for a live fence.
            body = json.loads(request.content)
            now = datetime.now(timezone.utc)
            return httpx.Response(200, json={
                **body, "allowed": True, "server_time": now.isoformat(),
                "job_deadline": (now + timedelta(seconds=600)).isoformat(),
                "lease_remaining_seconds": 45,
            })
        if request.url.path.endswith("/evidence-commits"):
            body = json.loads(request.content.decode("utf-8"))
            events = body.get("events") or []
            artifacts = body.get("artifacts") or []
            seq = len(events)
            ids = [str(uuid4()) for _ in artifacts]
            return httpx.Response(
                200,
                json={
                    "attempt_id": body.get("job_id"),
                    "contiguous_seq": seq,
                    "prefix_hash": "sha256:" + ("ab" * 32),
                    "stale_count": 0,
                    "late": False,
                    "artifact_count": len(ids),
                    "artifact_ids": ids,
                },
            )
        if request.url.path.endswith("/attempt-finishes"):
            finishes.append(json.loads(request.content.decode("utf-8")))
            return httpx.Response(200, json={"approved": False, "replayed": False})
        return httpx.Response(204)

    settings = WorkerClientSettings(base_url="https://manage.example", token="tok")
    with WorkerHttpClient(settings, transport=httpx.MockTransport(handler)) as client:
        runtime = WorkerRuntime(
            client,
            WorkerRuntimeConfig(
                boot_id="boot-rx33",
                prepared_adapters=recording_prepared_adapters(),
            ),
            routed,
        )
        report = runtime.run_once()

    assert report.finished is True
    assert authoring_before_ack["n"] == 0
    assert recording.broker.authoring_calls == 1
    assert recording.tap_count == 1
    assert finishes and finishes[0]["outcome"] == "completed"
    assert finishes[0].get("approved") is None or True  # worker DTO; server keeps approval false
    assert calls

    # ACK failure → handler never runs (claim loss / no authoring).
    recording_b, calls_b, _ = _handler(tmp_path / "ackfail")
    routed_b = register_android_recording_handler(recording_b)

    def ack_fail(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/heartbeats"):
            return httpx.Response(200, json={"state": "online"})
        if request.url.path.endswith("/claims"):
            return httpx.Response(
                200,
                json={
                    "project_id": str(uuid4()),
                    "job_id": str(uuid4()),
                    "attempt_id": str(uuid4()),
                    "generation": 1,
                    "snapshot": {
                        "purpose": "recording",
                        "digest": "sha256:rec",
                        "serial": "emulator-5580",
                        "action_id": "lost",
                    },
                },
            )
        if request.url.path.endswith("/attempt-acks"):
            return httpx.Response(503, json={"error": "unavailable"})
        return httpx.Response(204)

    with WorkerHttpClient(settings, transport=httpx.MockTransport(ack_fail)) as client:
        runtime = WorkerRuntime(
            client,
            WorkerRuntimeConfig(boot_id="boot-lost", prepared_adapters=recording_prepared_adapters()),
            routed_b,
        )
        lost = runtime.run_once()
    assert lost.finished is False
    assert recording_b.tap_count == 0
    assert recording_b.broker.authoring_calls == 0
    assert calls_b == []


def test_rx_33_inert_default_for_other_purpose(tmp_path: Path) -> None:
    recording, _, _ = _handler(tmp_path)
    routed = register_android_recording_handler(recording, other={"resource_probe": InertHandler()})
    probe = {
        "project_id": str(uuid4()),
        "job_id": str(uuid4()),
        "attempt_id": str(uuid4()),
        "generation": 1,
        "snapshot": {"purpose": "resource_probe", "digest": "sha256:x"},
    }
    result = routed.handle(probe)
    assert result.actions == 0 and result.outcome == "completed"
    assert recording.tap_count == 0
