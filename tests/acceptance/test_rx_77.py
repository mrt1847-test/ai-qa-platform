"""RX-77: browser-JS HTTP contracts → real WorkerRuntime → results and resource return.

Journey (one pytest, one physical resource, two cases):
recording-previews → recording → execution-previews → trial → review/approve (per case)
→ suite with two approved entries → suite regression (two items) → results / evidence.

What is NOT allowed here (and not done):
* no test-side lease release / cleanup-confirmations POST (WorkerRuntime does it; RX-73),
* no SQL that completes jobs, executions, or finalizations (reads only after the seed),
* no invented PASS: ``item_finalizations.core_result`` comes from the real finish path (RX-72).

Caveat: requests are the exact bodies ``recording_setup.js`` / ``execution_setup.js`` send,
issued through httpx ASGI, not DOM clicks. The optional screenshot is of the rendered HTML.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx

from aiqa.adapters.mobile_agent_android import MobileAgentAndroidAdapter, recording_broker
from aiqa.api.app import create_app
from aiqa.api.auth import bound_auth_store, enroll_worker
from aiqa.config import WorkerClientSettings, load_settings
from aiqa.contracts.models import OwnedCheck, RoleBinding
from aiqa.models.broker import ModelBroker
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


def _load_rx71():
    """Reuse RX-71 fixtures/helpers (png, observations, review entries, screenshot)."""

    path = Path(__file__).with_name("test_rx_71.py")
    spec = importlib.util.spec_from_file_location("rx71_helpers", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["rx71_helpers"] = module
    spec.loader.exec_module(module)
    return module


rx71 = _load_rx71()
_rows = rx71._rows
_headers = rx71._headers
_artifact_bytes = rx71._artifact_bytes

_ORIGIN = "http://127.0.0.1"
_SERIAL = "emulator-5581"
_WORKER = "worker-rx77"
_BOOT = "boot-rx77"
_CLEANUP_PATH = "/api/v1/worker/cleanup-confirmations"
# case name → (recorded click on the 1000x2000 device, expected replay tap on 100x200 capture, colours)
_CASES = {
    "A": {"click": "click(250, 500)", "tap": "25 50", "fills": (b"\xff\x00\x00", b"\x00\xff\x00")},
    "B": {"click": "click(500, 1000)", "tap": "50 100", "fills": (b"\x00\x00\xff", b"\xff\xff\x00")},
}


class _SpyTransport(httpx.BaseTransport):
    """Forward to the ASGI app and remember every worker cleanup request the runtime sends."""

    def __init__(self, inner: httpx.BaseTransport) -> None:
        self._inner = inner
        self.cleanup_requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = self._inner.handle_request(request)
        if request.url.path == _CLEANUP_PATH:
            self.cleanup_requests.append(request)
        return response


def _scalar(database: Path, sql: str, params: tuple = ()) -> object:
    return _rows(database, sql, params)[0][0]


def _settings_like_js(environment_id: str, physical: str) -> dict[str, object]:
    """``settings`` exactly as ``recording_setup.js`` ``read()`` builds them for an Android target."""

    return {
        "wizard": True,
        "target_kind": "android",
        "execution_mode": "recorded_replay",
        "resource_id": physical,
        "environment_revision_id": environment_id,
        "definition_buffer": "앱을 열고 버튼을 누른다",
        "web_url": "",
        "android_package": "com.example.app",
        "build": "",
        "account_ref": "",
        "data_revision_id": "",
        "reset_policy": "keep",
        "limits": {"timeout_seconds": 60, "max_actions": 20, "budget": "1", "currency": "USD"},
    }


def _definition_like_js(label: str) -> dict[str, object]:
    return {
        "raw_text": "앱을 열고 버튼을 누른다",
        "objective": f"버튼 탭 {label}",
        "preconditions": [],
        "variables": {},
        "secret_refs": {},
        "steps": [],
        "final_expected": [{"id": str(uuid4()), "kind": "text", "expected": "완료"}],
        "path_policy": {"must_use": [], "forbidden": []},
    }


class _Journey:
    """Holds the single app/worker fixture and the real-runtime worker driver."""

    def __init__(self, tmp_path: Path, monkeypatch) -> None:
        self.tmp_path = tmp_path
        root = tmp_path / "runtime"
        root.mkdir()
        settings = load_settings(
            {"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}
        )
        self.app = create_app(settings)
        owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
        store = self.app.state.open_store()
        migrate_store(store)
        with bind_store(store):
            project = create_project(owner, ProjectCreate("RX77", "rx77", "rx", "android"))
        actor = Actor(owner.actor_id, project.project_id, True)
        self.project_id = str(project.project_id)
        self.database = root / "db" / "aiqa.sqlite"
        with bound_auth_store(store):
            self.tokens = {
                purpose: enroll_worker(actor, _WORKER, purpose)
                for purpose in ("recording", "trial", "regression")
            }
        self.physical = str(uuid4())
        self.environment_id = str(uuid4())
        self.now = datetime.now(timezone.utc)
        monkeypatch.setattr("aiqa.api.worker._server_now", lambda: self.now)
        # Allowed seed only: worker/resource/inventory/presence/environment/authoring binding.
        with store.transaction() as connection:
            connection.execute(
                "INSERT INTO physical_resource_keys (physical_key_id, worker_id, native_id) VALUES (?, ?, ?)",
                (self.physical, _WORKER, _SERIAL),
            )
            connection.execute(
                "INSERT INTO resource_aliases (project_id, physical_key_id, display_name, target_kind) VALUES (?, ?, ?, ?)",
                (self.project_id, self.physical, "AVD", "android"),
            )
            connection.execute(
                """
                INSERT INTO resource_inventory (
                    physical_key_id, state, os_build, geometry, permissions, ime, observed_at
                ) VALUES (?, 'ready', '', '100x200@0', '[]', '', ?)
                """,
                (self.physical, self.now.isoformat()),
            )
            seed_presence(connection, self.project_id, _WORKER, self.now)
            connection.execute(
                """
                INSERT INTO environments (project_id, environment_id, name, next_revision, latest_revision_id)
                VALUES (?, 'env-rx77', '로컬', 2, ?)
                """,
                (self.project_id, self.environment_id),
            )
            connection.execute(
                """
                INSERT INTO environment_revisions (
                    project_id, environment_id, revision_id, revision, body_json, content_hash,
                    actor_id, created_at
                ) VALUES (?, 'env-rx77', ?, 1, '{}', 'env-hash', 'actor', '2026-11-06T00:00:00+00:00')
                """,
                (self.project_id, self.environment_id),
            )
            connection.execute(
                "INSERT INTO model_bindings (project_id, binding_id, name, next_revision, latest_revision_id) VALUES (?, 'bind-rx77', '작성', 2, 'rev-rx77')",
                (self.project_id,),
            )
            connection.execute(
                """
                INSERT INTO binding_revisions (
                    project_id, binding_id, revision_id, revision, role, provider, endpoint_kind,
                    endpoint, model, key_ref_id, key_revision, prompt_hash, tariff_id,
                    compatibility_status, content_hash, actor_id, created_at
                ) VALUES (?, 'bind-rx77', 'rev-rx77', 1, 'authoring', 'fixture', 'loopback',
                    'http://127.0.0.1', 'author-model', 'ref-rx77', 1, 'prompt', 'tariff',
                    'compatible', 'hash', ?, '2026-11-06T00:00:00+00:00')
                """,
                (self.project_id, str(owner.actor_id)),
            )
        self.artifacts_dir = store.config.artifacts_dir
        store.close()

        self.spy = _SpyTransport(SyncASGITransport(self.app))
        self.runs: list[object] = []
        self.finished_runtimes = 0
        self.replay_calls: list[tuple[str, ...]] = []
        trial_before = rx71._observation(fill=b"\x10\x20\x30", captured_at="2026-11-06T09:10:01+00:00")
        trial_after = rx71._observation(fill=b"\x30\x20\x10", captured_at="2026-11-06T09:10:02+00:00")
        self.replay_before, self.replay_after = trial_before, trial_after

        def replay_runner(argv, timeout):
            self.replay_calls.append(tuple(str(part) for part in argv))
            return subprocess.CompletedProcess(list(argv), 0, b"", b"")

        self.replay = AndroidReplayHandler(
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
                verify_transport=rx71._Script(),
                verify_control=rx71._Allow(),
            ),
        )

    # -- real WorkerRuntime driver -----------------------------------------------------------
    def recording_handler(self, label: str) -> tuple[AndroidRecordingHandler, tuple]:
        spec = _CASES[label]
        before1 = rx71._observation(fill=spec["fills"][0], captured_at="2026-11-06T09:00:01+00:00")
        after1 = rx71._observation(fill=spec["fills"][1], captured_at="2026-11-06T09:00:02+00:00")
        before2 = rx71._observation(fill=b"\x01\x02\x03", captured_at="2026-11-06T09:00:03+00:00")
        after2 = rx71._observation(fill=b"\x03\x02\x01", captured_at="2026-11-06T09:00:04+00:00")
        calls: list = []

        def runner(argv, timeout):
            calls.append(tuple(argv))
            return subprocess.CompletedProcess(list(argv), 0, b"", b"")

        handler = AndroidRecordingHandler(
            adapter=MobileAgentAndroidAdapter(),
            driver=AndroidDeterministicDriver(
                Path("C:/platform-tools/adb.exe"),
                _SERIAL,
                runner=runner,
                spool=EvidenceSpool(self.tmp_path / f"spool-{label}"),
            ),
            broker=recording_broker(),
            control=rx71._Allow(),
            guard=RemoteLeaseGuard(),
            journal=DispatchJournal(self.tmp_path / f"journal-{label}.jsonl"),
            spool=EvidenceSpool(self.tmp_path / f"handler-spool-{label}"),
            context=AndroidRecordingContext(
                expected_serial=_SERIAL,
                fixture_response="",
                fixture_responses=(spec["click"], "finish()"),
                step_observations=((before1, after1), (before2, after2)),
                lease_remaining_seconds=60.0,
                mono_seconds=100.0,
                max_actions=50,
            ),
        )
        return handler, (before1, after1, calls)

    def run_worker_once(self, purpose: str, handler: object, *, label: str) -> object:
        """One real ``WorkerRuntime.run_once``; nothing else touches leases or cleanup."""

        client_settings = WorkerClientSettings(
            base_url="https://127.0.0.1",
            token=self.tokens[purpose],
            timeout_seconds=10,
            verify_tls=False,
            ca_bundle=None,
        )
        before_cleanups = len(self.spy.cleanup_requests)
        with WorkerHttpClient(client_settings, transport=self.spy) as client:
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
                now=lambda: self.now,
                mono=lambda: 100.0,
            )
            report = runtime.run_once()
        assert report.claimed is True and report.finished is True, (label, report)
        assert report.state == "running", (label, report)  # cleanup_pending would mean no release
        assert runtime.pending_cleanup is None and runtime.finished == 1, label
        # The runtime itself, with its own idempotency key, posted exactly one cleanup.
        assert len(self.spy.cleanup_requests) == before_cleanups + 1, label
        key = self.spy.cleanup_requests[-1].headers["Idempotency-Key"]
        assert key.startswith("cleanup-"), key
        self.runs.append(report)
        self.assert_resource_returned(label)
        return report

    def assert_resource_returned(self, label: str) -> None:
        """RX-73: no held lease on the physical key; every cleanup row released, none quarantined."""

        assert _scalar(self.database, "SELECT COUNT(*) FROM leases WHERE physical_key_id = ?", (self.physical,)) == 0, label
        assert _scalar(self.database, "SELECT COUNT(*) FROM leases") == 0, label
        released = _scalar(
            self.database,
            "SELECT COUNT(*) FROM cleanup_confirmations WHERE released = 1 AND quarantined = 0 AND physical_key_id = ?",
            (self.physical,),
        )
        assert released == len(self.runs), (label, released, len(self.runs))
        assert _scalar(self.database, "SELECT COUNT(*) FROM cleanup_confirmations WHERE quarantined = 1") == 0, label
        assert _scalar(
            self.database, "SELECT COUNT(*) FROM resource_quarantine WHERE physical_key_id = ?", (self.physical,)
        ) == 0, label
        assert _rows(
            self.database,
            "SELECT state FROM resource_inventory WHERE physical_key_id = ?",
            (self.physical,),
        ) == [("ready",)], label

    def assert_item_pass(self, case_run_id: str, label: str) -> None:
        """RX-72: PASS comes from the finalization written by the real finish; plus cleanup for its job."""

        assert _rows(
            self.database,
            "SELECT core_result FROM item_finalizations WHERE project_id = ? AND case_run_id = ?",
            (self.project_id, case_run_id),
        ) == [("PASS",)], label
        job = _rows(
            self.database,
            "SELECT job_id, status FROM jobs WHERE project_id = ? AND case_run_id = ?",
            (self.project_id, case_run_id),
        )
        assert len(job) == 1 and job[0][1] == "completed", (label, job)
        assert _rows(
            self.database,
            "SELECT released, quarantined FROM cleanup_confirmations WHERE project_id = ? AND job_id = ?",
            (self.project_id, job[0][0]),
        ) == [(1, 0)], label


def test_rx_77_browser_contract_journey_results_and_resource_reuse(tmp_path: Path, monkeypatch) -> None:
    journey = _Journey(tmp_path, monkeypatch)
    project_id, database, physical = journey.project_id, journey.database, journey.physical
    artifacts_dir = journey.artifacts_dir
    app = journey.app

    approved: dict[str, dict[str, str]] = {}
    recorders: dict[str, tuple] = {}
    for label in ("A", "B"):
        # --- Recording (previews first, as recording_setup.js does) -----------------------
        ids = asyncio.run(_author_and_start_recording(app, project_id, journey, label))
        handler, (before1, after1, adb_calls) = journey.recording_handler(label)
        recording_handler = handler
        assembled = assemble_android_worker_handlers(recording=recording_handler, replay=journey.replay)
        journey.run_worker_once("recording", assembled, label=f"recording-{label}")
        assert recording_handler.finished_by_model is True and recording_handler.tap_count == 1
        assert len(adb_calls) == 1
        recorders[label] = (recording_handler, before1, after1)
        recording_id = ids["recording_id"]
        assert _rows(
            database,
            "SELECT completion_status, evidence_status, stop_status FROM recordings WHERE project_id = ? AND recording_id = ?",
            (project_id, recording_id),
        ) == [("completed", "complete", "stopped")]
        # A recording job has no case_run: the cleanup row is tied to the recording job.
        assert _rows(
            database,
            """
            SELECT cleanup_confirmations.released FROM cleanup_confirmations
            JOIN jobs ON jobs.project_id = cleanup_confirmations.project_id AND jobs.job_id = cleanup_confirmations.job_id
            WHERE jobs.project_id = ? AND jobs.recording_id = ?
            """,
            (project_id, recording_id),
        ) == [(1,)]

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
        version_id, package_id, version_hash, package_hash = (str(item) for item in produced[0])
        assert package_id != "None" and package_hash != "None"
        mapping = _rows(
            database,
            "SELECT action_mapping FROM recording_manifests WHERE project_id = ? AND recording_id = ?",
            (project_id, recording_id),
        )[0][0]
        expected_plan = "click(%s)" % ", ".join(_CASES[label]["tap"].split())
        assert mobile_agent_plan_from_android_mapping(mapping) == expected_plan

        # --- Trial (execution-previews → executions with frozen items, as the JS does) ---------
        trial = asyncio.run(
            _run_trial_like_js(app, project_id, ids["case_id"], version_id, journey, key=f"rx77-trial-{label}")
        )
        replay_before = len(journey.replay_calls)
        journey.run_worker_once("trial", assemble_android_worker_handlers(recording=recording_handler, replay=journey.replay), label=f"trial-{label}")
        assert len(journey.replay_calls) == replay_before + 1
        trial_item = trial["item_ids"][0]
        journey.assert_item_pass(trial_item, f"trial-{label}")

        # --- Review / approve from server-stored recording + trial evidence --------------------
        entries = rx71._review_entries(database, project_id, recording_id, trial_item)
        assert {entry["owner_kind"] for entry in entries} == {"REC", "ITEM"}
        for entry in entries:
            stored = _artifact_bytes(database, artifacts_dir, project_id, entry["artifact_id"])
            assert "sha256:" + hashlib.sha256(stored).hexdigest() == entry["expected_hash"]
            if (entry["owner_kind"], entry["role"]) == ("REC", "before"):
                assert stored == before1.png
            if (entry["owner_kind"], entry["role"]) == ("REC", "after"):
                assert stored == after1.png
            if (entry["owner_kind"], entry["role"]) == ("ITEM", "before"):
                assert stored == journey.replay_before.png
        approval = asyncio.run(
            _review_and_approve(
                app, database, project_id, ids["case_id"], version_id, version_hash, trial_item, entries,
                tmp_path / f"review-{label}.html", f"rx77-{label}",
            )
        )
        approved[label] = {
            "case_id": ids["case_id"],
            "version_id": version_id,
            "version_hash": version_hash,
            "approval_id": approval["approval_id"],
            "package_id": package_id,
            "package_hash": package_hash,
            "trial_item": trial_item,
        }
        assert _rows(
            database,
            "SELECT current_approval_id FROM automation_cases WHERE project_id = ? AND case_id = ?",
            (project_id, ids["case_id"]),
        ) == [(approval["approval_id"],)]

    # The physical was claimed and returned five times so far: 2 recordings + 2 trials.
    assert len(journey.runs) == 4
    assert len({entry["version_id"] for entry in approved.values()}) == 2

    # --- Suite with TWO approved cases ------------------------------------------------------
    suite = asyncio.run(_create_two_case_suite(app, project_id, approved, journey))
    regression = asyncio.run(
        _run_regression_suite(app, project_id, approved, journey, suite["suite_version_id"])
    )
    assert len(regression["item_ids"]) == 2, regression
    assert regression["execution_id"]

    # Before any worker run both items wait; one physical → the second can only start after cleanup.
    assert _rows(
        database,
        "SELECT status FROM jobs WHERE project_id = ? AND purpose = 'regression' ORDER BY job_id",
        (project_id,),
    ) == [("queued",), ("queued",)]
    detail0 = asyncio.run(_read_execution(app, project_id, regression["execution_id"], tmp_path / "execution-0.html"))
    assert detail0["finished_count"] == 0 and detail0["pass_count"] == 0

    first_physical_attempts = []
    for index in range(2):
        before_calls = len(journey.replay_calls)
        journey.run_worker_once(
            "regression",
            assemble_android_worker_handlers(recording=recorders["A"][0], replay=journey.replay),
            label=f"regression-{index + 1}",
        )
        assert len(journey.replay_calls) == before_calls + 1
        first_physical_attempts.append(
            _rows(
                database,
                """
                SELECT attempts.physical_key_id FROM attempts
                JOIN jobs ON jobs.project_id = attempts.project_id AND jobs.job_id = attempts.job_id
                WHERE jobs.project_id = ? AND jobs.purpose = 'regression'
                ORDER BY attempts.rowid
                """,
                (project_id,),
            )
        )
        # Progress is visible through the execution API after each finish (not at the end only).
        mid = asyncio.run(_read_execution(app, project_id, regression["execution_id"], tmp_path / f"execution-mid-{index}.html"))
        assert mid["finished_count"] == index + 1 and mid["pass_count"] == index + 1, mid

    # Resource reuse: both regression items ran on the same physical, one after the other.
    assert first_physical_attempts[-1] == [(physical,), (physical,)]
    assert len(journey.runs) == 6

    # Regression advanced BOTH items, each with its own approved replay plan (distinct taps).
    regression_taps = [call for call in journey.replay_calls[-2:]]
    flattened = [" ".join(call) for call in regression_taps]
    assert any(text.endswith("input tap 2 5") for text in flattened), flattened
    assert any(text.endswith("input tap 5 10") for text in flattened), flattened
    assert len({tuple(call) for call in regression_taps}) == 2

    # A third claim finds nothing: queue drained and no lease left behind.
    with WorkerHttpClient(
        WorkerClientSettings("https://127.0.0.1", journey.tokens["regression"], 10, False, None),
        transport=journey.spy,
    ) as client:
        client.heartbeat(_BOOT)
        drain = WorkerRuntime(
            client,
            WorkerRuntimeConfig(boot_id=_BOOT, prepared_adapters=android_worker_prepared_adapters(), max_cycles=1),
            assemble_android_worker_handlers(recording=recorders["A"][0], replay=journey.replay),
            registered_serial=_SERIAL,
            now=lambda: journey.now,
            mono=lambda: 100.0,
        ).run_once()
    assert drain.claimed is False, drain
    journey.assert_resource_returned("drained")

    # --- Results / evidence originals ------------------------------------------------------
    for label, info in approved.items():
        assert _rows(
            database, "SELECT content_hash FROM case_versions WHERE project_id = ? AND version_id = ?",
            (project_id, info["version_id"]),
        ) == [(info["version_hash"],)]
        assert _rows(
            database, "SELECT body_hash FROM replay_packages WHERE project_id = ? AND package_id = ?",
            (project_id, info["package_id"]),
        ) == [(info["package_hash"],)]

    execution_html = tmp_path / "execution.html"
    detail = asyncio.run(_read_execution(app, project_id, regression["execution_id"], execution_html))
    assert detail["api_status"] == 200 and detail["page_status"] == 200
    assert detail["list_has_execution"] is True
    assert detail["purpose"] == "regression" and detail["source"] == "suite"
    assert detail["suite_version_id"] == suite["suite_version_id"]
    assert len(detail["items"]) == 2

    finalizations = {
        row[0]: row[1]
        for row in _rows(
            database,
            "SELECT case_run_id, core_result FROM item_finalizations WHERE project_id = ?",
            (project_id,),
        )
    }
    pass_from_finalization = [
        item["case_run_id"] for item in detail["items"] if finalizations.get(item["case_run_id"]) == "PASS"
    ]
    # API counts are derived from real finalizations, not typed in.
    assert detail["finished_count"] == 2 and detail["pass_count"] == 2
    assert len(pass_from_finalization) == detail["pass_count"] == detail["finished_count"]
    assert {item["case_run_id"] for item in detail["items"]} == set(regression["item_ids"])
    # 2 trials + 2 regressions finalised; recordings have no case-run finalization.
    assert len(finalizations) == 4 and set(finalizations.values()) == {"PASS"}

    approval_by_version = {info["version_id"]: info for info in approved.values()}
    for item in detail["items"]:
        assert item["core_result"] == "PASS" and item["verdict"] == "PASS"
        assert item["job_status"] == "완료"
        assert item["calls"] == 0  # no model calls during regression
        info = approval_by_version[item["case_version_id"]]
        assert item["approval_id"] == info["approval_id"]
        assert item["replay_package_hash"] == info["package_hash"]
        journey.assert_item_pass(item["case_run_id"], "regression-final")
        stored = _rows(
            database,
            """
            SELECT artifact_id, role, content_hash FROM artifact_objects
            WHERE project_id = ? AND owner_kind = 'ITEM' AND owner_id = ? AND status = 'ready' AND acked = 1
            """,
            (project_id, item["case_run_id"]),
        )
        assert {row[1] for row in stored} >= {"before", "after", "log"}
        for artifact_id, role, content_hash in stored:
            body = _artifact_bytes(database, artifacts_dir, project_id, artifact_id)
            assert "sha256:" + hashlib.sha256(body).hexdigest() == content_hash
            if role == "before":
                assert body == journey.replay_before.png
            if role == "after":
                assert body == journey.replay_after.png
    page_html = detail["page_html"]
    assert regression["execution_id"] in page_html
    assert "PASS" in page_html
    html_text = execution_html.read_text(encoding="utf-8")
    assert "종료 2" in html_text and "성공 2" in html_text

    # Optional headless-browser screenshot of the rendered result page (soft).
    if rx71._find_browser() is not None:
        assert asyncio.run(rx71._browser_shot(execution_html, tmp_path / "rx77-execution.png")) is True

async def _author_and_start_recording(app, project_id: str, journey: _Journey, label: str) -> dict[str, str]:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=_ORIGIN) as http:
        base = await session(http, project_id)
        for url in (f"/ui/projects/{project_id}/recordings/wizard",):
            page = await http.get(url, headers=base)
            assert page.status_code == 200, (url, page.status_code)
        # persist(): case by name only, then version with JS-shaped settings and null parents.
        created = await http.post(
            f"/api/v1/projects/{project_id}/cases",
            json={"name": f"RX77 케이스 {label}"},
            headers=_headers(base, f"rx77-case-{label}:case"),
        )
        assert created.status_code in {200, 201}, created.text
        case_id = created.json()["case_id"]
        version = await http.post(
            f"/api/v1/projects/{project_id}/cases/{case_id}/versions",
            json={
                "definition": _definition_like_js(label),
                "settings": _settings_like_js(journey.environment_id, journey.physical),
                "recorded_steps": [],
                "parent_version_id": None,
                "base_version_id": None,
                "expected_head": None,
            },
            headers=_headers(base, f"rx77-case-{label}:version"),
        )
        assert version.status_code == 201, version.text
        version_id, version_hash = version.json()["id"], version.json()["content_hash"]
        for url in (
            f"/ui/projects/{project_id}/cases/{case_id}/execution-setup",
            f"/ui/projects/{project_id}/cases/{case_id}/review",
        ):
            page = await http.get(url, headers=base)
            assert page.status_code == 200, (url, page.status_code)
        start_body = {
            "case_id": case_id,
            "input_case_version_id": version_id,
            "input_version_hash": version_hash,
            "resource_id": journey.physical,
        }
        preview = await http.post(
            f"/api/v1/projects/{project_id}/recording-previews", json=start_body, headers=base
        )
        assert preview.status_code == 200, preview.text
        assert preview.json()["ready"] is True, preview.json()
        started = await http.post(
            f"/api/v1/projects/{project_id}/recordings",
            json=start_body,
            headers=_headers(base, f"rx77-recording-{label}"),
        )
        assert started.status_code == 201, started.text
        return {
            "case_id": case_id,
            "version_id": version_id,
            "version_hash": version_hash,
            "recording_id": started.json()["recording_id"],
        }


async def _run_trial_like_js(
    app, project_id: str, case_id: str, version_id: str, journey: _Journey, *, key: str
) -> dict:
    """``execution_setup.js``: preview(read()) then POST the frozen body with resolved items."""

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=_ORIGIN) as http:
        base = await session(http, project_id)
        selection = {
            "items": [
                {
                    "entry_id": case_id,
                    "case_version_id": version_id,
                    "environment_revision_id": journey.environment_id,
                    "resource_id": journey.physical,
                    "dataset_version_id": None,
                }
            ]
        }
        preview = await http.post(
            f"/api/v1/projects/{project_id}/execution-previews",
            json={
                "purpose": "trial",
                "source": "single",
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
        created = await http.post(
            f"/api/v1/projects/{project_id}/executions",
            json={
                "name": "시범 · RX77",
                "purpose": "trial",
                "source": "single",
                "failure_policy": "stop_on_non_pass",
                "self_healing_enabled": False,
                "exclusions": [],
                "preview_hash": body["preview_hash"],
                "items": [{**selection["items"][0], **item} for item in body["resolved_items"]],
            },
            headers=_headers(base, key),
        )
        assert created.status_code == 201, created.text
        return created.json()


async def _review_and_approve(
    app, database: Path, project_id: str, case_id: str, version_id: str, version_hash: str,
    trial_case_run_id: str, entries: list[dict[str, str]], review_html: Path, prefix: str,
) -> dict:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=_ORIGIN) as http:
        base = await session(http, project_id)
        early = await http.post(
            f"/api/v1/case-versions/{version_id}/approvals",
            json={
                "review_id": str(uuid4()),
                "version_hash": version_hash,
                "evidence_set_hash": "sha256:" + "0" * 64,
                "expected_current_approval_id": None,
                "reason": "premature",
            },
            headers=_headers(base, f"{prefix}-approve-early"),
        )
        assert early.status_code == 422, early.text
        requested = await http.post(
            f"/api/v1/case-versions/{version_id}/review-requests",
            json={"trial_case_run_id": trial_case_run_id, "entries": entries},
            headers=_headers(base, f"{prefix}-review-request"),
        )
        assert requested.status_code == 201, requested.text
        review = requested.json()
        review_id = review["id"]
        entry_rows = _rows(
            database,
            "SELECT entry_id, evidence_digest FROM review_evidence_entries WHERE project_id = ? AND review_id = ?",
            (project_id, review_id),
        )
        assert len(entry_rows) == len(entries)
        for index, (entry_id, digest) in enumerate(entry_rows):
            reviewed = await http.post(
                f"/api/v1/case-versions/{version_id}/action-reviews",
                json={
                    "review_id": review_id,
                    "entry_key": entry_id,
                    "evidence_digest": digest,
                    "state": "reviewed",
                    "comment": "확인함",
                },
                headers=_headers(base, f"{prefix}-action-review-{index}"),
            )
            assert reviewed.status_code == 201, reviewed.text
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
                "reason": "RX-77 승인",
            },
            headers=_headers(base, f"{prefix}-approve"),
        )
        assert approved.status_code == 201, approved.text
        return approved.json()


async def _create_two_case_suite(app, project_id: str, approved: dict, journey: _Journey) -> dict:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=_ORIGIN) as http:
        base = await session(http, project_id)
        created = await http.post(
            f"/api/v1/projects/{project_id}/suites",
            json={
                "name": "RX77 회귀 묶음",
                "description": "승인된 두 케이스",
                "target_kind": "android",
                "owner_name": "QA",
                "classification": "회귀",
            },
            headers=_headers(base, "rx77-suite"),
        )
        assert created.status_code == 201, created.text
        suite_id, head = created.json()["suite_id"], created.json()["version_id"]
        entries = [
            {
                "entry_id": f"entry-rx77-{label}",
                "case_id": info["case_id"],
                "case_version_id": info["version_id"],
                "approval_id": info["approval_id"],
                "data_name": "기본",
                "environment_revision_id": journey.environment_id,
                "reset_policy": "keep",
                "failure_policy": "continue",
                "resource_id": journey.physical,
                "target_kind": "android",
            }
            for label, info in sorted(approved.items())
        ]
        saved = await http.post(
            f"/api/v1/suites/{suite_id}/versions",
            json={"project_id": project_id, "expected_version_id": head, "entries": entries},
            headers=_headers(base, "rx77-suite-version"),
        )
        assert saved.status_code == 201, saved.text
        body = saved.json()
        assert [entry["case_version_id"] for entry in body["entries"]] == [e["case_version_id"] for e in entries]
        assert [entry["approval_id"] for entry in body["entries"]] == [e["approval_id"] for e in entries]
        page = await http.get(f"/ui/projects/{project_id}/suites/{suite_id}", headers=base)
        assert page.status_code == 200
        return {"suite_id": suite_id, "suite_version_id": body["suite_version_id"]}


async def _run_regression_suite(
    app, project_id: str, approved: dict, journey: _Journey, suite_version_id: str
) -> dict:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=_ORIGIN) as http:
        base = await session(http, project_id)
        common = {
            "name": "RX77 회귀",
            "purpose": "regression",
            "source": "suite",
            "failure_policy": "stop_on_non_pass",
            "self_healing_enabled": False,
            "exclusions": [],
        }
        preview = await http.post(
            f"/api/v1/projects/{project_id}/execution-previews",
            json={**common, "selection": {"suite_version_id": suite_version_id}},
            headers=_headers(base, "rx77-regression-preview"),
        )
        assert preview.status_code == 200, preview.text
        body = preview.json()
        assert body["ready"] is True, body
        assert len(body["resolved_items"]) == 2, body
        created = await http.post(
            f"/api/v1/projects/{project_id}/executions",
            json={
                **common,
                "preview_hash": body["preview_hash"],
                "items": body["resolved_items"],
                "suite_version_id": suite_version_id,
            },
            headers=_headers(base, "rx77-regression"),
        )
        assert created.status_code == 201, created.text
        return created.json()


async def _read_execution(app, project_id: str, execution_id: str, out_html: Path) -> dict:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=_ORIGIN) as http:
        base = await session(http, project_id)
        api = await http.get(f"/api/v1/executions/{execution_id}?project_id={project_id}", headers=base)
        listing = await http.get(f"/api/v1/projects/{project_id}/executions", headers=base)
        page = await http.get(f"/ui/projects/{project_id}/executions/{execution_id}", headers=base)
        out_html.write_text(page.text, encoding="utf-8")
        body = api.json()
        return {
            "api_status": api.status_code,
            "page_status": page.status_code,
            "page_html": page.text,
            "list_has_execution": listing.status_code == 200 and execution_id in json.dumps(listing.json()),
            "purpose": body["purpose"],
            "source": body["source"],
            "suite_version_id": body["suite_version_id"],
            "finished_count": body["finished_count"],
            "pass_count": body["pass_count"],
            "items": body["items"],
        }
