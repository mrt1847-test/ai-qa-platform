"""RX-34: Android approved-plan replay — digest/geometry/healing gates, actor AI 0."""

from __future__ import annotations

import binascii
import json
import struct
import subprocess
import zlib
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx

from aiqa.adapters.mobile_agent_android import MobileAgentAndroidAdapter, recording_broker
from aiqa.config import WorkerClientSettings
from aiqa.contracts.actions import CaptureGeometry, Observation
from aiqa.contracts.checks import CheckSpec
from aiqa.contracts.jobs import ControlDecision
from aiqa.contracts.models import OwnedCheck, RoleBinding
from aiqa.models.broker import ModelBroker, ModelTransport
from aiqa.replay.android_runner import AndroidDeterministicDriver, require_approved_digest
from aiqa.worker.android_jobs import (
    AndroidReplayContext,
    AndroidReplayHandler,
    register_android_replay_handler,
)
from aiqa.worker.control import RemoteLeaseGuard
from aiqa.worker.dispatch_journal import DispatchJournal
from aiqa.worker.http_client import WorkerHttpClient
from aiqa.worker.runtime import WorkerRuntime, WorkerRuntimeConfig, replay_prepared_adapters
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
        '{"nodes":[{"locator":"#ok","text":"ok","value":"","state":"visible"}]}',
        "[]",
        (),
        "",
        capture_ok,
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


def _replay(
    tmp_path: Path,
    *,
    digest: str = "sha256:approved",
    cancelled: bool = False,
    after: Observation | None = None,
    healing_enabled: bool = False,
    heal_budget: int = 0,
    checks: tuple = (),
    lease: float = 60.0,
):
    calls: list = []
    verify_broker = ModelBroker(
        "item-1",
        (RoleBinding("verification", 1, "fixture-v", "ref"), RoleBinding("healing", 1, "fixture-h", "ref")),
        (OwnedCheck("check-1", "item-1"),),
        (),
    )
    handler = AndroidReplayHandler(
        adapter=MobileAgentAndroidAdapter(),
        driver=_driver(tmp_path, calls),
        broker=recording_broker(),
        guard=RemoteLeaseGuard(),
        journal=DispatchJournal(tmp_path / "journal.jsonl"),
        spool=EvidenceSpool(tmp_path / "evidence"),
        context=AndroidReplayContext(
            expected_serial="emulator-5580",
            approved_digest=digest,
            approved_plan="click(250, 500)",
            before=_observation(),
            after=_observation() if after is None else after,
            lease_remaining_seconds=lease,
            mono_seconds=100.0,
            cancelled=cancelled,
            healing_enabled=healing_enabled,
            heal_budget_remaining=heal_budget,
            checks=checks,
            verify_broker=verify_broker,
            verify_transport=_Script(),
            verify_control=_Allow(),
            healable_check_id="check-1",
            approved_failure_reason="target_not_found",
        ),
    )
    return handler, calls


def _claim(*, purpose: str = "trial", digest: str = "sha256:approved", action_id: str = "r1") -> dict:
    return {
        "project_id": str(uuid4()),
        "job_id": str(uuid4()),
        "attempt_id": str(uuid4()),
        "generation": 1,
        "snapshot": {
            "purpose": purpose,
            "digest": digest,
            "serial": "emulator-5580",
            "action_id": action_id,
        },
    }


def test_rx_34_digest_geometry_cancel_healing_off_and_no_retransmit(tmp_path: Path) -> None:
    require_approved_digest("sha256:approved", "sha256:approved")
    ok, calls = _replay(tmp_path)
    result = ok.handle(_claim())
    assert result.actions == 1 and result.outcome == "completed"
    assert ok.dispatch_count == 1
    assert ok.authoring_calls_seen == 0
    assert ok.healer_calls == 0
    assert ok.package_digest_after == "sha256:approved"
    assert calls and calls[-1][4:8] == ("input", "tap", "25", "50")

    # Digest changed → no dispatch.
    changed, c_calls = _replay(tmp_path / "d")
    denied = changed.handle(_claim(digest="sha256:other"))
    assert denied.actions == 0 and changed.dispatch_count == 0 and c_calls == []

    # Bad geometry on before → reject before tap (no retransmit).
    bad_geo, g_calls = _replay(tmp_path / "g")
    bad_geo.context = AndroidReplayContext(
        expected_serial="emulator-5580",
        approved_digest="sha256:approved",
        approved_plan="click(250, 500)",
        before=_observation(geometry=_geometry(physical=(0, 200))),
        after=_observation(),
        mono_seconds=100.0,
        verify_broker=bad_geo.context.verify_broker,
        verify_transport=bad_geo.context.verify_transport,
        verify_control=_Allow(),
    )
    geo_denied = bad_geo.handle(_claim(action_id="geo"))
    assert geo_denied.actions == 0 and bad_geo.dispatch_count == 0
    assert bad_geo.original_failure
    assert g_calls == []

    # Cancel → no dispatch.
    cancelled, x_calls = _replay(tmp_path / "c", cancelled=True)
    assert cancelled.handle(_claim()).actions == 0 and x_calls == []

    # Healing OFF / budget 0 on check failure → healer 0, digest unchanged.
    from aiqa.worker.runner import verify_and_heal_after_replay

    web_fail = Observation(
        str(uuid4()),
        datetime.now(timezone.utc).isoformat(),
        _geometry(),
        _png(),
        '{"nodes":[{"locator":"#login","text":"실패","value":"","state":"visible"}]}',
        "",
        (),
        "",
        True,
        "web",
    )
    check = (CheckSpec("check-1", "text", "로그인됨", subject="#login", method="deterministic"),)
    verify_broker = ModelBroker(
        "item-1",
        (RoleBinding("verification", 1, "fixture-v", "ref"), RoleBinding("healing", 1, "fixture-h", "ref")),
        (OwnedCheck("check-1", "item-1"),),
        (),
    )
    off_verify = verify_and_heal_after_replay(
        checks=check,
        observation=web_fail,
        control=_Allow(),
        broker=verify_broker,
        transport=_Script(),
        healing_enabled=False,
        heal_budget_remaining=2,
        approved_failure_reason="target_not_found",
        healable_check_id="check-1",
        approved_package_digest="sha256:approved",
    )
    assert off_verify.success is False
    assert off_verify.record.healer_calls == 0
    assert off_verify.record.package_digest_after == "sha256:approved"
    assert off_verify.record.original_failure == "target_not_found"

    budget_verify = verify_and_heal_after_replay(
        checks=check,
        observation=web_fail,
        control=_Allow(),
        broker=verify_broker,
        transport=_Script(),
        healing_enabled=True,
        heal_budget_remaining=0,
        approved_failure_reason="target_not_found",
        healable_check_id="check-1",
        approved_package_digest="sha256:approved",
    )
    assert budget_verify.record.healer_calls == 0

    # Ambiguous STARTED → no retransmit.
    amb, a_calls = _replay(tmp_path / "a")
    claim = _claim(action_id="amb-1")
    amb.journal.append(str(claim["attempt_id"]), "amb-1", "planned")
    amb.journal.append(str(claim["attempt_id"]), "amb-1", "dispatch_started")
    blocked = amb.handle(claim)
    assert blocked.actions == 0 and blocked.ambiguous_dispatch is True
    assert amb.dispatch_count == 0 and a_calls == []


def test_rx_34_ack_loss_blocks_dispatch_and_adapters_include_replay(tmp_path: Path) -> None:
    assert "trial" in replay_prepared_adapters() and "regression" in replay_prepared_adapters()
    handler, calls = _replay(tmp_path)
    routed = register_android_replay_handler(handler)

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
                        "purpose": "regression",
                        "digest": "sha256:approved",
                        "serial": "emulator-5580",
                        "action_id": "lost",
                    },
                },
            )
        if request.url.path.endswith("/attempt-acks"):
            return httpx.Response(503, json={"error": "unavailable"})
        return httpx.Response(204)

    settings = WorkerClientSettings(base_url="https://manage.example", token="tok")
    with WorkerHttpClient(settings, transport=httpx.MockTransport(ack_fail)) as client:
        runtime = WorkerRuntime(
            client,
            WorkerRuntimeConfig(boot_id="boot-rx34", prepared_adapters=replay_prepared_adapters()),
            routed,
        )
        lost = runtime.run_once()
    assert lost.finished is False
    assert handler.dispatch_count == 0
    assert handler.broker.authoring_calls == 0
    assert calls == []
