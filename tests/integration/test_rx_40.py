"""RX-40: per-attempt model budget, fixture vs operational provider, stale generation."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from aiqa.api.app import create_app
from aiqa.api.auth import bound_auth_store, enroll_worker
from aiqa.config import load_settings
from aiqa.contracts.models import OwnedCheck, OwnedEpisode, RoleBinding
from aiqa.domain.projects import bind_store, create_project
from aiqa.models.broker import (
    AttemptModelPolicy,
    ModelRequestDenied,
    WorkerModelRequest,
    build_model_gateway,
)
from aiqa.models.provider_http import FixtureProviderHttp, OperationalProviderHttp
from aiqa.security.secrets import (
    MemorySecretBackend,
    bind_secret_store,
    build_server_secret_resolver,
)
from aiqa.store.database import migrate_store
from aiqa.store.models import Actor, ProjectCreate, SecretInput, SecretRef, WorkerScope


def _env(root: Path) -> dict[str, str]:
    return {
        "AIQA_HOST": "127.0.0.1",
        "AIQA_PORT": "8000",
        "AIQA_RUNTIME_ROOT": str(root),
    }


def _req(
    *,
    purpose: str,
    role: str,
    owner_kind: str = "check",
    owner_id: str = "check-1",
    check_id: str | None = "check-1",
    generation: int | None = 1,
) -> WorkerModelRequest:
    return WorkerModelRequest(
        call_id=uuid4(),
        purpose=purpose,
        role=role,
        owner_kind=owner_kind,
        owner_id=owner_id,
        binding_revision=1,
        sanitized_inputs=("ok",),
        token_output_limit=16,
        deadline="2099-01-01T00:00:00+00:00",
        check_id=check_id,
        generation=generation,
    )


def _policy(project_id, item_id: str, secret_ref: SecretRef, *, healing: bool, max_calls: int, generation: int = 1):
    return AttemptModelPolicy(
        project_id=project_id,
        item_id=item_id,
        purpose="regression",
        healing_enabled=healing,
        max_calls=max_calls,
        budget="2.00",
        bindings=(
            RoleBinding("verification", 1, "fixture-v", str(secret_ref.ref_id)),
            RoleBinding("healing", 1, "fixture-h", str(secret_ref.ref_id)),
            RoleBinding("authoring", 1, "fixture-a", str(secret_ref.ref_id)),
        ),
        checks=(OwnedCheck("check-1", item_id),),
        episodes=(OwnedEpisode("episode-1", item_id),),
        secret_refs={
            "verification": secret_ref,
            "healing": secret_ref,
            "authoring": secret_ref,
        },
        generation=generation,
    )


def test_rx_40_two_attempts_separate_budgets_and_gates(tmp_path: Path) -> None:
    settings = load_settings(_env(tmp_path / "runtime"))
    backend = MemorySecretBackend()
    resolver = build_server_secret_resolver(settings, backend=backend)
    provider = FixtureProviderHttp()
    gateway = build_model_gateway(resolver, provider=provider)
    assert getattr(gateway.provider, "kind") == "fixture"

    store = create_app(settings, secret_backend=backend).state.open_store()
    migrate_store(store)
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("RX40", "rx40", "", "web"))
    actor = Actor(owner.actor_id, project.project_id, True)
    with bind_secret_store(store):
        created = resolver.put(actor, SecretInput(value="fixture-model-secret", name="model"))
        secret_ref = SecretRef(project.project_id, created.ref_id, created.revision)

    worker = WorkerScope(
        worker_id=str(uuid4()),
        permitted_projects=frozenset({project.project_id}),
        permitted_purposes=frozenset({"regression", "recording", "trial"}),
        token_id=None,
    )

    a = "attempt-a"
    b = "attempt-b"
    gateway.register_policy(_policy(project.project_id, a, secret_ref, healing=True, max_calls=1))
    gateway.register_policy(_policy(project.project_id, b, secret_ref, healing=True, max_calls=1))

    # Each attempt consumes its own max_calls=1 budget.
    req_a = _req(purpose="regression", role="verification")
    req_b = _req(purpose="regression", role="verification")
    r1 = gateway.handle(
        worker,
        req_a,
        project_id=project.project_id,
        item_id=a,
        idempotency_key="a-1",
        actor_id=actor.actor_id,
        store=store,
    )
    r2 = gateway.handle(
        worker,
        req_b,
        project_id=project.project_id,
        item_id=b,
        idempotency_key="b-1",
        actor_id=actor.actor_id,
        store=store,
    )
    assert r1.usage["verification_calls"] == 1
    assert r2.usage["verification_calls"] == 1
    assert '"status":"satisfied"' in r1.content.replace(" ", "")
    assert provider.call_count == 2

    with pytest.raises(ModelRequestDenied, match="quota"):
        gateway.handle(
            worker,
            _req(purpose="regression", role="verification"),
            project_id=project.project_id,
            item_id=a,
            idempotency_key="a-2",
            actor_id=actor.actor_id,
            store=store,
        )
    assert provider.call_count == 2
    assert len(gateway.receipts_for(project.project_id, a)) == 1
    assert len(gateway.receipts_for(project.project_id, b)) == 1

    # Retransmit same key + body → no extra provider call.
    again = gateway.handle(
        worker,
        req_b,
        project_id=project.project_id,
        item_id=b,
        idempotency_key="b-1",
        actor_id=actor.actor_id,
        store=store,
    )
    assert again.replayed is True
    assert provider.call_count == 2

    # Stale generation refused.
    gateway.register_policy(
        _policy(project.project_id, "attempt-c", secret_ref, healing=False, max_calls=2, generation=2)
    )
    with pytest.raises(ModelRequestDenied, match="stale_generation"):
        gateway.handle(
            worker,
            _req(purpose="regression", role="verification", generation=1),
            project_id=project.project_id,
            item_id="attempt-c",
            idempotency_key="c-stale",
            actor_id=actor.actor_id,
            store=store,
        )
    assert provider.call_count == 2

    # Healing OFF / replay actor / missing key.
    gateway.register_policy(
        _policy(project.project_id, "attempt-d", secret_ref, healing=False, max_calls=3, generation=1)
    )
    with pytest.raises(ModelRequestDenied, match="healing_off"):
        gateway.handle(
            worker,
            _req(purpose="regression", role="healing", owner_kind="check", owner_id="check-1"),
            project_id=project.project_id,
            item_id="attempt-d",
            idempotency_key="d-heal",
            actor_id=actor.actor_id,
            store=store,
        )
    with pytest.raises(ModelRequestDenied, match="replay_actor"):
        gateway.handle(
            worker,
            _req(
                purpose="regression",
                role="authoring",
                owner_kind="authoring",
                owner_id="attempt-d",
                check_id=None,
            ),
            project_id=project.project_id,
            item_id="attempt-d",
            idempotency_key="d-actor",
            actor_id=actor.actor_id,
            store=store,
        )

    # Missing secret → no provider call.
    empty = AttemptModelPolicy(
        project_id=project.project_id,
        item_id="attempt-e",
        purpose="regression",
        healing_enabled=False,
        max_calls=2,
        budget="2.00",
        bindings=(RoleBinding("verification", 1, "fixture-v", str(uuid4())),),
        checks=(OwnedCheck("check-1", "attempt-e"),),
        episodes=(),
        secret_refs={},
        generation=1,
    )
    gateway.register_policy(empty)
    before = provider.call_count
    with pytest.raises(ModelRequestDenied, match="secret"):
        gateway.handle(
            worker,
            _req(purpose="regression", role="verification"),
            project_id=project.project_id,
            item_id="attempt-e",
            idempotency_key="e-secret",
            actor_id=actor.actor_id,
            store=store,
        )
    assert provider.call_count == before

    # Operational provider stays separate and disabled by default.
    ops = OperationalProviderHttp(allow_live=False)
    with pytest.raises(ValueError, match="not enabled|secret"):
        ops.complete(
            model="m",
            role="verification",
            secret="x" * 8,
            sanitized_inputs=("ok",),
            token_output_limit=8,
        )
    assert ops.call_count == 0


def test_rx_40_app_wires_fixture_provider(tmp_path: Path) -> None:
    settings = load_settings(_env(tmp_path / "app"))
    app = create_app(settings, secret_backend=MemorySecretBackend())
    assert getattr(app.state.model_gateway.provider, "kind") == "fixture"
