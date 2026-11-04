"""RX-10: deterministic Android input, geometry lock, sanitize, no auto-retry/AI."""

from __future__ import annotations

import binascii
import struct
import subprocess
import zlib
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from aiqa.contracts.actions import CaptureGeometry, Observation
from aiqa.recording.action_executor import ActionExecutor, run_android_deterministic
from aiqa.replay.android_plan import PlanRejected, build_typed_android_action
from aiqa.replay.android_runner import (
    AndroidDeterministicDriver,
    AndroidDispatchError,
    AndroidPreflight,
)
from aiqa.replay.targets import TargetBinding
from aiqa.worker.spool import EvidenceSpool


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


def _observation(*, width=24, height=48, rotation=0, stamp=None) -> Observation:
    return Observation(
        str(uuid4()),
        stamp or datetime.now(timezone.utc).isoformat(),
        CaptureGeometry(width, height, width, height, "identity", rotation, (0, 0, width, height)),
        _png(width, height),
        "",
        "[]",
        (),
        "",
        True,
        "android",
    )


def test_typed_actions_and_sensitive_text() -> None:
    tap = build_typed_android_action("tap", width=24, height=48, rotation=0, x=10, y=20)
    assert tap.kind == "tap" and tap.x == 10
    with pytest.raises(PlanRejected):
        build_typed_android_action("tap", width=24, height=48, rotation=0, x=100, y=1)
    with pytest.raises(PlanRejected):
        build_typed_android_action(
            "text", width=24, height=48, rotation=0, text="token-secret", secrets=("secret",)
        )
    with pytest.raises(PlanRejected):
        build_typed_android_action("text", width=24, height=48, rotation=0, text="hello world")


def test_deterministic_dispatch_gates_and_evidence(tmp_path: Path) -> None:
    calls: list[tuple[str, ...]] = []

    def runner(argv, timeout):
        seq = tuple(argv)
        calls.append(seq)
        assert timeout == 10.0
        assert str(seq[0]).endswith("adb") or str(seq[0]).endswith("adb.exe")
        assert seq[1:3] == ("-s", "emulator-5580")
        return subprocess.CompletedProcess(list(argv), 0, b"", b"")

    spool = EvidenceSpool(tmp_path / "spool")
    driver = AndroidDeterministicDriver(
        Path("C:/platform-tools/adb.exe"),
        "emulator-5580",
        runner=runner,
        spool=spool,
    )
    preflight = AndroidPreflight()
    before = _observation()
    after = _observation()
    binding = TargetBinding(
        "coordinate",
        x=12,
        y=24,
        approved=True,
        approved_rotation=0,
        approved_width=24,
        approved_height=48,
        approved_bounds=(0, 0, 24, 48),
    )
    action = build_typed_android_action("tap", width=24, height=48, rotation=0, x=12, y=24)
    result = driver.run(preflight=preflight, binding=binding, before=before, action=action, after=after)
    assert result.outcome == "acknowledged"
    assert result.native_calls == 1 and result.retries == 0 and result.ai_calls == 0
    assert result.before_ref and result.after_ref
    assert calls == [
        (
            str(Path("C:/platform-tools/adb.exe")),
            "-s",
            "emulator-5580",
            "shell",
            "input",
            "tap",
            "12",
            "24",
        )
    ]
    assert preflight.dispatches == 1
    assert driver.auto_retries == 0

    with pytest.raises(AndroidDispatchError) as serial_err:
        driver.run(
            preflight=AndroidPreflight(),
            binding=binding,
            before=_observation(),
            action=action,
            observed_serial="emulator-5554",
        )
    assert serial_err.value.reason == "serial mismatch"

    # ADB failure
    def fail(argv, timeout):
        return subprocess.CompletedProcess(argv, 1, b"", b"error")

    failing = AndroidDeterministicDriver(Path("C:/platform-tools/adb.exe"), "emulator-5580", runner=fail)
    with pytest.raises(AndroidDispatchError) as adb_err:
        failing.run(preflight=AndroidPreflight(), binding=binding, before=_observation(), action=action)
    assert adb_err.value.reason == "adb_failed"

    # timeout
    def slow(argv, timeout):
        raise subprocess.TimeoutExpired(argv, timeout)

    timed = AndroidDeterministicDriver(Path("C:/platform-tools/adb.exe"), "emulator-5580", runner=slow)
    with pytest.raises(AndroidDispatchError) as to_err:
        timed.run(preflight=AndroidPreflight(), binding=binding, before=_observation(), action=action)
    assert to_err.value.reason == "timeout"

    # geometry change after
    changed = _observation(width=24, height=48, rotation=90)
    with pytest.raises(AndroidDispatchError) as geo_err:
        driver.run(
            preflight=AndroidPreflight(),
            binding=binding,
            before=_observation(),
            action=action,
            after=changed,
        )
    assert geo_err.value.reason == "geometry changed"

    # sanitize failure with secrets
    secret_driver = AndroidDeterministicDriver(
        Path("C:/platform-tools/adb.exe"), "emulator-5580", runner=runner, secrets=("x",)
    )
    with pytest.raises(AndroidDispatchError) as san_err:
        secret_driver.run(
            preflight=AndroidPreflight(),
            binding=binding,
            before=_observation(),
            action=action,
        )
    assert san_err.value.reason == "sanitize_failed"

    # ambiguous target → blocked, zero native calls, no retry
    ambiguous = TargetBinding("resource", resource_id="btn", text="OK", context="")
    amb_before = _observation()
    # force hierarchy with two matches via stdout JSON list
    amb_obs = Observation(
        amb_before.observation_id,
        amb_before.captured_at,
        amb_before.geometry,
        amb_before.png,
        "",
        '{"nodes":[{"resource_id":"btn","text":"OK","context":""},{"resource_id":"btn","text":"OK","context":""}]}',
        (),
        "",
        True,
        "android",
    )
    amb = AndroidDeterministicDriver(Path("C:/platform-tools/adb.exe"), "emulator-5580", runner=runner)
    blocked = amb.run(
        preflight=AndroidPreflight(),
        binding=ambiguous,
        before=amb_obs,
        action=action,
    )
    assert blocked.outcome == "blocked" and blocked.reason == "ambiguous"
    assert blocked.native_calls == 0 and amb.auto_retries == 0 and amb.ai_calls == 0

    executor = ActionExecutor(spool=tmp_path / "exec")
    bridged = run_android_deterministic(
        executor,
        driver=AndroidDeterministicDriver(Path("C:/platform-tools/adb.exe"), "emulator-5580", runner=runner),
        preflight=AndroidPreflight(),
        binding=binding,
        before=_observation(),
        action=action,
        after=_observation(),
    )
    assert bridged.ai_calls == 0
    assert executor.post_dispatch_retries == 0
