"""Approval and rejection stay on the review screen. A stale pointer is not retried."""

from __future__ import annotations

import sqlite3
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from uuid import uuid4

from aiqa.store.models import Actor


def test_w19_02(tmp_path: Path) -> None:
    import asyncio

    from aiqa.api.app import create_app
    from aiqa.config import load_settings
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.store.database import migrate_store
    from aiqa.store.models import ProjectCreate

    root = tmp_path / "runtime"
    app = create_app(load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}))
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("결정", "w1902", "decision", "web"))
    store.close()
    database = root / "db" / "aiqa.sqlite"
    bundle = _graph()
    project_id = str(project.project_id)
    case_id = str(uuid4())
    default_id = str(uuid4())
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO automation_cases (
                project_id, case_id, name, folder_id, tc_reference, next_revision,
                latest_draft_version_id, current_approval_id, lock_version, archived_at
            ) VALUES (?, ?, '결정', NULL, NULL, 4, NULL, NULL, 0, NULL)
            """,
            (project_id, case_id),
        )
        current = bundle(connection, project_id, str(owner.actor_id), case_id, 1, "current")
        failed = bundle(connection, project_id, str(owner.actor_id), case_id, 2, "failed")
        candidate = bundle(connection, project_id, str(owner.actor_id), case_id, 3, "candidate")
        connection.execute(
            """
            INSERT INTO approval_events (
                project_id, approval_id, case_id, case_version_id, review_id, event_kind,
                prior_approval_id, version_hash, evidence_set_hash, reason
            ) VALUES (?, ?, ?, ?, ?, 'approved', NULL, ?, ?, '기존 기본본')
            """,
            (project_id, default_id, case_id, current["version"], current["review"], current["version_hash"], current["evidence_hash"]),
        )
        connection.execute(
            "UPDATE automation_cases SET current_approval_id = ? WHERE project_id = ? AND case_id = ?",
            (default_id, project_id, case_id),
        )
        connection.execute(
            """
            UPDATE recordings
            SET storage_status = 'spooling', stop_status = 'running', completion_status = 'interrupted'
            WHERE recording_id = ?
            """,
            (failed["recording"],),
        )
        connection.commit()
    failed_status, empty_status, rejected_status, stale_status, page = asyncio.run(
        _calls(app, project_id, case_id, default_id, failed, candidate)
    )
    with sqlite3.connect(database) as connection:
        pointer = connection.execute(
            "SELECT current_approval_id FROM automation_cases WHERE case_id = ?",
            (case_id,),
        ).fetchone()
        approvals = connection.execute("SELECT COUNT(*) FROM approval_events").fetchone()
        decision = connection.execute(
            "SELECT state, reason, version_hash FROM review_decisions WHERE review_id = ?",
            (candidate["review"],),
        ).fetchone()
    observed = {
        "failed_candidate_changes_default": failed_status < 400 or pointer is None or pointer[0] != default_id,
        "rejected_record_deleted": decision is None or decision[0] != "rejected" or decision[2] != candidate["version_hash"],
        "stale_approval_auto_retried": stale_status != 409 or approvals is None or int(approvals[0]) != 1 or 'data-auto-retry="false"' not in page,
        "reason_required": empty_status == 422 and rejected_status == 201 and decision is not None and decision[1] != "",
    }
    assert "이 버전 승인 및 기본 실행본으로 사용" in page
    assert "기본본은 유지됩니다." in page and "화면 방문만으로 승인하지 않습니다." in page
    assert "PASS" not in page
    assert observed == {
        "failed_candidate_changes_default": False,
        "rejected_record_deleted": False,
        "stale_approval_auto_retried": False,
        "reason_required": True,
    }


def _graph():
    path = Path(__file__).resolve().parents[1] / "integration" / "test_w19.py"
    spec = spec_from_file_location("w19_approval_graph", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("approval graph is missing")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._bundle


async def _calls(
    app: object,
    project_id: str,
    case_id: str,
    default_id: str,
    failed: dict[str, str],
    candidate: dict[str, str],
) -> tuple[int, int, int, int, str]:
    import httpx

    origin = "http://127.0.0.1"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        headers = await _session(client, origin, project_id)
        failed_status, _failed_body = await _post(
            client,
            f"/api/v1/case-versions/{failed['version']}/approvals",
            {
                "review_id": failed["review"],
                "version_hash": failed["version_hash"],
                "evidence_set_hash": failed["evidence_hash"],
                "expected_current_approval_id": default_id,
                "reason": "실패한 후보",
            },
            headers,
            "w1902-failed",
        )
        empty_status, _empty_body = await _post(
            client,
            f"/api/v1/case-versions/{candidate['version']}/rejections",
            {"review_id": candidate["review"], "version_hash": candidate["version_hash"], "reason": ""},
            headers,
            "w1902-empty",
        )
        rejected_status, _rejected_body = await _post(
            client,
            f"/api/v1/case-versions/{candidate['version']}/rejections",
            {"review_id": candidate["review"], "version_hash": candidate["version_hash"], "reason": "기대와 다릅니다."},
            headers,
            "w1902-reject",
        )
        stale_status, _stale_body = await _post(
            client,
            f"/api/v1/case-versions/{candidate['version']}/approvals",
            {
                "review_id": candidate["review"],
                "version_hash": candidate["version_hash"],
                "evidence_set_hash": candidate["evidence_hash"],
                "expected_current_approval_id": None,
                "reason": "오래된 기본본",
            },
            headers,
            "w1902-stale",
        )
        page = await client.get(f"/ui/projects/{project_id}/cases/{case_id}/review")
    assert page.status_code == 200
    return failed_status, empty_status, rejected_status, stale_status, page.text


async def _post(
    client: object, path: str, body: dict[str, object], headers: dict[str, str], key: str
) -> tuple[int, dict[str, object]]:
    sent = dict(headers)
    sent["Idempotency-Key"] = key
    response = await client.post(path, json=body, headers=sent)  # type: ignore[attr-defined]
    payload = response.json()
    assert type(payload) is dict
    return response.status_code, payload


async def _session(client: object, origin: str, project_id: str) -> dict[str, str]:
    issued = await client.post(  # type: ignore[attr-defined]
        "/api/v1/session/nonces",
        json={"origin": origin, "project_id": project_id},
        headers={"Idempotency-Key": "w1902-nonce", "Origin": origin},
    )
    booted = await client.post(  # type: ignore[attr-defined]
        "/api/v1/session/bootstrap",
        json={"nonce": issued.json()["nonce"]},
        headers={"Idempotency-Key": "w1902-boot", "Origin": origin},
    )
    client.cookies.set("aiqa_session", booted.cookies["aiqa_session"])  # type: ignore[attr-defined]
    return {"Origin": origin, "X-CSRF-Token": booted.json()["csrf_token"]}


def test_w19_03(tmp_path: Path) -> None:
    import asyncio
    from datetime import datetime, timezone

    from aiqa.api.app import create_app
    from aiqa.config import load_settings
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.store.database import migrate_store
    from aiqa.store.models import ProjectCreate, WorkerScope
    from aiqa.store.queue import claim_queued_job

    root = tmp_path / "runtime"
    app = create_app(load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}))
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("철회", "w1903", "revoke", "web"))
    store.close()
    database = root / "db" / "aiqa.sqlite"
    bundle = _graph()
    project_id = str(project.project_id)
    case_id = str(uuid4())
    current_id = str(uuid4())
    old_id = str(uuid4())
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO automation_cases (
                project_id, case_id, name, folder_id, tc_reference, next_revision,
                latest_draft_version_id, current_approval_id, lock_version, archived_at
            ) VALUES (?, ?, '철회', NULL, NULL, 3, NULL, NULL, 0, NULL)
            """,
            (project_id, case_id),
        )
        current = bundle(connection, project_id, str(owner.actor_id), case_id, 1, "current")
        old = _old_approval(connection, project_id, str(owner.actor_id), case_id, old_id)
        connection.execute(
            """
            INSERT INTO approval_events (
                project_id, approval_id, case_id, case_version_id, review_id, event_kind,
                prior_approval_id, version_hash, evidence_set_hash, reason
            ) VALUES (?, ?, ?, ?, ?, 'approved', NULL, ?, ?, '현재 기본본')
            """,
            (project_id, current_id, case_id, current["version"], current["review"], current["version_hash"], current["evidence_hash"]),
        )
        connection.execute(
            "UPDATE automation_cases SET current_approval_id = ? WHERE case_id = ?",
            (current_id, case_id),
        )
        queued_job, running_job = _runs(connection, project_id, case_id, current["version"])
        connection.execute(
            """
            INSERT INTO artifact_protections (
                project_id, protection_id, artifact_id, kind, backup_receipt_id, build_id, manual_request_id
            ) VALUES (?, ?, ?, 'approval', NULL, NULL, NULL)
            """,
            (project_id, str(uuid4()), current["source"]),
        )
        other_pin = str(uuid4())
        other_artifact = str(uuid4())
        connection.execute(
            """
            INSERT INTO artifact_refs (
                project_id, artifact_id, attempt_id, action_id, check_id, recording_id, review_id, build_id,
                export_id, package_id, healing_id, proposal_id, resource_observation_id
            ) VALUES (?, ?, NULL, NULL, NULL, ?, NULL, NULL, NULL, NULL, NULL, NULL, NULL)
            """,
            (project_id, other_artifact, current["recording"]),
        )
        connection.execute(
            """
            INSERT INTO artifact_protections (
                project_id, protection_id, artifact_id, kind, backup_receipt_id, build_id, manual_request_id
            ) VALUES (?, ?, ?, 'approval', NULL, NULL, NULL)
            """,
            (project_id, other_pin, other_artifact),
        )
        connection.execute(
            """
            INSERT INTO item_finalizations (
                project_id, case_run_id, created_seq, finalized_seq, release_label, content_hash, core_result, denominator
            ) VALUES (?, ?, 1, 1, 'fixture', 'qa-hash', 'INCONCLUSIVE', 1)
            """,
            (project_id, queued_job["final_run"]),
        )
        connection.commit()
    page, status, again = asyncio.run(_revoke_calls(app, project_id, case_id, current_id))
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        pointer = connection.execute(
            "SELECT current_approval_id FROM automation_cases WHERE case_id = ?",
            (case_id,),
        ).fetchone()
        queued = connection.execute("SELECT status FROM jobs WHERE job_id = ?", (queued_job["queued"],)).fetchone()
        blocked = connection.execute(
            "SELECT 1 FROM approval_queue_blocks WHERE job_id = ?",
            (queued_job["queued"],),
        ).fetchone()
        running = connection.execute("SELECT status FROM jobs WHERE job_id = ?", (running_job,)).fetchone()
        qa = connection.execute(
            "SELECT core_result FROM item_finalizations WHERE case_run_id = ?",
            (queued_job["final_run"],),
        ).fetchone()
        other = connection.execute(
            "SELECT 1 FROM approval_pin_releases WHERE protection_id = ?",
            (other_pin,),
        ).fetchone()
        claim_queued_job(
            connection,
            WorkerScope("worker-1", (project.project_id,), ("trial",)),
            datetime.now(timezone.utc),
        )
        after_claim = connection.execute("SELECT status FROM jobs WHERE job_id = ?", (queued_job["queued"],)).fetchone()
    observed = {
        "current_default_after_revoke": None if pointer is None or pointer[0] is None else pointer[0],
        "automatic_fallback": pointer is not None and pointer[0] == old,
        "queued_claim_blocked": blocked is not None and queued is not None and queued[0] == "queued" and after_claim is not None and after_claim[0] == "queued",
        "terminal_qa_changed": qa is None or qa[0] != "INCONCLUSIVE" or running is None or running[0] != "cancel_requested" or other is not None or again != 409,
    }
    assert "이전 승인으로 되돌리지 않습니다." in page and 'data-fallback="false"' in page
    assert "PASS" not in page and status == 201
    assert observed == {
        "current_default_after_revoke": None,
        "automatic_fallback": False,
        "queued_claim_blocked": True,
        "terminal_qa_changed": False,
    }


def _old_approval(connection: sqlite3.Connection, project_id: str, actor_id: str, case_id: str, approval_id: str) -> str:
    version_id = str(uuid4())
    review_id = str(uuid4())
    stamp = "2026-10-01T00:00:00+00:00"
    connection.execute(
        """
        INSERT INTO case_versions (
            project_id, case_id, version_id, revision, creation_kind, parent_version_id, base_version_id,
            is_branch, definition_json, settings_json, recorded_steps_json, content_hash, verification_digest,
            source_manifest_id, replay_package_id, readiness_json, actor_id, reason, created_at
        ) VALUES (?, ?, ?, 2, 'recorded', NULL, NULL, 0, '{}', '{}', '[]', 'old-hash', 'digest',
            NULL, NULL, '{}', ?, 'recorded', ?)
        """,
        (project_id, case_id, version_id, actor_id, stamp),
    )
    connection.execute(
        """
        INSERT INTO reviews (
            project_id, review_id, case_id, case_version_id, version_hash, source_manifest_id,
            trial_case_run_id, evidence_set_hash, expected_current_approval_id, created_commit_seq
        ) VALUES (?, ?, ?, ?, 'old-hash', NULL, NULL, 'old-evidence', NULL, 2)
        """,
        (project_id, review_id, case_id, version_id),
    )
    connection.execute(
        """
        INSERT INTO approval_events (
            project_id, approval_id, case_id, case_version_id, review_id, event_kind,
            prior_approval_id, version_hash, evidence_set_hash, reason
        ) VALUES (?, ?, ?, ?, ?, 'approved', NULL, 'old-hash', 'old-evidence', '이전 기본본')
        """,
        (project_id, approval_id, case_id, version_id, review_id),
    )
    return approval_id


def _runs(connection: sqlite3.Connection, project_id: str, case_id: str, version_id: str) -> tuple[dict[str, str], str]:
    ids = {
        "queued_execution": str(uuid4()),
        "running_execution": str(uuid4()),
        "final_execution": str(uuid4()),
        "queued_run": str(uuid4()),
        "running_run": str(uuid4()),
        "final_run": str(uuid4()),
        "queued": str(uuid4()),
        "running": str(uuid4()),
        "suite": str(uuid4()),
        "suite_version": str(uuid4()),
    }
    limits = '{"self_healing_enabled": false, "actor": 0}'
    connection.execute(
        "INSERT INTO suites (project_id, suite_id, name) VALUES (?, ?, '묶음')",
        (project_id, ids["suite"]),
    )
    connection.execute(
        "INSERT INTO suite_versions (project_id, suite_id, suite_version_id, content_hash) VALUES (?, ?, ?, 'suite-hash')",
        (project_id, ids["suite"], ids["suite_version"]),
    )
    for execution, run, stamp, purpose_job, status, suite in (
        (ids["queued_execution"], ids["queued_run"], "2026-11-01T01:00:00+00:00", ids["queued"], "queued", None),
        (ids["running_execution"], ids["running_run"], "2026-11-01T02:00:00+00:00", ids["running"], "running", ids["suite_version"]),
        (ids["final_execution"], ids["final_run"], "2026-11-01T03:00:00+00:00", None, None, None),
    ):
        connection.execute(
            """
            INSERT INTO executions (
                project_id, execution_id, name, purpose, source, suite_version_id, scope_requested_at
            ) VALUES (?, ?, '수행', 'regression', ?, ?, ?)
            """,
            (project_id, execution, "suite" if suite is not None else "single", suite, stamp),
        )
        connection.execute(
            """
            INSERT INTO case_runs (
                project_id, execution_id, case_run_id, case_id, case_version_id, purpose, requested_at
            ) VALUES (?, ?, ?, ?, ?, 'regression', ?)
            """,
            (project_id, execution, run, case_id, version_id, stamp),
        )
        if purpose_job is not None and status is not None:
            connection.execute(
                """
                INSERT INTO jobs (
                    project_id, job_id, purpose, recording_id, case_run_id, payload_hash, source_refs, limits, status
                ) VALUES (?, ?, 'regression', NULL, ?, 'payload', '[]', ?, ?)
                """,
                (project_id, purpose_job, run, limits, status),
            )
    return ids, ids["running"]


async def _revoke_calls(app: object, project_id: str, case_id: str, approval_id: str) -> tuple[str, int, int]:
    import httpx

    origin = "http://127.0.0.1"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        headers = await _session(client, origin, project_id)
        page = await client.get(f"/ui/projects/{project_id}/cases/{case_id}/review")
        status, _body = await _post(
            client,
            f"/api/v1/approvals/{approval_id}/revoke",
            {"reason": "이 승인을 거둡니다.", "expected_current_approval_id": approval_id},
            headers,
            "w1903-revoke",
        )
        again, _again_body = await _post(
            client,
            f"/api/v1/approvals/{approval_id}/revoke",
            {"reason": "이 승인을 거둡니다.", "expected_current_approval_id": None},
            headers,
            "w1903-again",
        )
    assert page.status_code == 200
    return page.text, status, again
