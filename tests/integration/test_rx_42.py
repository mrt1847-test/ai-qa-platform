"""RX-42: Web worker entry — fixture guest recording, evidence ACK, proof-less zero actions."""

from __future__ import annotations

import binascii
import json
import struct
import zlib
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from aiqa.adapters.cuawright_web import CuawrightWebAdapter
from aiqa.api.app import create_app
from aiqa.api.auth import bound_auth_store, enroll_worker
from aiqa.config import WorkerClientSettings, load_settings
from aiqa.contracts.actions import CaptureGeometry, Observation
from aiqa.contracts.cases import CaseDefinition, CaseRevisionInput, CaseSettings, PathPolicy
from aiqa.contracts.jobs import IdempotencyKey, JobSubmission
from aiqa.domain.projects import bind_store, create_project
from aiqa.domain.versions import bind_case_store, create_case, save_case_revision
from aiqa.store.database import migrate_store
from aiqa.store.models import Actor, ProjectCreate, Transaction
from aiqa.store.queue import enqueue_job
from aiqa.worker.control import RemoteLeaseGuard
from aiqa.worker.dispatch_journal import DispatchJournal
from aiqa.worker.http_client import SyncASGITransport, WorkerHttpClient
from aiqa.worker.isolated_web import bind_web_vm_transport
from aiqa.worker.runtime import WorkerRuntime, WorkerRuntimeConfig, web_worker_prepared_adapters
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
    assemble_web_worker_handlers,
)
from aiqa.worker.web_vm_transport import load_web_guest_entry_binding, spawn_local_guest_process

ORIGIN = "https://app.example.test"
ENDPOINT = "guest-ipc://web-rx42"
PEER = "rx42-peer-token"


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
        "<button id='go'>Go</button>",
        "",
        (),
        "",
        True,
        "web",
    )


def _trajectory() -> dict[str, object]:
    return {
        "complete": True,
        "steps": [
            {
                "hook": "hook.web.code_output.step_script",
                "code": "qa_runtime.click('#go')",
                "summary": {"type": "click", "selector": "#go"},
            }
        ],
    }


def test_load_web_guest_entry_binding() -> None:
    assert load_web_guest_entry_binding({}) is None
    bound = load_web_guest_entry_binding(
        {
            "AIQA_WEB_GUEST_ENDPOINT": ENDPOINT,
            "AIQA_WEB_GUEST_PEER_TOKEN": PEER,
            "AIQA_WEB_APPROVED_ORIGIN": ORIGIN,
        }
    )
    assert bound is not None
    assert bound.endpoint_id == ENDPOINT
    assert bound.approved_origin == ORIGIN
    assert "recording" in web_worker_prepared_adapters()


def test_rx_42_fixture_guest_recording_evidence_and_no_proof_zero(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "runtime"
    root.mkdir()
    settings = load_settings(
        {"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}
    )
    app = create_app(settings)
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("Web", "rx42", "rx", "web"))
    actor = Actor(owner.actor_id, project.project_id, True)
    worker_id = "worker-rx42"
    with bound_auth_store(store):
        token = enroll_worker(actor, worker_id, "recording")

    with bind_case_store(store):
        case = create_case(actor, "RX42", None)
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
    now = datetime(2026, 11, 4, 19, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("aiqa.api.worker._server_now", lambda: now)
    with store.transaction() as connection:
        connection.execute(
            "INSERT INTO physical_resource_keys (physical_key_id, worker_id, native_id) VALUES (?, ?, ?)",
            (physical, worker_id, "web-fixture"),
        )
        connection.execute(
            "INSERT INTO resource_aliases (project_id, physical_key_id, display_name, target_kind) VALUES (?, ?, ?, ?)",
            (str(project.project_id), physical, "WebGuest", "web"),
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

    gate = WebIsolationGate(
        IsolationConfig(
            backend=fixture_backend(allowed_origins=(ORIGIN,)),
            proof_secret=b"rx42-fixture-secret!!",
        )
    )
    proof = gate.issue_proof(now=now)
    guest = spawn_local_guest_process(endpoint_id=ENDPOINT, peer_token=PEER)
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
                trajectory=_trajectory(),
                before=_observation(),
                after=_observation(),
                proof=proof,
                now=now,
                guest_process=guest,
                endpoint_id=ENDPOINT,
            ),
        )
        handler = assemble_web_worker_handlers(recording=recording)

        client_settings = WorkerClientSettings(
            base_url="https://127.0.0.1",
            token=token,
            timeout_seconds=10,
            verify_tls=False,
            ca_bundle=None,
        )
        with WorkerHttpClient(client_settings, transport=SyncASGITransport(app)) as client:
            client.heartbeat("boot-rx42")
            store = app.state.open_store()
            try:
                with store.transaction() as connection:
                    receipt = enqueue_job(
                        Transaction(connection),
                        JobSubmission(
                            project.project_id,
                            "recording",
                            case.case_id,
                            version.id,
                            (physical,),
                            "{}",
                        ),
                        IdempotencyKey(
                            actor.actor_id, project.project_id, "enqueue_job", "rx42-rec"
                        ),
                        now=now,
                    )
                recording_id = receipt.recording_id
            finally:
                store.close()

            runtime = WorkerRuntime(
                client,
                WorkerRuntimeConfig(
                    boot_id="boot-rx42",
                    prepared_adapters=web_worker_prepared_adapters(),
                    max_cycles=1,
                ),
                handler,
                approved_web_origin=ORIGIN,
                now=lambda: now,
                mono=lambda: 100.0,
            )
            report = runtime.run_once()

        assert report.claimed is True
        assert report.finished is True
        assert report.actions == 1
        assert recording.authoring_dispatches == 1
        assert recording.evidence_commits and recording.evidence_commits[0]["review_pending"] is True

        store = app.state.open_store()
        try:
            with store.transaction() as connection:
                events = connection.execute(
                    "SELECT COUNT(*) FROM attempt_events WHERE attempt_id IN "
                    "(SELECT attempt_id FROM attempts WHERE project_id = ?)",
                    (str(project.project_id),),
                ).fetchone()
                finish = connection.execute(
                    """
                    SELECT response_body FROM attempt_finish_requests
                    WHERE project_id = ?
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (str(project.project_id),),
                ).fetchone()
                rec = connection.execute(
                    """
                    SELECT completion_status, evidence_status FROM recordings
                    WHERE project_id = ? AND recording_id = ?
                    """,
                    (str(project.project_id), str(recording_id)),
                ).fetchone()
        finally:
            store.close()

        assert events is not None and int(events[0]) >= 2
        assert finish is not None
        body = json.loads(str(finish[0]))
        assert body["approved"] is False
        assert body["verdict"] is None
        assert rec is not None and str(rec[0]) == "completed" and str(rec[1]) == "complete"
    finally:
        guest.terminate()

    # Proof-less / forged proof → zero target actions (guest may still spawn).
    bad_proof = IsolationProof(
        backend=proof.backend,
        issued_at=proof.issued_at,
        expires_at=proof.expires_at,
        scope_hash=proof.scope_hash,
        nonce=proof.nonce,
        token="sha256:" + ("d" * 64),
    )
    guest_b = spawn_local_guest_process(endpoint_id=ENDPOINT, peer_token=PEER)
    try:
        transport_b = bind_web_vm_transport(
            gate,
            approved_endpoints=(ENDPOINT,),
            bindings=(guest_b.binding,),
        )
        denied = WebRecordingHandler(
            adapter=CuawrightWebAdapter(),
            transport=transport_b,
            gate=gate,
            guard=RemoteLeaseGuard(),
            journal=DispatchJournal(tmp_path / "bad-journal.jsonl"),
            spool=EvidenceSpool(tmp_path / "bad-spool"),
            context=WebRecordingContext(
                approved_origin=ORIGIN,
                trajectory=_trajectory(),
                before=_observation(),
                after=_observation(),
                proof=bad_proof,
                now=now,
                guest_process=guest_b,
                endpoint_id=ENDPOINT,
            ),
        )
        result = denied.handle(
            {
                "attempt_id": str(uuid4()),
                "snapshot": {
                    "purpose": "recording",
                    "origin": ORIGIN,
                    "revision": "lock-1",
                    "action_id": "no-proof",
                    "endpoint_id": ENDPOINT,
                },
            }
        )
        assert result.actions == 0
        assert result.outcome == "error"
        assert denied.authoring_dispatches == 0
        assert denied.evidence_commits == []
    finally:
        guest_b.terminate()
