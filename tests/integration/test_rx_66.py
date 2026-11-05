"""RX-66: multi-step sealed plan replay with per-step observation and Check."""

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
from aiqa.contracts.checks import CheckSpec
from aiqa.contracts.jobs import ControlDecision
from aiqa.contracts.models import OwnedCheck, RoleBinding
from aiqa.models.broker import ModelBroker, ModelTransport
from aiqa.replay.android_runner import AndroidDeterministicDriver
from aiqa.worker.android_jobs import AndroidReplayContext, AndroidReplayHandler
from aiqa.worker.control import RemoteLeaseGuard
from aiqa.worker.dispatch_journal import DispatchJournal
from aiqa.worker.spool import EvidenceSpool


def _png(width: int = 100, height: int = 200, fill: bytes = b"\x00\x00\x00") -> bytes:
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


def _hierarchy(*, text: str = "로그인됨", resource_id: str = "com.app:id/ok") -> str:
    return json.dumps(
        {"nodes": [{"resource_id": resource_id, "text": text, "value": "", "state": "visible"}]},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _observation(
    *,
    fill: bytes = b"\x00\x00\x00",
    text: str = "로그인됨",
    captured_at: str | None = None,
) -> Observation:
    return Observation(
        str(uuid4()),
        captured_at or datetime.now(timezone.utc).isoformat(),
        _geometry(),
        _png(fill=fill),
        "",
        _hierarchy(text=text),
        (),
        "",
        True,
        "android",
    )


class _Allow:
    def checkpoint(self) -> ControlDecision:
        return ControlDecision(True, "before_model")

    def allow_model_action(self, *, late: bool) -> ControlDecision:
        return ControlDecision(not late, "before_model")


class _Script(ModelTransport):
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, check_id: str) -> str:
        self.calls += 1
        return '{"status":"satisfied","reason":"ok"}'


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
    plan: str,
    steps: tuple[tuple[Observation, Observation], ...],
    checks: tuple[CheckSpec, ...] = (),
    healing_enabled: bool = False,
    purpose_digest: str = "sha256:approved",
    cancelled: bool | object = False,
    lease: float = 60.0,
) -> AndroidReplayHandler:
    verify_broker = ModelBroker(
        "item-1",
        (
            RoleBinding("verification", 1, "fixture-v", "ref"),
            RoleBinding("healing", 1, "fixture-h", "ref"),
        ),
        (OwnedCheck("check-1", "item-1"),),
        (),
    )
    return AndroidReplayHandler(
        adapter=MobileAgentAndroidAdapter(),
        driver=_driver(tmp_path, calls),
        broker=recording_broker(),
        guard=RemoteLeaseGuard(),
        journal=DispatchJournal(tmp_path / "journal.jsonl"),
        spool=EvidenceSpool(tmp_path / "evidence"),
        context=AndroidReplayContext(
            expected_serial="emulator-5580",
            approved_digest=purpose_digest,
            approved_plan=plan,
            step_observations=steps,
            lease_remaining_seconds=lease,
            mono_seconds=100.0,
            cancelled=cancelled,  # type: ignore[arg-type]
            healing_enabled=healing_enabled,
            heal_budget_remaining=2 if healing_enabled else 0,
            checks=checks,
            verify_broker=verify_broker,
            verify_transport=_Script(),
            verify_control=_Allow(),
            healable_check_id="check-1",
            approved_failure_reason="target_not_found",
        ),
    )


def _claim(*, purpose: str = "trial", digest: str = "sha256:approved") -> dict:
    return {
        "project_id": str(uuid4()),
        "job_id": str(uuid4()),
        "attempt_id": str(uuid4()),
        "generation": 1,
        "snapshot": {
            "purpose": purpose,
            "digest": digest,
            "serial": "emulator-5580",
            "action_id": "rx66",
        },
    }


def test_rx_66_two_steps_run_in_order_with_distinct_observations(tmp_path: Path) -> None:
    calls: list = []
    t0 = "2026-11-05T12:00:00+00:00"
    t1 = "2026-11-05T12:00:01+00:00"
    t2 = "2026-11-05T12:00:02+00:00"
    t3 = "2026-11-05T12:00:03+00:00"
    before1 = _observation(fill=b"\xff\x00\x00", captured_at=t0)
    after1 = _observation(fill=b"\x00\xff\x00", captured_at=t1)
    before2 = _observation(fill=b"\x00\x00\xff", captured_at=t2)
    after2 = _observation(fill=b"\xff\xff\x00", captured_at=t3)
    plan = "click(250, 500)\nclick(300, 600)"
    handler = _handler(
        tmp_path,
        calls,
        plan=plan,
        steps=((before1, after1), (before2, after2)),
        checks=(CheckSpec("check-1", "text", "로그인됨", subject="com.app:id/ok"),),
    )
    result = handler.handle(_claim())
    assert result.outcome == "completed"
    assert result.actions == 2
    assert handler.dispatch_count == 2
    assert handler.authoring_calls_seen == 0
    assert handler.healer_calls == 0
    assert len(calls) == 2
    assert calls[0][4:8] == ("input", "tap", "25", "50")
    assert calls[1][4:8] == ("input", "tap", "30", "60")
    assert len(result.evidence_events) == 4
    captured = [json.loads(str(event["detail_payload"])) for event in result.evidence_events]
    assert [item["action_seq"] for item in captured] == [1, 1, 2, 2]
    assert [event["captured_at"] for event in result.evidence_events] == [t0, t1, t2, t3]
    png_hashes = [item["png_sha256"] for item in captured]
    assert len(set(png_hashes)) == 4


def test_rx_66_broken_expectation_stops_further_input(tmp_path: Path) -> None:
    calls: list = []
    bad_after = _observation(text="실패")
    handler = _handler(
        tmp_path,
        calls,
        plan="click(250, 500)\nclick(300, 600)",
        steps=(
            (_observation(), bad_after),
            (_observation(), _observation()),
        ),
        checks=(CheckSpec("check-1", "text", "로그인됨", subject="com.app:id/ok"),),
    )
    result = handler.handle(_claim(purpose="regression"))
    assert result.outcome == "error"
    assert result.actions == 1
    assert handler.stopped_reason == "check_failed"
    assert handler.original_failure
    assert handler.healer_calls == 0
    assert len(calls) == 1


def test_rx_66_bad_digest_cancel_and_lease_dispatch_zero(tmp_path: Path) -> None:
    steps = ((_observation(), _observation()), (_observation(), _observation()))
    plan = "click(250, 500)\nclick(300, 600)"

    calls: list = []
    forged = _handler(tmp_path / "d", calls, plan=plan, steps=steps)
    denied = forged.handle(_claim(digest="sha256:other"))
    assert denied.actions == 0 and forged.dispatch_count == 0 and calls == []

    calls2: list = []
    cancelled = _handler(tmp_path / "c", calls2, plan=plan, steps=steps, cancelled=True)
    assert cancelled.handle(_claim()).actions == 0 and calls2 == []

    calls3: list = []
    expired = _handler(tmp_path / "l", calls3, plan=plan, steps=steps, lease=0.0)
    assert expired.handle(_claim()).actions == 0 and calls3 == []


def test_rx_66_cancel_after_first_step_blocks_further_input(tmp_path: Path) -> None:
    calls: list = []
    handler = _handler(
        tmp_path,
        calls,
        plan="click(250, 500)\nclick(300, 600)",
        steps=((_observation(), _observation()), (_observation(), _observation())),
    )
    handler.context.cancelled = lambda: handler.dispatch_count >= 1
    result = handler.handle(_claim())
    assert result.actions == 1
    assert result.outcome == "cancelled"
    assert handler.stopped_reason == "cancelled"
    assert len(calls) == 1


def test_rx_66_trial_forces_healing_off_and_actor_zero(tmp_path: Path) -> None:
    calls: list = []
    handler = _handler(
        tmp_path,
        calls,
        plan="click(250, 500)",
        steps=((_observation(), _observation(text="실패")),),
        checks=(CheckSpec("check-1", "text", "로그인됨", subject="com.app:id/ok"),),
        healing_enabled=True,
    )
    result = handler.handle(_claim(purpose="trial"))
    assert result.outcome == "error"
    assert result.actions == 1
    assert handler.authoring_calls_seen == 0
    assert handler.healer_calls == 0
    assert handler.package_digest_after == "sha256:approved"
