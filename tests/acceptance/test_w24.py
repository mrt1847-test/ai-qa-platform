"""Cumulative analytics keeps an empty sample empty and leaves a late cost out."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from uuid import uuid4


def test_w24_03(tmp_path: Path) -> None:
    import asyncio

    from aiqa.api.app import create_app
    from aiqa.config import load_settings
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.store.database import migrate_store
    from aiqa.store.models import Actor, ProjectCreate

    root = tmp_path / "runtime"
    app = create_app(load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}))
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("분석", "w2403", "추세", "web"))
    store.close()
    project_id = str(project.project_id)
    seeded = _analytics_graph(root / "db" / "aiqa.sqlite", project_id, str(owner.actor_id))
    listed, empty, page = asyncio.run(_analytics(app, project_id, seeded))
    observed = {
        "no_sample_rates": empty["rates"],
        "not_run_duration": listed["not_run_duration"],
        "filters_preserved": all(
            token in page
            for token in (seeded["case"], "regression", "2026-11-01", "2026-11-02", "all_observations", "15")
        ),
        "late_usage_asof_respected": listed["cost"] == "1.00" and "9.00" not in str(listed["cost"]),
    }
    assert listed["sample_count"] == 4 and listed["condition_count"] == 2
    assert listed["p50"] == 100 and listed["p95"] == 200
    assert "실행하지 않은 항목의 시간은 비어 있습니다" in page
    assert "빈 표본은 비율을 내지 않습니다" not in page
    assert "늦은 비용은 기준 시각 뒤에 더하지 않습니다" in page
    assert "PASS" not in page
    assert observed == {
        "no_sample_rates": None,
        "not_run_duration": None,
        "filters_preserved": True,
        "late_usage_asof_respected": True,
    }


def _analytics_graph(database: Path, project_id: str, actor_id: str) -> dict[str, str]:
    stamp = "2026-11-01T00:00:00+00:00"
    execution_id, case_id, version_id = str(uuid4()), str(uuid4()), str(uuid4())
    env_a, env_b = str(uuid4()), str(uuid4())
    missed, running, failed, other = (
        "00000000-0000-4000-8000-000000000001",
        "00000000-0000-4000-8000-000000000002",
        "00000000-0000-4000-8000-000000000003",
        "00000000-0000-4000-8000-000000000004",
    )
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO executions (project_id, execution_id, name, purpose, source, suite_version_id, scope_requested_at)
            VALUES (?, ?, '분석', 'regression', 'selection', NULL, ?)
            """,
            (project_id, execution_id, stamp),
        )
        connection.execute(
            """
            INSERT INTO automation_cases (
                project_id, case_id, name, folder_id, tc_reference, next_revision,
                latest_draft_version_id, current_approval_id, lock_version, archived_at
            ) VALUES (?, ?, '분석 케이스', NULL, NULL, 2, NULL, NULL, 0, NULL)
            """,
            (project_id, case_id),
        )
        connection.execute(
            """
            INSERT INTO case_versions (
                project_id, case_id, version_id, revision, creation_kind, parent_version_id, base_version_id,
                is_branch, definition_json, settings_json, recorded_steps_json, content_hash, verification_digest,
                source_manifest_id, replay_package_id, readiness_json, actor_id, reason, created_at
            ) VALUES (?, ?, ?, 1, 'recorded', NULL, NULL, 0, '{}', '{}', '[]', 'hash-analytics', 'digest-analytics',
                NULL, NULL, '{}', ?, 'recorded', ?)
            """,
            (project_id, case_id, version_id, actor_id, stamp),
        )
        _item(connection, project_id, execution_id, failed, case_id, version_id, stamp, env_a, 100, "FAIL")
        _item(connection, project_id, execution_id, missed, case_id, version_id, stamp, env_a, 99, "NOT_RUN")
        _item(connection, project_id, execution_id, running, case_id, version_id, stamp, env_a, None, None)
        _item(connection, project_id, execution_id, other, case_id, version_id, stamp, env_b, 200, "FAIL")
        connection.execute(
            """
            INSERT INTO usage_adjustments (
                project_id, adjustment_id, case_run_id, commit_seq, role, measurement_status, amount, currency
            ) VALUES (?, ?, ?, 10, 'verification', 'measured', '1.00', 'USD')
            """,
            (project_id, str(uuid4()), failed),
        )
        connection.execute(
            """
            INSERT INTO usage_adjustments (
                project_id, adjustment_id, case_run_id, commit_seq, role, measurement_status, amount, currency
            ) VALUES (?, ?, ?, 20, 'verification', 'measured', '9.00', 'USD')
            """,
            (project_id, str(uuid4()), failed),
        )
    return {"case": case_id}


def _item(
    connection: sqlite3.Connection,
    project_id: str,
    execution_id: str,
    run_id: str,
    case_id: str,
    version_id: str,
    stamp: str,
    environment: str,
    duration: int | None,
    code: str | None,
) -> None:
    limits = {
        "environment_revision_id": environment,
        "data_fingerprint": "data-1",
        "build_id": "build-1",
        "model_status": "not_used",
        "release_label": "2026-11",
        "duration_ms": duration,
    }
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
        ) VALUES (?, ?, 'regression', NULL, ?, 'payload', '["source"]', ?, ?)
        """,
        (project_id, str(uuid4()), run_id, json.dumps(limits), "completed" if code else "running"),
    )
    if code is not None:
        connection.execute(
            """
            INSERT INTO item_finalizations (
                project_id, case_run_id, created_seq, finalized_seq, release_label, content_hash, core_result, denominator
            ) VALUES (?, ?, 1, 1, '2026-11', ?, ?, 1)
            """,
            (project_id, run_id, f"{code}:{run_id}", code),
        )


async def _analytics(app: object, project_id: str, seeded: dict[str, str]):
    import httpx

    origin = "http://127.0.0.1"
    params = {
        "from": "2026-11-01",
        "to": "2026-11-02",
        "as_of": "15",
        "purpose": "regression",
        "case": seeded["case"],
        "criteria": "all_observations",
    }
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        headers = await _session(client, origin, project_id, "w2403")
        listed = await client.get(f"/api/v1/projects/{project_id}/analytics", params=params, headers=headers)
        empty = await client.get(
            f"/api/v1/projects/{project_id}/analytics",
            params={**params, "case": "missing-case"},
            headers=headers,
        )
        page = await client.get(f"/ui/projects/{project_id}/analytics", params=params)
    assert listed.status_code == 200, listed.text
    assert empty.status_code == 200, empty.text
    assert page.status_code == 200, page.text
    return listed.json(), empty.json(), page.text


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


def test_w24_04(tmp_path: Path) -> None:
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
        project = create_project(owner, ProjectCreate("비교", "w2404", "수행", "web"))
    store.close()
    project_id = str(project.project_id)
    database = root / "db" / "aiqa.sqlite"
    seeded = _comparison_graph(database, project_id, str(owner.actor_id), item_result(FailureLatch().value, True, None))
    before = _stored_hash(database, seeded["failed"])
    compared, page = asyncio.run(_compare(app, project_id, seeded))
    after = _stored_hash(database, seeded["failed"])
    changed = next(pair for pair in compared["pairs"] if pair["kind"] == "changed")
    observed = {
        "condition_difference_visible": {"environment", "build", "expected"}.issubset(changed["condition_fields"]),
        "changed_verification_separate": changed["separate_series"] is True,
        "mixed_banner": compared["mixed"] is True and compared["constituent_count"] > 1,
        "original_fail_preserved": compared["original_fail_preserved"] is True and before == after == "kept-fail",
    }
    assert compared["confirmed_improvements"] == 0 and compared["confirmed_regressions"] == 0
    assert changed["baseline"]["result_label"] == "실패" and changed["candidate"]["result_label"] == "만족"
    assert changed["baseline"]["capture"] == "화면이 없습니다" and changed["baseline"]["cost"] == "1.00"
    assert any(pair["kind"] == "continued_failure" for pair in compared["pairs"])
    assert any(pair["kind"] == "added" for pair in compared["pairs"])
    assert any(pair["kind"] == "removed" for pair in compared["pairs"])
    assert "조건이 섞였습니다" in page and "절차가 바뀌어 다른 비교입니다." in page
    assert "원본 실패는 그대로입니다." in page and "PASS" not in page and "PASS" not in json.dumps(compared)
    assert observed == {
        "condition_difference_visible": True,
        "changed_verification_separate": True,
        "mixed_banner": True,
        "original_fail_preserved": True,
    }


def _comparison_graph(database: Path, project_id: str, actor_id: str, satisfied: str) -> dict[str, str]:
    stamp = "2026-11-01T00:00:00+00:00"
    case_id = str(uuid4())
    baseline_id, candidate_id = str(uuid4()), str(uuid4())
    version_a, version_b, version_same = str(uuid4()), str(uuid4()), str(uuid4())
    failed = str(uuid4())
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO automation_cases (
                project_id, case_id, name, folder_id, tc_reference, next_revision,
                latest_draft_version_id, current_approval_id, lock_version, archived_at
            ) VALUES (?, ?, '비교 케이스', NULL, NULL, 2, NULL, NULL, 0, NULL)
            """,
            (project_id, case_id),
        )
        _version(connection, project_id, case_id, version_a, 1, "procedure-1", actor_id, stamp)
        _version(connection, project_id, case_id, version_b, 2, "procedure-2", actor_id, stamp)
        _version(connection, project_id, case_id, version_same, 3, "procedure-same", actor_id, stamp)
        _execution(connection, project_id, baseline_id, "기준", stamp)
        _execution(connection, project_id, candidate_id, "비교", stamp)
        _compared_item(
            connection, project_id, baseline_id, failed, case_id, version_a, stamp,
            {"data_fingerprint": "data-1", "target_kind": "web", "environment_revision_id": "env-a", "build_id": "build-1", "oracle_policy": "strict", "healing_requested": "off", "step_id": "단계-1", "observed": "원래", "duration_ms": 10, "model_status": "not_used"},
            "FAIL", "kept-fail",
        )
        connection.execute(
            """
            INSERT INTO usage_adjustments (
                project_id, adjustment_id, case_run_id, commit_seq, role, measurement_status, amount, currency
            ) VALUES (?, ?, ?, 10, 'verification', 'measured', '1.00', 'USD')
            """,
            (project_id, str(uuid4()), failed),
        )
        _compared_item(
            connection, project_id, candidate_id, str(uuid4()), case_id, version_b, stamp,
            {"data_fingerprint": "data-1", "target_kind": "web", "environment_revision_id": "env-b", "build_id": "build-2", "oracle_policy": "relaxed", "healing_requested": "on", "step_id": "단계-2", "observed": "다음", "duration_ms": 20, "model_status": "not_used"},
            satisfied, f"next-{satisfied}",
        )
        _compared_item(
            connection, project_id, baseline_id, str(uuid4()), case_id, version_same, stamp,
            {"data_fingerprint": "data-keep", "target_kind": "web", "environment_revision_id": "env-a", "build_id": "build-1", "oracle_policy": "strict", "healing_requested": "off", "model_status": "not_used"},
            "FAIL", "kept-same",
        )
        _compared_item(
            connection, project_id, candidate_id, str(uuid4()), case_id, version_same, stamp,
            {"data_fingerprint": "data-keep", "target_kind": "web", "environment_revision_id": "env-a", "build_id": "build-1", "oracle_policy": "strict", "healing_requested": "off", "model_status": "not_used"},
            "FAIL", "kept-same-new",
        )
        _compared_item(
            connection, project_id, baseline_id, str(uuid4()), case_id, version_a, stamp,
            {"data_fingerprint": "data-only-base", "target_kind": "web", "environment_revision_id": "env-a", "oracle_policy": "strict", "healing_requested": "off", "model_status": "not_used"},
            "FAIL", "only-base",
        )
        _compared_item(
            connection, project_id, candidate_id, str(uuid4()), case_id, version_b, stamp,
            {"data_fingerprint": "data-only-new", "target_kind": "web", "environment_revision_id": "env-b", "oracle_policy": "relaxed", "healing_requested": "on", "model_status": "not_used"},
            "FAIL", "only-new",
        )
    return {"baseline": baseline_id, "candidate": candidate_id, "failed": failed}


def _execution(connection: sqlite3.Connection, project_id: str, execution_id: str, name: str, stamp: str) -> None:
    connection.execute(
        """
        INSERT INTO executions (project_id, execution_id, name, purpose, source, suite_version_id, scope_requested_at)
        VALUES (?, ?, ?, 'regression', 'selection', NULL, ?)
        """,
        (project_id, execution_id, name, stamp),
    )


def _version(
    connection: sqlite3.Connection,
    project_id: str,
    case_id: str,
    version_id: str,
    revision: int,
    digest: str,
    actor_id: str,
    stamp: str,
) -> None:
    connection.execute(
        """
        INSERT INTO case_versions (
            project_id, case_id, version_id, revision, creation_kind, parent_version_id, base_version_id,
            is_branch, definition_json, settings_json, recorded_steps_json, content_hash, verification_digest,
            source_manifest_id, replay_package_id, readiness_json, actor_id, reason, created_at
        ) VALUES (?, ?, ?, ?, 'recorded', NULL, NULL, 0, '{}', '{}', '[]', ?, ?,
            NULL, NULL, '{}', ?, 'recorded', ?)
        """,
        (project_id, case_id, version_id, revision, f"hash-{digest}", digest, actor_id, stamp),
    )


def _compared_item(
    connection: sqlite3.Connection,
    project_id: str,
    execution_id: str,
    run_id: str,
    case_id: str,
    version_id: str,
    stamp: str,
    limits: dict[str, object],
    code: str,
    content_hash: str,
) -> None:
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
        ) VALUES (?, ?, 'regression', NULL, ?, 'payload', '["source"]', ?, 'completed')
        """,
        (project_id, str(uuid4()), run_id, json.dumps(limits)),
    )
    connection.execute(
        """
        INSERT INTO item_finalizations (
            project_id, case_run_id, created_seq, finalized_seq, release_label, content_hash, core_result, denominator
        ) VALUES (?, ?, 1, 1, '', ?, ?, 1)
        """,
        (project_id, run_id, content_hash, code),
    )


def _stored_hash(database: Path, case_run_id: str) -> str:
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT content_hash, core_result FROM item_finalizations WHERE case_run_id = ?",
            (case_run_id,),
        ).fetchone()
    assert row is not None and str(row[1]) == "FAIL"
    return str(row[0])


async def _compare(app: object, project_id: str, seeded: dict[str, str]):
    import httpx

    origin = "http://127.0.0.1"
    params = {"baseline": seeded["baseline"], "candidate": seeded["candidate"], "as_of": "15"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        headers = await _session(client, origin, project_id, "w2404")
        compared = await client.get(
            f"/api/v1/projects/{project_id}/execution-comparisons",
            params=params,
            headers=headers,
        )
        page = await client.get(f"/ui/projects/{project_id}/execution-comparisons", params=params)
    assert compared.status_code == 200, compared.text
    assert page.status_code == 200, page.text
    return compared.json(), page.text
