"""RX-72: a worker finish writes the item result and advances the run."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from worker_presence_support import seed_inventory, seed_presence

from aiqa.api.app import create_app
from aiqa.config import load_settings
from aiqa.contracts.worker_attempt import WorkerAttemptFinishInput
from aiqa.domain.projects import bind_store, create_project
from aiqa.domain.report_math import summarize_execution
from aiqa.contracts.reports import CaseRunFacts
from aiqa.store.database import migrate_store
from aiqa.store.models import Actor, ProjectCreate, WorkerScope
from aiqa.store.queue import claim_queued_job, finish_worker_attempt

_WORKER = "worker-rx72"
_STAMP = "2026-11-01T00:00:00+00:00"


def _empty_hash() -> str:
    return "sha256:" + hashlib.sha256(b"").hexdigest()


def test_rx_72_finish_writes_item_results_and_advances(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    app = create_app(load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}))
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("결과", "rx72", "실행", "web"))
    store.close()
    project_id = project.project_id
    database = root / "db" / "aiqa.sqlite"
    key_id = _device(database, str(project_id))
    graph = {
        "pass_fail": _execution(database, str(project_id), str(owner.actor_id), key_id, "continue", 2),
        "cancel": _execution(database, str(project_id), str(owner.actor_id), key_id, "continue", 2),
        "stop": _execution(database, str(project_id), str(owner.actor_id), key_id, "stop_on_non_pass", 2),
    }
    worker = WorkerScope(_WORKER, (project_id,), ("regression",))

    # A. first item completes with full evidence -> PASS written by the finish itself.
    run_a = graph["pass_fail"]
    claim_1 = _claim(database, worker)
    assert claim_1 is not None and claim_1[0] == run_a["jobs"][0]
    # The next item is not claimable while item 1 is open.
    receipt_1 = _finish(database, worker, claim_1, outcome="completed", evidence_complete=True, key="rx72-a1")
    assert receipt_1.outcome == "completed" and receipt_1.verdict == "PASS"
    assert _result(database, str(project_id), run_a["items"][0]) == "PASS"
    assert _count(database, str(project_id), run_a["items"][0]) == 1
    assert _result(database, str(project_id), run_a["items"][1]) is None
    _release(database, claim_1)

    # The next item becomes claimable only because the first one is finalized.
    claim_2 = _claim(database, worker)
    assert claim_2 is not None and claim_2[0] == run_a["jobs"][1]

    # B. second item errors with a required violation -> FAIL, execution terminal.
    receipt_2 = _finish(
        database, worker, claim_2, outcome="error", required_violation=True, evidence_complete=False, key="rx72-a2"
    )
    assert receipt_2.verdict == "FAIL"
    assert _result(database, str(project_id), run_a["items"][1]) == "FAIL"
    assert _finalization_total(database, str(project_id), run_a["items"]) == 2
    summary = summarize_execution(
        [CaseRunFacts(status=_result(database, str(project_id), item) or "") for item in run_a["items"]]
    )
    assert summary.completion_rate == 1

    # C. retransmit of the same finish key -> same receipt, still one row per item.
    again = _finish(
        database, worker, claim_2, outcome="error", required_violation=True, evidence_complete=False, key="rx72-a2"
    )
    assert again.replayed is True and again.verdict == receipt_2.verdict and again.status == receipt_2.status
    assert _count(database, str(project_id), run_a["items"][1]) == 1
    assert _finalization_total(database, str(project_id), run_a["items"]) == 2
    # A late finish with a new key after the result is stored must not overwrite it.
    late = _finish(database, worker, claim_2, outcome="completed", evidence_complete=True, key="rx72-a2-late")
    assert late.verdict == "FAIL"
    assert _result(database, str(project_id), run_a["items"][1]) == "FAIL"
    assert _count(database, str(project_id), run_a["items"][1]) == 1
    _release(database, claim_2)

    # D. user cancel on the first item -> CANCELLED and the rest of the run is cancelled.
    run_c = graph["cancel"]
    claim_c = _claim(database, worker)
    assert claim_c is not None and claim_c[0] == run_c["jobs"][0]
    cancelled = _finish(database, worker, claim_c, outcome="cancelled", evidence_complete=False, key="rx72-c1")
    assert cancelled.status == "cancelled"
    assert _result(database, str(project_id), run_c["items"][0]) == "CANCELLED"
    assert _result(database, str(project_id), run_c["items"][1]) == "CANCELLED"
    assert _status(database, run_c["jobs"][1]) == "cancelled"
    _release(database, claim_c)

    # D2. an error under stop_on_non_pass marks the later item NOT_RUN, not CANCELLED.
    run_s = graph["stop"]
    claim_s = _claim(database, worker)
    assert claim_s is not None and claim_s[0] == run_s["jobs"][0]
    _finish(database, worker, claim_s, outcome="error", evidence_complete=False, key="rx72-s1")
    assert _result(database, str(project_id), run_s["items"][0]) in {"FAIL", "INCONCLUSIVE"}
    assert _result(database, str(project_id), run_s["items"][1]) == "NOT_RUN"
    assert _claim(database, worker) is None


def _device(database: Path, project_id: str) -> str:
    enrollment_id, key_id = str(uuid4()), str(uuid4())
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "INSERT INTO worker_enrollments (enrollment_id, worker_id, project_id, created_at) VALUES (?, ?, ?, ?)",
            (enrollment_id, _WORKER, project_id, _STAMP),
        )
        connection.execute(
            "INSERT INTO physical_resource_keys (physical_key_id, worker_id, native_id) VALUES (?, ?, 'native-rx72')",
            (key_id, _WORKER),
        )
        connection.execute(
            "INSERT INTO resource_aliases (project_id, physical_key_id, display_name, target_kind) VALUES (?, ?, '결과 기기', 'web')",
            (project_id, key_id),
        )
        seed_presence(connection, project_id, _WORKER)
        seed_inventory(connection, key_id)
    return key_id


def _execution(
    database: Path, project_id: str, actor_id: str, key_id: str, policy: str, count: int
) -> dict[str, list[str]]:
    execution_id = str(uuid4())
    items: list[str] = []
    jobs: list[str] = []
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO executions (project_id, execution_id, name, purpose, source, suite_version_id, scope_requested_at)
            VALUES (?, ?, ?, 'regression', 'selection', NULL, ?)
            """,
            (project_id, execution_id, f"rx72-{policy}", _STAMP),
        )
        for index in range(count):
            case_id, version_id, run_id, job_id = str(uuid4()), str(uuid4()), str(uuid4()), str(uuid4())
            connection.execute(
                """
                INSERT INTO automation_cases (
                    project_id, case_id, name, folder_id, tc_reference, next_revision,
                    latest_draft_version_id, current_approval_id, lock_version, archived_at
                ) VALUES (?, ?, ?, NULL, NULL, 2, NULL, NULL, 0, NULL)
                """,
                (project_id, case_id, f"rx72-{index}"),
            )
            connection.execute(
                """
                INSERT INTO case_versions (
                    project_id, case_id, version_id, revision, creation_kind, parent_version_id, base_version_id,
                    is_branch, definition_json, settings_json, recorded_steps_json, content_hash, verification_digest,
                    source_manifest_id, replay_package_id, readiness_json, actor_id, reason, created_at
                ) VALUES (?, ?, ?, 1, 'recorded', NULL, NULL, 0, '{}', '{}', '[]', 'version-hash', ?,
                    NULL, NULL, '{}', ?, 'recorded', ?)
                """,
                (project_id, case_id, version_id, f"digest-{execution_id}-{index}", actor_id, _STAMP),
            )
            package_id, manifest_id, recording_id = str(uuid4()), str(uuid4()), str(uuid4())
            connection.execute(
                """
                INSERT INTO recordings (
                    project_id, case_id, recording_id, creation_kind, input_case_version_id,
                    storage_status, stop_status, completion_status, evidence_status
                ) VALUES (?, ?, ?, 'recorded', ?, 'stored', 'stopped', 'completed', 'complete')
                """,
                (project_id, case_id, recording_id, version_id),
            )
            connection.execute(
                """
                INSERT INTO recording_manifests (
                    project_id, case_id, recording_id, manifest_id, revision, kind,
                    input_version_hash, source_artifact_hashes, action_mapping, evidence_completeness,
                    request_key, body_hash
                ) VALUES (?, ?, ?, ?, 1, 'original', 'input-hash', '[]', '{}', 'complete', ?, 'manifest-hash')
                """,
                (project_id, case_id, recording_id, manifest_id, manifest_id),
            )
            run_version_id = str(uuid4())
            connection.execute(
                """
                INSERT INTO case_versions (
                    project_id, case_id, version_id, revision, creation_kind, parent_version_id, base_version_id,
                    is_branch, definition_json, settings_json, recorded_steps_json, content_hash, verification_digest,
                    source_manifest_id, replay_package_id, readiness_json, actor_id, reason, created_at
                ) VALUES (?, ?, ?, 2, 'recorded', NULL, NULL, 1, '{}', '{}', '[]', 'version-hash-2', ?,
                    ?, ?, '{}', ?, 'recorded', ?)
                """,
                (
                    project_id, case_id, run_version_id, f"digest2-{execution_id}-{index}",
                    manifest_id, package_id, actor_id, _STAMP,
                ),
            )
            connection.execute(
                """
                INSERT INTO replay_packages (
                    project_id, package_id, case_id, case_version_id, ready, schema_version,
                    source_manifest_id, source_manifest_hash, raw_source_hash, approved_code_hash,
                    runtime_ref, compiler_ref, lock_hash, step_mapping_hash, body_hash
                ) VALUES (?, ?, ?, ?, 1, 'replay-package-v1', ?, 'manifest-hash', 'raw', 'code',
                    'web', 'web-ipc-subset', 'lock', 'map', ?)
                """,
                (project_id, package_id, case_id, run_version_id, manifest_id, f"pkg-{package_id}"),
            )
            connection.execute(
                "INSERT INTO package_version_links (project_id, case_id, version_id, package_id) VALUES (?, ?, ?, ?)",
                (project_id, case_id, run_version_id, package_id),
            )
            connection.execute(
                """
                INSERT INTO case_runs (
                    project_id, execution_id, case_run_id, case_id, case_version_id, purpose, requested_at
                ) VALUES (?, ?, ?, ?, ?, 'regression', ?)
                """,
                (project_id, execution_id, run_id, case_id, run_version_id, _STAMP),
            )
            connection.execute(
                """
                INSERT INTO jobs (
                    project_id, job_id, purpose, recording_id, case_run_id, payload_hash, source_refs, limits, status
                ) VALUES (?, ?, 'regression', NULL, ?, 'payload', ?, ?, 'queued')
                """,
                (
                    project_id,
                    job_id,
                    run_id,
                    json.dumps([key_id]),
                    json.dumps(
                        {
                            "failure_policy": policy,
                            "replay_package_id": package_id,
                            "replay_package_hash": f"pkg-{package_id}",
                        },
                        separators=(",", ":"),
                    ),
                ),
            )
            items.append(run_id)
            jobs.append(job_id)
    return {"execution_id": [execution_id], "items": items, "jobs": jobs}


def _claim(database: Path, worker: WorkerScope) -> tuple[str, str, str, str, str] | None:
    """Claim and start-ACK one job. Returns job_id, attempt_id, project_id, physical_key_id, generation."""

    now = datetime.now(timezone.utc)
    connection = sqlite3.connect(database)
    try:
        lease = claim_queued_job(connection, worker, now)
        if lease is None:
            connection.commit()
            return None
        connection.execute(
            "INSERT INTO attempt_runners (project_id, attempt_id, runner_nonce, acked_at) VALUES (?, ?, ?, ?)",
            (str(lease.project_id), str(lease.attempt_id), str(uuid4()), now.isoformat()),
        )
        connection.commit()
    finally:
        connection.close()
    return (
        str(lease.job_id),
        str(lease.attempt_id),
        str(lease.project_id),
        "" if lease.physical_key_id is None else str(lease.physical_key_id),
        str(lease.generation),
    )


def _finish(
    database: Path,
    worker: WorkerScope,
    claim: tuple[str, str, str, str, str],
    *,
    outcome: str,
    evidence_complete: bool,
    key: str,
    required_violation: bool = False,
    expect_rejected: bool = False,
):
    job_id, attempt_id, project_id, physical_key_id, generation = claim
    finish = WorkerAttemptFinishInput(
        UUID(project_id),
        UUID(job_id),
        UUID(attempt_id),
        int(generation),
        outcome,
        0,
        0,
        _empty_hash(),
        _manifest_digest(database, project_id, attempt_id),
        evidence_complete,
        False,
        physical_key_id=UUID(physical_key_id) if physical_key_id else None,
        required_violation=required_violation,
    )
    body_hash = hashlib.sha256(json.dumps([outcome, evidence_complete, required_violation]).encode()).hexdigest()
    connection = sqlite3.connect(database)
    try:
        try:
            receipt = finish_worker_attempt(
                connection,
                worker,
                finish,
                request_key=key,
                body_hash=body_hash,
                now=datetime.now(timezone.utc),
            )
        except Exception:
            connection.rollback()
            if expect_rejected:
                return None
            raise
        connection.commit()
        return receipt
    finally:
        connection.close()


def _release(database: Path, claim: tuple[str, str, str, str, str]) -> None:
    """Stand in for the worker cleanup confirmation that frees the device lease."""

    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM leases WHERE job_id = ?", (claim[0],))


def _manifest_digest(database: Path, project_id: str, attempt_id: str) -> str:
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT digest FROM claim_receipts WHERE project_id = ? AND attempt_id = ?",
            (project_id, attempt_id),
        ).fetchone()
    return "sha256:manifest" if row is None else str(row[0])


def _result(database: Path, project_id: str, case_run_id: str) -> str | None:
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT core_result FROM item_finalizations WHERE project_id = ? AND case_run_id = ?",
            (project_id, case_run_id),
        ).fetchone()
    return None if row is None else str(row[0])


def _count(database: Path, project_id: str, case_run_id: str) -> int:
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT COUNT(*) FROM item_finalizations WHERE project_id = ? AND case_run_id = ?",
            (project_id, case_run_id),
        ).fetchone()
    return int(row[0])


def _finalization_total(database: Path, project_id: str, items: list[str]) -> int:
    return sum(_count(database, project_id, item) for item in items)


def _status(database: Path, job_id: str) -> str:
    with sqlite3.connect(database) as connection:
        row = connection.execute("SELECT status FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
    return str(row[0])
