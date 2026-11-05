"""RX-64: per-attempt recording counters; cancel/budget are not approval-ready completed."""

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
from aiqa.worker.android_jobs import AndroidRecordingContext, AndroidRecordingHandler
from aiqa.worker.control import RemoteLeaseGuard
from aiqa.worker.dispatch_journal import DispatchJournal
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


def _observation() -> Observation:
    return Observation(
        str(uuid4()),
        datetime.now(timezone.utc).isoformat(),
        _geometry(),
        _png(),
        "",
        "[]",
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


def _handler(
    tmp_path: Path,
    calls: list,
    *,
    responses: tuple[str, ...] = ("click(250, 500)", "finish()"),
    max_actions: int = 50,
) -> AndroidRecordingHandler:
    observations = tuple((_observation(), _observation()) for _ in responses)
    return AndroidRecordingHandler(
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
            fixture_responses=responses,
            step_observations=observations,
            lease_remaining_seconds=60.0,
            mono_seconds=100.0,
            max_actions=max_actions,
        ),
    )


def _claim() -> dict:
    return {
        "project_id": str(uuid4()),
        "job_id": str(uuid4()),
        "attempt_id": str(uuid4()),
        "generation": 1,
        "snapshot": {"purpose": "recording", "serial": "emulator-5580"},
    }


def test_rx_64_two_attempts_do_not_accumulate_actions(tmp_path: Path) -> None:
    calls: list = []
    handler = _handler(tmp_path, calls, responses=("click(250, 500)", "finish()"))
    first = handler.handle(_claim())
    assert first.outcome == "completed"
    assert first.actions == 1
    assert first.review_pending is True
    owners_first = {item["attempt_id"] for item in handler.evidence_commits}
    assert len(owners_first) == 1
    assert len(calls) == 1

    second = handler.handle(_claim())
    assert second.outcome == "completed"
    assert second.actions == 1
    assert second.actions != 2
    owners_second = {item["attempt_id"] for item in handler.evidence_commits}
    assert len(owners_second) == 1
    assert owners_second != owners_first
    assert len(calls) == 2


def test_rx_64_cancel_is_not_completed_and_keeps_prior_evidence(tmp_path: Path) -> None:
    calls: list = []
    handler = _handler(
        tmp_path / "cancel",
        calls,
        responses=("click(250, 500)", "click(300, 600)", "finish()"),
    )
    handler.context.cancelled = lambda: handler.tap_count >= 1
    result = handler.handle(_claim())
    assert result.actions == 1
    assert result.outcome == "cancelled"
    assert result.evidence_complete is True
    assert result.review_pending is False
    assert handler.stopped_reason == "cancelled"
    assert len(handler.evidence_commits) == 1
    assert len(calls) == 1


def test_rx_64_timeout_after_first_step_is_error_not_completed(tmp_path: Path) -> None:
    calls: list = []
    handler = _handler(
        tmp_path / "timeout",
        calls,
        responses=("click(250, 500)", "click(300, 600)", "finish()"),
        max_actions=50,
    )
    handler.context.max_seconds = 50.0
    handler.context.mono_seconds = 10.0
    original = handler._run_recording_step

    def bump(claim, *, action_seq: int):
        step = original(claim, action_seq=action_seq)
        handler.context.mono_seconds = 60.0
        return step

    handler._run_recording_step = bump  # type: ignore[method-assign]
    result = handler.handle(_claim())
    assert result.actions == 1
    assert result.outcome == "error"
    assert result.review_pending is False
    assert handler.stopped_reason == "time_budget"
    assert len(handler.evidence_commits) == 1
