"""RX-61: Web recording + approved package replay common contract."""

from __future__ import annotations

import binascii
import json
import struct
import zlib
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from aiqa.adapters.cuawright_web import (
    CuawrightWebAdapter,
    local_web_fixture,
    load_web_contract_package,
)
from aiqa.api.app import create_app
from aiqa.api.auth import bound_auth_store, enroll_worker
from aiqa.config import load_settings
from aiqa.contracts.actions import CaptureGeometry, Observation
from aiqa.contracts.cases import CaseDefinition, CaseRevisionInput, CaseSettings, PathPolicy
from aiqa.contracts.checks import CheckSpec
from aiqa.contracts.jobs import ControlDecision, IdempotencyKey, JobSubmission
from aiqa.contracts.models import ModelRequest, OwnedCheck, OwnedEpisode, RoleBinding
from aiqa.domain.projects import bind_store, create_project
from aiqa.domain.versions import bind_case_store, create_case, save_case_revision
from aiqa.healing.targets import HealingContext
from aiqa.models.broker import ModelBroker, ModelTransport
from aiqa.replay.driver import ApprovedWebPackage
from aiqa.store.database import migrate_store
from aiqa.store.models import Actor, ProjectCreate, Transaction
from aiqa.store.queue import enqueue_job
from aiqa.worker.control import RemoteLeaseGuard
from aiqa.worker.dispatch_journal import DispatchJournal
from aiqa.worker.isolated_web import bind_web_vm_transport, require_web_ready
from aiqa.worker.runner import verify_and_heal_after_replay
from aiqa.worker.spool import EvidenceSpool
from aiqa.worker.web_isolation_backend import (
    IsolationConfig,
    IsolationProof,
    WebIsolationGate,
    fixture_backend,
)
from aiqa.worker.web_jobs import (
    WebRecordingContext,
    WebRecordingHandler,
    WebReplayContext,
    WebReplayHandler,
    assemble_web_worker_handlers,
    resolve_web_claim_origin,
)
from aiqa.worker.web_vm_transport import spawn_local_guest_process

ORIGIN = "https://app.example.test"
ENDPOINT = "guest-ipc://web-rx61"
PEER = "rx61-peer-token-ok"
SECRET = b"rx61-fixture-proof!!!!"


class _Script(ModelTransport):
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, check_id: str) -> str:
        self.calls += 1
        return '{"status":"satisfied","reason":"ok"}'


class _Allow:
    def checkpoint(self) -> ControlDecision:
        return ControlDecision(True, "before_model")

    def allow_model_action(self, *, late: bool) -> ControlDecision:
        return ControlDecision(not late, "before_model")


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


def _checks() -> tuple[CheckSpec, ...]:
    return (CheckSpec("check-1", "text", "Go", subject="#go", method="deterministic"),)


def _heal_context(digest: str) -> HealingContext:
    request = ModelRequest(
        uuid4(),
        "healing",
        "episode",
        "episode-1",
        1,
        (),
        20,
        "2026-11-05T00:00:00+00:00",
        None,
        "episode-1",
    )
    payload = {
        "basis": "typed",
        "role": "button",
        "name": "Go",
        "container": "main",
        "resource_id": "id.go",
        "text": "Go",
        "context": "main",
        "locator": "#go",
        "action": "click",
        "input": "",
        "path": "/",
        "coordinates": [1, 1],
        "approved_digest": digest,
    }
    return HealingContext(
        "button",
        "Go",
        "main",
        "id.go",
        "Go",
        "main",
        "#go",
        "click",
        "",
        "/",
        request,
        payload,
    )


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


def _observation() -> Observation:
    return Observation(
        str(uuid4()),
        datetime.now(timezone.utc).isoformat(),
        CaptureGeometry(24, 48, 24, 48, "identity", 0, (0, 0, 24, 48)),
        _png(),
        json.dumps({"nodes": [{"locator": "#go", "text": "Go", "value": "", "state": "visible"}]}),
        "",
        (),
        "",
        True,
        "web",
    )


def test_rx_61_local_fixture_two_actions_package_pin_actor0_and_proof(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 11, 5, 20, 0, tzinfo=timezone.utc)
    fixture = local_web_fixture(origin=ORIGIN)
    assert "id='go'" in fixture.page_html
    assert len(fixture.trajectory["steps"]) == 2  # type: ignore[arg-type]

    gate = WebIsolationGate(
        IsolationConfig(
            backend=fixture_backend(allowed_origins=(ORIGIN,)),
            proof_secret=SECRET,
        )
    )
    proof = gate.issue_proof(now=now)
    guest = spawn_local_guest_process(endpoint_id=ENDPOINT, peer_token=PEER)
    package_root = tmp_path / "packages"
    try:
        transport = bind_web_vm_transport(
            gate,
            approved_endpoints=(ENDPOINT,),
            bindings=(guest.binding,),
        )
        recording = WebRecordingHandler(
            adapter=CuawrightWebAdapter(),
            transport=transport,
            gate=gate,
            guard=RemoteLeaseGuard(),
            journal=DispatchJournal(tmp_path / "journal.jsonl"),
            spool=EvidenceSpool(tmp_path / "spool"),
            context=WebRecordingContext(
                approved_origin=ORIGIN,
                trajectory=fixture.trajectory,
                before=_observation(),
                after=_observation(),
                proof=proof,
                now=now,
                guest_process=guest,
                endpoint_id=ENDPOINT,
                package_root=package_root,
                package_id="pkg-rx61",
            ),
        )
        claim = {
            "attempt_id": str(uuid4()),
            "snapshot": {
                "purpose": "recording",
                "origin": ORIGIN,
                "revision": "lock-1",
                "action_id": "rec-1",
            },
        }
        recorded = recording.handle(claim)
        assert recorded.actions == 2
        assert recorded.outcome == "completed"
        assert recording.authoring_dispatches == 2
        assert len(recording.persisted_packages) == 1
        package = recording.persisted_packages[0]
        assert package.package_id == "pkg-rx61"
        assert len(package.step_code_digests) == 2
        assert package.evidence_before and package.evidence_after
        assert (package_root / "pkg-rx61.json").is_file()
        loaded = load_web_contract_package(package_root, "pkg-rx61")
        assert loaded.digest == package.digest
        assert recorded.source_artifact_hashes[:2] == package.step_code_digests
    finally:
        guest.terminate()

    # Unverified proof → zero actions (fresh guest; forged proof never reaches IPC).
    forged = IsolationProof(
        backend="fixture",
        issued_at=now.isoformat(),
        expires_at=now.isoformat(),
        scope_hash=gate.config.scope_hash,
        nonce="bad",
        token="sha256:" + ("0" * 64),
    )
    assert require_web_ready(gate.web_ready(forged, now=now)) is False
    guest2 = spawn_local_guest_process(endpoint_id=ENDPOINT, peer_token=PEER)
    try:
        bad_recording = WebRecordingHandler(
            adapter=CuawrightWebAdapter(),
            transport=bind_web_vm_transport(
                gate,
                approved_endpoints=(ENDPOINT,),
                bindings=(guest2.binding,),
            ),
            gate=gate,
            guard=RemoteLeaseGuard(),
            journal=DispatchJournal(tmp_path / "journal-bad.jsonl"),
            spool=EvidenceSpool(tmp_path / "spool-bad"),
            context=WebRecordingContext(
                approved_origin=ORIGIN,
                trajectory=fixture.trajectory,
                before=_observation(),
                after=_observation(),
                proof=forged,
                now=now,
                guest_process=guest2,
                endpoint_id=ENDPOINT,
            ),
        )
        denied = bad_recording.handle(
            {
                "attempt_id": str(uuid4()),
                "snapshot": {
                    "purpose": "recording",
                    "origin": ORIGIN,
                    "revision": "lock-1",
                    "action_id": "rec-bad",
                },
            }
        )
        assert denied.actions == 0
        assert bad_recording.authoring_dispatches == 0
    finally:
        guest2.terminate()

    # Shared Check/healing port (RX-54) remains the only verify entry for Web replay.
    shared = verify_and_heal_after_replay(
        checks=_checks(),
        observation=_observation(),
        control=_Allow(),
        broker=_broker(),
        transport=_Script(),
        healing_enabled=False,
        heal_budget_remaining=0,
        approved_failure_reason=None,
        healable_check_id="check-1",
        approved_package_digest=package.digest,
        healing_context=_heal_context(package.digest),
    )
    assert shared.success is True
    assert shared.record.healer_calls == 0
    assert shared.record.package_digest_after == package.digest

    from aiqa.worker.local_page import local_page_from_fixture_html

    page = local_page_from_fixture_html(origin=ORIGIN)

    def _replay(purpose: str) -> WebReplayHandler:
        return WebReplayHandler(
            adapter=CuawrightWebAdapter(),
            gate=gate,
            guard=RemoteLeaseGuard(),
            journal=DispatchJournal(tmp_path / f"journal-{purpose}.jsonl"),
            spool=EvidenceSpool(tmp_path / f"spool-{purpose}"),
            context=WebReplayContext(
                approved=ApprovedWebPackage(package.digest, package.revision, ORIGIN),
                bundle_source={"complete": True, "steps": []},
                before=_observation(),
                after=_observation(),
                proof=proof,
                now=now,
                package_root=package_root,
                checks=_checks(),
                verify_broker=_broker(),
                verify_transport=_Script(),
                verify_control=_Allow(),
                healing_enabled=False,
                healing_context=_heal_context(package.digest),
                runner=page.as_runner(),
            ),
        )

    trial = _replay("trial")
    trial_result = trial.handle(
        {
            "attempt_id": str(uuid4()),
            "snapshot": {
                "purpose": "trial",
                "origin": ORIGIN,
                "revision": package.revision,
                "replay_package_id": package.package_id,
                "replay_package_hash": package.digest,
                "approved_digest": package.digest,
                "live_source": package.reviewable_source,
            },
        }
    )
    assert trial_result.actions == 2
    assert trial.actor_ai_calls == 0
    assert trial.package_digest_after == package.digest
    assert trial.healer_calls == 0

    regression = _replay("regression")
    reg_result = regression.handle(
        {
            "attempt_id": str(uuid4()),
            "snapshot": {
                "purpose": "regression",
                "origin": ORIGIN,
                "revision": package.revision,
                "replay_package_id": package.package_id,
                "replay_package_hash": package.digest,
                "approved_digest": package.digest,
                "live_source": package.reviewable_source,
            },
        }
    )
    assert reg_result.actions == 2
    assert regression.actor_ai_calls == 0
    assert regression.package_digest_after == package.digest

    pinned = _replay("pin")
    bad_pin = pinned.handle(
        {
            "attempt_id": str(uuid4()),
            "snapshot": {
                "purpose": "trial",
                "origin": ORIGIN,
                "revision": package.revision,
                "replay_package_id": package.package_id,
                "replay_package_hash": "sha256:" + ("f" * 64),
                "live_source": package.reviewable_source,
            },
        }
    )
    assert bad_pin.actions == 0


def test_rx_61_claim_origin_fixed_on_server_job(tmp_path: Path, monkeypatch) -> None:
    import asyncio

    root = tmp_path / "runtime"
    settings = load_settings(
        {"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}
    )
    app = create_app(settings)
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("Web61", "rx61", "rx", "web"))
    actor = Actor(owner.actor_id, project.project_id, True)
    worker_id = f"worker-rx61-{uuid4()}"
    with bound_auth_store(store):
        token = enroll_worker(actor, worker_id, "recording")
    with bind_case_store(store):
        case = create_case(actor, "RX61", None)
        version = save_case_revision(
            actor,
            case.case_id,
            CaseRevisionInput(
                CaseDefinition("open", "open", (), {}, {}, (), (), PathPolicy()),
                CaseSettings("web"),
            ),
            None,
        )
    physical = str(uuid4())
    now = datetime(2026, 11, 5, 20, 30, tzinfo=timezone.utc)
    monkeypatch.setattr("aiqa.api.worker._server_now", lambda: now)
    with store.transaction() as connection:
        connection.execute(
            "INSERT INTO physical_resource_keys (physical_key_id, worker_id, native_id) VALUES (?, ?, ?)",
            (physical, worker_id, "web-fixture"),
        )
        connection.execute(
            """
            INSERT INTO resource_aliases (
                project_id, physical_key_id, display_name, target_kind, alias_id
            ) VALUES (?, ?, ?, 'web', ?)
            """,
            (str(project.project_id), physical, "Web", str(uuid4())),
        )
        connection.execute(
            """
            INSERT INTO resource_inventory (
                physical_key_id, state, os_build, geometry, permissions, ime, observed_at
            ) VALUES (?, 'ready', '', '', '[]', '', ?)
            """,
            (physical, now.isoformat()),
        )
    store.close()

    async def _claim() -> dict[str, object]:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            assert (
                await client.post(
                    "/api/v1/worker/heartbeats",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"boot_id": "boot-rx61"},
                )
            ).status_code == 200
            # Enqueue after heartbeat so presence + session pin are ready.
            store2 = app.state.open_store()
            try:
                with store2.transaction() as connection:
                    enqueue_job(
                        Transaction(connection),
                        JobSubmission(
                            project.project_id,
                            "recording",
                            case.case_id,
                            version.id,
                            (physical,),
                            json.dumps({"origin": ORIGIN}),
                        ),
                        IdempotencyKey(
                            actor.actor_id, project.project_id, "enqueue_job", "rx61-origin"
                        ),
                        now=now,
                    )
            finally:
                store2.close()
            claimed = await client.post(
                "/api/v1/worker/claims",
                headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "rx61-claim"},
                json={"boot_id": "boot-rx61", "now": now.isoformat()},
            )
            assert claimed.status_code == 200, claimed.text
            return claimed.json()

    body = asyncio.run(_claim())
    assert body["snapshot"]["origin"] == ORIGIN
    bound = resolve_web_claim_origin(
        {"attempt_id": body["attempt_id"], "snapshot": {"purpose": "recording"}},
        approved_origin=ORIGIN,
    )
    assert bound["snapshot"]["origin"] == ORIGIN
    handlers = assemble_web_worker_handlers()
    assert handlers is not None
