"""RX-11: server model broker, purpose gates, fixture provider, no live LLM."""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from aiqa.api.app import create_app
from aiqa.api.auth import bound_auth_store, enroll_worker
from aiqa.config import load_settings
from aiqa.contracts.models import OwnedCheck, OwnedEpisode, RoleBinding
from aiqa.domain.projects import bind_store, create_project
from aiqa.models.broker import (
    AttemptModelPolicy,
    ModelRequestDenied,
    ServerModelGateway,
    WorkerModelRequest,
)
from aiqa.models.provider_http import FixtureProviderHttp
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


def _request(
    *,
    purpose: str,
    role: str,
    owner_kind: str = "authoring",
    owner_id: str = "item-1",
    check_id: str | None = None,
    episode_id: str | None = None,
    binding_revision: int = 1,
) -> WorkerModelRequest:
    return WorkerModelRequest(
        call_id=uuid4(),
        purpose=purpose,
        role=role,
        owner_kind=owner_kind,
        owner_id=owner_id,
        binding_revision=binding_revision,
        sanitized_inputs=("ok",),
        token_output_limit=16,
        deadline="2099-01-01T00:00:00+00:00",
        check_id=check_id,
        episode_id=episode_id,
    )


def test_gateway_rejects_off_healer_replay_actor_forged_purpose_and_quota(tmp_path: Path) -> None:
    settings = load_settings(_env(tmp_path / "runtime"))
    backend = MemorySecretBackend()
    resolver = build_server_secret_resolver(settings, backend=backend)
    provider = FixtureProviderHttp()
    gateway = ServerModelGateway(provider=provider, resolver=resolver)

    store = create_app(settings).state.open_store()
    migrate_store(store)
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("RX11", "rx11", "", "web"))
    actor = Actor(owner.actor_id, project.project_id, True)
    with bind_secret_store(store):
        created = resolver.put(actor, SecretInput(value="fixture-model-secret", name="author"))
        secret_ref = SecretRef(project.project_id, created.ref_id, created.revision)

    item_id = "item-1"
    off_policy = AttemptModelPolicy(
        project_id=project.project_id,
        item_id=item_id,
        purpose="regression",
        healing_enabled=False,
        max_calls=1,
        budget="2.00",
        bindings=(
            RoleBinding("authoring", 1, "fixture-author", str(secret_ref.ref_id)),
            RoleBinding("verification", 1, "fixture-verify", str(secret_ref.ref_id)),
            RoleBinding("healing", 1, "fixture-heal", str(secret_ref.ref_id)),
        ),
        checks=(OwnedCheck("check-1", item_id),),
        episodes=(OwnedEpisode("episode-1", item_id),),
        secret_refs={
            "authoring": secret_ref,
            "verification": secret_ref,
            "healing": secret_ref,
        },
    )
    gateway.register_policy(off_policy)
    worker = WorkerScope("worker-rx11", (project.project_id,), ("regression",))

    with pytest.raises(ModelRequestDenied, match="healing_off"):
        gateway.handle(
            worker,
            _request(
                purpose="regression",
                role="healing",
                owner_kind="episode",
                owner_id="episode-1",
                episode_id="episode-1",
            ),
            project_id=project.project_id,
            item_id=item_id,
            idempotency_key="heal-off",
            actor_id=actor.actor_id,
        )

    with pytest.raises(ModelRequestDenied, match="replay_actor"):
        gateway.handle(
            worker,
            _request(purpose="regression", role="authoring"),
            project_id=project.project_id,
            item_id=item_id,
            idempotency_key="replay-author",
            actor_id=actor.actor_id,
        )

    forged = WorkerScope("worker-rx11", (project.project_id,), ("recording",))
    with pytest.raises(ModelRequestDenied, match="forged_purpose"):
        gateway.handle(
            forged,
            _request(
                purpose="regression",
                role="verification",
                owner_kind="check",
                owner_id="check-1",
                check_id="check-1",
            ),
            project_id=project.project_id,
            item_id=item_id,
            idempotency_key="forged",
            actor_id=actor.actor_id,
        )

    first = gateway.handle(
        worker,
        _request(
            purpose="regression",
            role="verification",
            owner_kind="check",
            owner_id="check-1",
            check_id="check-1",
        ),
        project_id=project.project_id,
        item_id=item_id,
        idempotency_key="verify-1",
        actor_id=actor.actor_id,
        store=store,
    )
    assert first.allowed is True
    assert first.measurement_status == "metered"
    assert provider.call_count == 1
    assert provider.calls_for("verification") == 1

    with pytest.raises(ModelRequestDenied, match="quota"):
        gateway.handle(
            worker,
            _request(
                purpose="regression",
                role="verification",
                owner_kind="check",
                owner_id="check-1",
                check_id="check-1",
            ),
            project_id=project.project_id,
            item_id=item_id,
            idempotency_key="verify-2",
            actor_id=actor.actor_id,
            store=store,
        )
    assert provider.call_count == 1
    store.close()


def test_model_requests_route_idempotency_and_secret_scrub(tmp_path: Path) -> None:
    asyncio.run(_route_flow(tmp_path))


async def _route_flow(tmp_path: Path) -> None:
    root = tmp_path / "api"
    settings = load_settings(_env(root))
    backend = MemorySecretBackend()
    resolver = build_server_secret_resolver(settings, backend=backend)
    provider = FixtureProviderHttp()
    app = create_app(settings)
    app.state.secret_resolver = resolver
    gateway = ServerModelGateway(provider=provider, resolver=resolver)
    app.state.model_gateway = gateway

    store = app.state.open_store()
    migrate_store(store)
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("Route", "rx11r", "", "web"))
    actor = Actor(owner.actor_id, project.project_id, True)
    with bound_auth_store(store):
        token = enroll_worker(actor, "worker-rx11-route", "recording")
    with bind_secret_store(store):
        created = resolver.put(actor, SecretInput(value="route-secret-VALUE", name="author"))
        secret_ref = SecretRef(project.project_id, created.ref_id, created.revision)

    item_id = "rec-item"
    gateway.register_policy(
        AttemptModelPolicy(
            project_id=project.project_id,
            item_id=item_id,
            purpose="recording",
            healing_enabled=False,
            max_calls=4,
            budget="2.00",
            bindings=(RoleBinding("authoring", 1, "fixture-author", str(secret_ref.ref_id)),),
            checks=(),
            episodes=(),
            secret_refs={"authoring": secret_ref},
        )
    )
    on_item = "heal-item"
    gateway.register_policy(
        AttemptModelPolicy(
            project_id=project.project_id,
            item_id=on_item,
            purpose="recording",
            healing_enabled=True,
            max_calls=4,
            budget="2.00",
            bindings=(
                RoleBinding("authoring", 1, "fixture-author", str(secret_ref.ref_id)),
                RoleBinding("healing", 1, "fixture-heal", str(secret_ref.ref_id)),
            ),
            checks=(),
            episodes=(OwnedEpisode("episode-1", on_item),),
            secret_refs={"authoring": secret_ref, "healing": secret_ref},
        )
    )
    store.close()

    call_id = str(uuid4())
    body = {
        "project_id": str(project.project_id),
        "item_id": item_id,
        "actor_id": str(actor.actor_id),
        "call_id": call_id,
        "purpose": "recording",
        "role": "authoring",
        "owner_kind": "authoring",
        "owner_id": item_id,
        "binding_revision": 1,
        "sanitized_inputs": ["step"],
        "token_output_limit": 32,
        "deadline": "2099-01-01T00:00:00+00:00",
    }
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": "rx11-auth"}
        first = await client.post("/api/v1/worker/model-requests", headers=headers, json=body)
        assert first.status_code == 200, first.text
        payload = first.json()
        assert payload["allowed"] is True
        assert payload["role"] == "authoring"
        assert payload["replayed"] is False
        assert payload["usage"]["authoring_calls"] == 1
        assert "secret" not in payload or payload.get("secret") in {None, "[redacted]", ""}
        assert "api_key" not in payload
        assert "route-secret-VALUE" not in first.text

        replayed = await client.post("/api/v1/worker/model-requests", headers=headers, json=body)
        assert replayed.status_code == 200
        assert replayed.json()["replayed"] is True
        assert provider.call_count == 1

        conflict = await client.post(
            "/api/v1/worker/model-requests",
            headers=headers,
            json={**body, "call_id": str(uuid4())},
        )
        assert conflict.status_code == 409

        forged = await client.post(
            "/api/v1/worker/model-requests",
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "rx11-forged"},
            json={**body, "purpose": "regression", "call_id": str(uuid4())},
        )
        assert forged.status_code == 403
        assert forged.json()["error"]["message"] == "forged_purpose"

        heal_off = await client.post(
            "/api/v1/worker/model-requests",
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "rx11-heal"},
            json={
                **body,
                "item_id": item_id,
                "role": "healing",
                "owner_kind": "episode",
                "owner_id": "episode-1",
                "episode_id": "episode-1",
                "call_id": str(uuid4()),
            },
        )
        assert heal_off.status_code == 403
        assert heal_off.json()["error"]["message"] in {"healing_off", "purpose_role"}

        heal_on = await client.post(
            "/api/v1/worker/model-requests",
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "rx11-heal-on"},
            json={
                **body,
                "item_id": on_item,
                "role": "healing",
                "owner_kind": "episode",
                "owner_id": "episode-1",
                "episode_id": "episode-1",
                "call_id": str(uuid4()),
            },
        )
        assert heal_on.status_code == 200, heal_on.text
        assert heal_on.json()["role"] == "healing"
        assert provider.calls_for("healing") == 1
        assert provider.calls_for("authoring") == 1


def test_fixture_provider_counts_without_storing_secret() -> None:
    provider = FixtureProviderHttp()
    result = provider.complete(
        model="fixture-author",
        role="authoring",
        secret="plain-SECRET",
        sanitized_inputs=("a",),
        token_output_limit=8,
    )
    assert result.provider_request_id == "fixture-1"
    assert provider.call_count == 1
    assert provider.calls[0].secret_present is True
    assert "plain-SECRET" not in repr(provider.calls)
