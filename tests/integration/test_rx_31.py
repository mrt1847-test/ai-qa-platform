"""RX-31: replay verify + healing gates, worker model bridge, separate results."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from aiqa.api.app import create_app
from aiqa.api.worker import connect_verify_heal_model_bridge
from aiqa.config import load_settings
from aiqa.contracts.actions import Observation
from aiqa.contracts.checks import CheckSpec
from aiqa.contracts.jobs import ControlDecision
from aiqa.contracts.models import ModelRequest, OwnedCheck, OwnedEpisode, RoleBinding
from aiqa.domain.executions import separate_verify_heal_storage
from aiqa.domain.projects import bind_store, create_project
from aiqa.healing.service import run_replay_verify_and_heal
from aiqa.healing.targets import HealingContext
from aiqa.models.broker import (
    AttemptModelPolicy,
    ModelBroker,
    ModelTransport,
    ServerModelGateway,
)
from aiqa.models.provider_http import FixtureProviderHttp
from aiqa.security.secrets import (
    MemorySecretBackend,
    bind_secret_store,
    build_server_secret_resolver,
)
from aiqa.store.database import migrate_store
from aiqa.store.models import Actor, ProjectCreate, SecretInput, SecretRef, WorkerScope
from aiqa.worker.runner import verify_and_heal_after_replay


def _env(root: Path) -> dict[str, str]:
    return {
        "AIQA_HOST": "127.0.0.1",
        "AIQA_PORT": "8000",
        "AIQA_RUNTIME_ROOT": str(root),
    }


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


def _web(text: str) -> str:
    return '{"nodes":[{"locator":"#login","text":"' + text + '","value":"ada","state":"visible"}]}'


def _observation(dom: str, messages: tuple[str, ...] = ()) -> Observation:
    return Observation("obs-1", "2026-11-01T00:00:00+00:00", None, b"", dom, "", messages, "", True, "web")


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


def _context(payload: dict[str, object]) -> HealingContext:
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
        payload,
    )


def _payload(locator: str = "#new") -> dict[str, object]:
    return {
        "basis": "typed",
        "role": "button",
        "name": "저장",
        "container": "form",
        "resource_id": "id.save",
        "text": "저장",
        "context": "main",
        "locator": locator,
        "action": "click",
        "input": "",
        "path": "/form",
        "coordinates": [20, 20],
    }


def _heal_screen() -> Observation:
    import json

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
        "obs-1",
        "2026-11-01T00:00:00+00:00",
        None,
        b"",
        json.dumps({"elements": [element]}),
        "",
        (),
        "",
        True,
        "web",
    )


def _broker(*, healing: bool = True) -> ModelBroker:
    bindings = [RoleBinding("verification", 1, "fixture-verify", "ref-1")]
    if healing:
        bindings.append(RoleBinding("healing", 1, "fixture-heal", "ref-1"))
    return ModelBroker(
        "item-1",
        tuple(bindings),
        (OwnedCheck("check-1", "item-1"), OwnedCheck("check-2", "item-1")),
        (OwnedEpisode("episode-1", "item-1"),),
    )


def test_rx_31_off_budget_wrong_reason_other_check_timeout_and_package() -> None:
    transport = _Script()
    broker = _broker()
    control = _Allow()
    failed = _observation(_web("실패"))
    digest = "pkg-digest-v1"
    checks = (CheckSpec("check-1", "text", "로그인됨", subject="#login", method="deterministic"),)

    off = verify_and_heal_after_replay(
        checks=checks,
        observation=failed,
        control=control,
        broker=broker,
        transport=transport,
        healing_enabled=False,
        heal_budget_remaining=2,
        approved_failure_reason="target_not_found",
        healable_check_id="check-1",
        approved_package_digest=digest,
        healing_context=_context(_payload()),
        heal_observation=_heal_screen(),
    )
    assert off.record.healer_calls == 0
    assert off.success is False
    assert off.record.attempt_result == "rejected_policy"
    assert off.record.package_digest_after == digest

    no_budget = run_replay_verify_and_heal(
        checks=checks,
        observation=failed,
        control=control,
        broker=broker,
        transport=transport,
        healing_enabled=True,
        heal_budget_remaining=0,
        approved_failure_reason="target_not_found",
        healable_check_id="check-1",
        approved_package_digest=digest,
        healing_context=_context(_payload()),
        heal_observation=_heal_screen(),
    )
    assert no_budget.record.healer_calls == 0

    wrong_reason = run_replay_verify_and_heal(
        checks=checks,
        observation=failed,
        control=control,
        broker=broker,
        transport=transport,
        healing_enabled=True,
        heal_budget_remaining=2,
        approved_failure_reason="network_blip",
        healable_check_id="check-1",
        approved_package_digest=digest,
        healing_context=_context(_payload()),
        heal_observation=_heal_screen(),
    )
    assert wrong_reason.record.healer_calls == 0

    other_check = run_replay_verify_and_heal(
        checks=checks,
        observation=failed,
        control=control,
        broker=broker,
        transport=transport,
        healing_enabled=True,
        heal_budget_remaining=2,
        approved_failure_reason="target_not_found",
        healable_check_id="check-2",
        approved_package_digest=digest,
        healing_context=_context(_payload()),
        heal_observation=_heal_screen(),
    )
    assert other_check.record.healer_calls == 0
    assert other_check.record.original_check_id == "check-1"

    timed = _Script()
    timed.timeout = True
    ai = run_replay_verify_and_heal(
        checks=(CheckSpec("check-1", "text", "로그인됨", subject="#login", method="ai_visual"),),
        observation=_observation(_web("로그인됨")),
        control=control,
        broker=broker,
        transport=timed,
        healing_enabled=True,
        heal_budget_remaining=2,
        approved_failure_reason=None,
        healable_check_id="check-1",
        approved_package_digest=digest,
    )
    assert ai.success is False
    assert ai.record.original_failure == "timed out"
    assert ai.record.healer_calls == 0

    undeclared_before = transport.calls
    undeclared = run_replay_verify_and_heal(
        checks=(CheckSpec("check-1", "text", "로그인됨", subject="#login", method="guess"),),
        observation=_observation(_web("로그인됨")),
        control=control,
        broker=broker,
        transport=transport,
        healing_enabled=True,
        heal_budget_remaining=2,
        approved_failure_reason=None,
        healable_check_id=None,
        approved_package_digest=digest,
    )
    assert undeclared.record.verifier_calls == 0
    assert transport.calls == undeclared_before
    assert undeclared.check_results[0].reason == "method is not declared"

    stored = separate_verify_heal_storage(
        original_failure=off.record.original_failure,
        attempt_result=off.record.attempt_result,
        approved_package_digest=off.record.approved_package_digest,
        package_digest_after=off.record.package_digest_after,
        healer_calls=off.record.healer_calls,
        verifier_calls=off.record.verifier_calls,
    )
    assert stored["approved_package_mutated"] is False
    assert stored["original_failure"] != stored["healing_attempt_result"] or stored["healing_attempt_result"] == "rejected_policy"


def test_rx_31_on_heal_via_worker_model_bridge_keeps_package(tmp_path: Path) -> None:
    settings = load_settings(_env(tmp_path / "runtime"))
    backend = MemorySecretBackend()
    resolver = build_server_secret_resolver(settings, backend=backend)
    provider = FixtureProviderHttp()
    gateway = ServerModelGateway(provider=provider, resolver=resolver)

    store = create_app(settings).state.open_store()
    migrate_store(store)
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("RX31", "rx31", "", "web"))
    actor = Actor(owner.actor_id, project.project_id, True)
    with bind_secret_store(store):
        created = resolver.put(actor, SecretInput(value="fixture-model-secret", name="heal"))
        secret_ref = SecretRef(project.project_id, created.ref_id, created.revision)

    item_id = "item-1"
    gateway.register_policy(
        AttemptModelPolicy(
            project_id=project.project_id,
            item_id=item_id,
            purpose="regression",
            healing_enabled=True,
            max_calls=4,
            budget="4.00",
            bindings=(
                RoleBinding("verification", 1, "fixture-verify", str(secret_ref.ref_id)),
                RoleBinding("healing", 1, "fixture-heal", str(secret_ref.ref_id)),
            ),
            checks=(OwnedCheck("check-1", item_id),),
            episodes=(OwnedEpisode("episode-1", item_id),),
            secret_refs={"verification": secret_ref, "healing": secret_ref},
        )
    )
    worker = WorkerScope("worker-rx31", (project.project_id,), ("regression",))
    bridge = connect_verify_heal_model_bridge(
        gateway,
        worker,
        project_id=project.project_id,
        item_id=item_id,
        actor_id=actor.actor_id,
        purpose="regression",
        store=store,
    )

    digest = "approved-pkg-31"
    transport = _Script()
    result = run_replay_verify_and_heal(
        checks=(CheckSpec("check-1", "text", "로그인됨", subject="#login", method="deterministic"),),
        observation=_observation(_web("실패")),
        control=_Allow(),
        broker=_broker(),
        transport=transport,
        healing_enabled=True,
        heal_budget_remaining=2,
        approved_failure_reason="target_not_found",
        healable_check_id="check-1",
        approved_package_digest=digest,
        healing_context=_context(_payload()),
        heal_observation=_heal_screen(),
        worker_model_call=bridge,
    )
    assert result.record.healer_calls == 1
    assert "healing" in bridge.roles
    assert provider.calls_for("healing") == 1
    assert result.record.proposal_admitted is True
    assert result.record.proposal_accepted is True
    assert result.record.attempt_result == "accepted"
    assert result.record.package_digest_after == digest
    assert result.record.approved_package_digest == digest
    assert result.success is False
    assert result.record.original_failure == "target_not_found"

    off_bridge = connect_verify_heal_model_bridge(
        gateway,
        worker,
        project_id=project.project_id,
        item_id=item_id,
        actor_id=actor.actor_id,
        purpose="regression",
        store=store,
        force_timeout=True,
    )
    timed = run_replay_verify_and_heal(
        checks=(CheckSpec("check-1", "text", "로그인됨", subject="#login", method="deterministic"),),
        observation=_observation(_web("실패")),
        control=_Allow(),
        broker=_broker(),
        transport=_Script(),
        healing_enabled=True,
        heal_budget_remaining=2,
        approved_failure_reason="ambiguous",
        healable_check_id="check-1",
        approved_package_digest=digest,
        healing_context=_context(_payload()),
        heal_observation=_heal_screen(),
        worker_model_call=off_bridge,
    )
    assert timed.success is False
    assert timed.record.attempt_result == "timed_out"
    assert timed.record.healer_calls == 1
    store.close()


def test_rx_31_deterministic_before_ai_supplement() -> None:
    transport = _Script()
    broker = _broker(healing=False)
    violated = run_replay_verify_and_heal(
        checks=(
            CheckSpec(
                "check-1",
                "text",
                "로그인됨",
                subject="#login",
                method="deterministic_then_ai_unknown",
                allow_unknown_supplement=True,
            ),
        ),
        observation=_observation(_web("실패")),
        control=_Allow(),
        broker=broker,
        transport=transport,
        healing_enabled=False,
        heal_budget_remaining=0,
        approved_failure_reason=None,
        healable_check_id=None,
        approved_package_digest="pkg",
    )
    assert violated.check_results[0].status == "violated"
    assert violated.record.verifier_calls == 0
    assert transport.calls == 0
