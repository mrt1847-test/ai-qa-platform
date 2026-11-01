"""An item keeps its first failure and does not replace a missing capture."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from uuid import uuid4


def test_w23_02(tmp_path: Path) -> None:
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
        project = create_project(owner, ProjectCreate("항목", "w2302", "근거", "web"))
        other = create_project(owner, ProjectCreate("다른", "w2302b", "근거", "web"))
    store.close()
    project_id = str(project.project_id)
    database = root / "db" / "aiqa.sqlite"
    seeded = _graph(database, project_id, str(owner.actor_id))
    first, second, attempts, hidden, page = asyncio.run(_read(app, project_id, str(other.project_id), seeded))
    observed = {
        "first_failure_preserved": first["first_failure_attempt_id"] == seeded["first_attempt"] and second["first_failure_attempt_id"] == seeded["first_attempt"] and second["check_status"] == "satisfied",
        "exact_attempt_navigation": first["selected_attempt_id"] == seeded["first_attempt"] and second["selected_attempt_id"] == seeded["second_attempt"] and first["action_id"] == second["action_id"] == "A001",
        "model_render_replaces_capture": first["capture_substituted"] or second["capture_substituted"],
        "evidence_expiry_reason": first["evidence_reason"] == "보관 기한이 지났습니다." and "보관 기한이 지났습니다." in page,
    }
    assert attempts["items"][0]["attempt_id"] == seeded["first_attempt"]
    assert attempts["items"][0]["failed"] is True
    assert attempts["items"][1]["failed"] is False
    assert hidden == 404
    assert "정확한 버전" in page
    assert "첫 실패" in page
    assert "기대와 다릅니다" in page
    assert "원래 lookup은 그대로입니다" in page
    assert "모델 그림으로 바꾸지 않습니다" in page
    assert "PASS" not in page
    assert observed == {
        "first_failure_preserved": True,
        "exact_attempt_navigation": True,
        "model_render_replaces_capture": False,
        "evidence_expiry_reason": True,
    }


def _graph(database: Path, project_id: str, actor_id: str) -> dict[str, str]:
    case_id, version_id = str(uuid4()), str(uuid4())
    execution_id, run_id, job_id = str(uuid4()), str(uuid4()), str(uuid4())
    first_attempt, second_attempt = str(uuid4()), str(uuid4())
    review_id, artifact_id, protection_id, event_id = str(uuid4()), str(uuid4()), str(uuid4()), str(uuid4())
    stamp = "2026-11-01T00:00:00+00:00"
    limits = json.dumps(
        {"data_name": "행-가", "environment_revision_id": "env-1", "build_id": "build-1", "device": "기기-1", "engine": "engine-1", "model": "model-1"},
        ensure_ascii=False,
    )
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO automation_cases (
                project_id, case_id, name, folder_id, tc_reference, next_revision,
                latest_draft_version_id, current_approval_id, lock_version, archived_at
            ) VALUES (?, ?, '로그인 검증', NULL, NULL, 2, NULL, NULL, 0, NULL)
            """,
            (project_id, case_id),
        )
        connection.execute(
            """
            INSERT INTO case_versions (
                project_id, case_id, version_id, revision, creation_kind, parent_version_id, base_version_id,
                is_branch, definition_json, settings_json, recorded_steps_json, content_hash, verification_digest,
                source_manifest_id, replay_package_id, readiness_json, actor_id, reason, created_at
            ) VALUES (?, ?, ?, 1, 'recorded', NULL, NULL, 0, '{}', '{"policy":"계속"}', '[]', 'version-hash', 'digest-w2302',
                NULL, NULL, '{}', ?, 'recorded', ?)
            """,
            (project_id, case_id, version_id, actor_id, stamp),
        )
        connection.execute(
            """
            INSERT INTO executions (project_id, execution_id, name, purpose, source, suite_version_id, scope_requested_at)
            VALUES (?, ?, '항목 수행', 'trial', 'single', NULL, ?)
            """,
            (project_id, execution_id, stamp),
        )
        connection.execute(
            """
            INSERT INTO case_runs (
                project_id, execution_id, case_run_id, case_id, case_version_id, purpose, requested_at
            ) VALUES (?, ?, ?, ?, ?, 'trial', ?)
            """,
            (project_id, execution_id, run_id, case_id, version_id, stamp),
        )
        connection.execute(
            """
            INSERT INTO jobs (
                project_id, job_id, purpose, recording_id, case_run_id, payload_hash, source_refs, limits, status
            ) VALUES (?, ?, 'trial', NULL, ?, 'payload', '[]', ?, 'completed')
            """,
            (project_id, job_id, run_id, limits),
        )
        connection.execute(
            "INSERT INTO attempts (project_id, attempt_id, job_id, generation, physical_key_id) VALUES (?, ?, ?, 1, NULL)",
            (project_id, first_attempt, job_id),
        )
        connection.execute(
            "INSERT INTO attempts (project_id, attempt_id, job_id, generation, physical_key_id) VALUES (?, ?, ?, 2, NULL)",
            (project_id, second_attempt, job_id),
        )
        connection.execute(
            """
            INSERT INTO actions (
                project_id, attempt_id, action_seq, step_id, action_id, package_step_id, proposal_hash,
                dispatch_state, case_id, case_version_id, outcome_known
            ) VALUES (?, ?, 1, 'step-1', 'A001', NULL, 'proposal', 'lookup_failed', ?, ?, 1)
            """,
            (project_id, first_attempt, case_id, version_id),
        )
        connection.execute(
            """
            INSERT INTO actions (
                project_id, attempt_id, action_seq, step_id, action_id, package_step_id, proposal_hash,
                dispatch_state, case_id, case_version_id, outcome_known
            ) VALUES (?, ?, 1, 'step-1', 'A001', NULL, 'proposal', 'observed', ?, ?, 1)
            """,
            (project_id, second_attempt, case_id, version_id),
        )
        connection.execute(
            """
            INSERT INTO check_results (
                project_id, attempt_id, action_id, check_id, status, method, expected_snapshot,
                sanitized_observed, reason, artifact_refs, observed_at
            ) VALUES (?, ?, 'A001', 'check-1', 'violated', 'deterministic', '{}', '{}', '기대와 다릅니다', '[]', ?)
            """,
            (project_id, first_attempt, stamp),
        )
        connection.execute(
            """
            INSERT INTO check_results (
                project_id, attempt_id, action_id, check_id, status, method, expected_snapshot,
                sanitized_observed, reason, artifact_refs, observed_at
            ) VALUES (?, ?, 'A001', 'check-2', 'satisfied', 'deterministic', '{}', '{}', '확인', '[]', ?)
            """,
            (project_id, second_attempt, stamp),
        )
        connection.execute(
            """
            INSERT INTO artifact_refs (
                project_id, artifact_id, attempt_id, action_id, check_id, recording_id, review_id, build_id,
                export_id, package_id, healing_id, proposal_id, resource_observation_id
            ) VALUES (?, ?, ?, 'A001', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL)
            """,
            (project_id, artifact_id, first_attempt),
        )
        connection.execute(
            """
            INSERT INTO reviews (
                project_id, review_id, case_id, case_version_id, version_hash,
                source_manifest_id, trial_case_run_id, evidence_set_hash,
                expected_current_approval_id, created_commit_seq
            ) VALUES (?, ?, ?, ?, 'version-hash', NULL, NULL, 'evidence-hash', NULL, 1)
            """,
            (project_id, review_id, case_id, version_id),
        )
        connection.execute(
            """
            INSERT INTO artifact_protections (
                project_id, protection_id, artifact_id, kind, backup_receipt_id, build_id, manual_request_id
            ) VALUES (?, ?, ?, 'review', NULL, NULL, NULL)
            """,
            (project_id, protection_id, artifact_id),
        )
        connection.execute(
            """
            INSERT INTO review_retention_events (
                project_id, event_id, review_id, protection_id, artifact_id, reason, expires_at, created_at
            ) VALUES (?, ?, ?, ?, ?, '보관 기한이 지났습니다.', '2020-01-01T00:00:00+00:00', ?)
            """,
            (project_id, event_id, review_id, protection_id, artifact_id, stamp),
        )
    return {"run_id": run_id, "first_attempt": first_attempt, "second_attempt": second_attempt}


def test_w23_03(tmp_path: Path) -> None:
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
        project = create_project(owner, ProjectCreate("분석", "w2303", "기록", "web"))
        other = create_project(owner, ProjectCreate("다른", "w2303b", "기록", "web"))
    store.close()
    project_id = str(project.project_id)
    database = root / "db" / "aiqa.sqlite"
    seeded = _analysis_graph(database, project_id, str(owner.actor_id))
    listed, unsafe, hidden, page = asyncio.run(_notes(app, project_id, str(other.project_id), seeded["run_id"]))
    verdict, content_hash, finish = _qa(database, project_id, seeded["run_id"])
    issue_tables = _issue_tables(database)
    comment = listed["items"][0]["comment"]
    observed = {
        "analysis_records": len(listed["items"]),
        "original_verdict": verdict,
        "issue_auto_created": any(item["issue_created"] for item in listed["items"]) or issue_tables != [],
        "unsafe_url_accepted": unsafe < 400,
        "comment_html_escaped": "&lt;script&gt;alert(1)&lt;/script&gt;" in page and "<script>alert(1)</script>" not in page and comment.startswith("<script"),
    }
    assert listed["items"][1]["record_kind"] == "dissent"
    assert listed["items"][1]["prior_record_id"] == listed["items"][0]["record_id"]
    assert content_hash == "qa-hash" and finish == "FAIL"
    assert hidden == 404
    assert "원래 판정은 바꾸지 않습니다." in page
    assert "외부 이슈를 만들지 않습니다." in page
    assert "정정 의견" in page
    assert "PASS" not in page
    assert observed == {
        "analysis_records": 2,
        "original_verdict": "FAIL",
        "issue_auto_created": False,
        "unsafe_url_accepted": False,
        "comment_html_escaped": True,
    }


def _analysis_graph(database: Path, project_id: str, actor_id: str) -> dict[str, str]:
    case_id, version_id = str(uuid4()), str(uuid4())
    execution_id, run_id, job_id = str(uuid4()), str(uuid4()), str(uuid4())
    stamp = "2026-11-01T00:00:00+00:00"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO automation_cases (
                project_id, case_id, name, folder_id, tc_reference, next_revision,
                latest_draft_version_id, current_approval_id, lock_version, archived_at
            ) VALUES (?, ?, '분석 검증', NULL, NULL, 2, NULL, NULL, 0, NULL)
            """,
            (project_id, case_id),
        )
        connection.execute(
            """
            INSERT INTO case_versions (
                project_id, case_id, version_id, revision, creation_kind, parent_version_id, base_version_id,
                is_branch, definition_json, settings_json, recorded_steps_json, content_hash, verification_digest,
                source_manifest_id, replay_package_id, readiness_json, actor_id, reason, created_at
            ) VALUES (?, ?, ?, 1, 'recorded', NULL, NULL, 0, '{}', '{}', '[]', 'version-hash', 'digest-w2303',
                NULL, NULL, '{}', ?, 'recorded', ?)
            """,
            (project_id, case_id, version_id, actor_id, stamp),
        )
        connection.execute(
            """
            INSERT INTO executions (project_id, execution_id, name, purpose, source, suite_version_id, scope_requested_at)
            VALUES (?, ?, '분석 수행', 'regression', 'single', NULL, ?)
            """,
            (project_id, execution_id, stamp),
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
            INSERT INTO job_finish_facts (
                project_id, job_id, verdict, finish_reason, cleanup_failed, resource_state, created_at
            ) VALUES (?, ?, 'FAIL', 'crash', 0, 'unchanged', ?)
            """,
            (project_id, job_id, stamp),
        )
        connection.execute(
            """
            INSERT INTO item_finalizations (
                project_id, case_run_id, created_seq, finalized_seq, release_label, content_hash, core_result, denominator
            ) VALUES (?, ?, 1, 1, '2026-11', 'qa-hash', 'FAIL', 1)
            """,
            (project_id, run_id),
        )
    return {"run_id": run_id}


def _qa(database: Path, project_id: str, run_id: str) -> tuple[str, str, str]:
    with sqlite3.connect(database) as connection:
        final = connection.execute(
            "SELECT core_result, content_hash FROM item_finalizations WHERE project_id = ? AND case_run_id = ?",
            (project_id, run_id),
        ).fetchone()
        finish = connection.execute(
            """
            SELECT job_finish_facts.verdict
            FROM job_finish_facts
            JOIN jobs ON jobs.project_id = job_finish_facts.project_id AND jobs.job_id = job_finish_facts.job_id
            WHERE jobs.project_id = ? AND jobs.case_run_id = ?
            """,
            (project_id, run_id),
        ).fetchone()
    return str(final[0]), str(final[1]), str(finish[0])


def _issue_tables(database: Path) -> list[str]:
    with sqlite3.connect(database) as connection:
        rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE '%issue%'").fetchall()
    return [str(row[0]) for row in rows]


async def _notes(app: object, project_id: str, other_project_id: str, run_id: str):
    import httpx

    origin = "http://127.0.0.1"
    memo = "<script>alert(1)</script>"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        headers = await _session(client, origin, project_id, "w2303")
        headers["Idempotency-Key"] = "w2303-note"
        first = await client.post(
            f"/api/v1/case-runs/{run_id}/analysis-records",
            params={"project_id": project_id},
            json={
                "status": "in_progress",
                "classification": "product",
                "assignee": "담당자",
                "comment": memo,
                "issue_url": "https://example.test/item",
                "record_kind": "analysis",
            },
            headers=headers,
        )
        headers["Idempotency-Key"] = "w2303-dissent"
        second = await client.post(
            f"/api/v1/case-runs/{run_id}/analysis-records",
            params={"project_id": project_id},
            json={
                "status": "resolved",
                "classification": "automation",
                "assignee": "담당자",
                "comment": "정정 의견",
                "issue_url": "http://example.test/note",
                "record_kind": "dissent",
                "prior_record_id": first.json()["record_id"],
            },
            headers=headers,
        )
        headers["Idempotency-Key"] = "w2303-bad-url"
        unsafe = await client.post(
            f"/api/v1/case-runs/{run_id}/analysis-records",
            params={"project_id": project_id},
            json={
                "status": "unclassified",
                "classification": "unclassified",
                "assignee": "담당자",
                "comment": "잘못된 주소",
                "issue_url": "javascript:alert(1)",
                "record_kind": "analysis",
            },
            headers=headers,
        )
        headers["Idempotency-Key"] = "w2303-list"
        listed = await client.get(
            f"/api/v1/case-runs/{run_id}/analysis-records",
            params={"project_id": project_id},
            headers=headers,
        )
        page = await client.get(f"/ui/projects/{project_id}/case-runs/{run_id}/analysis")
        other_headers = await _session(client, origin, other_project_id, "w2303-other")
        other_headers["Idempotency-Key"] = "w2303-hidden"
        hidden = await client.post(
            f"/api/v1/case-runs/{run_id}/analysis-records",
            params={"project_id": other_project_id},
            json={
                "status": "in_progress",
                "classification": "data",
                "assignee": "다른",
                "comment": "다른 프로젝트",
                "issue_url": "https://example.test/other",
            },
            headers=other_headers,
        )
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert listed.status_code == 200, listed.text
    assert page.status_code == 200, page.text
    return listed.json(), unsafe.status_code, hidden.status_code, page.text


async def _read(app: object, project_id: str, other_project_id: str, seeded: dict[str, str]):
    import httpx

    origin = "http://127.0.0.1"
    run_id = seeded["run_id"]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        headers = await _session(client, origin, project_id, "w2302-read")
        first = await client.get(
            f"/api/v1/case-runs/{run_id}",
            params={"project_id": project_id, "attempt": seeded["first_attempt"]},
            headers=headers,
        )
        second = await client.get(
            f"/api/v1/case-runs/{run_id}",
            params={"project_id": project_id, "attempt": seeded["second_attempt"]},
            headers=headers,
        )
        attempts = await client.get(
            f"/api/v1/case-runs/{run_id}/attempts",
            params={"project_id": project_id},
            headers=headers,
        )
        page = await client.get(f"/ui/projects/{project_id}/case-runs/{run_id}?attempt={seeded['first_attempt']}")
        other_headers = await _session(client, origin, other_project_id, "w2302-other")
        hidden = await client.get(
            f"/api/v1/case-runs/{run_id}",
            params={"project_id": other_project_id},
            headers=other_headers,
        )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert attempts.status_code == 200, attempts.text
    assert page.status_code == 200, page.text
    return first.json(), second.json(), attempts.json(), hidden.status_code, page.text


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


def test_w23_04(tmp_path: Path) -> None:
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
        project = create_project(owner, ProjectCreate("리포트", "w2304", "보고", "web"))
        other = create_project(owner, ProjectCreate("다른", "w2304b", "보고", "web"))
    store.close()
    project_id = str(project.project_id)
    database = root / "db" / "aiqa.sqlite"
    satisfied = item_result(FailureLatch().value, True, None)
    seeded = _report_graph(database, project_id, str(owner.actor_id), satisfied)
    listed, trial_list, empty, report, single, interim, hidden, page, list_page, interim_page = asyncio.run(
        _reports(app, project_id, str(other.project_id), seeded)
    )
    observed = {
        "n10_rates": report["rates"],
        "trial_default_included": seeded["trial"] in {item["execution_id"] for item in listed["items"]},
        "rec_included": any(item["purpose"] == "recording" or item["source"] == "recording" for item in listed["items"]),
        "interim_report_labeled": interim["interim"] is True and "중간 보고" in interim_page,
    }
    assert report["n"] == 10 and report["unverified"] == 2 and report["exclusion_outside"] == 0
    assert single["n"] == 1 and single["first_attempt_id"] != single["latest_attempt_id"]
    assert single["analysis_count"] == 1 and single["issue_url"] == "https://example.test/item"
    assert empty["n"] == 0 and empty["rates"] is None
    assert listed["items"] != [] and trial_list["items"] == []
    assert "시범을 포함했습니다." in list_page
    assert "녹화는 포함하지 않습니다." in list_page
    assert "목록으로" in page and "purpose=regression" in page
    assert "https://example.test/item" in page
    assert "2026-11-01 09:00 KST" in page
    assert "확정 전 제외는 분모 밖에 있습니다." in page
    assert "원본과 다른 새 수행입니다." in page
    assert "시범" in list_page
    assert "PASS" not in page and "PASS" not in list_page and "PASS" not in interim_page
    assert hidden == 404
    assert observed == {
        "n10_rates": [1, 0.75, 0.6],
        "trial_default_included": False,
        "rec_included": False,
        "interim_report_labeled": True,
    }


def _report_graph(database: Path, project_id: str, actor_id: str, satisfied: str) -> dict[str, str]:
    stamp = "2026-11-01T00:00:00+00:00"
    wide = str(uuid4())
    single = str(uuid4())
    interim = str(uuid4())
    empty = str(uuid4())
    trial = str(uuid4())
    codes = [satisfied] * 6 + ["FAIL", "FAIL", "BLOCKED", "NOT_RUN"]
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        _execution(connection, project_id, wide, "열 개", "regression", "selection", stamp)
        for index, code in enumerate(codes):
            _item(connection, project_id, actor_id, wide, f"wide-{index}", code, stamp, index == 0)
        _execution(connection, project_id, single, "하나", "regression", "rerun", stamp)
        single_run = _item(connection, project_id, actor_id, single, "single", "FAIL", stamp, True)
        connection.execute(
            """
            INSERT INTO analysis_records (project_id, record_id, case_run_id, commit_seq, body)
            VALUES (?, ?, ?, 1, ?)
            """,
            (
                project_id,
                str(uuid4()),
                single_run,
                json.dumps({"issue_url": "https://example.test/item", "comment": "분석"}, ensure_ascii=False),
            ),
        )
        job_id = connection.execute("SELECT job_id FROM jobs WHERE case_run_id = ?", (single_run,)).fetchone()
        first_attempt, second_attempt = str(uuid4()), str(uuid4())
        connection.execute(
            "INSERT INTO attempts (project_id, attempt_id, job_id, generation, physical_key_id) VALUES (?, ?, ?, 1, NULL)",
            (project_id, first_attempt, str(job_id[0])),
        )
        connection.execute(
            "INSERT INTO attempts (project_id, attempt_id, job_id, generation, physical_key_id) VALUES (?, ?, ?, 2, NULL)",
            (project_id, second_attempt, str(job_id[0])),
        )
        _execution(connection, project_id, interim, "진행", "regression", "single", stamp)
        _item(connection, project_id, actor_id, interim, "open", None, stamp, False)
        _execution(connection, project_id, empty, "빈 수행", "regression", "single", stamp)
        _execution(connection, project_id, trial, "시범", "trial", "single", stamp)
        _item(connection, project_id, actor_id, trial, "trial", "FAIL", stamp, False)
        case_id = connection.execute("SELECT case_id FROM case_runs WHERE case_run_id = ?", (single_run,)).fetchone()
        version_id = connection.execute("SELECT case_version_id FROM case_runs WHERE case_run_id = ?", (single_run,)).fetchone()
        recording_id = str(uuid4())
        connection.execute(
            """
            INSERT INTO recordings (
                project_id, case_id, recording_id, creation_kind, input_case_version_id, storage_status,
                stop_status, completion_status, evidence_status
            ) VALUES (?, ?, ?, 'recorded', ?, 'stored', 'stopped', 'completed', 'complete')
            """,
            (project_id, str(case_id[0]), recording_id, str(version_id[0])),
        )
        connection.execute(
            """
            INSERT INTO jobs (
                project_id, job_id, purpose, recording_id, case_run_id, payload_hash, source_refs, limits, status
            ) VALUES (?, ?, 'recording', ?, NULL, 'payload', '["source"]', '{}', 'completed')
            """,
            (project_id, str(uuid4()), recording_id),
        )
    return {"wide": wide, "single": single, "interim": interim, "empty": empty, "trial": trial}


def _execution(connection: sqlite3.Connection, project_id: str, execution_id: str, name: str, purpose: str, source: str, stamp: str) -> None:
    connection.execute(
        """
        INSERT INTO executions (project_id, execution_id, name, purpose, source, suite_version_id, scope_requested_at)
        VALUES (?, ?, ?, ?, ?, NULL, ?)
        """,
        (project_id, execution_id, name, purpose, source, stamp),
    )


def _item(
    connection: sqlite3.Connection,
    project_id: str,
    actor_id: str,
    execution_id: str,
    name: str,
    code: str | None,
    stamp: str,
    with_job: bool,
) -> str:
    case_id, version_id, run_id = str(uuid4()), str(uuid4()), str(uuid4())
    purpose = connection.execute("SELECT purpose FROM executions WHERE execution_id = ?", (execution_id,)).fetchone()
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
        ) VALUES (?, ?, ?, 1, 'recorded', NULL, NULL, 0, '{}', '{}', '[]', 'version-hash', ?,
            NULL, NULL, '{}', ?, 'recorded', ?)
        """,
        (project_id, case_id, version_id, f"digest-{name}", actor_id, stamp),
    )
    connection.execute(
        """
        INSERT INTO case_runs (
            project_id, execution_id, case_run_id, case_id, case_version_id, purpose, requested_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (project_id, execution_id, run_id, case_id, version_id, str(purpose[0]), stamp),
    )
    if with_job:
        connection.execute(
            """
            INSERT INTO jobs (
                project_id, job_id, purpose, recording_id, case_run_id, payload_hash, source_refs, limits, status
            ) VALUES (?, ?, ?, NULL, ?, 'payload', '["source"]', '{"environment":"web"}', 'completed')
            """,
            (project_id, str(uuid4()), "regression" if str(purpose[0]) != "trial" else "trial", run_id),
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
    return run_id


async def _reports(app: object, project_id: str, other_project_id: str, seeded: dict[str, str]):
    import httpx

    origin = "http://127.0.0.1"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        headers = await _session(client, origin, project_id, "w2304")
        listed = await client.get(f"/api/v1/projects/{project_id}/reports", headers=headers)
        empty_filter = await client.get(
            f"/api/v1/projects/{project_id}/reports",
            params={"purpose": "reverification"},
            headers=headers,
        )
        report = await client.get(
            f"/api/v1/executions/{seeded['wide']}/report",
            params={"project_id": project_id},
            headers=headers,
        )
        single = await client.get(
            f"/api/v1/executions/{seeded['single']}/report",
            params={"project_id": project_id},
            headers=headers,
        )
        interim = await client.get(
            f"/api/v1/executions/{seeded['interim']}/report",
            params={"project_id": project_id},
            headers=headers,
        )
        empty = await client.get(
            f"/api/v1/executions/{seeded['empty']}/report",
            params={"project_id": project_id},
            headers=headers,
        )
        page = await client.get(f"/ui/projects/{project_id}/executions/{seeded['single']}/report?purpose=regression")
        interim_page = await client.get(f"/ui/projects/{project_id}/executions/{seeded['interim']}/report")
        list_page = await client.get(f"/ui/projects/{project_id}/reports?include_trial=1")
        other_headers = await _session(client, origin, other_project_id, "w2304-other")
        hidden = await client.get(
            f"/api/v1/executions/{seeded['wide']}/report",
            params={"project_id": other_project_id},
            headers=other_headers,
        )
    assert listed.status_code == 200, listed.text
    assert report.status_code == 200, report.text
    assert single.status_code == 200, single.text
    assert interim.status_code == 200, interim.text
    assert empty.status_code == 200, empty.text
    assert page.status_code == 200, page.text
    assert interim_page.status_code == 200, interim_page.text
    assert list_page.status_code == 200, list_page.text
    return (
        listed.json(),
        empty_filter.json(),
        empty.json(),
        report.json(),
        single.json(),
        interim.json(),
        hidden.status_code,
        page.text,
        list_page.text,
        interim_page.text,
    )


def test_w23_05(tmp_path: Path) -> None:
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
        project = create_project(owner, ProjectCreate("측정", "w2305", "보고", "web"))
    store.close()
    project_id = str(project.project_id)
    satisfied = item_result(FailureLatch().value, True, None)
    seeded = _assistance_graph(root / "db" / "aiqa.sqlite", project_id, str(owner.actor_id), satisfied)
    report, page, item_page = asyncio.run(_assistance(app, project_id, seeded))
    buckets = page.count("<li>")
    observed = {
        "pass_bucket": report["pass_bucket"],
        "healed_pass": report["healed_pass"],
        "unassisted_pass": report["unassisted_pass"],
        "terminal_bucket_count": report["terminal_bucket_count"],
        "missing_usage_display": report["missing_usage_display"],
    }
    assert report["action_retry"] == 1 and report["verifier_used"] == 1
    assert "치유 성공 1" in report["episode_result"]
    assert buckets == 8
    assert "끝 구분 7" in page and "도움 없이 만족 4" in page and "치유를 사용한 만족 1" in page
    assert "측정 partial" in page and "검증 역할은 따로 셉니다." in page
    assert "미사용은 불명과 다릅니다." in page and "원래 오류는 치유 결과와 따로 남습니다." in page
    assert "치유를 사용한 만족입니다." in item_page and "측정 null" in item_page
    assert "PASS" not in page and "PASS" not in item_page
    assert observed == {
        "pass_bucket": 6,
        "healed_pass": 1,
        "unassisted_pass": 4,
        "terminal_bucket_count": 7,
        "missing_usage_display": "partial",
    }


def _assistance_graph(database: Path, project_id: str, actor_id: str, satisfied: str) -> dict[str, str]:
    stamp = "2026-11-01T00:00:00+00:00"
    execution_id = str(uuid4())
    healed = str(uuid4())
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO executions (project_id, execution_id, name, purpose, source, suite_version_id, scope_requested_at)
            VALUES (?, ?, '측정', 'regression', 'selection', NULL, ?)
            """,
            (project_id, execution_id, stamp),
        )
        verifier = _plain_item(connection, project_id, actor_id, execution_id, "verifier", satisfied, stamp)
        _model_call(connection, project_id, verifier, "verification", "measured", 3)
        for index in range(3):
            _plain_item(connection, project_id, actor_id, execution_id, f"plain-{index}", satisfied, stamp)
        healed_ids = _plain_item(connection, project_id, actor_id, execution_id, "healed", satisfied, stamp)
        healed = healed_ids["case_run_id"]
        _model_call(connection, project_id, healed_ids, "healing", "unreported", None)
        retry = _plain_item(connection, project_id, actor_id, execution_id, "retry", satisfied, stamp)
        connection.execute(
            """
            INSERT INTO attempt_events (
                project_id, event_id, attempt_id, local_seq, captured_at, event_type,
                minimum_facts, payload_hash, body_hash, detail_payload
            ) VALUES (?, ?, ?, 1, ?, 'action_retry', '{}', 'payload', 'body', NULL)
            """,
            (project_id, str(uuid4()), retry["attempt_id"], stamp),
        )
    return {"execution": execution_id, "healed": healed}


def _plain_item(
    connection: sqlite3.Connection,
    project_id: str,
    actor_id: str,
    execution_id: str,
    name: str,
    code: str,
    stamp: str,
) -> dict[str, str]:
    case_id, version_id, run_id, job_id, attempt_id = (str(uuid4()) for _ in range(5))
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
        INSERT INTO item_finalizations (
            project_id, case_run_id, created_seq, finalized_seq, release_label, content_hash, core_result, denominator
        ) VALUES (?, ?, 1, 1, '2026-11', ?, ?, 1)
        """,
        (project_id, run_id, f"{code}:{run_id}", code),
    )
    return {"case_run_id": run_id, "case_id": case_id, "version_id": version_id, "attempt_id": attempt_id}


def _model_call(
    connection: sqlite3.Connection,
    project_id: str,
    item: dict[str, str],
    role: str,
    measurement: str,
    tokens: int | None,
) -> None:
    action_id = str(uuid4())
    connection.execute(
        """
        INSERT INTO actions (
            project_id, attempt_id, action_seq, step_id, action_id, package_step_id,
            proposal_hash, dispatch_state, case_id, case_version_id, outcome_known
        ) VALUES (?, ?, 1, 'step', ?, NULL, 'proposal', 'observed', ?, ?, 1)
        """,
        (project_id, item["attempt_id"], action_id, item["case_id"], item["version_id"]),
    )
    connection.execute(
        """
        INSERT INTO model_call_facts (
            project_id, call_id, attempt_id, role, action_id, check_id, measurement_status,
            input_tokens, output_tokens, cache_tokens, image_tokens
        ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, NULL, NULL)
        """,
        (project_id, str(uuid4()), item["attempt_id"], role, action_id, measurement, tokens, 0 if tokens is not None else None),
    )


async def _assistance(app: object, project_id: str, seeded: dict[str, str]):
    import httpx

    origin = "http://127.0.0.1"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        headers = await _session(client, origin, project_id, "w2305")
        report = await client.get(
            f"/api/v1/executions/{seeded['execution']}/report",
            params={"project_id": project_id},
            headers=headers,
        )
        page = await client.get(f"/ui/projects/{project_id}/executions/{seeded['execution']}/report")
        item_page = await client.get(f"/ui/projects/{project_id}/case-runs/{seeded['healed']}")
    assert report.status_code == 200, report.text
    assert page.status_code == 200, page.text
    assert item_page.status_code == 200, item_page.text
    return report.json(), page.text, item_page.text
