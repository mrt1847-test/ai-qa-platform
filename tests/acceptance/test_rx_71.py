"""RX-71: browser API → recording → trial → review/approve → suite regression, no SQL shortcuts."""

from __future__ import annotations

import asyncio
import binascii
import hashlib
import json
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
from aiqa.contracts.jobs import ControlDecision
from aiqa.contracts.models import OwnedCheck, RoleBinding
from aiqa.models.broker import ModelBroker, ModelTransport
from aiqa.domain.projects import bind_store, create_project
from aiqa.replay.android_runner import AndroidDeterministicDriver
from aiqa.replay.packages import mobile_agent_plan_from_android_mapping
from aiqa.store.database import migrate_store
from aiqa.store.models import Actor, ProjectCreate
from aiqa.worker.android_jobs import (
    AndroidRecordingContext,
    AndroidRecordingHandler,
    AndroidReplayContext,
    AndroidReplayHandler,
    assemble_android_worker_handlers,
)
from aiqa.worker.control import RemoteLeaseGuard
from aiqa.worker.dispatch_journal import DispatchJournal
from aiqa.worker.http_client import SyncASGITransport, WorkerHttpClient
from aiqa.worker.runtime import WorkerRuntime, WorkerRuntimeConfig, android_worker_prepared_adapters
from aiqa.worker.spool import EvidenceSpool
from worker_presence_support import seed_presence
from ux_support import session

_BROWSERS = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
)
_ORIGIN = "http://127.0.0.1"
_SERIAL = "emulator-5580"
_WORKER = "worker-rx71"
_BOOT = "boot-rx71"


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


def _observation(*, fill: bytes, captured_at: str) -> Observation:
    return Observation(
        str(uuid4()),
        captured_at,
        CaptureGeometry(100, 200, 1000, 2000, "scale", 0, (0, 0, 100, 200)),
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

    def allow_model_action(self, *, late: bool) -> ControlDecision:
        return ControlDecision(not late, "before_model")


class _Script(ModelTransport):
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, check_id: str) -> str:
        self.calls += 1
        return '{"status":"satisfied","reason":"ok"}'


def _find_browser() -> Path | None:
    return next((path for path in _BROWSERS if path.is_file()), None)


async def _browser_shot(html_path: Path, out: Path) -> bool:
    browser = _find_browser()
    if browser is None:
        return False
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
    try:
        await asyncio.wait_for(proc.wait(), timeout=30)
    except asyncio.TimeoutError:
        proc.kill()
        return False
    return out.is_file() and out.stat().st_size > 1024


def _definition() -> dict[str, object]:
    return {
        "raw_text": "앱을 열고 버튼을 누른다",
        "objective": "버튼 탭",
        "preconditions": [],
        "variables": {},
        "secret_refs": {},
        "steps": [],
        "final_expected": [{"id": "exp-1", "kind": "text", "expected": "완료"}],
        "path_policy": {"must_use": [], "forbidden": []},
    }


def _settings() -> dict[str, object]:
    return {
        "target_kind": "android",
        "android_package": "com.example.app",
        "limits": {"timeout_seconds": 60, "max_actions": 20, "budget": "1", "currency": "USD"},
    }


def _rows(database: Path, sql: str, params: tuple = ()) -> list[tuple]:
    connection = sqlite3.connect(database)
    try:
        return connection.execute(sql, params).fetchall()
    finally:
        connection.close()


def _artifact_bytes(database: Path, artifacts_dir: Path, project_id: str, artifact_id: str) -> bytes:
    row = _rows(
        database,
        "SELECT object_key, byte_length FROM artifact_objects WHERE project_id = ? AND artifact_id = ?",
        (project_id, artifact_id),
    )[0]
    body = (artifacts_dir / str(row[0])).read_bytes()
    assert len(body) == int(row[1])
    return body


def _headers(base: dict[str, str], key: str) -> dict[str, str]:
    return {**base, "Idempotency-Key": key}


def test_rx_71_browser_recording_trial_approve_suite_regression(tmp_path: Path, monkeypatch) -> None:
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
        project = create_project(owner, ProjectCreate("RX71", "rx71", "rx", "android"))
    actor = Actor(owner.actor_id, project.project_id, True)
    project_id = str(project.project_id)
    database = root / "db" / "aiqa.sqlite"
    with bound_auth_store(store):
        tokens = {purpose: enroll_worker(actor, _WORKER, purpose) for purpose in ("recording", "trial", "regression")}

    # Allowed seed: worker/resource/inventory/presence/environment/authoring binding only.
    physical = str(uuid4())
    environment_id = str(uuid4())
    now = datetime.now(timezone.utc)
    monkeypatch.setattr("aiqa.api.worker._server_now", lambda: now)
    with store.transaction() as connection:
        connection.execute(
            "INSERT INTO physical_resource_keys (physical_key_id, worker_id, native_id) VALUES (?, ?, ?)",
            (physical, _WORKER, _SERIAL),
        )
        connection.execute(
            "INSERT INTO resource_aliases (project_id, physical_key_id, display_name, target_kind) VALUES (?, ?, ?, ?)",
            (project_id, physical, "AVD", "android"),
        )
        connection.execute(
            """
            INSERT INTO resource_inventory (
                physical_key_id, state, os_build, geometry, permissions, ime, observed_at
            ) VALUES (?, 'ready', '', '100x200@0', '[]', '', ?)
            """,
            (physical, now.isoformat()),
        )
        seed_presence(connection, project_id, _WORKER, now)
        connection.execute(
            """
            INSERT INTO environments (project_id, environment_id, name, next_revision, latest_revision_id)
            VALUES (?, 'env-rx71', '로컬', 2, ?)
            """,
            (project_id, environment_id),
        )
        connection.execute(
            """
            INSERT INTO environment_revisions (
                project_id, environment_id, revision_id, revision, body_json, content_hash,
                actor_id, created_at
            ) VALUES (?, 'env-rx71', ?, 1, '{}', 'env-hash', 'actor', '2026-11-06T00:00:00+00:00')
            """,
            (project_id, environment_id),
        )
        connection.execute(
            "INSERT INTO model_bindings (project_id, binding_id, name, next_revision, latest_revision_id) VALUES (?, 'bind-rx71', '작성', 2, 'rev-rx71')",
            (project_id,),
        )
        connection.execute(
            """
            INSERT INTO binding_revisions (
                project_id, binding_id, revision_id, revision, role, provider, endpoint_kind,
                endpoint, model, key_ref_id, key_revision, prompt_hash, tariff_id,
                compatibility_status, content_hash, actor_id, created_at
            ) VALUES (?, 'bind-rx71', 'rev-rx71', 1, 'authoring', 'fixture', 'loopback',
                'http://127.0.0.1', 'author-model', 'ref-rx71', 1, 'prompt', 'tariff',
                'compatible', 'hash', ?, '2026-11-06T00:00:00+00:00')
            """,
            (project_id, str(owner.actor_id)),
        )
    artifacts_dir = store.config.artifacts_dir
    store.close()

    # --- Browser API: case, version, pages, recording start --------------------------------
    ids = asyncio.run(_author_and_start_recording(app, project_id, physical))
    case_id, version_id, version_hash, recording_id = (
        ids["case_id"],
        ids["version_id"],
        ids["version_hash"],
        ids["recording_id"],
    )

    # --- Worker: recording -----------------------------------------------------------------
    calls: list = []

    def runner(argv, timeout):
        calls.append(tuple(argv))
        return subprocess.CompletedProcess(list(argv), 0, b"", b"")

    before1 = _observation(fill=b"\xff\x00\x00", captured_at="2026-11-06T09:00:01+00:00")
    after1 = _observation(fill=b"\x00\xff\x00", captured_at="2026-11-06T09:00:02+00:00")
    before2 = _observation(fill=b"\x00\x00\xff", captured_at="2026-11-06T09:00:03+00:00")
    after2 = _observation(fill=b"\xff\xff\x00", captured_at="2026-11-06T09:00:04+00:00")
    recording = AndroidRecordingHandler(
        adapter=MobileAgentAndroidAdapter(),
        driver=AndroidDeterministicDriver(
            Path("C:/platform-tools/adb.exe"),
            _SERIAL,
            runner=runner,
            spool=EvidenceSpool(tmp_path / "spool"),
        ),
        broker=recording_broker(),
        control=_Allow(),
        guard=RemoteLeaseGuard(),
        journal=DispatchJournal(tmp_path / "journal.jsonl"),
        spool=EvidenceSpool(tmp_path / "handler-spool"),
        context=AndroidRecordingContext(
            expected_serial=_SERIAL,
            fixture_response="",
            fixture_responses=("click(250, 500)", "finish()"),
            step_observations=((before1, after1), (before2, after2)),
            lease_remaining_seconds=60.0,
            mono_seconds=100.0,
            max_actions=50,
        ),
    )
    replay_calls: list = []

    def replay_runner(argv, timeout):
        replay_calls.append(tuple(argv))
        return subprocess.CompletedProcess(list(argv), 0, b"", b"")

    trial_before = _observation(fill=b"\x10\x20\x30", captured_at="2026-11-06T09:10:01+00:00")
    trial_after = _observation(fill=b"\x30\x20\x10", captured_at="2026-11-06T09:10:02+00:00")
    replay = AndroidReplayHandler(
        adapter=MobileAgentAndroidAdapter(),
        driver=AndroidDeterministicDriver(
            Path("C:/platform-tools/adb.exe"),
            _SERIAL,
            runner=replay_runner,
            spool=EvidenceSpool(tmp_path / "replay-spool"),
        ),
        broker=recording_broker("replay"),
        guard=RemoteLeaseGuard(),
        journal=DispatchJournal(tmp_path / "replay-journal.jsonl"),
        spool=EvidenceSpool(tmp_path / "replay-evidence"),
        context=AndroidReplayContext(
            expected_serial=_SERIAL,
            approved_digest="",
            approved_plan="",
            step_observations=((trial_before, trial_after),),
            lease_remaining_seconds=60.0,
            mono_seconds=100.0,
            verify_broker=ModelBroker(
                "item-1",
                (
                    RoleBinding("verification", 1, "fixture-v", "ref"),
                    RoleBinding("healing", 1, "fixture-h", "ref"),
                ),
                (OwnedCheck("check-1", "item-1"),),
                (),
            ),
            verify_transport=_Script(),
            verify_control=_Allow(),
        ),
    )
    handler = assemble_android_worker_handlers(recording=recording, replay=replay)
    transport = SyncASGITransport(app)

    def run_worker_once(purpose: str) -> object:
        client_settings = WorkerClientSettings(
            base_url="https://127.0.0.1",
            token=tokens[purpose],
            timeout_seconds=10,
            verify_tls=False,
            ca_bundle=None,
        )
        with WorkerHttpClient(client_settings, transport=transport) as client:
            client.heartbeat(_BOOT)
            runtime = WorkerRuntime(
                client,
                WorkerRuntimeConfig(
                    boot_id=_BOOT,
                    prepared_adapters=android_worker_prepared_adapters(),
                    max_cycles=1,
                ),
                handler,
                registered_serial=_SERIAL,
                now=lambda: now,
                mono=lambda: 100.0,
            )
            runtime._registered_physical_key_id = physical
            result = runtime.run_once()
        _release_lease(app, database, tokens[purpose], physical, now, f"rx71-clean-{uuid4()}")
        return result

    report = run_worker_once("recording")
    assert report.claimed is True, report
    assert report.finished is True, report
    assert recording.finished_by_model is True
    assert recording.tap_count == 1
    assert len(calls) == 1
    assert recording.authoring_calls_seen >= 1

    rec_rows = _rows(
        database,
        "SELECT completion_status, evidence_status, stop_status FROM recordings WHERE project_id = ? AND recording_id = ?",
        (project_id, recording_id),
    )
    assert rec_rows == [("completed", "complete", "stopped")], rec_rows
    assert _rows(
        database, "SELECT current_approval_id FROM automation_cases WHERE project_id = ? AND case_id = ?", (project_id, case_id)
    ) == [(None,)]
    rec_artifacts = _rows(
        database,
        """
        SELECT artifact_id, role, byte_length FROM artifact_objects
        WHERE project_id = ? AND owner_kind = 'REC' AND owner_id = ? AND status = 'ready' AND acked = 1
        """,
        (project_id, recording_id),
    )
    assert {row[1] for row in rec_artifacts} >= {"before", "after", "log"}
    for artifact_id, role, _length in rec_artifacts:
        body = _artifact_bytes(database, artifacts_dir, project_id, artifact_id)
        if role == "before":
            assert body == before1.png
        if role == "after":
            assert body == after1.png

    produced = _rows(
        database,
        """
        SELECT versions.version_id, versions.replay_package_id, versions.content_hash, packages.body_hash
        FROM materialization_receipts AS receipts
        JOIN recording_manifests AS manifests
          ON manifests.project_id = receipts.project_id AND manifests.manifest_id = receipts.manifest_id
        JOIN case_versions AS versions
          ON versions.project_id = receipts.project_id AND versions.version_id = receipts.produced_version_id
        LEFT JOIN replay_packages AS packages
          ON packages.project_id = versions.project_id AND packages.package_id = versions.replay_package_id
        WHERE manifests.project_id = ? AND manifests.recording_id = ?
        """,
        (project_id, recording_id),
    )
    assert len(produced) == 1, produced
    produced_version, package_id, produced_hash, package_body_hash = (str(item) for item in produced[0])
    assert package_id != "None" and package_body_hash != "None"
    manifest_mapping = _rows(
        database,
        "SELECT action_mapping FROM recording_manifests WHERE project_id = ? AND recording_id = ?",
        (project_id, recording_id),
    )[0][0]
    assert mobile_agent_plan_from_android_mapping(manifest_mapping) == "click(25, 50)"

    # --- Trial -----------------------------------------------------------------------------
    trial = asyncio.run(
        _run_execution(
            app,
            project_id,
            produced_version,
            environment_id,
            physical,
            purpose="trial",
            source="single",
            key="rx71-trial",
        )
    )
    report = run_worker_once("trial")
    assert report.claimed is True, report
    assert report.finished is True, report
    assert replay.authoring_calls_seen == 0
    assert replay.healer_calls == 0
    assert len(replay_calls) == 1
    assert _rows(
        database, "SELECT body_hash FROM replay_packages WHERE project_id = ? AND package_id = ?", (project_id, package_id)
    ) == [(package_body_hash,)]
    trial_item = trial["item_ids"][0]
    assert _rows(
        database,
        "SELECT status FROM jobs WHERE project_id = ? AND case_run_id = ?",
        (project_id, trial_item),
    ) == [("completed",)]
    assert _rows(
        database, "SELECT current_approval_id FROM automation_cases WHERE project_id = ? AND case_id = ?", (project_id, case_id)
    ) == [(None,)]

    # --- Review / approve: entries come from server-stored recording + trial evidence --------
    entries = _review_entries(database, project_id, recording_id, trial_item)
    assert {entry["owner_kind"] for entry in entries} == {"REC", "ITEM"}
    for entry in entries:
        stored = _artifact_bytes(database, artifacts_dir, project_id, entry["artifact_id"])
        assert "sha256:" + hashlib.sha256(stored).hexdigest() == entry["expected_hash"]
        if entry["role"] == "before" and entry["owner_kind"] == "REC":
            assert stored == before1.png
        if entry["role"] == "after" and entry["owner_kind"] == "REC":
            assert stored == after1.png
        if entry["role"] == "before" and entry["owner_kind"] == "ITEM":
            assert stored == trial_before.png
        if entry["role"] == "after" and entry["owner_kind"] == "ITEM":
            assert stored == trial_after.png
    review_html = tmp_path / "review.html"
    approval = asyncio.run(
        _review_and_approve(
            app,
            database,
            project_id,
            case_id,
            produced_version,
            produced_hash,
            trial_item,
            entries,
            review_html,
        )
    )
    approval_id = approval["approval_id"]
    assert _rows(
        database, "SELECT current_approval_id FROM automation_cases WHERE project_id = ? AND case_id = ?", (project_id, case_id)
    ) == [(approval_id,)]
    assert _rows(
        database, "SELECT content_hash FROM case_versions WHERE project_id = ? AND version_id = ?", (project_id, produced_version)
    ) == [(produced_hash,)]
    assert _rows(
        database, "SELECT body_hash FROM replay_packages WHERE project_id = ? AND package_id = ?", (project_id, package_id)
    ) == [(package_body_hash,)]

    # --- Suite regression through the suite HTTP API ----------------------------------------
    suite = asyncio.run(
        _create_suite_version(
            app,
            project_id,
            case_id=case_id,
            version_id=produced_version,
            approval_id=approval_id,
            environment_id=environment_id,
            physical=physical,
        )
    )
    regression = asyncio.run(
        _run_execution(
            app,
            project_id,
            produced_version,
            environment_id,
            physical,
            purpose="regression",
            source="suite",
            key="rx71-regression",
            suite_version_id=suite["suite_version_id"],
        )
    )
    report = run_worker_once("regression")
    assert report.claimed is True, report
    assert report.finished is True, report
    assert report.actions == 1
    assert len(replay_calls) == 2
    assert replay.authoring_calls_seen == 0 and replay.healer_calls == 0
    assert replay.broker.authoring_calls == 0
    assert recording.broker.authoring_calls >= 1  # authoring happened only during recording
    assert replay.package_digest_after == package_body_hash

    regression_item = regression["item_ids"][0]
    assert _rows(
        database,
        "SELECT purpose, status FROM jobs WHERE project_id = ? AND case_run_id = ?",
        (project_id, regression_item),
    ) == [("regression", "completed")]
    assert _rows(
        database,
        "SELECT source, suite_version_id FROM executions WHERE project_id = ? AND execution_id = ?",
        (project_id, regression["execution_id"]),
    ) == [("suite", suite["suite_version_id"])]
    regression_limits = json.loads(
        _rows(
            database,
            "SELECT limits FROM jobs WHERE project_id = ? AND case_run_id = ?",
            (project_id, regression_item),
        )[0][0]
    )
    assert regression_limits["approval_id"] == approval_id
    assert regression_limits["replay_package_id"] == package_id
    assert regression_limits["replay_package_hash"] == package_body_hash
    assert regression_limits["self_healing_enabled"] is False
    assert regression_limits["actor"] == 0
    regression_artifacts = _rows(
        database,
        """
        SELECT artifact_id, role FROM artifact_objects
        WHERE project_id = ? AND owner_kind = 'ITEM' AND owner_id = ? AND status = 'ready' AND acked = 1
        """,
        (project_id, regression_item),
    )
    assert {row[1] for row in regression_artifacts} >= {"before", "after", "log"}
    for artifact_id, role in regression_artifacts:
        body = _artifact_bytes(database, artifacts_dir, project_id, artifact_id)
        if role == "before":
            assert body == trial_before.png
        if role == "after":
            assert body == trial_after.png

    # Package digest and approved version stay byte-identical after trial + regression.
    assert _rows(
        database, "SELECT body_hash FROM replay_packages WHERE project_id = ? AND package_id = ?", (project_id, package_id)
    ) == [(package_body_hash,)]
    assert _rows(
        database, "SELECT content_hash FROM case_versions WHERE project_id = ? AND version_id = ?", (project_id, produced_version)
    ) == [(produced_hash,)]

    execution_html = tmp_path / "execution.html"
    detail = asyncio.run(
        _read_execution(app, project_id, regression["execution_id"], regression_item, execution_html)
    )
    assert detail["api_status"] == 200
    assert detail["page_status"] == 200
    assert detail["list_has_execution"] is True
    assert detail["purpose"] == "regression" and detail["source"] == "suite"
    assert detail["suite_version_id"] == suite["suite_version_id"]
    assert detail["finished_count"] == 1 and detail["pass_count"] == 1
    assert detail["item"]["job_status"] == "완료"
    assert detail["item"]["calls"] == 0  # no model calls during regression
    assert detail["item"]["approval_id"] == approval_id
    assert detail["item"]["replay_package_hash"] == package_body_hash
    assert regression["execution_id"] in detail["page_html"]

    # Optional headless-browser screenshots (soft: skipped when no browser is installed).
    if _find_browser() is not None:
        assert asyncio.run(_browser_shot(execution_html, tmp_path / "rx71-execution.png")) is True
        assert asyncio.run(_browser_shot(review_html, tmp_path / "rx71-review.png")) is True


def _review_entries(
    database: Path, project_id: str, recording_id: str, trial_case_run_id: str
) -> list[dict[str, str]]:
    """Real server ids for the recording attempt and the trial case run."""

    rows = _rows(
        database,
        """
        SELECT objects.owner_kind, objects.owner_id, objects.attempt_id, objects.action_id,
               objects.artifact_id, objects.role, objects.content_hash
        FROM artifact_objects AS objects
        JOIN artifact_refs AS refs
          ON refs.project_id = objects.project_id AND refs.artifact_id = objects.artifact_id
         AND refs.attempt_id = objects.attempt_id AND refs.action_id = objects.action_id
        JOIN actions
          ON actions.project_id = objects.project_id AND actions.attempt_id = objects.attempt_id
         AND actions.action_id = objects.action_id
        WHERE objects.project_id = ? AND objects.status = 'ready' AND objects.acked = 1
          AND objects.role IN ('before', 'after', 'log')
          AND ((objects.owner_kind = 'REC' AND objects.owner_id = ?)
            OR (objects.owner_kind = 'ITEM' AND objects.owner_id = ?))
        ORDER BY objects.owner_kind DESC, objects.role, objects.artifact_id
        """,
        (project_id, recording_id, trial_case_run_id),
    )
    return [
        {
            "owner_kind": str(row[0]),
            "owner_id": str(row[1]),
            "attempt_id": str(row[2]),
            "action_id": str(row[3]),
            "artifact_id": str(row[4]),
            "role": str(row[5]),
            "expected_hash": str(row[6]),
        }
        for row in rows
    ]


async def _review_and_approve(
    app,
    database: Path,
    project_id: str,
    case_id: str,
    version_id: str,
    version_hash: str,
    trial_case_run_id: str,
    entries: list[dict[str, str]],
    review_html: Path,
) -> dict:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=_ORIGIN
    ) as http:
        base = await session(http, project_id)
        # Approving before review must fail closed.
        early = await http.post(
            f"/api/v1/case-versions/{version_id}/approvals",
            json={
                "review_id": str(uuid4()),
                "version_hash": version_hash,
                "evidence_set_hash": "sha256:" + "0" * 64,
                "expected_current_approval_id": None,
                "reason": "premature",
            },
            headers=_headers(base, "rx71-approve-early"),
        )
        assert early.status_code == 422, early.text

        requested = await http.post(
            f"/api/v1/case-versions/{version_id}/review-requests",
            json={"trial_case_run_id": trial_case_run_id, "entries": entries},
            headers=_headers(base, "rx71-review-request"),
        )
        assert requested.status_code == 201, requested.text
        review = requested.json()
        assert review["version_hash"] == version_hash
        assert review["trial_case_run_id"] == trial_case_run_id
        review_id = review["id"]

        entry_rows = _rows(
            database,
            "SELECT entry_id, evidence_digest, owner_kind FROM review_evidence_entries WHERE project_id = ? AND review_id = ?",
            (project_id, review_id),
        )
        assert len(entry_rows) == len(entries)

        premature = await http.post(
            f"/api/v1/case-versions/{version_id}/approvals",
            json={
                "review_id": review_id,
                "version_hash": version_hash,
                "evidence_set_hash": review["evidence_set_hash"],
                "expected_current_approval_id": None,
                "reason": "premature",
            },
            headers=_headers(base, "rx71-approve-unreviewed"),
        )
        assert premature.status_code == 422, premature.text

        for index, (entry_id, digest, _kind) in enumerate(entry_rows):
            reviewed = await http.post(
                f"/api/v1/case-versions/{version_id}/action-reviews",
                json={
                    "review_id": review_id,
                    "entry_key": entry_id,
                    "evidence_digest": digest,
                    "state": "reviewed",
                    "comment": "확인함",
                },
                headers=_headers(base, f"rx71-action-review-{index}"),
            )
            assert reviewed.status_code == 201, reviewed.text
        assert reviewed.json()["source_reviewed"] == reviewed.json()["source_total"] > 0
        assert reviewed.json()["trial_reviewed"] == reviewed.json()["trial_total"] > 0

        page = await http.get(f"/ui/projects/{project_id}/cases/{case_id}/review", headers=base)
        assert page.status_code == 200
        review_html.write_text(page.text, encoding="utf-8")

        approved = await http.post(
            f"/api/v1/case-versions/{version_id}/approvals",
            json={
                "review_id": review_id,
                "version_hash": version_hash,
                "evidence_set_hash": review["evidence_set_hash"],
                "expected_current_approval_id": None,
                "reason": "RX-71 승인",
            },
            headers=_headers(base, "rx71-approve"),
        )
        assert approved.status_code == 201, approved.text
        return approved.json()


async def _create_suite_version(
    app,
    project_id: str,
    *,
    case_id: str,
    version_id: str,
    approval_id: str,
    environment_id: str,
    physical: str,
) -> dict:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=_ORIGIN
    ) as http:
        base = await session(http, project_id)
        created = await http.post(
            f"/api/v1/projects/{project_id}/suites",
            json={
                "name": "RX71 회귀",
                "description": "승인된 케이스",
                "target_kind": "android",
                "owner_name": "QA",
                "classification": "회귀",
            },
            headers=_headers(base, "rx71-suite"),
        )
        assert created.status_code == 201, created.text
        suite_id = created.json()["suite_id"]
        head = created.json()["version_id"]
        saved = await http.post(
            f"/api/v1/suites/{suite_id}/versions",
            json={
                "project_id": project_id,
                "expected_version_id": head,
                "entries": [
                    {
                        "entry_id": "entry-rx71",
                        "case_id": case_id,
                        "case_version_id": version_id,
                        "approval_id": approval_id,
                        "data_name": "기본",
                        "environment_revision_id": environment_id,
                        "reset_policy": "keep",
                        "failure_policy": "continue",
                        "resource_id": physical,
                        "target_kind": "android",
                    }
                ],
            },
            headers=_headers(base, "rx71-suite-version"),
        )
        assert saved.status_code == 201, saved.text
        body = saved.json()
        assert body["entries"][0]["case_version_id"] == version_id
        assert body["entries"][0]["approval_id"] == approval_id
        page = await http.get(f"/ui/projects/{project_id}/suites/{suite_id}", headers=base)
        assert page.status_code == 200
        return {"suite_id": suite_id, "suite_version_id": body["suite_version_id"]}


async def _read_execution(
    app, project_id: str, execution_id: str, case_run_id: str, out_html: Path
) -> dict:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=_ORIGIN
    ) as http:
        base = await session(http, project_id)
        api = await http.get(
            f"/api/v1/executions/{execution_id}?project_id={project_id}", headers=base
        )
        listing = await http.get(f"/api/v1/projects/{project_id}/executions", headers=base)
        page = await http.get(f"/ui/projects/{project_id}/executions", headers=base)
        out_html.write_text(page.text, encoding="utf-8")
        listed = listing.status_code == 200 and execution_id in json.dumps(listing.json())
        body = api.json()
        item = next(row for row in body["items"] if row["case_run_id"] == case_run_id)
        return {
            "api_status": api.status_code,
            "page_status": page.status_code,
            "page_html": page.text,
            "list_has_execution": listed,
            "purpose": body["purpose"],
            "source": body["source"],
            "suite_version_id": body["suite_version_id"],
            "finished_count": body["finished_count"],
            "pass_count": body["pass_count"],
            "item": item,
        }


async def _author_and_start_recording(app, project_id: str, physical: str) -> dict[str, str]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=_ORIGIN
    ) as http:
        base = await session(http, project_id)
        created = await http.post(
            f"/api/v1/projects/{project_id}/cases",
            json={"name": "RX71 버튼", "tc_reference": None},
            headers=_headers(base, "rx71-case"),
        )
        assert created.status_code in {200, 201}, created.text
        case_id = created.json()["case_id"]
        version = await http.post(
            f"/api/v1/projects/{project_id}/cases/{case_id}/versions",
            json={"definition": _definition(), "settings": _settings()},
            headers=_headers(base, "rx71-version"),
        )
        assert version.status_code == 201, version.text
        version_id = version.json()["id"]
        version_hash = version.json()["content_hash"]

        for url in (
            f"/ui/projects/{project_id}/recordings/wizard",
            f"/ui/projects/{project_id}/cases/{case_id}/execution-setup",
            f"/ui/projects/{project_id}/cases/{case_id}/review",
        ):
            page = await http.get(url, headers=base)
            assert page.status_code == 200, (url, page.status_code)

        started = await http.post(
            f"/api/v1/projects/{project_id}/recordings",
            json={
                "case_id": case_id,
                "input_case_version_id": version_id,
                "input_version_hash": version_hash,
                "resource_id": physical,
            },
            headers=_headers(base, "rx71-recording"),
        )
        assert started.status_code == 201, started.text
        return {
            "case_id": case_id,
            "version_id": version_id,
            "version_hash": version_hash,
            "recording_id": started.json()["recording_id"],
        }


async def _run_execution(
    app,
    project_id: str,
    version_id: str,
    environment_id: str,
    resource_id: str,
    *,
    purpose: str,
    source: str,
    key: str,
    suite_version_id: str | None = None,
) -> dict:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=_ORIGIN
    ) as http:
        base = await session(http, project_id)
        if source == "suite":
            selection: dict[str, object] = {"suite_version_id": suite_version_id}
        else:
            selection = {
                "items": [
                    {
                        "entry_id": "item-1",
                        "case_version_id": version_id,
                        "environment_revision_id": environment_id,
                        "resource_id": resource_id,
                        "install_policy": "none",
                    }
                ]
            }
        preview = await http.post(
            f"/api/v1/projects/{project_id}/execution-previews",
            json={
                "name": "RX71",
                "purpose": purpose,
                "source": source,
                "failure_policy": "stop_on_non_pass",
                "self_healing_enabled": False,
                "exclusions": [],
                "selection": selection,
            },
            headers=_headers(base, key + "-preview"),
        )
        assert preview.status_code == 200, preview.text
        body = preview.json()
        assert body["ready"] is True, body
        request: dict[str, object] = {
            "name": "RX71",
            "purpose": purpose,
            "source": source,
            "failure_policy": "stop_on_non_pass",
            "self_healing_enabled": False,
            "preview_hash": body["preview_hash"],
            "exclusions": [],
            "items": body["resolved_items"],
        }
        if suite_version_id is not None:
            request["suite_version_id"] = suite_version_id
        created = await http.post(
            f"/api/v1/projects/{project_id}/executions",
            json=request,
            headers=_headers(base, key),
        )
        assert created.status_code == 201, created.text
        return created.json()






def _release_lease(app, database: Path, token: str, physical: str, now: datetime, key: str) -> None:
    """Confirm cleanup so the next job can claim the same physical scope."""

    rows = _rows(
        database,
        """
        SELECT leases.project_id, leases.job_id, leases.generation, attempts.attempt_id
        FROM leases
        JOIN attempts
          ON attempts.project_id = leases.project_id
         AND attempts.job_id = leases.job_id
         AND attempts.generation = leases.generation
        WHERE leases.physical_key_id = ?
        """,
        (physical,),
    )
    if not rows:
        return
    row = rows[0]
    with httpx.Client(transport=SyncASGITransport(app), base_url="https://127.0.0.1") as http:
        response = http.post(
            "/api/v1/worker/cleanup-confirmations",
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": key},
            json={
                "project_id": str(row[0]),
                "job_id": str(row[1]),
                "generation": int(row[2]),
                "attempt_id": str(row[3]),
                "physical_key_id": physical,
                "proof_refs": ["adb:released"],
                "now": now.isoformat(),
            },
        )
    assert response.status_code == 200, response.text



