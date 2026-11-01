"""Observation windows use UTC bounds and one row per item."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4


def test_w24_01(tmp_path: Path) -> None:
    import asyncio

    from aiqa.api.app import create_app
    from aiqa.config import load_settings
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.domain.verdicts import FailureLatch, item_result
    from aiqa.store.database import migrate_store
    from aiqa.store.models import Actor, ProjectCreate

    root = tmp_path / "runtime"
    app = create_app(load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}))
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("관측", "w2401", "기간", "web"))
        other = create_project(owner, ProjectCreate("다른", "w2401b", "기간", "web"))
    store.close()
    project_id = str(project.project_id)
    satisfied = item_result(FailureLatch().value, True, None)
    seeded = _observation_graph(root / "db" / "aiqa.sqlite", project_id, str(owner.actor_id), satisfied)
    listed, hidden = asyncio.run(_observations(app, project_id, str(other.project_id)))
    by_run = {item["case_run_id"]: item for item in listed["items"]}
    retry = by_run[seeded["retry"]]
    original = by_run[seeded["original"]]
    rerun = by_run[seeded["rerun"]]
    pending = by_run[seeded["pending"]]
    missed = by_run[seeded["missed"]]
    observed = {
        "attempts_do_not_add_observations": retry["attempt_count"] == 2 and sum(1 for item in listed["items"] if item["execution_id"] == seeded["retry_execution"]) == 1,
        "rerun_observations": sum(1 for item in listed["items"] if item["execution_id"] in {seeded["original_execution"], seeded["rerun_execution"]}),
        "asof15_terminal": pending["terminal"],
        "not_run_in_denominator": missed["in_denominator"],
    }
    assert seeded["start"] in by_run and seeded["before"] not in by_run and seeded["end"] not in by_run
    assert seeded["trial"] not in by_run
    assert pending["in_denominator"] is True and pending["result"] is None
    assert missed["result"] == "NOT_RUN"
    assert original["result"] == "FAIL" and rerun["result"] == satisfied
    assert hidden == 404
    assert observed == {
        "attempts_do_not_add_observations": True,
        "rerun_observations": 2,
        "asof15_terminal": False,
        "not_run_in_denominator": True,
    }


def _observation_graph(database: Path, project_id: str, actor_id: str, satisfied: str) -> dict[str, str]:
    inside = "2026-11-01T00:00:00+00:00"
    start_at = "2026-10-31T15:00:00+00:00"
    before_at = "2026-10-31T14:59:59+00:00"
    end_at = "2026-11-01T15:00:00+00:00"
    ids = {name: str(uuid4()) for name in ("start", "before", "end", "retry", "original", "rerun", "pending", "missed", "trial")}
    executions = {name: str(uuid4()) for name in ("start", "before", "end", "retry", "original", "rerun", "pending", "missed", "trial")}
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        _run(connection, project_id, actor_id, executions["start"], ids["start"], "start", "regression", "selection", start_at, "FAIL", 1, 1)
        _run(connection, project_id, actor_id, executions["before"], ids["before"], "before", "regression", "selection", before_at, "FAIL", 1, 1)
        _run(connection, project_id, actor_id, executions["end"], ids["end"], "end", "regression", "selection", end_at, "FAIL", 1, 1)
        job = _run(connection, project_id, actor_id, executions["retry"], ids["retry"], "retry", "regression", "selection", inside, "FAIL", 1, 1)
        for generation in (1, 2):
            connection.execute(
                "INSERT INTO attempts (project_id, attempt_id, job_id, generation, physical_key_id) VALUES (?, ?, ?, ?, NULL)",
                (project_id, str(uuid4()), job, generation),
            )
        _run(connection, project_id, actor_id, executions["original"], ids["original"], "original", "regression", "selection", inside, "FAIL", 1, 1)
        _run(connection, project_id, actor_id, executions["rerun"], ids["rerun"], "rerun", "regression", "rerun", inside, satisfied, 1, 1)
        _run(connection, project_id, actor_id, executions["pending"], ids["pending"], "pending", "regression", "selection", inside, "FAIL", 10, 20)
        _run(connection, project_id, actor_id, executions["missed"], ids["missed"], "missed", "regression", "selection", inside, "NOT_RUN", 1, 1)
        _run(connection, project_id, actor_id, executions["trial"], ids["trial"], "trial", "trial", "single", inside, "FAIL", 1, 1)
    return {
        "start": ids["start"],
        "before": ids["before"],
        "end": ids["end"],
        "retry": ids["retry"],
        "retry_execution": executions["retry"],
        "original": ids["original"],
        "original_execution": executions["original"],
        "rerun": ids["rerun"],
        "rerun_execution": executions["rerun"],
        "pending": ids["pending"],
        "missed": ids["missed"],
        "trial": ids["trial"],
    }


def _run(
    connection: sqlite3.Connection,
    project_id: str,
    actor_id: str,
    execution_id: str,
    run_id: str,
    name: str,
    purpose: str,
    source: str,
    stamp: str,
    code: str,
    created_seq: int,
    finalized_seq: int,
) -> str:
    case_id, version_id, job_id = str(uuid4()), str(uuid4()), str(uuid4())
    connection.execute(
        """
        INSERT INTO executions (project_id, execution_id, name, purpose, source, suite_version_id, scope_requested_at)
        VALUES (?, ?, ?, ?, ?, NULL, ?)
        """,
        (project_id, execution_id, name, purpose, source, stamp),
    )
    connection.execute(
        """
        INSERT INTO automation_cases (
            project_id, case_id, name, folder_id, tc_reference, next_revision,
            latest_draft_version_id, current_approval_id, lock_version, archived_at
        ) VALUES (?, ?, ?, NULL, NULL, 2, NULL, NULL, 0, NULL)
        """,
        (project_id, case_id, name),
    )
    connection.execute(
        """
        INSERT INTO case_versions (
            project_id, case_id, version_id, revision, creation_kind, parent_version_id, base_version_id,
            is_branch, definition_json, settings_json, recorded_steps_json, content_hash, verification_digest,
            source_manifest_id, replay_package_id, readiness_json, actor_id, reason, created_at
        ) VALUES (?, ?, ?, 1, 'recorded', NULL, NULL, 0, '{}', '{}', '[]', ?, ?,
            NULL, NULL, '{}', ?, 'recorded', ?)
        """,
        (project_id, case_id, version_id, f"version-{name}", f"digest-{name}", actor_id, stamp),
    )
    connection.execute(
        """
        INSERT INTO case_runs (
            project_id, execution_id, case_run_id, case_id, case_version_id, purpose, requested_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (project_id, execution_id, run_id, case_id, version_id, purpose, stamp),
    )
    connection.execute(
        """
        INSERT INTO jobs (
            project_id, job_id, purpose, recording_id, case_run_id, payload_hash, source_refs, limits, status
        ) VALUES (?, ?, ?, NULL, ?, 'payload', '["source"]', '{}', 'completed')
        """,
        (project_id, job_id, "regression" if purpose != "trial" else "trial", run_id),
    )
    connection.execute(
        """
        INSERT INTO item_finalizations (
            project_id, case_run_id, created_seq, finalized_seq, release_label, content_hash, core_result, denominator
        ) VALUES (?, ?, ?, ?, '', ?, ?, 1)
        """,
        (project_id, run_id, created_seq, finalized_seq, f"{code}:{run_id}", code),
    )
    return job_id


async def _observations(app: object, project_id: str, other_project_id: str):
    import httpx

    origin = "http://127.0.0.1"
    params = {"from": "2026-11-01", "to": "2026-11-02", "as_of": "15"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        headers = await _session(client, origin, project_id, "w2401")
        listed = await client.get(f"/api/v1/projects/{project_id}/observations", params=params, headers=headers)
        other_headers = await _session(client, origin, other_project_id, "w2401-other")
        hidden = await client.get(
            f"/api/v1/projects/{project_id}/observations",
            params=params,
            headers=other_headers,
        )
    assert listed.status_code == 200, listed.text
    return listed.json(), hidden.status_code


async def _session(client: object, origin: str, project_id: str, key: str) -> dict[str, str]:
    issued = await client.post(  # type: ignore[attr-defined]
        "/api/v1/session/nonces",
        json={"origin": origin, "project_id": project_id},
        headers={"Idempotency-Key": key + "-nonce", "Origin": origin},
    )
    booted = await client.post(  # type: ignore[attr-defined]
        "/api/v1/session/bootstrap",
        json={"nonce": issued.json()["nonce"]},
        headers={"Idempotency-Key": key + "-boot", "Origin": origin},
    )
    client.cookies.set("aiqa_session", booted.cookies["aiqa_session"])  # type: ignore[attr-defined]
    return {"Origin": origin, "X-CSRF-Token": booted.json()["csrf_token"], "Idempotency-Key": key}


def test_w24_02() -> None:
    from dataclasses import replace

    from aiqa.contracts.reports import CaseRunFacts
    from aiqa.domain.analytics import latest_terminals
    from aiqa.domain.cohorts import compute_series_key, compute_strict_cohort_key

    base = _cohort()
    relaxed = replace(base, oracle_policy="relaxed")
    procedure = replace(base, verification_digest="procedure-2")
    enabled = replace(base, healing_requested="on")
    unknown = replace(base, model_status="unknown")
    hidden = replace(base, secret_ref="hidden-ref")
    later_build = replace(base, actual_build="build-2", actual_build_seq=20)
    running = replace(
        base,
        status="running",
        item_id="open",
        requested_at="2026-11-01T01:00:00+00:00",
        execution_id="later-run",
    )
    chosen = latest_terminals((base, running), 15)
    observed = {
        "changed_expected_same_series": compute_series_key(base).value == compute_series_key(relaxed).value,
        "on_off_same_strict": compute_strict_cohort_key(base, 15).value == compute_strict_cohort_key(enabled, 15).value,
        "unused_equals_unknown": compute_strict_cohort_key(base, 15).value == compute_strict_cohort_key(unknown, 15).value,
        "latest_terminal_ignores_newer_running": len(chosen) == 1 and chosen[0].item_id == "finished",
    }
    assert compute_series_key(base).value != compute_series_key(procedure).value
    assert compute_series_key(base).value == compute_series_key(enabled).value
    assert compute_series_key(base).value == compute_series_key(hidden).value
    assert compute_strict_cohort_key(base, 15).value == compute_strict_cohort_key(hidden, 15).value
    assert compute_strict_cohort_key(later_build, 15).value == compute_strict_cohort_key(base, 15).value
    assert compute_strict_cohort_key(later_build, 20).value != compute_strict_cohort_key(base, 20).value
    assert compute_series_key(base).schema_version == "canon-json-v1"
    assert observed == {
        "changed_expected_same_series": False,
        "on_off_same_strict": False,
        "unused_equals_unknown": False,
        "latest_terminal_ignores_newer_running": True,
    }


def test_w24_05(tmp_path: Path) -> None:
    from aiqa.api.app import create_app
    from aiqa.config import load_settings
    from aiqa.domain.analytics import ReportSnapshotQuery, clear_report_snapshot_cache, resolve_report_snapshot
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.store.database import migrate_store
    from aiqa.store.models import Actor, ProjectCreate, Transaction

    root = tmp_path / "runtime"
    app = create_app(load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}))
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("과거", "w2405", "사실", "web"))
    store.close()
    database = root / "db" / "aiqa.sqlite"
    _snapshot_graph(database, str(project.project_id), str(owner.actor_id))
    reader = Actor(actor_id=owner.actor_id, project_scope=project.project_id, is_local_owner=True)
    clear_report_snapshot_cache()
    store = app.state.open_store()
    try:
        with store.transaction() as connection:
            tx = Transaction(connection)
            opened = _snap(tx, reader, project.project_id, 15, "criteria-1")
            settled = _snap(tx, reader, project.project_id, 25, "criteria-1")
            billed = _snap(tx, reader, project.project_id, 35, "criteria-1")
            other = _snap(tx, reader, project.project_id, 25, "criteria-2")
    finally:
        store.close()
    connection = sqlite3.connect(database)
    try:
        connection.execute("UPDATE attempt_events SET detail_payload = NULL")
        connection.commit()
        expired = connection.execute("SELECT detail_payload FROM attempt_events").fetchone()
    finally:
        connection.close()
    clear_report_snapshot_cache()
    store = app.state.open_store()
    try:
        with store.transaction() as connection:
            tx = Transaction(connection)
            opened_again = _snap(tx, reader, project.project_id, 15, "criteria-1")
            settled_again = _snap(tx, reader, project.project_id, 25, "criteria-1")
            billed_again = _snap(tx, reader, project.project_id, 35, "criteria-1")
    finally:
        store.close()
    observed = {
        "historical_snapshot_equal": opened == opened_again and settled == settled_again and billed == billed_again,
        "expired_payload_breaks_stats": expired != (None,) or billed_again.denominator != 1 or billed_again.finalized != 1 or billed_again.cost != "1.00",
        "late_usage_rewrites_export": settled_again.cost == "1.00" or settled_again != settled,
    }
    assert opened.in_progress == 1 and opened.finalized == 0 and opened.cost is None
    assert settled.finalized == 1 and settled.content_hashes == ("kept-fail",) and settled.cost is None
    assert billed.fingerprints == ("procedure-1|web|env-a|data-1|strict",)
    assert other.criteria_version == "criteria-2" and other != settled
    assert observed == {
        "historical_snapshot_equal": True,
        "expired_payload_breaks_stats": False,
        "late_usage_rewrites_export": False,
    }


def _snap(tx: object, actor: object, project_id: object, as_of: int, criteria_version: str):
    from aiqa.domain.analytics import ReportSnapshotQuery, resolve_report_snapshot

    return resolve_report_snapshot(
        tx,  # type: ignore[arg-type]
        actor,  # type: ignore[arg-type]
        ReportSnapshotQuery(project_id, as_of, criteria_version),  # type: ignore[arg-type]
    )


def _snapshot_graph(database: Path, project_id: str, actor_id: str) -> None:
    stamp = "2026-08-01T00:00:00+00:00"
    case_id, version_id, execution_id, run_id, job_id, attempt_id = (str(uuid4()) for _ in range(6))
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO executions (project_id, execution_id, name, purpose, source, suite_version_id, scope_requested_at)
            VALUES (?, ?, '과거', 'regression', 'selection', NULL, ?)
            """,
            (project_id, execution_id, stamp),
        )
        connection.execute(
            """
            INSERT INTO automation_cases (
                project_id, case_id, name, folder_id, tc_reference, next_revision,
                latest_draft_version_id, current_approval_id, lock_version, archived_at
            ) VALUES (?, ?, '과거 케이스', NULL, NULL, 2, NULL, NULL, 0, NULL)
            """,
            (project_id, case_id),
        )
        connection.execute(
            """
            INSERT INTO case_versions (
                project_id, case_id, version_id, revision, creation_kind, parent_version_id, base_version_id,
                is_branch, definition_json, settings_json, recorded_steps_json, content_hash, verification_digest,
                source_manifest_id, replay_package_id, readiness_json, actor_id, reason, created_at
            ) VALUES (?, ?, ?, 1, 'recorded', NULL, NULL, 0, '{}', '{}', '[]', 'version-hash', 'procedure-1',
                NULL, NULL, '{}', ?, 'recorded', ?)
            """,
            (project_id, case_id, version_id, actor_id, stamp),
        )
        connection.execute(
            """
            INSERT INTO case_runs (
                project_id, execution_id, case_run_id, case_id, case_version_id, purpose, requested_at
            ) VALUES (?, ?, ?, ?, ?, 'regression', ?)
            """,
            (project_id, execution_id, run_id, case_id, version_id, stamp),
        )
        connection.execute(
            """
            INSERT INTO jobs (
                project_id, job_id, purpose, recording_id, case_run_id, payload_hash, source_refs, limits, status
            ) VALUES (?, ?, 'regression', NULL, ?, 'payload', '["source"]', '{}', 'completed')
            """,
            (project_id, job_id, run_id),
        )
        connection.execute(
            """
            INSERT INTO attempts (project_id, attempt_id, job_id, generation, physical_key_id)
            VALUES (?, ?, ?, 1, NULL)
            """,
            (project_id, attempt_id, job_id),
        )
        connection.execute(
            """
            INSERT INTO attempt_events (
                project_id, event_id, attempt_id, local_seq, captured_at, event_type,
                minimum_facts, payload_hash, body_hash, detail_payload
            ) VALUES (?, ?, ?, 1, ?, 'action', '{"kept":true}', 'payload-hash', 'body-hash', 'day-91-detail')
            """,
            (project_id, str(uuid4()), attempt_id, stamp),
        )
        connection.execute(
            """
            INSERT INTO item_finalizations (
                project_id, case_run_id, created_seq, finalized_seq, release_label, content_hash, core_result, denominator
            ) VALUES (?, ?, 10, 20, '', 'kept-fail', 'FAIL', 1)
            """,
            (project_id, run_id),
        )
        connection.execute(
            """
            INSERT INTO item_lifecycle_events (project_id, event_id, case_run_id, commit_seq, kind)
            VALUES (?, ?, ?, 10, 'created')
            """,
            (project_id, str(uuid4()), run_id),
        )
        connection.execute(
            """
            INSERT INTO item_lifecycle_events (project_id, event_id, case_run_id, commit_seq, kind)
            VALUES (?, ?, ?, 20, 'finalized')
            """,
            (project_id, str(uuid4()), run_id),
        )
        connection.execute(
            """
            INSERT INTO usage_adjustments (
                project_id, adjustment_id, case_run_id, commit_seq, role, measurement_status, amount, currency
            ) VALUES (?, ?, ?, 30, 'verification', 'measured', '1.00', 'USD')
            """,
            (project_id, str(uuid4()), run_id),
        )
        connection.execute(
            """
            INSERT INTO fingerprint_observations (
                project_id, observation_id, case_run_id, case_id, commit_seq, verification_digest,
                target_kind, env_profile_revision, data_fingerprint, oracle_policy, schema_version
            ) VALUES (?, ?, ?, ?, 10, 'procedure-1', 'web', 'env-a', 'data-1', 'strict', 'canon-json-v1')
            """,
            (project_id, str(uuid4()), run_id, case_id),
        )


def _cohort() -> CaseRunFacts:
    from aiqa.contracts.reports import CaseRunFacts

    return CaseRunFacts(
        "FAIL",
        project_id="project-1",
        case_id="case-1",
        verification_digest="procedure-1",
        target_kind="web",
        env_profile_revision="env-1",
        data_fingerprint="data-1",
        oracle_policy="strict",
        model_status="not_used",
        healing_requested="off",
        healing_policy_hash="policy-1",
        execution_id="run-1",
        item_id="finished",
        requested_at="2026-11-01T00:00:00+00:00",
    )
