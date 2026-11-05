"""RX-46: same-PC Android preflight — operational mock HTTPS authoring + approved replay."""

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
from aiqa.api.app import create_app
from aiqa.api.auth import bound_auth_store, enroll_worker
from aiqa.config import WorkerClientSettings, load_settings
from aiqa.contracts.actions import CaptureGeometry, Observation
from aiqa.contracts.jobs import ControlDecision
from aiqa.contracts.models import OwnedCheck, RoleBinding
from aiqa.domain.projects import bind_store, create_project
from aiqa.models.broker import ModelBroker, ModelTransport, recording_authoring_policy
from aiqa.models.provider_http import OperationalProviderHttp
from aiqa.replay.android_runner import AndroidDeterministicDriver
from aiqa.security.secrets import (
    MemorySecretBackend,
    bind_secret_store,
    build_server_secret_resolver,
)
from aiqa.store.database import migrate_store
from aiqa.store.models import Actor, ProjectCreate, SecretInput, SecretRef
from aiqa.worker.android_jobs import (
    AndroidRecordingContext,
    AndroidRecordingHandler,
    AndroidReplayContext,
    AndroidReplayHandler,
    assemble_android_worker_handlers,
    server_model_plan_provider,
)
from aiqa.worker.control import RemoteLeaseGuard
from aiqa.worker.dispatch_journal import DispatchJournal
from aiqa.worker.http_client import SyncASGITransport, WorkerHttpClient
from aiqa.worker.spool import EvidenceSpool

SWIPE_PLAN = "swipe(360, 1200, 360, 400, 300)"
APPROVED_DIGEST = "sha256:approved-rx46"


def _env(root: Path, **extra: str) -> dict[str, str]:
    values = {
        "AIQA_HOST": "127.0.0.1",
        "AIQA_PORT": "8000",
        "AIQA_RUNTIME_ROOT": str(root),
    }
    values.update(extra)
    return values


def _png(width: int = 720, height: int = 1600) -> bytes:
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


def _geometry() -> CaptureGeometry:
    return CaptureGeometry(720, 1600, 720, 1600, "identity", 0, (0, 0, 720, 1600))


def _observation() -> Observation:
    return Observation(
        str(uuid4()),
        datetime.now(timezone.utc).isoformat(),
        _geometry(),
        _png(),
        "",
        "[]",
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


class _QuietTransport(ModelTransport):
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, check_id: str) -> str:
        self.calls += 1
        return '{"status":"satisfied","reason":"ok"}'


def test_rx_46_operational_mock_https_authoring_and_approved_replay(tmp_path: Path) -> None:
    hits: list[str] = []

    def provider_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/complete"
        assert request.headers.get("Authorization") == "Bearer mock-ops-secret"
        body = json.loads(request.content.decode("utf-8"))
        hits.append(str(body.get("role")))
        role = str(body.get("role") or "")
        content = SWIPE_PLAN if role == "authoring" else json.dumps({"status": "satisfied"})
        return httpx.Response(
            200,
            json={
                "content": content,
                "provider_request_id": f"mock-{len(hits)}",
                "actual_model": body.get("model"),
            },
        )

    provider = OperationalProviderHttp(
        allow_live=True,
        base_url="https://provider.example",
        verify_tls=False,
        transport=httpx.MockTransport(provider_handler),
    )
    backend = MemorySecretBackend()
    settings = load_settings(
        _env(
            tmp_path / "runtime",
            AIQA_MODEL_PROVIDER_MODE="operational",
            AIQA_MODEL_PROVIDER_BASE_URL="https://provider.example",
            AIQA_MODEL_PROVIDER_VERIFY_TLS="0",
        )
    )
    app = create_app(settings, secret_backend=backend, model_provider=provider)
    assert getattr(app.state.model_gateway.provider, "kind") == "operational"

    store = app.state.open_store()
    migrate_store(store)
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("RX46", "rx46", "", "android"))
    actor = Actor(owner.actor_id, project.project_id, True)
    resolver = build_server_secret_resolver(settings, backend=backend)
    with bind_secret_store(store):
        created = resolver.put(actor, SecretInput(value="mock-ops-secret", name="authoring"))
        secret_ref = SecretRef(project.project_id, created.ref_id, created.revision)

    attempt_id = str(uuid4())
    app.state.model_gateway.ensure_policy(
        recording_authoring_policy(project.project_id, attempt_id, secret_ref)
    )

    worker_id = "worker-rx46"
    with bound_auth_store(store):
        token = enroll_worker(actor, worker_id, "recording")
    store.close()

    transport = SyncASGITransport(app)
    client_settings = WorkerClientSettings(
        base_url="https://127.0.0.1",
        token=token,
        timeout_seconds=10,
        verify_tls=False,
        ca_bundle=None,
    )

    adb_calls: list = []

    def runner(argv, timeout):
        adb_calls.append(tuple(argv))
        return subprocess.CompletedProcess(list(argv), 0, b"", b"")

    serial = "emulator-5580"
    with WorkerHttpClient(client_settings, transport=transport) as client:
        direct = client.request_model(
            project_id=str(project.project_id),
            item_id=attempt_id,
            payload={
                "call_id": str(uuid4()),
                "purpose": "recording",
                "role": "authoring",
                "owner_kind": "authoring",
                "owner_id": attempt_id,
                "binding_revision": 1,
                "sanitized_inputs": ["sanitized"],
                "token_output_limit": 64,
                "deadline": "2099-01-01T00:00:00+00:00",
            },
            idempotency_key=f"direct-{attempt_id}",
        )
        assert direct["allowed"] is True
        assert direct["content"] == SWIPE_PLAN
        assert "secret" not in direct
        assert hits == ["authoring"]

        recording = AndroidRecordingHandler(
            adapter=MobileAgentAndroidAdapter(),
            driver=AndroidDeterministicDriver(
                Path("C:/platform-tools/adb.exe"),
                serial,
                runner=runner,
                spool=EvidenceSpool(tmp_path / "spool"),
            ),
            broker=recording_broker(),
            control=_Allow(),
            guard=RemoteLeaseGuard(),
            journal=DispatchJournal(tmp_path / "journal.jsonl"),
            spool=EvidenceSpool(tmp_path / "spool"),
            context=AndroidRecordingContext(
                expected_serial=serial,
                fixture_response="",
                before=_observation(),
                after=_observation(),
                lease_remaining_seconds=60.0,
                mono_seconds=100.0,
                plan_provider=server_model_plan_provider(client),
            ),
        )
        claim = {
            "project_id": str(project.project_id),
            "job_id": str(uuid4()),
            "attempt_id": attempt_id,
            "generation": 1,
            "snapshot": {
                "purpose": "recording",
                "serial": serial,
                "action_id": "rec-1",
            },
        }
        # Fresh attempt id for a second authoring admission under the same policy item
        # would need a new policy; reuse the same attempt so gateway quota admits once more
        # via a new call_id (max_calls=2).
        result = recording.handle(claim)
        assert result.actions == 1
        assert result.outcome == "completed"
        assert result.review_pending is True
        assert recording.authoring_calls_seen == 1
        # Same role/inputs reuse the operational provider's idempotent cache (no second HTTP).
        assert hits == ["authoring"]
        assert provider.call_count == 2
        assert adb_calls and "swipe" in adb_calls[-1]

        replay_calls: list = []

        def replay_runner(argv, timeout):
            replay_calls.append(tuple(argv))
            return subprocess.CompletedProcess(list(argv), 0, b"", b"")

        verify_broker = ModelBroker(
            "replay-1",
            (
                RoleBinding("verification", 1, "fixture-v", "ref"),
                RoleBinding("healing", 1, "fixture-h", "ref"),
            ),
            (OwnedCheck("check-1", "replay-1"),),
            (),
        )
        replay = AndroidReplayHandler(
            adapter=MobileAgentAndroidAdapter(),
            driver=AndroidDeterministicDriver(
                Path("C:/platform-tools/adb.exe"),
                serial,
                runner=replay_runner,
                spool=EvidenceSpool(tmp_path / "replay-spool"),
            ),
            broker=recording_broker("replay-1"),
            guard=RemoteLeaseGuard(),
            journal=DispatchJournal(tmp_path / "replay-journal.jsonl"),
            spool=EvidenceSpool(tmp_path / "replay-spool"),
            context=AndroidReplayContext(
                expected_serial=serial,
                approved_digest=APPROVED_DIGEST,
                approved_plan=SWIPE_PLAN,
                before=_observation(),
                after=_observation(),
                lease_remaining_seconds=60.0,
                mono_seconds=100.0,
                healing_enabled=False,
                heal_budget_remaining=0,
                checks=(),
                verify_broker=verify_broker,
                verify_transport=_QuietTransport(),
                verify_control=_Allow(),
            ),
        )
        routed = assemble_android_worker_handlers(recording=recording, replay=replay)
        replay_result = routed.handle(
            {
                "project_id": str(project.project_id),
                "job_id": str(uuid4()),
                "attempt_id": str(uuid4()),
                "generation": 1,
                "snapshot": {
                    "purpose": "trial",
                    "serial": serial,
                    "digest": APPROVED_DIGEST,
                    "action_id": "trial-1",
                },
            }
        )
        assert replay_result.actions == 1
        assert replay_result.outcome == "completed"
        assert replay.authoring_calls_seen == 0
        assert replay.dispatch_count == 1
        assert replay_calls and "swipe" in replay_calls[-1]
        # Approved replay must not call the operational provider again.
        assert hits == ["authoring"]
        assert provider.call_count == 2
