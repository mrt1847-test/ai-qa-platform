"""Execution and item cancellation."""

from __future__ import annotations

from worker_presence_support import seed_presence

import json
import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


def test_w22_01(tmp_path: Path) -> None:
    import asyncio

    from aiqa.api.app import create_app
    from aiqa.config import load_settings
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.store.database import migrate_store
    from aiqa.store.models import Actor, ProjectCreate
    from aiqa.store.queue import finish_job

    root = tmp_path / "runtime"
    app = create_app(load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}))
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("취소", "w2201", "수행", "web"))
        other = create_project(owner, ProjectCreate("다른", "w2201b", "수행", "web"))
    store.close()
    project_id = str(project.project_id)
    seeded = _cancel_graph(root / "db" / "aiqa.sqlite", project_id, str(owner.actor_id))
    before = _result_hash(root / "db" / "aiqa.sqlite", seeded["done"])
    item, item_again, execution, execution_again, hidden, page, denied = asyncio.run(
        _cancel(app, project_id, str(other.project_id), seeded)
    )
    store = app.state.open_store()
    with store.transaction() as connection:
        raced = finish_job(connection, project.project_id, seeded["running_job"])
    store.close()
    after = _result_hash(root / "db" / "aiqa.sqlite", seeded["done"])
    queued = _core(root / "db" / "aiqa.sqlite", seeded["queued"])
    observed = {
        "violation_then_cancel": execution["preserved_result"],
        "done_item_changed": before != after,
        "duplicate_cancel_effects": execution_again["effects"],
    }
    assert item["phase"] == "requested" and item["replayed"] is False
    assert item_again["replayed"] is True and item_again["effects"] == 1
    assert raced == "cancel_requested"
    assert queued == "CANCELLED"
    assert denied == 409
    assert hidden == 404
    assert "취소 요청" in page and "정지" in page and "정리" in page
    assert "전체 취소" in page and "항목 취소" in page
    assert "완료된 항목은 바꾸지 않습니다." in page and "실패는 유지합니다." in page
    assert "PASS" not in page
    assert observed == {
        "violation_then_cancel": "FAIL",
        "done_item_changed": False,
        "duplicate_cancel_effects": 1,
    }


def _cancel_graph(database: Path, project_id: str, actor_id: str) -> dict[str, object]:
    stamp = "2026-11-01T00:00:00+00:00"
    execution_id, done, running, queued = str(uuid4()), str(uuid4()), str(uuid4()), str(uuid4())
    running_job = str(uuid4())
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO executions (project_id, execution_id, name, purpose, source, suite_version_id, scope_requested_at)
            VALUES (?, ?, '경합', 'regression', 'selection', NULL, ?)
            """,
            (project_id, execution_id, stamp),
        )
        _item(connection, project_id, actor_id, execution_id, done, "done", "completed", "FAIL", "kept-result", stamp)
        _item(connection, project_id, actor_id, execution_id, running, "running", "running", None, "", stamp, running_job)
        _item(connection, project_id, actor_id, execution_id, queued, "queued", "queued", None, "", stamp)
    return {
        "execution": execution_id,
        "done": done,
        "running": running,
        "running_job": __import__("uuid").UUID(running_job),
        "queued": queued,
    }


def _item(
    connection: sqlite3.Connection,
    project_id: str,
    actor_id: str,
    execution_id: str,
    run_id: str,
    name: str,
    status: str,
    code: str | None,
    content_hash: str,
    stamp: str,
    job_id: str | None = None,
) -> None:
    case_id, version_id = str(uuid4()), str(uuid4())
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
        ) VALUES (?, ?, 'regression', NULL, ?, 'payload', '["source"]', ?, ?)
        """,
        (
            project_id,
            job_id or str(uuid4()),
            run_id,
            json.dumps({"failure_policy": "stop_on_non_pass", "environment": "web"}, ensure_ascii=False),
            status,
        ),
    )
    if code is not None:
        connection.execute(
            """
            INSERT INTO item_finalizations (
                project_id, case_run_id, created_seq, finalized_seq, release_label, content_hash, core_result, denominator
            ) VALUES (?, ?, 1, 1, '2026-11', ?, ?, 1)
            """,
            (project_id, run_id, content_hash, code),
        )


def _result_hash(database: Path, case_run_id: str) -> str:
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT content_hash, core_result FROM item_finalizations WHERE case_run_id = ?",
            (case_run_id,),
        ).fetchone()
    assert row is not None and str(row[1]) == "FAIL"
    return str(row[0])


def _core(database: Path, case_run_id: str) -> str:
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT core_result FROM item_finalizations WHERE case_run_id = ?",
            (case_run_id,),
        ).fetchone()
    assert row is not None
    return str(row[0])


async def _cancel(app: object, project_id: str, other_project_id: str, seeded: dict[str, object]):
    import httpx

    origin = "http://127.0.0.1"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        headers = await _session(client, origin, project_id, "w2201")
        item = await client.post(
            f"/api/v1/case-runs/{seeded['running']}/cancel",
            params={"project_id": project_id},
            headers=headers,
            json={},
        )
        headers["Idempotency-Key"] = "w2201"
        item_again = await client.post(
            f"/api/v1/case-runs/{seeded['running']}/cancel",
            params={"project_id": project_id},
            headers=headers,
            json={},
        )
        execution = await client.post(
            f"/api/v1/executions/{seeded['execution']}/cancel",
            params={"project_id": project_id},
            headers={**headers, "Idempotency-Key": "w2201-run"},
            json={},
        )
        execution_again = await client.post(
            f"/api/v1/executions/{seeded['execution']}/cancel",
            params={"project_id": project_id},
            headers={**headers, "Idempotency-Key": "w2201-run"},
            json={},
        )
        denied = await client.post(
            f"/api/v1/case-runs/{seeded['done']}/cancel",
            params={"project_id": project_id},
            headers={**headers, "Idempotency-Key": "w2201-done"},
            json={},
        )
        page = await client.get(f"/ui/projects/{project_id}/executions/{seeded['execution']}")
        other_headers = await _session(client, origin, other_project_id, "w2201-other")
        hidden = await client.post(
            f"/api/v1/executions/{seeded['execution']}/cancel",
            params={"project_id": other_project_id},
            headers=other_headers,
            json={},
        )
    assert item.status_code == 202, item.text
    assert item_again.status_code == 200, item_again.text
    assert execution.status_code == 202, execution.text
    assert execution_again.status_code == 200, execution_again.text
    assert page.status_code == 200, page.text
    return item.json(), item_again.json(), execution.json(), execution_again.json(), hidden.status_code, page.text, denied.status_code


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


def test_w22_02(tmp_path: Path) -> None:
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
        project = create_project(owner, ProjectCreate("건너뛰기", "w2202", "수행", "web"))
    store.close()
    project_id = str(project.project_id)
    database = root / "db" / "aiqa.sqlite"
    seeded = _skip_graph(database, project_id, str(owner.actor_id))
    before = _fail_hash(database, seeded["failed"])
    skipped, again, running, failed, claimed, page = asyncio.run(_skip(app, project_id, seeded))
    after = _fail_hash(database, seeded["failed"])
    observed = {
        "queued_display_result": skipped["result"],
        "running_skip_status": running,
        "skip_physical_sessions": _sessions(database, seeded["queued_job"]),
        "fail_rewritten": before != after,
    }
    assert again["replayed"] is True and again["reason"] == skipped["reason"] == "자원이 없어 건너뜁니다"
    assert again["actor_id"] == skipped["actor_id"]
    assert _skipped_rows(database, seeded["queued"]) == 1
    assert _core(database, seeded["later"]) == "NOT_RUN"
    assert failed == 409 and claimed == 409
    assert "미시작 항목만 건너뜁니다." in page and "진행 중 항목은 건너뛰지 않습니다." in page
    assert "건너뜀은 한 번만 집계합니다." in page and "자원은 잡지 않습니다." in page
    assert "자원이 없어 건너뜁니다" in page and "PASS" not in page
    assert observed == {
        "queued_display_result": "SKIPPED",
        "running_skip_status": 409,
        "skip_physical_sessions": 0,
        "fail_rewritten": False,
    }


def _skip_graph(database: Path, project_id: str, actor_id: str) -> dict[str, str]:
    stamp = "2026-11-01T00:00:00+00:00"
    execution_id = str(uuid4())
    queued, later, running, failed, claimed = (str(uuid4()) for _ in range(5))
    queued_job = str(uuid4())
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO executions (project_id, execution_id, name, purpose, source, suite_version_id, scope_requested_at)
            VALUES (?, ?, '건너뛰기', 'regression', 'selection', NULL, ?)
            """,
            (project_id, execution_id, stamp),
        )
        _skip_item(connection, project_id, actor_id, execution_id, queued, "queued", "queued", None, "", stamp, queued_job)
        _skip_item(connection, project_id, actor_id, execution_id, later, "later", "queued", None, "", stamp, None)
        _skip_item(connection, project_id, actor_id, execution_id, running, "running", "running", None, "", stamp, None)
        _skip_item(connection, project_id, actor_id, execution_id, failed, "failed", "completed", "FAIL", "kept-fail", stamp, None)
        _skip_item(connection, project_id, actor_id, execution_id, claimed, "claimed", "preparing", None, "", stamp, None)
    return {
        "execution": execution_id,
        "queued": queued,
        "queued_job": queued_job,
        "later": later,
        "running": running,
        "failed": failed,
        "claimed": claimed,
    }


def _skip_item(
    connection: sqlite3.Connection,
    project_id: str,
    actor_id: str,
    execution_id: str,
    run_id: str,
    name: str,
    status: str,
    code: str | None,
    content_hash: str,
    stamp: str,
    job_id: str | None,
) -> None:
    case_id, version_id = str(uuid4()), str(uuid4())
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
        ) VALUES (?, ?, 'regression', NULL, ?, 'payload', '["source"]', ?, ?)
        """,
        (
            project_id,
            job_id or str(uuid4()),
            run_id,
            json.dumps({"failure_policy": "stop_on_non_pass"}, ensure_ascii=False),
            status,
        ),
    )
    if code is not None:
        connection.execute(
            """
            INSERT INTO item_finalizations (
                project_id, case_run_id, created_seq, finalized_seq, release_label, content_hash, core_result, denominator
            ) VALUES (?, ?, 1, 1, '2026-11', ?, ?, 1)
            """,
            (project_id, run_id, content_hash, code),
        )


def _fail_hash(database: Path, case_run_id: str) -> str:
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT content_hash, core_result FROM item_finalizations WHERE case_run_id = ?",
            (case_run_id,),
        ).fetchone()
    assert row is not None and str(row[1]) == "FAIL"
    return str(row[0])


def _core(database: Path, case_run_id: str) -> str:
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT core_result FROM item_finalizations WHERE case_run_id = ?",
            (case_run_id,),
        ).fetchone()
    assert row is not None
    return str(row[0])


def _skipped_rows(database: Path, case_run_id: str) -> int:
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT COUNT(*) FROM item_finalizations WHERE case_run_id = ? AND core_result = 'SKIPPED'",
            (case_run_id,),
        ).fetchone()
    return int(row[0])


def _sessions(database: Path, job_id: str) -> int:
    with sqlite3.connect(database) as connection:
        leases = connection.execute("SELECT COUNT(*) FROM leases WHERE job_id = ?", (job_id,)).fetchone()
        physical = connection.execute(
            "SELECT COUNT(*) FROM attempts WHERE job_id = ? AND physical_key_id IS NOT NULL",
            (job_id,),
        ).fetchone()
    return int(leases[0]) + int(physical[0])


async def _skip(app: object, project_id: str, seeded: dict[str, str]):
    import httpx

    origin = "http://127.0.0.1"
    body = {"reason": "자원이 없어 건너뜁니다"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        headers = await _session(client, origin, project_id, "w2202")
        skipped = await client.post(
            f"/api/v1/case-runs/{seeded['queued']}/skip",
            params={"project_id": project_id},
            headers=headers,
            json=body,
        )
        again = await client.post(
            f"/api/v1/case-runs/{seeded['queued']}/skip",
            params={"project_id": project_id},
            headers=headers,
            json=body,
        )
        running = await client.post(
            f"/api/v1/case-runs/{seeded['running']}/skip",
            params={"project_id": project_id},
            headers={**headers, "Idempotency-Key": "w2202-running"},
            json=body,
        )
        failed = await client.post(
            f"/api/v1/case-runs/{seeded['failed']}/skip",
            params={"project_id": project_id},
            headers={**headers, "Idempotency-Key": "w2202-failed"},
            json=body,
        )
        claimed = await client.post(
            f"/api/v1/case-runs/{seeded['claimed']}/skip",
            params={"project_id": project_id},
            headers={**headers, "Idempotency-Key": "w2202-claimed"},
            json=body,
        )
        page = await client.get(f"/ui/projects/{project_id}/executions/{seeded['execution']}")
    assert skipped.status_code == 202, skipped.text
    assert again.status_code == 200, again.text
    assert page.status_code == 200, page.text
    return skipped.json(), again.json(), running.status_code, failed.status_code, claimed.status_code, page.text


def test_w22_03(tmp_path: Path) -> None:
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
        project = create_project(owner, ProjectCreate("재실행", "w2203", "수행", "web"))
    store.close()
    project_id = str(project.project_id)
    database = root / "db" / "aiqa.sqlite"
    seeded = _rerun_graph(database, project_id, str(owner.actor_id))
    before = _fail_hash(database, seeded["failed"])
    created, again, changed, revoked, pages = asyncio.run(_rerun(app, project_id, database, seeded))
    after = _fail_hash(database, seeded["failed"])
    observed = {
        "original_result": after and "FAIL",
        "new_result_independent": before == after and _attempt_count(database, seeded["failed_job"]) == 2 and _new_results(database, seeded["execution"]) == 0,
        "lineage_preserved": _lineage(database, seeded["execution"], seeded["failed"]),
        "duplicate_new_runs": _rerun_executions(database, seeded["execution"]),
    }
    assert created["ready"] is True and created["proposed_n"] == 1
    assert again["preview_hash"] == created["preview_hash"] and again["ready"] is True
    assert changed == 422
    assert revoked["ready"] is False and any(item["code"] == "APPROVAL_REVOKED" for item in revoked["blockers"])
    for page in pages:
        assert "같은 구성으로 다시 실행합니다" in page
        assert "원본 결과는 바꾸지 않습니다" in page
        assert "새 결과는 따로 보입니다" in page
        assert "철회된 승인은 다시 확인합니다" in page
        assert "새 버전" in page and "재녹화" in page
        assert seeded["reason"] in page
        assert "PASS" not in page
    assert observed == {
        "original_result": "FAIL",
        "new_result_independent": True,
        "lineage_preserved": True,
        "duplicate_new_runs": 1,
    }


def _rerun_graph(database: Path, project_id: str, actor_id: str) -> dict[str, str]:
    stamp = "2026-11-01T00:00:00+00:00"
    execution_id, failed, missed = str(uuid4()), str(uuid4()), str(uuid4())
    case_id, version_id = str(uuid4()), str(uuid4())
    failed_job, approval_id, review_id = str(uuid4()), str(uuid4()), str(uuid4())
    environment_id, revision_id, resource_id = str(uuid4()), str(uuid4()), str(uuid4())
    content_hash = "kept-fail"
    limits = json.dumps(
        {
            "approval_id": approval_id,
            "environment_revision_id": revision_id,
            "resource_id": resource_id,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "INSERT INTO worker_enrollments(enrollment_id,worker_id,project_id,created_at) VALUES(?,'rerun-worker',?,?)",
            (str(uuid4()), project_id, stamp),
        )
        seed_presence(connection, project_id, "rerun-worker")
        connection.execute(
            "INSERT INTO physical_resource_keys(physical_key_id,worker_id,native_id) VALUES(?,'rerun-worker',?)",
            (resource_id, resource_id),
        )
        connection.execute(
            "INSERT INTO resource_aliases(project_id,physical_key_id,display_name,target_kind) VALUES(?,?,'Rerun Web','web')",
            (project_id, resource_id),
        )
        connection.execute(
            "INSERT INTO resource_inventory(physical_key_id,state,os_build,geometry,permissions,ime,observed_at) VALUES(?,'ready','','','[]','','2026-11-02T00:00:00+00:00')",
            (resource_id,),
        )
        connection.execute(
            """
            INSERT INTO executions (project_id, execution_id, name, purpose, source, suite_version_id, scope_requested_at)
            VALUES (?, ?, '원본', 'regression', 'selection', NULL, ?)
            """,
            (project_id, execution_id, stamp),
        )
        connection.execute(
            """
            INSERT INTO automation_cases (
                project_id, case_id, name, folder_id, tc_reference, next_revision,
                latest_draft_version_id, current_approval_id, lock_version, archived_at
            ) VALUES (?, ?, '재실행 케이스', NULL, NULL, 2, NULL, NULL, 0, NULL)
            """,
            (project_id, case_id),
        )
        connection.execute(
            """
            INSERT INTO case_versions (
                project_id, case_id, version_id, revision, creation_kind, parent_version_id, base_version_id,
                is_branch, definition_json, settings_json, recorded_steps_json, content_hash, verification_digest,
                source_manifest_id, replay_package_id, readiness_json, actor_id, reason, created_at
            ) VALUES (?, ?, ?, 1, 'recorded', NULL, NULL, 0, '{}', '{"target_kind":"web"}', '[]', ?, 'digest-rerun',
                NULL, NULL, '{}', ?, 'recorded', ?)
            """,
            (project_id, case_id, version_id, content_hash, actor_id, stamp),
        )
        connection.execute(
            """
            INSERT INTO environments (project_id, environment_id, name, next_revision, latest_revision_id)
            VALUES (?, ?, '환경', 2, ?)
            """,
            (project_id, environment_id, revision_id),
        )
        connection.execute(
            """
            INSERT INTO environment_revisions (
                project_id, environment_id, revision_id, revision, body_json, content_hash, actor_id, created_at
            ) VALUES (?, ?, ?, 1, '{}', 'env-hash', ?, ?)
            """,
            (project_id, environment_id, revision_id, actor_id, stamp),
        )
        connection.execute(
            """
            INSERT INTO reviews (
                project_id, review_id, case_id, case_version_id, version_hash, source_manifest_id,
                trial_case_run_id, evidence_set_hash, expected_current_approval_id, created_commit_seq
            ) VALUES (?, ?, ?, ?, ?, NULL, NULL, 'evidence', NULL, 1)
            """,
            (project_id, review_id, case_id, version_id, content_hash),
        )
        connection.execute(
            """
            INSERT INTO approval_events (
                project_id, approval_id, case_id, case_version_id, review_id, event_kind,
                prior_approval_id, version_hash, evidence_set_hash, reason
            ) VALUES (?, ?, ?, ?, ?, 'approved', NULL, ?, 'evidence', '승인')
            """,
            (project_id, approval_id, case_id, version_id, review_id, content_hash),
        )
        for run_id, code, job_id in ((failed, "FAIL", failed_job), (missed, "NOT_RUN", str(uuid4()))):
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
                (project_id, job_id, run_id, limits),
            )
            connection.execute(
                """
                INSERT INTO item_finalizations (
                    project_id, case_run_id, created_seq, finalized_seq, release_label, content_hash, core_result, denominator
                ) VALUES (?, ?, 1, 1, '', ?, ?, 1)
                """,
                (project_id, run_id, content_hash if code == "FAIL" else f"missed-{run_id}", code),
            )
        for generation in (1, 2):
            connection.execute(
                "INSERT INTO attempts (project_id, attempt_id, job_id, generation, physical_key_id) VALUES (?, ?, ?, ?, NULL)",
                (project_id, str(uuid4()), failed_job, generation),
            )
    return {
        "execution": execution_id,
        "failed": failed,
        "failed_job": failed_job,
        "approval": approval_id,
        "reason": "같은 구성으로 다시 확인합니다",
    }


def _lineage(database: Path, execution_id: str, case_run_id: str) -> bool:
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            """
            SELECT jobs.limits
            FROM jobs
            JOIN case_runs ON case_runs.project_id = jobs.project_id AND case_runs.case_run_id = jobs.case_run_id
            JOIN executions ON executions.project_id = case_runs.project_id AND executions.execution_id = case_runs.execution_id
            WHERE executions.source = 'rerun'
            """
        ).fetchall()
    if len(rows) != 1:
        return False
    limits = json.loads(str(rows[0][0]))
    return (
        limits.get("original_execution_id") == execution_id
        and limits.get("root_execution_id") == execution_id
        and limits.get("original_case_run_id") == case_run_id
        and limits.get("rerun_reason") == "같은 구성으로 다시 확인합니다"
        and limits.get("configuration_changed") is False
    )


def _rerun_executions(database: Path, execution_id: str) -> int:
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT COUNT(*) FROM executions WHERE source = 'rerun' AND execution_id != ?",
            (execution_id,),
        ).fetchone()
    return int(row[0])


def _attempt_count(database: Path, job_id: str) -> int:
    with sqlite3.connect(database) as connection:
        row = connection.execute("SELECT COUNT(*) FROM attempts WHERE job_id = ?", (job_id,)).fetchone()
    return int(row[0])


def _new_results(database: Path, execution_id: str) -> int:
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            """
            SELECT COUNT(*)
            FROM item_finalizations
            JOIN case_runs
              ON case_runs.project_id = item_finalizations.project_id
             AND case_runs.case_run_id = item_finalizations.case_run_id
            JOIN executions
              ON executions.project_id = case_runs.project_id
             AND executions.execution_id = case_runs.execution_id
            WHERE executions.source = 'rerun' AND case_runs.execution_id != ?
            """,
            (execution_id,),
        ).fetchone()
    return int(row[0])


async def _rerun(app: object, project_id: str, database: Path, seeded: dict[str, str]):
    import httpx

    origin = "http://127.0.0.1"
    body = {"reason": seeded["reason"], "scope": "failed"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        headers = await _session(client, origin, project_id, "w2203")
        created = await client.post(
            f"/api/v1/executions/{seeded['execution']}/reruns",
            params={"project_id": project_id},
            headers=headers,
            json=body,
        )
        again = await client.post(
            f"/api/v1/executions/{seeded['execution']}/reruns",
            params={"project_id": project_id},
            headers=headers,
            json=body,
        )
        changed = await client.post(
            f"/api/v1/executions/{seeded['execution']}/reruns",
            params={"project_id": project_id},
            headers={**headers, "Idempotency-Key": "w2203-env"},
            json={**body, "environment_revision_id": str(uuid4())},
        )
        assert created.status_code == 201, created.text
        assert again.status_code == 200, again.text
        new_run, new_item = _created_ids(database)
        execution_page = await client.get(f"/ui/projects/{project_id}/executions/{new_run}")
        item_page = await client.get(f"/ui/projects/{project_id}/case-runs/{new_item}")
        report_page = await client.get(f"/ui/projects/{project_id}/executions/{new_run}/report")
        _revoke(database, project_id, seeded["approval"])
        revoked = await client.post(
            f"/api/v1/executions/{seeded['execution']}/reruns",
            params={"project_id": project_id},
            headers={**headers, "Idempotency-Key": "w2203-revoked"},
            json=body,
        )
    assert execution_page.status_code == 200, execution_page.text
    assert item_page.status_code == 200, item_page.text
    assert report_page.status_code == 200, report_page.text
    return created.json(), again.json(), changed.status_code, revoked.json(), (execution_page.text, item_page.text, report_page.text)


def _created_ids(database: Path) -> tuple[str, str]:
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            """
            SELECT case_runs.execution_id, case_runs.case_run_id
            FROM case_runs
            JOIN executions
              ON executions.project_id = case_runs.project_id
             AND executions.execution_id = case_runs.execution_id
            WHERE executions.source = 'rerun'
            """
        ).fetchone()
    assert row is not None
    return str(row[0]), str(row[1])


def _revoke(database: Path, project_id: str, approval_id: str) -> None:
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        source = connection.execute(
            """
            SELECT case_id, case_version_id, review_id, version_hash, evidence_set_hash
            FROM approval_events
            WHERE project_id = ? AND approval_id = ?
            """,
            (project_id, approval_id),
        ).fetchone()
        assert source is not None
        connection.execute(
            """
            INSERT INTO approval_events (
                project_id, approval_id, case_id, case_version_id, review_id, event_kind,
                prior_approval_id, version_hash, evidence_set_hash, reason
            ) VALUES (?, ?, ?, ?, ?, 'revoked', ?, ?, ?, '철회')
            """,
            (project_id, str(uuid4()), source[0], source[1], source[2], approval_id, source[3], source[4]),
        )

