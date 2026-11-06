"""RX-69: structure uses project model binding/secret; distinct NL; no duplicate calls."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import uuid4

import httpx

from aiqa.api.app import create_app
from aiqa.config import load_settings
from aiqa.domain.model_bindings import bind_model_store, save_model_binding_revision
from aiqa.domain.projects import bind_store, create_project
from aiqa.models.provider_http import FixtureProviderHttp, ProviderHttpError
from aiqa.security.secrets import MemorySecretBackend, bind_secret_store
from aiqa.store.database import migrate_store
from aiqa.store.models import Actor, ModelBindingInput, ProjectCreate, SecretInput, SecretRef
from ux_support import session

_NL_A = "로그인한 뒤 주문 내역에서 첫 주문을 열고 주문번호를 확인해줘."
_NL_B = "장바구니에 담은 상품의 결제 금액이 표시되는지 확인해줘."
_PROMPT = "sha256:" + ("ab" * 32)


class FlakyStructureProvider(FixtureProviderHttp):
    """Fixture provider that can inject 401/429 after recording calls."""

    def __init__(self) -> None:
        super().__init__()
        self.fail_mode: str | None = None

    def complete(self, *, model, role, secret, sanitized_inputs, token_output_limit):
        if self.fail_mode == "unauthorized":
            raise ProviderHttpError("provider_unauthorized", status=401)
        if self.fail_mode == "rate_limited":
            raise ProviderHttpError("provider_quota", status=429)
        return super().complete(
            model=model,
            role=role,
            secret=secret,
            sanitized_inputs=sanitized_inputs,
            token_output_limit=token_output_limit,
        )


def _seed_structure_binding(app, store, *, project, actor, secret_value: str = "structure-key") -> None:
    resolver = app.state.secret_resolver
    with bind_secret_store(store):
        created = resolver.put(actor, SecretInput(value=secret_value, name="structure"))
    with bind_model_store(store):
        save_model_binding_revision(
            ModelBindingInput(
                project_id=project.project_id,
                actor_id=actor.actor_id,
                name="structure",
                role="structure",
                provider="fixture",
                endpoint_kind="https",
                endpoint="https://model.example/v1/structure",
                model="fixture-structure-model",
                key_ref=SecretRef(project.project_id, created.ref_id, created.revision),
                prompt_hash=_PROMPT,
                tariff_id="structure-t1",
                compatibility_status="compatible",
                binding_id=None,
            )
        )


def test_rx_69_structure_uses_project_binding(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    settings = load_settings(
        {"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}
    )
    backend = MemorySecretBackend()
    provider = FlakyStructureProvider()
    app = create_app(settings, secret_backend=backend, model_provider=provider)
    owner = Actor(uuid4(), None, True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("구조연결", "rx69", "모델", "web"))
    actor = Actor(owner.actor_id, project.project_id, True)
    _seed_structure_binding(app, store, project=project, actor=actor)
    store.close()
    project_id = str(project.project_id)

    observed = asyncio.run(_flow(app, project_id, provider, tmp_path))
    assert observed["missing_binding"] == 422
    assert observed["missing_retryable"] is True
    assert observed["a_status"] == 201
    assert observed["b_status"] == 201
    assert observed["a_objective"] != observed["b_objective"]
    assert observed["a_input"] != observed["b_input"]
    assert observed["provider_model"] == "fixture-structure-model"
    assert observed["replay_status"] in {200, 201}
    assert observed["replay_proposal"] == observed["a_proposal"]
    assert observed["model_calls_after_replay"] == observed["model_calls_before_replay"]
    assert observed["unauthorized_status"] == 401
    assert observed["unauthorized_retryable"] is True
    assert observed["rate_status"] == 429
    assert observed["rate_retryable"] is True
    assert observed["secret_leaked"] is False
    assert observed["auto_applied"] is False
    assert observed["accept_delta"] == 1


async def _flow(
    app: object, project_id: str, provider: FlakyStructureProvider, tmp_path: Path
) -> dict[str, object]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        headers = await session(client, project_id)

        # Project without structure binding is covered by a second app below; here first
        # exercise two distinct NL drafts on the bound project.
        async def create_case(name: str, nl: str, key: str) -> tuple[str, str]:
            headers["Idempotency-Key"] = f"{key}-case"
            created = await client.post(
                f"/api/v1/projects/{project_id}/cases",
                json={"name": name, "tc_reference": None},
                headers=headers,
            )
            assert created.status_code == 201, created.text
            case_id = created.json()["case_id"]
            headers["Idempotency-Key"] = f"{key}-draft"
            draft = await client.post(
                f"/api/v1/projects/{project_id}/cases/{case_id}/versions",
                json={
                    "definition": {
                        "raw_text": nl,
                        "objective": "",
                        "preconditions": [],
                        "variables": {},
                        "secret_refs": {},
                        "steps": [],
                        "final_expected": [],
                        "path_policy": {"must_use": [], "forbidden": []},
                    },
                    "settings": {"target_kind": "web", "definition_buffer": nl},
                    "recorded_steps": [],
                    "parent_version_id": None,
                    "base_version_id": None,
                    "reason": "draft",
                    "expected_head": None,
                    "branch": False,
                },
                headers=headers,
            )
            assert draft.status_code == 201, draft.text
            return case_id, draft.json()["id"]

        case_a, version_a = await create_case("주문A", _NL_A, "rx69a")
        case_b, version_b = await create_case("결제B", _NL_B, "rx69b")

        headers["Idempotency-Key"] = "rx69-a"
        structured_a = await client.post(
            f"/api/v1/projects/{project_id}/cases/{case_a}/versions/{version_a}/structure",
            json={},
            headers=headers,
        )
        assert structured_a.status_code == 201, structured_a.text
        body_a = structured_a.json()
        assert body_a["auto_applied"] is False

        headers["Idempotency-Key"] = "rx69-b"
        structured_b = await client.post(
            f"/api/v1/projects/{project_id}/cases/{case_b}/versions/{version_b}/structure",
            json={},
            headers=headers,
        )
        assert structured_b.status_code == 201, structured_b.text
        body_b = structured_b.json()

        proposal_a = await client.get(
            f"/api/v1/projects/{project_id}/cases/{case_a}/proposals/{body_a['proposal_id']}"
        )
        proposal_b = await client.get(
            f"/api/v1/projects/{project_id}/cases/{case_b}/proposals/{body_b['proposal_id']}"
        )
        # proposals GET may not exist — fall back to accept path body via list/page or DB through accept
        obj_a = obj_b = ""
        if proposal_a.status_code == 200 and proposal_b.status_code == 200:
            obj_a = str(proposal_a.json().get("body", {}).get("objective", ""))
            obj_b = str(proposal_b.json().get("body", {}).get("objective", ""))

        calls_before = provider.call_count
        headers["Idempotency-Key"] = "rx69-a"
        replay = await client.post(
            f"/api/v1/projects/{project_id}/cases/{case_a}/versions/{version_a}/structure",
            json={},
            headers=headers,
        )
        calls_after = provider.call_count

        provider.fail_mode = "unauthorized"
        headers["Idempotency-Key"] = "rx69-401"
        unauthorized = await client.post(
            f"/api/v1/projects/{project_id}/cases/{case_a}/versions/{version_a}/structure",
            json={},
            headers=headers,
        )
        provider.fail_mode = "rate_limited"
        headers["Idempotency-Key"] = "rx69-429"
        rate = await client.post(
            f"/api/v1/projects/{project_id}/cases/{case_b}/versions/{version_b}/structure",
            json={},
            headers=headers,
        )
        provider.fail_mode = None
        dumped = unauthorized.text + rate.text + structured_a.text + structured_b.text
        secret_leaked = "structure-key" in dumped

        # Accept B proposal → new version (+1).
        before = 0
        store = app.state.open_store()
        try:
            with store.transaction() as connection:
                before = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM case_versions WHERE case_id = ?",
                        (case_b,),
                    ).fetchone()[0]
                )
                if not obj_a:
                    row = connection.execute(
                        "SELECT body FROM case_edit_proposals WHERE proposal_id = ?",
                        (body_a["proposal_id"],),
                    ).fetchone()
                    obj_a = str(json.loads(str(row[0])).get("objective", "")) if row else ""
                if not obj_b:
                    row = connection.execute(
                        "SELECT body FROM case_edit_proposals WHERE proposal_id = ?",
                        (body_b["proposal_id"],),
                    ).fetchone()
                    obj_b = str(json.loads(str(row[0])).get("objective", "")) if row else ""
        finally:
            store.close()

        headers["Idempotency-Key"] = "rx69-accept"
        accepted = await client.post(
            f"/api/v1/projects/{project_id}/cases/{case_b}/proposal-acceptances",
            json={"proposal_id": body_b["proposal_id"], "expected_head": version_b},
            headers=headers,
        )
        assert accepted.status_code == 201, accepted.text
        store = app.state.open_store()
        try:
            with store.transaction() as connection:
                after = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM case_versions WHERE case_id = ?",
                        (case_b,),
                    ).fetchone()[0]
                )
        finally:
            store.close()

        structure_calls = [call for call in provider.calls if call.role == "structure"]
        inputs = [call.sanitized_inputs for call in structure_calls[:2]]

    # Missing binding project.
    missing_status, missing_retryable = await _missing_binding_case(tmp_path)

    return {
        "a_status": structured_a.status_code,
        "b_status": structured_b.status_code,
        "a_objective": obj_a,
        "b_objective": obj_b,
        "a_input": inputs[0] if inputs else (),
        "b_input": inputs[1] if len(inputs) > 1 else (),
        "provider_model": structure_calls[0].model if structure_calls else "",
        "replay_status": replay.status_code,
        "replay_proposal": replay.json().get("proposal_id")
        if replay.status_code in {200, 201}
        else None,
        "a_proposal": body_a["proposal_id"],
        "model_calls_before_replay": calls_before,
        "model_calls_after_replay": calls_after,
        "unauthorized_status": unauthorized.status_code,
        "unauthorized_retryable": bool(unauthorized.json().get("error", {}).get("retryable")),
        "rate_status": rate.status_code,
        "rate_retryable": bool(rate.json().get("error", {}).get("retryable")),
        "secret_leaked": secret_leaked,
        "auto_applied": body_a["auto_applied"],
        "accept_delta": after - before,
        "missing_binding": missing_status,
        "missing_retryable": missing_retryable,
    }


async def _missing_binding_case(tmp_path: Path) -> tuple[int, bool]:
    root = tmp_path / "missing"
    settings = load_settings(
        {"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}
    )
    app = create_app(settings, secret_backend=MemorySecretBackend())
    owner = Actor(uuid4(), None, True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("무설정", "rx69m", "", "web"))
    store.close()
    project_id = str(project.project_id)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        headers = await session(client, project_id)
        headers["Idempotency-Key"] = "miss-case"
        created = await client.post(
            f"/api/v1/projects/{project_id}/cases",
            json={"name": "없음", "tc_reference": None},
            headers=headers,
        )
        case_id = created.json()["case_id"]
        headers["Idempotency-Key"] = "miss-draft"
        draft = await client.post(
            f"/api/v1/projects/{project_id}/cases/{case_id}/versions",
            json={
                "definition": {
                    "raw_text": _NL_A,
                    "objective": "",
                    "preconditions": [],
                    "variables": {},
                    "secret_refs": {},
                    "steps": [],
                    "final_expected": [],
                    "path_policy": {"must_use": [], "forbidden": []},
                },
                "settings": {"target_kind": "web", "definition_buffer": _NL_A},
                "recorded_steps": [],
                "parent_version_id": None,
                "base_version_id": None,
                "reason": "draft",
                "expected_head": None,
                "branch": False,
            },
            headers=headers,
        )
        version_id = draft.json()["id"]
        headers["Idempotency-Key"] = "miss-structure"
        response = await client.post(
            f"/api/v1/projects/{project_id}/cases/{case_id}/versions/{version_id}/structure",
            json={},
            headers=headers,
        )
        return response.status_code, bool(response.json().get("error", {}).get("retryable"))
