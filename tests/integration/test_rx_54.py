"""RX-54: shared Check + limited healing on Android and Web mock handlers."""

from __future__ import annotations

import binascii
import json
import struct
import subprocess
import zlib
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from aiqa.adapters.cuawright_web import CuawrightWebAdapter, make_recording_manifest
from aiqa.adapters.mobile_agent_android import MobileAgentAndroidAdapter
from aiqa.contracts.actions import CaptureGeometry, Observation
from aiqa.contracts.checks import CheckSpec
from aiqa.contracts.jobs import ControlDecision
from aiqa.contracts.models import ModelRequest, OwnedCheck, OwnedEpisode, RoleBinding
from aiqa.domain.executions import separate_verify_heal_storage
from aiqa.healing.targets import HealingContext
from aiqa.models.broker import ModelBroker, ModelTransport
from aiqa.replay.driver import ApprovedWebPackage
from aiqa.worker.android_jobs import AndroidReplayContext, AndroidReplayHandler
from aiqa.worker.control import RemoteLeaseGuard
from aiqa.worker.dispatch_journal import DispatchJournal
from aiqa.worker.runner import verify_and_heal_after_replay
from aiqa.worker.spool import EvidenceSpool
from aiqa.worker.web_isolation_backend import IsolationConfig, WebIsolationGate, fixture_backend
from aiqa.worker.web_jobs import WebReplayContext, WebReplayHandler
from aiqa.replay.android_runner import AndroidDeterministicDriver

ORIGIN = "https://app.example.test"


class _Script(ModelTransport):
    def __init__(self, body: str = '{"status":"satisfied","reason":"ok"}') -> None:
        self.calls = 0
        self.body = body
        self.timeout = False

    def complete(self, check_id: str) -> str:
        self.calls += 1
        if self.timeout:
            raise TimeoutError("timed out")
        return self.body


class _Allow:
    def checkpoint(self) -> ControlDecision:
        return ControlDecision(True, "before_model")

    def allow_model_action(self, *, late: bool) -> ControlDecision:
        return ControlDecision(not late, "before_model")


class _HealBridge:
    def __init__(self) -> None:
        self.roles: list[str] = []

    def complete_role(self, role: str, episode_id: object = None) -> str:
        self.roles.append(role)
        return json.dumps(_payload())


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


def _geometry(*, physical: tuple[int, int] = (100, 200), model: tuple[int, int] = (1000, 2000)) -> CaptureGeometry:
    pw, ph = physical
    mw, mh = model
    return CaptureGeometry(pw, ph, mw, mh, "scale", 0, (0, 0, pw, ph))


def _failed_obs() -> Observation:
    # Shared Check fixtures use the web node shape; handlers assert platform wiring separately.
    return Observation(
        str(uuid4()),
        datetime.now(timezone.utc).isoformat(),
        _geometry(),
        _png(100, 200),
        '{"nodes":[{"locator":"#login","text":"실패","value":"","state":"visible"}]}',
        "",
        (),
        "",
        True,
        "web",
    )


def _heal_screen() -> Observation:
    element = {
        "role": "button",
        "name": "저장",
        "container": "form",
        "resource_id": "id.save",
        "text": "저장",
        "context": "main",
        "locator": "#new",
        "visible": True,
        "enabled": True,
        "bounds": [10, 10, 40, 30],
        "kind": "element",
    }
    return Observation(
        str(uuid4()),
        datetime.now(timezone.utc).isoformat(),
        _geometry(),
        _png(100, 200),
        json.dumps({"elements": [element]}),
        "",
        (),
        "",
        True,
        "web",
    )


def _broker() -> ModelBroker:
    return ModelBroker(
        "item-1",
        (
            RoleBinding("verification", 1, "fixture-v", "ref"),
            RoleBinding("healing", 1, "fixture-h", "ref"),
        ),
        (OwnedCheck("check-1", "item-1"),),
        (OwnedEpisode("episode-1", "item-1"),),
    )


def _heal_request() -> ModelRequest:
    return ModelRequest(
        uuid4(),
        "healing",
        "episode",
        "episode-1",
        1,
        (),
        20,
        "2026-11-01T00:00:00+00:00",
        None,
        "episode-1",
    )


def _payload() -> dict[str, object]:
    return {
        "basis": "typed",
        "role": "button",
        "name": "저장",
        "container": "form",
        "resource_id": "id.save",
        "text": "저장",
        "context": "main",
        "locator": "#new",
        "action": "click",
        "input": "",
        "path": "/form",
        "coordinates": [20, 20],
    }


def _context() -> HealingContext:
    return HealingContext(
        "button",
        "저장",
        "form",
        "id.save",
        "저장",
        "main",
        "#old",
        "click",
        "",
        "/form",
        _heal_request(),
        _payload(),
    )


def _checks() -> tuple[CheckSpec, ...]:
    return (CheckSpec("check-1", "text", "로그인됨", subject="#login", method="deterministic"),)


def test_rx_54_common_port_gates_both_platforms() -> None:
    digest = "sha256:approved-rx54"
    # Same common port for both platforms; Observation fixtures stay web-shaped.
    for _platform in ("android", "web"):
        failed = _failed_obs()
        broker = _broker()
        transport = _Script()
        off = verify_and_heal_after_replay(
            checks=_checks(),
            observation=failed,
            control=_Allow(),
            broker=broker,
            transport=transport,
            healing_enabled=False,
            heal_budget_remaining=2,
            approved_failure_reason="target_not_found",
            healable_check_id="check-1",
            approved_package_digest=digest,
            healing_context=_context(),
            heal_observation=_heal_screen(),
        )
        assert off.record.healer_calls == 0
        assert off.success is False
        assert off.record.package_digest_after == digest

        budget = verify_and_heal_after_replay(
            checks=_checks(),
            observation=failed,
            control=_Allow(),
            broker=_broker(),
            transport=_Script(),
            healing_enabled=True,
            heal_budget_remaining=0,
            approved_failure_reason="target_not_found",
            healable_check_id="check-1",
            approved_package_digest=digest,
            healing_context=_context(),
            heal_observation=_heal_screen(),
        )
        assert budget.record.healer_calls == 0

        timed = _Script()
        timed.timeout = True
        timeout = verify_and_heal_after_replay(
            checks=(CheckSpec("check-1", "text", "로그인됨", subject="#login", method="ai_visual"),),
            observation=_failed_obs(),
            control=_Allow(),
            broker=_broker(),
            transport=timed,
            healing_enabled=True,
            heal_budget_remaining=2,
            approved_failure_reason=None,
            healable_check_id="check-1",
            approved_package_digest=digest,
        )
        assert timeout.success is False
        assert timeout.record.original_failure == "timed out"
        assert timeout.record.healer_calls == 0

        bridge = _HealBridge()
        healed = verify_and_heal_after_replay(
            checks=_checks(),
            observation=failed,
            control=_Allow(),
            broker=_broker(),
            transport=_Script(),
            healing_enabled=True,
            heal_budget_remaining=2,
            approved_failure_reason="target_not_found",
            healable_check_id="check-1",
            approved_package_digest=digest,
            healing_context=_context(),
            heal_observation=_heal_screen(),
            worker_model_call=bridge,
        )
        assert healed.record.healer_calls == 1
        assert bridge.roles == ["healing"]
        assert healed.record.original_failure == "target_not_found"
        assert healed.record.attempt_result == "accepted"
        assert healed.record.package_digest_after == digest
        assert healed.success is False
        stored = separate_verify_heal_storage(
            original_failure=healed.record.original_failure,
            attempt_result=healed.record.attempt_result,
            approved_package_digest=healed.record.approved_package_digest,
            package_digest_after=healed.record.package_digest_after,
            healer_calls=healed.record.healer_calls,
            verifier_calls=healed.record.verifier_calls,
        )
        assert stored["approved_package_mutated"] is False
        assert stored["original_failure"] != stored["healing_attempt_result"]


def _android_handler(tmp_path: Path, *, healing_enabled: bool, heal_budget: int, after: Observation) -> AndroidReplayHandler:
    calls: list = []

    def runner(argv, timeout):
        calls.append(tuple(argv))
        return subprocess.CompletedProcess(list(argv), 0, b"", b"")

    driver = AndroidDeterministicDriver(
        Path("C:/platform-tools/adb.exe"),
        "emulator-5580",
        runner=runner,
        spool=EvidenceSpool(tmp_path / "spool"),
    )
    before = Observation(
        str(uuid4()),
        datetime.now(timezone.utc).isoformat(),
        _geometry(),
        _png(100, 200),
        '{"nodes":[{"locator":"#ok","text":"ok","value":"","state":"visible"}]}',
        "[]",
        (),
        "",
        True,
        "android",
    )
    return AndroidReplayHandler(
        adapter=MobileAgentAndroidAdapter(),
        driver=driver,
        broker=ModelBroker("item-1", (), (), ()),
        guard=RemoteLeaseGuard(),
        journal=DispatchJournal(tmp_path / "journal.jsonl"),
        spool=EvidenceSpool(tmp_path / "evidence"),
        context=AndroidReplayContext(
            expected_serial="emulator-5580",
            approved_digest="sha256:approved",
            approved_plan="click(250, 500)",
            before=before,
            after=after,
            healing_enabled=healing_enabled,
            heal_budget_remaining=heal_budget,
            checks=_checks(),
            verify_broker=_broker(),
            verify_transport=_Script(),
            verify_control=_Allow(),
            healable_check_id="check-1",
            approved_failure_reason="target_not_found",
        ),
    )


def test_rx_54_android_handler_off_and_actor_zero(tmp_path: Path) -> None:
    # Check fixtures remain web-shaped; Android handler still routes through the shared port.
    failed = _failed_obs()
    handler = _android_handler(tmp_path, healing_enabled=False, heal_budget=2, after=failed)
    result = handler.handle(
        {
            "attempt_id": str(uuid4()),
            "snapshot": {
                "purpose": "regression",
                "digest": "sha256:approved",
                "serial": "emulator-5580",
                "action_id": "a1",
            },
        }
    )
    assert handler.authoring_calls_seen == 0
    assert handler.healer_calls == 0
    assert handler.package_digest_after == "sha256:approved"
    assert result.outcome == "error"
    assert handler.original_failure == "target_not_found"


def test_rx_54_web_handler_off_budget_on_timeout(tmp_path: Path) -> None:
    now = datetime(2026, 11, 5, 10, 0, tzinfo=timezone.utc)
    gate = WebIsolationGate(
        IsolationConfig(backend=fixture_backend(allowed_origins=(ORIGIN,)), proof_secret=b"rx54-fixture-secret!!")
    )
    proof = gate.issue_proof(now=now)
    adapter = CuawrightWebAdapter()
    trajectory = {
        "complete": True,
        "steps": [
            {
                "hook": "hook.web.code_output.step_script",
                "code": "qa_runtime.click('#go')",
                "summary": {"type": "click", "selector": "#go"},
            }
        ],
    }
    bundle = adapter.extract_trajectory(trajectory)
    draft = adapter.build_approval_package(
        bundle,
        origin=ORIGIN,
        revision="lock-1",
        manifest=make_recording_manifest(raw_source=bundle.reviewable_source),
        lock_hash="lock-1",
    )
    approved = ApprovedWebPackage(digest=draft.digest, revision="lock-1", origin=ORIGIN)
    failed = _failed_obs()
    heal = _heal_screen()
    before = Observation(
        str(uuid4()),
        now.isoformat(),
        _geometry(physical=(24, 48), model=(24, 48)),
        _png(24, 48),
        "<button id='go'>Go</button>",
        "",
        (),
        "",
        True,
        "web",
    )

    def _handler(
        *,
        healing_enabled: bool,
        heal_budget: int,
        transport: ModelTransport | None = None,
        bridge: object | None = None,
        purpose_checks: bool = True,
    ) -> WebReplayHandler:
        return WebReplayHandler(
            adapter=adapter,
            gate=gate,
            guard=RemoteLeaseGuard(),
            journal=DispatchJournal(tmp_path / f"j-{uuid4()}.jsonl"),
            spool=EvidenceSpool(tmp_path / f"s-{uuid4()}"),
            context=WebReplayContext(
                approved=approved,
                bundle_source=trajectory,
                before=before,
                after=failed,
                proof=proof,
                now=now,
                runner=lambda action: None,
                healing_enabled=healing_enabled,
                heal_budget_remaining=heal_budget,
                checks=_checks() if purpose_checks else (),
                verify_broker=_broker() if purpose_checks else None,
                verify_transport=transport or _Script(),
                verify_control=_Allow(),
                healable_check_id="check-1",
                approved_failure_reason="target_not_found",
                healing_context=_context() if healing_enabled else None,
                heal_observation=heal if healing_enabled else None,
                worker_model_call=bridge,
            ),
        )

    def _claim(purpose: str = "regression") -> dict:
        return {
            "attempt_id": str(uuid4()),
            "snapshot": {
                "purpose": purpose,
                "origin": ORIGIN,
                "digest": approved.digest,
                "revision": "lock-1",
                "action_id": str(uuid4()),
            },
        }

    off = _handler(healing_enabled=False, heal_budget=2)
    off_result = off.handle(_claim())
    assert off.actor_ai_calls == 0
    assert off.healer_calls == 0
    assert off.package_digest_after == approved.digest
    assert off_result.outcome == "error"
    assert off.original_failure == "target_not_found"

    budget = _handler(healing_enabled=True, heal_budget=0)
    budget.handle(_claim())
    assert budget.healer_calls == 0
    assert budget.package_digest_after == approved.digest

    timed_transport = _Script()
    timed_transport.timeout = True
    # AI check timeout preserves failure and skips healer.
    timed = WebReplayHandler(
        adapter=adapter,
        gate=gate,
        guard=RemoteLeaseGuard(),
        journal=DispatchJournal(tmp_path / "timed.jsonl"),
        spool=EvidenceSpool(tmp_path / "timed-spool"),
        context=WebReplayContext(
            approved=approved,
            bundle_source=trajectory,
            before=before,
            after=failed,
            proof=proof,
            now=now,
            runner=lambda action: None,
            healing_enabled=True,
            heal_budget_remaining=2,
            checks=(CheckSpec("check-1", "text", "로그인됨", subject="#login", method="ai_visual"),),
            verify_broker=_broker(),
            verify_transport=timed_transport,
            verify_control=_Allow(),
            healable_check_id="check-1",
            healing_context=_context(),
            heal_observation=heal,
        ),
    )
    timed_result = timed.handle(_claim())
    assert timed_result.outcome == "error"
    assert timed.original_failure == "timed out"
    assert timed.healer_calls == 0
    assert timed.package_digest_after == approved.digest

    bridge = _HealBridge()
    on = _handler(healing_enabled=True, heal_budget=2, bridge=bridge)
    on_result = on.handle(_claim())
    assert on.actor_ai_calls == 0
    assert on.healer_calls == 1
    assert bridge.roles == ["healing"]
    assert on.original_failure == "target_not_found"
    assert on.package_digest_after == approved.digest
    assert on_result.outcome == "error"

    trial = _handler(healing_enabled=True, heal_budget=2, bridge=_HealBridge())
    trial.handle(_claim("trial"))
    assert trial.healer_calls == 0
