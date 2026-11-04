"""RX-12: Mobile-Agent Android adapter — parse, rescale, typed driver, replay authoring 0."""

from __future__ import annotations

import binascii
import struct
import subprocess
import zlib
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from aiqa.adapters.mobile_agent_android import (
    MobileAgentAndroidAdapter,
    MobileAgentRejected,
    recording_broker,
)
from aiqa.contracts.actions import CaptureGeometry, Observation
from aiqa.contracts.jobs import ControlDecision
from aiqa.replay.android_plan import (
    PlanRejected,
    parse_mobile_agent_action,
    rescale_coordinates,
    typed_from_upstream,
)
from aiqa.replay.android_runner import AndroidDeterministicDriver
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


def _geometry(*, physical=(100, 200), model=(1000, 2000), rotation=0) -> CaptureGeometry:
    pw, ph = physical
    mw, mh = model
    return CaptureGeometry(pw, ph, mw, mh, "scale", rotation, (0, 0, pw, ph))


def _observation(*, geometry: CaptureGeometry | None = None, capture_ok: bool = True) -> Observation:
    geo = geometry or _geometry()
    return Observation(
        str(uuid4()),
        datetime.now(timezone.utc).isoformat(),
        geo,
        _png(geo.physical_width, geo.physical_height),
        "",
        "[]",
        (),
        "",
        capture_ok,
        "android",
    )


class _Allow:
    allowed = True

    def checkpoint(self) -> ControlDecision:
        return ControlDecision(self.allowed, "before_model")


def test_parser_rescale_and_rejects() -> None:
    geo = _geometry(physical=(100, 200), model=(1000, 2000))
    parsed = parse_mobile_agent_action("Action: click(100, 200)")
    assert parsed.kind == "tap"
    assert rescale_coordinates(100, 200, geo) == (10, 20)
    assert rescale_coordinates(0, 0, geo) == (0, 0)
    assert rescale_coordinates(1000, 2000, geo) == (99, 199)
    typed = typed_from_upstream(parsed, geo)
    assert typed.kind == "tap" and typed.x == 10 and typed.y == 20

    swipe = parse_mobile_agent_action("swipe(0, 0, 500, 1000, 400)")
    typed_swipe = typed_from_upstream(swipe, geo)
    assert typed_swipe.kind == "swipe" and typed_swipe.duration_ms == 400
    assert (typed_swipe.x, typed_swipe.y, typed_swipe.x2, typed_swipe.y2) == (0, 0, 50, 100)

    text = parse_mobile_agent_action("type(content='hello')")
    assert typed_from_upstream(text, geo).text == "hello"
    assert parse_mobile_agent_action("back()").kind == "back"

    with pytest.raises(PlanRejected, match="shell"):
        parse_mobile_agent_action("shell('id')")
    with pytest.raises(PlanRejected, match="unsupported"):
        parse_mobile_agent_action("open_app('Settings')")
    with pytest.raises(PlanRejected, match="unsupported"):
        parse_mobile_agent_action("drag(1, 2, 3, 4)")
    with pytest.raises(PlanRejected, match="geometry|outside"):
        rescale_coordinates(-1, 0, geo)
    with pytest.raises(PlanRejected, match="outside|geometry"):
        typed_from_upstream(parse_mobile_agent_action("click(1001, 10)"), geo)


def test_adapter_record_replay_and_sanitize_gates(tmp_path: Path) -> None:
    adapter = MobileAgentAndroidAdapter()
    broker = recording_broker()
    control = _Allow()
    calls: list[tuple[str, ...]] = []

    def runner(argv, timeout):
        calls.append(tuple(argv))
        return subprocess.CompletedProcess(list(argv), 0, b"", b"")

    driver = AndroidDeterministicDriver(
        Path("C:/platform-tools/adb.exe"),
        "emulator-5580",
        runner=runner,
        spool=EvidenceSpool(tmp_path / "spool"),
    )
    before = _observation()
    after = _observation()

    with pytest.raises(MobileAgentRejected, match="geometry"):
        adapter.sanitize(_observation(geometry=_geometry(physical=(0, 200))))
    with pytest.raises(MobileAgentRejected, match="sanitize"):
        adapter.sanitize(_observation(), secrets=("secret",))
    with pytest.raises(MobileAgentRejected, match="shell"):
        adapter.parse_to_typed("shell('reboot')", before)

    recorded = adapter.record_step(
        observation=before,
        after=after,
        fixture_response="click(250, 500)",
        broker=broker,
        control=control,
        driver=driver,
    )
    assert recorded.authoring_calls == 1
    assert recorded.provider_calls == 1
    assert recorded.action.x == 25 and recorded.action.y == 50
    assert recorded.before_ref and recorded.after_ref
    assert broker.authoring_calls == 1
    assert calls[-1][4:8] == ("input", "tap", "25", "50")

    replay_calls_before = broker.authoring_calls
    replayed = adapter.replay_step(
        plan_response="click(250, 500)",
        observation=_observation(),
        after=_observation(),
        driver=driver,
        broker=broker,
    )
    assert replayed.authoring_calls == 0
    assert replayed.provider_calls == 0
    assert broker.authoring_calls == replay_calls_before
    assert replayed.action.x == 25
