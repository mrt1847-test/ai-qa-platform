"""RX-48: Android multi-step recording — tap→swipe→finish with budgets and fail-closed."""

from __future__ import annotations

import binascii
import json
import struct
import subprocess
import zlib
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from aiqa.adapters.mobile_agent_android import MobileAgentAndroidAdapter, recording_broker
from aiqa.contracts.actions import CaptureGeometry, Observation
from aiqa.contracts.jobs import ControlDecision
from aiqa.replay.android_plan import parse_mobile_agent_action, typed_from_upstream
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


def _observation(*, stamp: str | None = None) -> Observation:
    return Observation(
        str(uuid4()),
        stamp or datetime.now(timezone.utc).isoformat(),
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
    responses: tuple[str, ...] = (),
    fixture_response: str = "click(250, 500)",
    cancelled: bool | object = False,
    max_actions: int = 50,
    max_seconds: float | None = None,
    mono_seconds: float | None = 100.0,
    steps: int = 3,
) -> AndroidRecordingHandler:
    observations = tuple((_observation(), _observation()) for _ in range(steps))
    return AndroidRecordingHandler(
        adapter=MobileAgentAndroidAdapter(),
        driver=_driver(tmp_path, calls),
        broker=recording_broker(),
        control=_Allow(),
        guard=RemoteLeaseGuard(),
        journal=DispatchJournal(tmp_path / "journal.jsonl"),
        spool=EvidenceSpool(tmp_path / "spool"),
        context=AndroidRecordingContext(
            expected_serial="emulator-5580",
            fixture_response=fixture_response,
            fixture_responses=responses,
            step_observations=observations,
            lease_remaining_seconds=60.0,
            mono_seconds=mono_seconds,
            max_actions=max_actions,
            max_seconds=max_seconds,
            cancelled=cancelled,  # type: ignore[arg-type]
        ),
    )


def _claim(*, attempt: str | None = None) -> dict:
    return {
        "project_id": str(uuid4()),
        "job_id": str(uuid4()),
        "attempt_id": attempt or str(uuid4()),
        "generation": 1,
        "snapshot": {
            "purpose": "recording",
            "serial": "emulator-5580",
        },
    }


def test_rx_48_finish_verb_parses_without_dispatch_geometry() -> None:
    parsed = parse_mobile_agent_action("finish()")
    assert parsed.kind == "finish"
    typed = typed_from_upstream(parsed, _geometry())
    assert typed.kind == "finish"


def test_rx_48_tap_swipe_finish_preserves_step_evidence(tmp_path: Path) -> None:
    calls: list = []
    handler = _handler(
        tmp_path,
        calls,
        responses=(
            "click(250, 500)",
            "swipe(100, 1800, 100, 400, 300)",
            "finish()",
        ),
        steps=3,
    )
    result = handler.handle(_claim())
    assert result.outcome == "completed"
    assert result.actions == 2
    assert result.review_pending is True
    assert handler.finished_by_model is True
    assert handler.stopped_reason == "model_finish"
    assert handler.authoring_calls_seen == 3
    assert len(handler.evidence_commits) == 2
    assert [item["action_seq"] for item in handler.evidence_commits] == [1, 2]
    assert result.final_seq == 4  # 2 events per physical step
    seqs = [int(event["local_seq"]) for event in result.evidence_events]
    assert seqs == [1, 2, 3, 4]
    details = [json.loads(str(event["detail_payload"])) for event in result.evidence_events]
    assert {item["action_seq"] for item in details} == {1, 2}
    # tap then swipe; finish never reaches ADB.
    assert len(calls) == 2
    assert calls[0][4:8] == ("input", "tap", "25", "50")
    assert calls[1][4] == "shell" or "swipe" in str(calls[1])


def test_rx_48_cancel_keeps_prior_steps_and_stops(tmp_path: Path) -> None:
    calls: list = []
    handler = _handler(
        tmp_path / "cancel",
        calls,
        responses=("click(250, 500)", "swipe(100, 1800, 100, 400, 300)", "finish()"),
        steps=3,
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


def test_rx_48_ambiguous_and_sanitize_preserve_prior(tmp_path: Path) -> None:
    calls2: list = []
    journal = DispatchJournal(tmp_path / "amb" / "shared.jsonl")
    attempt2 = str(uuid4())
    action2 = f"rec-{attempt2}-2"
    journal.append(attempt2, action2, "planned")
    journal.append(attempt2, action2, "dispatch_started")
    journal.mark_started_only_unknown(attempt2, action2)
    handler2 = AndroidRecordingHandler(
        adapter=MobileAgentAndroidAdapter(),
        driver=_driver(tmp_path / "amb2", calls2),
        broker=recording_broker(),
        control=_Allow(),
        guard=RemoteLeaseGuard(),
        journal=journal,
        spool=EvidenceSpool(tmp_path / "amb2" / "spool"),
        context=AndroidRecordingContext(
            expected_serial="emulator-5580",
            fixture_response="",
            fixture_responses=("click(250, 500)", "click(300, 600)", "finish()"),
            step_observations=(
                (_observation(), _observation()),
                (_observation(), _observation()),
                (_observation(), _observation()),
            ),
            lease_remaining_seconds=60.0,
            mono_seconds=100.0,
            max_actions=50,
        ),
    )
    result = handler2.handle(_claim(attempt=attempt2))
    assert result.actions == 1
    assert result.outcome == "error"
    assert handler2.stopped_reason == "ambiguous_dispatch"
    assert len(handler2.evidence_commits) == 1
    assert len(calls2) == 1

    calls3: list = []
    bad_after = _observation()
    bad_geo = CaptureGeometry(0, 200, 1000, 2000, "scale", 0, (0, 0, 0, 200))
    bad_before = Observation(
        str(uuid4()),
        datetime.now(timezone.utc).isoformat(),
        bad_geo,
        _png(),
        "",
        "[]",
        (),
        "",
        True,
        "android",
    )
    handler3 = AndroidRecordingHandler(
        adapter=MobileAgentAndroidAdapter(),
        driver=_driver(tmp_path / "bad", calls3),
        broker=recording_broker(),
        control=_Allow(),
        guard=RemoteLeaseGuard(),
        journal=DispatchJournal(tmp_path / "bad" / "journal.jsonl"),
        spool=EvidenceSpool(tmp_path / "bad" / "spool"),
        context=AndroidRecordingContext(
            expected_serial="emulator-5580",
            fixture_response="",
            fixture_responses=("click(250, 500)", "click(250, 500)", "finish()"),
            step_observations=(
                (_observation(), _observation()),
                (bad_before, bad_after),
                (_observation(), _observation()),
            ),
            lease_remaining_seconds=60.0,
            mono_seconds=100.0,
            max_actions=50,
        ),
    )
    rejected = handler3.handle(_claim())
    assert rejected.actions == 1
    assert rejected.outcome == "error"
    assert rejected.evidence_complete is True
    assert rejected.review_pending is False
    assert handler3.stopped_reason == "sanitize_failed"
    assert len(handler3.evidence_commits) == 1
    assert len(calls3) == 1


def test_rx_48_action_and_time_budget_stop_further_actions(tmp_path: Path) -> None:
    calls: list = []
    handler = _handler(
        tmp_path / "budget",
        calls,
        responses=("click(250, 500)", "swipe(100, 1800, 100, 400, 300)", "click(250, 500)"),
        max_actions=2,
        steps=3,
    )
    result = handler.handle(_claim())
    assert result.actions == 2
    assert result.outcome == "error"
    assert result.review_pending is False
    assert handler.finished_by_model is False
    assert handler.stopped_reason == "action_budget"
    assert len(calls) == 2

    calls_t: list = []
    timed = _handler(
        tmp_path / "time",
        calls_t,
        responses=("click(250, 500)", "swipe(100, 1800, 100, 400, 300)", "finish()"),
        max_seconds=50.0,
        mono_seconds=10.0,
        steps=3,
    )
    # After first step, jump mono past the time budget.
    original_step = timed._run_recording_step

    def bump_then_run(claim, *, action_seq: int):
        result_step = original_step(claim, action_seq=action_seq)
        timed.context.mono_seconds = 60.0
        return result_step

    timed._run_recording_step = bump_then_run  # type: ignore[method-assign]
    timed_result = timed.handle(_claim())
    assert timed_result.actions == 1
    assert timed_result.outcome == "error"
    assert timed.stopped_reason == "time_budget"
    assert len(calls_t) == 1


def test_rx_48_single_step_fixture_still_one_action(tmp_path: Path) -> None:
    calls: list = []
    handler = AndroidRecordingHandler(
        adapter=MobileAgentAndroidAdapter(),
        driver=_driver(tmp_path / "one", calls),
        broker=recording_broker(),
        control=_Allow(),
        guard=RemoteLeaseGuard(),
        journal=DispatchJournal(tmp_path / "one" / "journal.jsonl"),
        spool=EvidenceSpool(tmp_path / "one" / "spool"),
        context=AndroidRecordingContext(
            expected_serial="emulator-5580",
            fixture_response="click(250, 500)",
            before=_observation(),
            after=_observation(),
            lease_remaining_seconds=60.0,
            mono_seconds=100.0,
        ),
    )
    result = handler.handle(_claim())
    assert result.actions == 1
    assert result.review_pending is True
    assert len(calls) == 1
