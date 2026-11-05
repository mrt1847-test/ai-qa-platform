"""RX-65: observe → sanitize → model plan → dispatch; capture failure skips the model."""

from __future__ import annotations

import binascii
import struct
import subprocess
import zlib
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from aiqa.adapters.mobile_agent_android import MobileAgentAndroidAdapter, recording_broker
from aiqa.contracts.actions import CaptureGeometry, Observation
from aiqa.contracts.jobs import ControlDecision
from aiqa.replay.android_runner import AndroidDeterministicDriver
from aiqa.worker.android_jobs import (
    AndroidRecordingContext,
    AndroidRecordingHandler,
    observation_authoring_inputs,
    server_model_plan_provider,
)
from aiqa.worker.control import RemoteLeaseGuard
from aiqa.worker.dispatch_journal import DispatchJournal
from aiqa.worker.spool import EvidenceSpool


def _png(width: int = 100, height: int = 200, fill: bytes = b"\xff\x00\x00") -> bytes:
    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body))
            + kind
            + body
            + struct.pack(">I", binascii.crc32(kind + body) & 0xFFFFFFFF)
        )

    row = b"\x00" + fill * width
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(row * height))
        + chunk(b"IEND", b"")
    )


def _geometry() -> CaptureGeometry:
    return CaptureGeometry(100, 200, 1000, 2000, "scale", 0, (0, 0, 100, 200))


def _observation(*, obs_id: str | None = None, fill: bytes = b"\xff\x00\x00", stdout: str = "[]") -> Observation:
    return Observation(
        obs_id or str(uuid4()),
        datetime.now(timezone.utc).isoformat(),
        _geometry(),
        _png(fill=fill),
        "",
        stdout,
        (),
        "",
        True,
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


def _claim() -> dict:
    return {
        "project_id": str(uuid4()),
        "job_id": str(uuid4()),
        "attempt_id": str(uuid4()),
        "generation": 1,
        "snapshot": {"purpose": "recording", "serial": "emulator-5580"},
    }


def test_rx_65_different_observations_yield_different_actions(tmp_path: Path) -> None:
    calls: list = []
    seen: list[str] = []

    def plan_provider(claim: dict) -> str:
        obs = claim["observation"]
        assert isinstance(obs, Observation)
        inputs = observation_authoring_inputs(obs, previous_result=str(claim.get("previous_result") or ""))
        assert any(item.startswith("observation_id:") for item in inputs)
        assert any(item.startswith("screen_digest:sha256:") for item in inputs)
        assert b"\x89PNG" not in " ".join(inputs).encode()
        seen.append(obs.observation_id)
        if obs.observation_id.endswith("a"):
            return "click(100, 200)"
        return "click(300, 400)"

    first = _observation(obs_id="obs-a", fill=b"\xff\x00\x00")
    second = _observation(obs_id="obs-b", fill=b"\x00\xff\x00")
    handler = AndroidRecordingHandler(
        adapter=MobileAgentAndroidAdapter(),
        driver=_driver(tmp_path, calls),
        broker=recording_broker(),
        control=_Allow(),
        guard=RemoteLeaseGuard(),
        journal=DispatchJournal(tmp_path / "journal.jsonl"),
        spool=EvidenceSpool(tmp_path / "handler-spool"),
        context=AndroidRecordingContext(
            expected_serial="emulator-5580",
            fixture_response="",
            fixture_responses=(),
            step_observations=(
                (first, _observation()),
                (second, _observation()),
                (_observation(), _observation()),
            ),
            plan_provider=plan_provider,
            lease_remaining_seconds=60.0,
            mono_seconds=100.0,
            max_actions=2,
        ),
    )
    # Force stop after two taps without finish → error, but actions still show distinct plans.
    result = handler.handle(_claim())
    assert result.actions == 2
    assert seen == ["obs-a", "obs-b"]
    assert len(calls) == 2
    assert calls[0][4:8] == ("input", "tap", "10", "20")
    assert calls[1][4:8] == ("input", "tap", "30", "40")


def test_rx_65_capture_failure_skips_model_and_device(tmp_path: Path) -> None:
    calls: list = []
    model_calls = {"n": 0}

    def plan_provider(claim: dict) -> str:
        model_calls["n"] += 1
        return "click(250, 500)"

    bad = Observation(
        str(uuid4()),
        datetime.now(timezone.utc).isoformat(),
        _geometry(),
        b"",
        "",
        "[]",
        (),
        "",
        False,
        "android",
    )
    handler = AndroidRecordingHandler(
        adapter=MobileAgentAndroidAdapter(),
        driver=_driver(tmp_path / "fail", calls),
        broker=recording_broker(),
        control=_Allow(),
        guard=RemoteLeaseGuard(),
        journal=DispatchJournal(tmp_path / "fail" / "journal.jsonl"),
        spool=EvidenceSpool(tmp_path / "fail" / "handler-spool"),
        context=AndroidRecordingContext(
            expected_serial="emulator-5580",
            fixture_response="",
            plan_provider=plan_provider,
            before=bad,
            after=_observation(),
            lease_remaining_seconds=60.0,
            mono_seconds=100.0,
            max_actions=1,
        ),
    )
    result = handler.handle(_claim())
    assert result.actions == 0
    assert result.outcome == "error"
    assert model_calls["n"] == 0
    assert calls == []


def test_rx_65_model_finish_dispatches_zero_device_actions(tmp_path: Path) -> None:
    calls: list = []
    model_calls = {"n": 0}

    def plan_provider(claim: dict) -> str:
        model_calls["n"] += 1
        assert claim["observation"].observation_id
        return "finish()"

    handler = AndroidRecordingHandler(
        adapter=MobileAgentAndroidAdapter(),
        driver=_driver(tmp_path / "finish", calls),
        broker=recording_broker(),
        control=_Allow(),
        guard=RemoteLeaseGuard(),
        journal=DispatchJournal(tmp_path / "finish" / "journal.jsonl"),
        spool=EvidenceSpool(tmp_path / "finish" / "handler-spool"),
        context=AndroidRecordingContext(
            expected_serial="emulator-5580",
            fixture_response="",
            plan_provider=plan_provider,
            step_observations=((_observation(), _observation()),),
            lease_remaining_seconds=60.0,
            mono_seconds=100.0,
            max_actions=3,
        ),
    )
    result = handler.handle(_claim())
    assert result.outcome == "completed"
    assert result.actions == 0
    assert handler.finished_by_model is True
    assert model_calls["n"] == 1
    assert calls == []


def test_rx_65_server_plan_provider_sends_observation_digests(tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    class _Client:
        def request_model(self, **kwargs):
            captured.update(kwargs["payload"])
            return {"allowed": True, "content": "finish()"}

    provider = server_model_plan_provider(_Client())
    obs = _observation(obs_id="obs-server", stdout='{"nodes":[]}')
    content = provider(
        {
            "project_id": str(uuid4()),
            "attempt_id": str(uuid4()),
            "snapshot": {"intent_hash": "sha256:" + ("a" * 64)},
            "observation": obs,
            "previous_result": "tap:1,2",
        }
    )
    assert content == "finish()"
    inputs = captured["sanitized_inputs"]
    assert isinstance(inputs, list)
    assert inputs[0].startswith("observation_id:obs-server")
    assert any(item.startswith("screen_digest:sha256:") for item in inputs)
    assert any(item.startswith("hierarchy_digest:sha256:") for item in inputs)
    assert "previous_result:tap:1,2" in inputs
    assert captured["intent_hash"].startswith("sha256:")
