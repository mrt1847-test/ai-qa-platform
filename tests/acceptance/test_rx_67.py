"""RX-67: per-step evidence ACK appears on the live recording timeline before finish."""

from __future__ import annotations

import asyncio
import binascii
import sqlite3
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
)
from aiqa.worker.control import RemoteLeaseGuard
from aiqa.worker.dispatch_journal import DispatchJournal
from aiqa.worker.http_client import SyncASGITransport, WorkerHttpClient
from aiqa.worker.runtime import WorkerRuntime, WorkerRuntimeConfig, android_worker_prepared_adapters
from aiqa.worker.spool import EvidenceSpool
from ux_support import session

_BROWSERS = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
)


def _png(width: int = 100, height: int = 200, fill: bytes = b"\xff\x00\x00") -> bytes:
    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body))
            + kind
            + body
            + struct.pack(">I", binascii.crc32(kind + body) & 0xFFFFFFFF)
        )

    row = b"\x00" + fill * width
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(row * height))
        + chunk(b"IEND", b"")
    )


def _geometry() -> CaptureGeometry:
    return CaptureGeometry(100, 200, 1000, 2000, "scale", 0, (0, 0, 100, 200))


def _observation(*, fill: bytes = b"\xff\x00\x00", captured_at: str | None = None) -> Observation:
    return Observation(
        str(uuid4()),
        captured_at or datetime.now(timezone.utc).isoformat(),
        _geometry(),
        _png(fill=fill),
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


def _artifact_bytes(database: Path, artifacts_dir: Path, project_id: str, role: str) -> bytes:
    connection = sqlite3.connect(database)
    try:
        row = connection.execute(
            """
            SELECT object_key, byte_length FROM artifact_objects
            WHERE project_id = ? AND role = ? AND status = 'ready' AND acked = 1
            ORDER BY stored_at LIMIT 1
            """,
            (project_id, role),
        ).fetchone()
    finally:
        connection.close()
    assert row is not None
    body = (artifacts_dir / str(row[0])).read_bytes()
    assert len(body) == int(row[1])
    return body


def _find_browser() -> Path | None:
    return next((path for path in _BROWSERS if path.is_file()), None)


async def _browser_shot(html_path: Path, out: Path) -> None:
    browser = _find_browser()
    if browser is None:
        return
    proc = await asyncio.create_subprocess_exec(
        str(browser),
        "--headless=new",
        "--disable-gpu",
        f"--screenshot={out}",
        "--window-size=1280,900",
        html_path.resolve().as_uri(),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await asyncio.wait_for(proc.wait(), timeout=30)
    assert out.is_file() and out.stat().st_size > 1024


def test_rx_67_step_ack_timeline_retransmit_and_prefix(tmp_path: Path, monkeypatch) -> None:
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
        project = create_project(owner, ProjectCreate("타임라인", "rx67", "rx", "android"))
    actor = Actor(owner.actor_id, project.project_id, True)
    worker_id = "worker-rx67"
    serial = "emulator-5580"
    with bound_auth_store(store):
        token = enroll_worker(actor, worker_id, "recording")

    with bind_case_store(store):
        case = create_case(actor, "RX67", None)
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
    now = datetime(2026, 11, 5, 18, 0, tzinfo=timezone.utc)
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
    artifacts_dir = store.config.artifacts_dir
    store.close()

    calls: list = []

    def runner(argv, timeout):
        calls.append(tuple(argv))
        return subprocess.CompletedProcess(list(argv), 0, b"", b"")

    before1 = _observation(fill=b"\xff\x00\x00", captured_at="2026-11-05T18:00:01+00:00")
    after1 = _observation(fill=b"\x00\xff\x00", captured_at="2026-11-05T18:00:02+00:00")
    before2 = _observation(fill=b"\x00\x00\xff", captured_at="2026-11-05T18:00:03+00:00")
    after2 = _observation(fill=b"\xff\xff\x00", captured_at="2026-11-05T18:00:04+00:00")
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
        spool=EvidenceSpool(tmp_path / "handler-spool"),
        context=AndroidRecordingContext(
            expected_serial=serial,
            fixture_response="",
            fixture_responses=("click(250, 500)", "click(300, 600)"),
            step_observations=((before1, after1), (before2, after2)),
            lease_remaining_seconds=60.0,
            mono_seconds=100.0,
            max_actions=50,
            cancelled=lambda: recording.tap_count >= 1,
        ),
    )
    handler = assemble_android_worker_handlers(recording=recording)
    transport = SyncASGITransport(app)
    client_settings = WorkerClientSettings(
        base_url="https://127.0.0.1",
        token=token,
        timeout_seconds=10,
        verify_tls=False,
        ca_bundle=None,
    )

    captured_commits: list[dict] = []
    with WorkerHttpClient(client_settings, transport=transport) as client:
        original_commit = client.commit_evidence

        def capture_commit(**kwargs):
            captured_commits.append(dict(kwargs))
            return original_commit(**kwargs)

        client.commit_evidence = capture_commit  # type: ignore[method-assign]
        client.heartbeat("boot-rx67")
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
                    IdempotencyKey(actor.actor_id, project.project_id, "enqueue_job", "rx67-rec"),
                    now=now,
                )
            recording_id = str(receipt.recording_id)
        finally:
            store.close()

        runtime = WorkerRuntime(
            client,
            WorkerRuntimeConfig(
                boot_id="boot-rx67",
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
    assert len(calls) == 1
    assert recording.evidence_commits and recording.evidence_commits[0].get("acked") is True

    project_id = str(project.project_id)
    database = root / "db" / "aiqa.sqlite"
    store = app.state.open_store()
    try:
        with store.transaction() as connection:
            actions = connection.execute(
                """
                SELECT action_id, action_seq, dispatch_state FROM actions
                WHERE project_id = ?
                ORDER BY action_seq
                """,
                (project_id,),
            ).fetchall()
            objects = connection.execute(
                """
                SELECT role, byte_length, acked, status FROM artifact_objects
                WHERE project_id = ?
                ORDER BY role
                """,
                (project_id,),
            ).fetchall()
            events = connection.execute(
                "SELECT COUNT(*) FROM attempt_events WHERE attempt_id IN "
                "(SELECT attempt_id FROM attempts WHERE project_id = ?)",
                (project_id,),
            ).fetchone()[0]
            attempt_id = str(
                connection.execute(
                    "SELECT attempt_id FROM attempts WHERE project_id = ? LIMIT 1",
                    (project_id,),
                ).fetchone()[0]
            )
            job_id = str(
                connection.execute(
                    "SELECT job_id FROM jobs WHERE project_id = ? LIMIT 1",
                    (project_id,),
                ).fetchone()[0]
            )
            rec = connection.execute(
                """
                SELECT completion_status, evidence_status, stop_status FROM recordings
                WHERE project_id = ? AND recording_id = ?
                """,
                (project_id, recording_id),
            ).fetchone()
    finally:
        store.close()

    assert len(actions) == 1
    assert actions[0][1] == 1 and actions[0][2] == "observed"
    assert events == 2
    assert {"before", "after", "log"} <= {row[0] for row in objects}
    assert all(int(row[2]) == 1 and str(row[3]) == "ready" for row in objects)
    before_bytes = _artifact_bytes(database, artifacts_dir, project_id, "before")
    after_bytes = _artifact_bytes(database, artifacts_dir, project_id, "after")
    assert before_bytes == before1.png
    assert after_bytes == after1.png
    action_id = str(actions[0][0])

    # Retransmit the exact lost commit body: duplicate action 0, same file bytes.
    assert len(captured_commits) == 1
    replay_body = captured_commits[0]
    with WorkerHttpClient(client_settings, transport=transport) as client:
        first = client.commit_evidence(**replay_body)
        second = client.commit_evidence(**replay_body)
    assert first["contiguous_seq"] == second["contiguous_seq"] == 2
    assert first["prefix_hash"] == second["prefix_hash"]
    assert first["artifact_ids"] == second["artifact_ids"]

    store = app.state.open_store()
    try:
        with store.transaction() as connection:
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM actions WHERE project_id = ?",
                    (project_id,),
                ).fetchone()[0]
                == 1
            )
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM artifact_objects WHERE project_id = ? AND acked = 1",
                    (project_id,),
                ).fetchone()[0]
                == 3
            )
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM attempt_events WHERE attempt_id = ?",
                    (attempt_id,),
                ).fetchone()[0]
                == 2
            )
    finally:
        store.close()
    assert _artifact_bytes(database, artifacts_dir, project_id, "before") == before_bytes
    assert _artifact_bytes(database, artifacts_dir, project_id, "after") == after_bytes

    asyncio.run(
        _check_timeline_ui(
            app=app,
            project_id=project_id,
            recording_id=recording_id,
            action_id=action_id,
            tmp_path=tmp_path,
        )
    )

    # Handler keeps ACK'd prefix when the next step is cancelled without a bulk re-upload.
    held_commits: list[dict] = []

    def held_commit(**kwargs):
        held_commits.append(kwargs)
        return {
            "attempt_id": attempt_id,
            "contiguous_seq": 2,
            "prefix_hash": "sha256:" + ("cd" * 32),
            "stale_count": 0,
            "late": False,
            "artifact_count": 3,
            "artifact_ids": [str(uuid4()) for _ in range(3)],
        }

    held = AndroidRecordingHandler(
        adapter=MobileAgentAndroidAdapter(),
        driver=AndroidDeterministicDriver(
            Path("C:/platform-tools/adb.exe"),
            serial,
            runner=lambda argv, timeout: subprocess.CompletedProcess(list(argv), 0, b"", b""),
            spool=EvidenceSpool(tmp_path / "held-spool"),
        ),
        broker=recording_broker("held"),
        control=_Allow(),
        guard=RemoteLeaseGuard(),
        journal=DispatchJournal(tmp_path / "held-journal.jsonl"),
        spool=EvidenceSpool(tmp_path / "held-handler-spool"),
        context=AndroidRecordingContext(
            expected_serial=serial,
            fixture_response="",
            fixture_responses=("click(250, 500)", "click(300, 600)"),
            step_observations=((before1, after1), (before2, after2)),
            lease_remaining_seconds=60.0,
            mono_seconds=100.0,
            max_actions=2,
            cancelled=lambda: held.tap_count >= 1,
            step_evidence_commit=lambda **kw: held_commit(**kw),
        ),
    )
    held_result = held.handle(
        {
            "project_id": project_id,
            "job_id": str(uuid4()),
            "attempt_id": str(uuid4()),
            "generation": 1,
            "snapshot": {"purpose": "recording", "serial": serial},
        }
    )
    assert held_result.actions == 1
    assert held_result.outcome == "cancelled"
    assert held_result.evidence_events == ()
    assert held_result.evidence_artifacts == ()
    assert held_result.source_artifact_hashes
    assert len(held_commits) == 1
    assert rec is not None


async def _check_timeline_ui(
    *,
    app,
    project_id: str,
    recording_id: str,
    action_id: str,
    tmp_path: Path,
) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as http:
        headers = await session(http, project_id)
        timeline = await http.get(
            f"/api/v1/projects/{project_id}/recordings/{recording_id}/timeline",
            headers=headers,
        )
        assert timeline.status_code == 200, timeline.text
        body = timeline.json()
        assert len(body["actions"]) == 1
        assert body["actions"][0]["action_id"] == action_id
        assert body["actions"][0]["action_seq"] == 1
        assert body["actions"][0]["before"] == "stored"
        assert body["actions"][0]["after"] == "stored"
        assert body["actions"][0]["log"] == "stored"

        page = await http.get(
            f"/ui/projects/{project_id}/recordings/{recording_id}",
            headers=headers,
        )
        assert page.status_code == 200
        assert 'id="recording-timeline"' in page.text
        assert f'data-timeline-action="{action_id}"' in page.text
        assert page.text.count('data-timeline-action="') == 1
        rendered = tmp_path / "recording.html"
        rendered.write_text(page.text, encoding="utf-8")
        await _browser_shot(rendered, tmp_path / "rx67-timeline.png")
