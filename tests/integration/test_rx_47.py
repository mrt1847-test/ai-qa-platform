"""RX-47: freeze case verification goals onto recording claim and model authoring."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from aiqa.api.app import create_app
from aiqa.api.auth import bound_auth_store, enroll_worker
from aiqa.config import WorkerClientSettings, load_settings
from aiqa.contracts.cases import (
    CaseDefinition,
    CaseRevisionInput,
    CaseSettings,
    CheckSpec,
    PathPolicy,
    StepSpec,
)
from aiqa.contracts.jobs import IdempotencyKey, JobSubmission
from aiqa.domain.projects import bind_store, create_project
from aiqa.domain.versions import bind_case_store, create_case, save_case_revision
from aiqa.domain.model_bindings import bind_model_store, save_model_binding_revision
from aiqa.recording.service import RecordingStartInput, start_recording
from aiqa.models.provider_http import FixtureProviderHttp
from aiqa.recording.intent import authoring_inputs, load_recording_intent, bind_authoring_sanitized_inputs
from aiqa.security.secrets import (
    MemorySecretBackend,
    bind_secret_store,
    build_server_secret_resolver,
)
from aiqa.store.database import migrate_store
from aiqa.store.models import Actor, ModelBindingInput, ProjectCreate, SecretInput, SecretRef, Transaction
from aiqa.store.queue import enqueue_job
from aiqa.worker.http_client import SyncASGITransport, WorkerHttpClient, WorkerHttpError


def _env(root: Path) -> dict[str, str]:
    return {
        "AIQA_HOST": "127.0.0.1",
        "AIQA_PORT": "8000",
        "AIQA_RUNTIME_ROOT": str(root),
        "AIQA_MODEL_PRICE_MODE": "estimate",
    }


class _CaptureProvider(FixtureProviderHttp):
    def __init__(self) -> None:
        super().__init__()
        self.last_inputs: tuple[str, ...] = ()

    def complete(self, **kwargs):  # type: ignore[no-untyped-def]
        self.last_inputs = tuple(kwargs.get("sanitized_inputs") or ())
        return super().complete(**kwargs)


def test_rx_47_intent_frozen_on_claim_and_authoring(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "runtime"
    root.mkdir()
    settings = load_settings(_env(root))
    backend = MemorySecretBackend()
    provider = _CaptureProvider()
    app = create_app(settings, secret_backend=backend, model_provider=provider)
    store = app.state.open_store()
    migrate_store(store)

    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("RX47", "rx47", "", "android"))
    actor = Actor(owner.actor_id, project.project_id, True)
    resolver = build_server_secret_resolver(settings, backend=backend)
    with bind_secret_store(store):
        created = resolver.put(actor, SecretInput(value="model-secret", name="login"))
        secret_ref = SecretRef(project.project_id, created.ref_id, created.revision)
    with bind_model_store(store):
        save_model_binding_revision(ModelBindingInput(project.project_id, actor.actor_id, "author", "authoring",
            "fixture", "loopback", "http://127.0.0.1", "fixture-author", secret_ref,
            "sha256:"+"a"*64, "fixture-tariff", "compatible"))

    objective = "설정 화면에서 알림 항목을 연다"
    with bind_case_store(store):
        case = create_case(actor, "GoalCase", None)
        version = save_case_revision(
            actor,
            case.case_id,
            CaseRevisionInput(
                CaseDefinition(
                    "raw goal",
                    objective,
                    ("앱이 전면이다",),
                    {"account": "demo"},
                    {"login": secret_ref},
                    (
                        StepSpec(
                            "s1",
                            "알림을 연다",
                            (CheckSpec("c1", "text", "알림"),),
                        ),
                    ),
                    (CheckSpec("f1", "visible", "알림"),),
                    PathPolicy(must_use=("settings",), forbidden=("factory",)),
                ),
                CaseSettings("android", document={"limits":{"timeout_seconds":60,"max_model_calls":3,"budget":"1.00","currency":"USD"}}),
            ),
            None,
        )

    worker_id = "worker-rx47"
    serial = "emulator-5580"
    with bound_auth_store(store):
        token = enroll_worker(actor, worker_id, "recording")

    physical = str(uuid4())
    now = datetime.now(timezone.utc)
    monkeypatch.setattr("aiqa.api.worker._server_now", lambda: now)
    with store.transaction() as connection:
        connection.execute(
            "INSERT INTO physical_resource_keys (physical_key_id, worker_id, native_id) VALUES (?, ?, ?)",
            (physical, worker_id, serial),
        )
        connection.execute(
            "INSERT INTO resource_aliases (project_id, physical_key_id, display_name, target_kind) VALUES (?, ?, ?, ?)",
            (str(project.project_id), physical, "AVD", "android"),
        )
        connection.execute(
            """
            INSERT INTO resource_inventory (
                physical_key_id, state, os_build, geometry, permissions, ime, observed_at
            ) VALUES (?, 'ready', '', '720x1600@0', '[]', '', ?)
            """,
            (physical, now.isoformat()),
        )
    store.close()

    transport = SyncASGITransport(app)
    client_settings = WorkerClientSettings(
        base_url="https://127.0.0.1",
        token=token,
        timeout_seconds=10,
        verify_tls=False,
        ca_bundle=None,
    )
    with WorkerHttpClient(client_settings, transport=transport) as client:
        client.heartbeat("boot-rx47")
        store = app.state.open_store()
        try:
            with store.transaction() as connection:
                receipt = start_recording(connection, actor, project.project_id,
                    RecordingStartInput(case.case_id, version.id, version.content_hash, physical), "rx47-rec")
                frozen = load_recording_intent(connection, project.project_id, receipt.recording_id)
            assert frozen is not None
            assert frozen.objective == objective
            assert frozen.content_hash == version.content_hash
            assert "login" in frozen.secret_refs
            assert "model-secret" not in json.dumps(frozen.secret_refs)

            # Later case edits must not change the frozen recording intent.
            with bind_case_store(store):
                save_case_revision(
                    actor,
                    case.case_id,
                    CaseRevisionInput(
                        CaseDefinition(
                            "edited",
                            "완전히 다른 목표",
                            (),
                            {},
                            {},
                            (),
                            (),
                            PathPolicy(),
                        ),
                        CaseSettings("android", document={"limits":{"timeout_seconds":60,"max_model_calls":3,"budget":"1.00","currency":"USD"}}),
                        parent_version_id=version.id,
                    ),
                    version.id,
                )
        finally:
            store.close()

        claimed = client.claim(
            boot_id="boot-rx47",
            now=now.isoformat(),
            idempotency_key="claim-rx47",
            project_id=str(project.project_id),
        )
        assert claimed is not None
        snapshot = claimed["snapshot"]
        assert snapshot["intent_hash"] == frozen.intent_hash
        assert snapshot["intent"]["objective"] == objective
        assert snapshot["intent"]["preconditions"] == ["앱이 전면이다"]
        assert "model-secret" not in json.dumps(snapshot["intent"])
        assert snapshot["intent_hash"] == frozen.intent_hash

        # Lost claim response: same key returns the same frozen goal.
        again = client.claim(
            boot_id="boot-rx47",
            now=now.isoformat(),
            idempotency_key="claim-rx47",
            project_id=str(project.project_id),
        )
        assert again is not None and again["replayed"] is True
        assert again["snapshot"]["intent_hash"] == frozen.intent_hash
        assert again["snapshot"]["intent"]["objective"] == objective
        assert again["snapshot"]["digest"] == snapshot["digest"]

        attempt_id = str(claimed["attempt_id"])
        client.acknowledge(project_id=str(project.project_id), job_id=claimed["job_id"],
            generation=claimed["generation"], runner_nonce=str(uuid4()), now=now.isoformat(), idempotency_key="ack-rx47")

        # Frozen intent binding stays testable independently of sensitive pixel coverage.
        store = app.state.open_store()
        try:
            with store.transaction() as connection:
                bound = bind_authoring_sanitized_inputs(connection, project_id=project.project_id,
                    attempt_id=attempt_id, presented_hash=frozen.intent_hash, worker_inputs=("worker-ignored",))
            assert bound == authoring_inputs(frozen)
            assert any(item.startswith(f"objective:{objective}") for item in bound)
            assert not any("model-secret" in item for item in bound)
        finally:
            store.close()
        # A target SecretRef cannot authorize sending unverified sensitive pixels.
        with pytest.raises(WorkerHttpError) as unproven_frame:
            client.request_model(
                project_id=str(project.project_id),
                item_id=attempt_id,
                payload={
                    "call_id": str(uuid4()),
                    "purpose": "recording",
                    "role": "authoring",
                    "owner_kind": "authoring",
                    "owner_id": attempt_id,
                    "binding_revision": 1,
                    "generation": claimed["generation"],
                    "sanitized_inputs": ["worker-ignored"],
                    "token_output_limit": 64,
                    "deadline": "2099-01-01T00:00:00+00:00",
                    "intent_hash": frozen.intent_hash,
                },
                idempotency_key=f"author-{attempt_id}",
            )
        assert unproven_frame.value.status_code == 403
        assert unproven_frame.value.provider_dispatched is False
        assert provider.call_count == 0

        with pytest.raises(WorkerHttpError) as forged:
            client.request_model(
                project_id=str(project.project_id),
                item_id=attempt_id,
                payload={
                    "call_id": str(uuid4()),
                    "purpose": "recording",
                    "role": "authoring",
                    "owner_kind": "authoring",
                    "owner_id": attempt_id,
                    "binding_revision": 1,
                "generation": claimed["generation"],
                    "sanitized_inputs": ["ok"],
                    "token_output_limit": 16,
                    "deadline": "2099-01-01T00:00:00+00:00",
                    "intent_hash": "sha256:" + ("ab" * 32),
                },
                idempotency_key=f"forged-{attempt_id}",
            )
        assert forged.value.status_code == 403

        with pytest.raises(WorkerHttpError) as secret_plain:
            client.request_model(
                project_id=str(project.project_id),
                item_id=attempt_id,
                payload={
                    "call_id": str(uuid4()),
                    "purpose": "recording",
                    "role": "authoring",
                    "owner_kind": "authoring",
                    "owner_id": attempt_id,
                    "binding_revision": 1,
                "generation": claimed["generation"],
                    "sanitized_inputs": ["password=hunter2"],
                    "token_output_limit": 16,
                    "deadline": "2099-01-01T00:00:00+00:00",
                    "intent_hash": frozen.intent_hash,
                },
                idempotency_key=f"secret-{attempt_id}",
            )
        assert secret_plain.value.status_code == 403

        foreign = str(uuid4())
        with pytest.raises(WorkerHttpError) as foreign_project:
            client.request_model(
                project_id=foreign,
                item_id=attempt_id,
                payload={
                    "call_id": str(uuid4()),
                    "purpose": "recording",
                    "role": "authoring",
                    "owner_kind": "authoring",
                    "owner_id": attempt_id,
                    "binding_revision": 1,
                "generation": claimed["generation"],
                    "sanitized_inputs": ["ok"],
                    "token_output_limit": 16,
                    "deadline": "2099-01-01T00:00:00+00:00",
                },
                idempotency_key=f"foreign-{attempt_id}",
            )
        assert foreign_project.value.status_code == 403
