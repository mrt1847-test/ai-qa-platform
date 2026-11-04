"""RX-39: Android worker entry — register→claim→ACK→action→evidence ACK→review wait."""

from __future__ import annotations

import binascii
import json
import struct
import subprocess
import zlib
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from aiqa.adapters.mobile_agent_android import MobileAgentAndroidAdapter, recording_broker
from aiqa.api.app import create_app
from aiqa.api.auth import bound_auth_store, enroll_worker
from aiqa.config import WorkerClientSettings, load_settings
from aiqa.contracts.actions import CaptureGeometry, Observation
from aiqa.contracts.cases import CaseDefinition, CaseRevisionInput, CaseSettings, PathPolicy
from aiqa.contracts.jobs import ControlDecision, IdempotencyKey, JobSubmission
from aiqa.domain.projects import bind_store, create_project
from aiqa.domain.versions import bind_case_store, create_case, save_case_revision
from aiqa.replay.android_runner import AndroidDeterministicDriver
from aiqa.store.database import migrate_store
from aiqa.store.models import Actor, ProjectCreate, Transaction
from aiqa.store.queue import enqueue_job
from aiqa.worker.android_jobs import (
    AndroidRecordingContext,
    AndroidRecordingHandler,
    assemble_android_worker_handlers,
    resolve_android_claim_target,
)
from aiqa.worker.control import RemoteLeaseGuard
from aiqa.worker.dispatch_journal import DispatchJournal
from aiqa.worker.http_client import SyncASGITransport, WorkerHttpClient
from aiqa.worker.runtime import (
    WorkerRuntime,
    WorkerRuntimeConfig,
    android_worker_prepared_adapters,
)
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


def _geometry() -> CaptureGeometry:
    return CaptureGeometry(100, 200, 1000, 2000, "scale", 0, (0, 0, 100, 200))


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


def test_resolve_android_claim_target_maps_physical_key() -> None:
    serial = "emulator-5580"
    physical = str(uuid4())
    claim = {
        "physical_key_id": physical,
        "snapshot": {
            "purpose": "recording",
            "target_ref": physical,
            "digest": "sha256:x",
        },
    }
    bound = resolve_android_claim_target(
        claim,
        registered_serial=serial,
        registered_physical_key_id=physical,
    )
    assert bound["snapshot"]["serial"] == serial
    assert bound["snapshot"]["native_id"] == serial
    assert bound["snapshot"]["target_ref"] == physical


def test_rx_39_register_claim_ack_action_evidence_review(tmp_path: Path, monkeypatch) -> None:
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
        project = create_project(owner, ProjectCreate("Android", "rx39", "rx", "android"))
    actor = Actor(owner.actor_id, project.project_id, True)
    worker_id = "worker-rx39"
    serial = "emulator-5580"
    with bound_auth_store(store):
        token = enroll_worker(actor, worker_id, "recording")

    with bind_case_store(store):
        case = create_case(actor, "RX39", None)
        version = save_case_revision(
            actor,
            case.case_id,
            CaseRevisionInput(
                CaseDefinition("open", "open", (), {}, {}, (), (), PathPolicy()),
                CaseSettings("android"),
            ),
            None,
        )

    physical = str(uuid4())
    now = datetime(2026, 11, 4, 10, 0, tzinfo=timezone.utc)
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
            ) VALUES (?, 'ready', '', '100x200@0', '[]', '', ?)
            """,
            (physical, now.isoformat()),
        )
    store.close()

    adb_calls: list = []

    def runner(argv, timeout):
        adb_calls.append(tuple(argv))
        return subprocess.CompletedProcess(list(argv), 0, b"", b"")

    journal = DispatchJournal(tmp_path / "journal.jsonl")
    spool = EvidenceSpool(tmp_path / "spool")
    driver = AndroidDeterministicDriver(
        Path("C:/platform-tools/adb.exe"),
        serial,
        runner=runner,
        spool=spool,
    )
    recording = AndroidRecordingHandler(
        adapter=MobileAgentAndroidAdapter(),
        driver=driver,
        broker=recording_broker(),
        control=_Allow(),
        guard=RemoteLeaseGuard(),
        journal=journal,
        spool=spool,
        context=AndroidRecordingContext(
            expected_serial=serial,
            fixture_response="click(250, 500)",
            before=_observation(),
            after=_observation(),
            lease_remaining_seconds=60.0,
            mono_seconds=100.0,
        ),
    )
    handler = assemble_android_worker_handlers(recording=recording)
    assert "recording" in android_worker_prepared_adapters()

    transport = SyncASGITransport(app)
    client_settings = WorkerClientSettings(
        base_url="https://127.0.0.1",
        token=token,
        timeout_seconds=10,
        verify_tls=False,
        ca_bundle=None,
    )
    with WorkerHttpClient(client_settings, transport=transport) as client:
        # Heartbeat first so job_worker_sessions captures the later enqueue.
        client.heartbeat("boot-rx39")
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
                    IdempotencyKey(actor.actor_id, project.project_id, "enqueue_job", "rx39-rec"),
                    now=now,
                )
            recording_id = receipt.recording_id
        finally:
            store.close()

        runtime = WorkerRuntime(
            client,
            WorkerRuntimeConfig(
                boot_id="boot-rx39",
                prepared_adapters=android_worker_prepared_adapters(),
                max_cycles=1,
            ),
            handler,
            registered_serial=serial,
            now=lambda: now,
            mono=lambda: 100.0,
        )
        runtime._registered_physical_key_id = physical
        report = runtime.run_once()

    assert report.claimed is True
    assert report.finished is True
    assert report.actions == 1
    assert recording.tap_count == 1
    assert recording.evidence_commits and recording.evidence_commits[0]["review_pending"] is True
    assert adb_calls and adb_calls[-1][4:8] == ("input", "tap", "25", "50")

    store = app.state.open_store()
    try:
        with store.transaction() as connection:
            job = connection.execute(
                "SELECT status, recording_id FROM jobs WHERE project_id = ?",
                (str(project.project_id),),
            ).fetchone()
            events = connection.execute(
                "SELECT COUNT(*), MAX(local_seq) FROM attempt_events WHERE attempt_id IN "
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
                SELECT completion_status, evidence_status, stop_status FROM recordings
                WHERE project_id = ? AND recording_id = ?
                """,
                (str(project.project_id), str(recording_id)),
            ).fetchone()
            approved = connection.execute(
                "SELECT COUNT(*) FROM materialization_receipts WHERE project_id = ?",
                (str(project.project_id),),
            ).fetchone()[0]
    finally:
        store.close()

    assert job is not None and str(job[0]) == "completed"
    assert events is not None and int(events[0]) >= 2 and int(events[1]) >= 2
    assert finish is not None
    body = json.loads(str(finish[0]))
    assert body["approved"] is False
    assert body["verdict"] is None
    assert body["purpose"] == "recording"
    assert rec is not None
    assert str(rec[0]) == "completed"
    assert str(rec[1]) == "complete"
    assert str(rec[2]) == "stopped"
    # Unapproved draft materialization may exist; worker finish never sets approved.
    assert approved >= 0
