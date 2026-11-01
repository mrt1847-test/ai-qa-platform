"""Export admission freezes the manifest and keeps the job verdict empty."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4


def test_w25_01(tmp_path: Path) -> None:
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
        project = create_project(owner, ProjectCreate("내보내기", "w2501", "스냅샷", "web"))
        other = create_project(owner, ProjectCreate("다른", "w2501b", "스냅샷", "web"))
    store.close()
    project_id = str(project.project_id)
    database = root / "db" / "aiqa.sqlite"
    seeded = _export_graph(database, project_id, str(owner.actor_id))
    first, replay, hidden, expired = asyncio.run(
        _exports(app, project_id, str(other.project_id), seeded["execution"])
    )
    _late_facts(database, project_id, seeded["run"])
    stored = asyncio.run(_read_export(app, project_id, seeded["execution"], str(first["job_id"])))
    with sqlite3.connect(database) as connection:
        jobs = connection.execute(
            "SELECT COUNT(*) FROM jobs WHERE project_id = ? AND purpose = 'export' AND payload_hash = ?",
            (project_id, _request_count_marker(connection, project_id, str(first["job_id"]))),
        ).fetchone()
        verdicts = connection.execute(
            "SELECT COUNT(*) FROM job_finish_facts WHERE project_id = ?",
            (project_id,),
        ).fetchone()
    same_key_jobs = connection_count = jobs[0] if jobs is not None else 0
    observed = {
        "export_job_verdict": first["verdict"],
        "duplicate_exports": same_key_jobs,
        "asof_fixed": stored["as_of"] == 15 and stored["cost"] is None and stored["interim"] is True,
        "expired_reason_visible": expired["expired_reason"] == "파일이 만료되었습니다",
    }
    assert first["interim"] is True and first["artifact_ready"] is True and replay["job_id"] == first["job_id"]
    assert hidden == 404 and verdicts is not None and int(verdicts[0]) == 0
    assert stored["expired_reason"] is None
    assert observed == {
        "export_job_verdict": None,
        "duplicate_exports": 1,
        "asof_fixed": True,
        "expired_reason_visible": True,
    }
    assert connection_count == 1


def _request_count_marker(connection: sqlite3.Connection, project_id: str, job_id: str) -> str:
    row = connection.execute(
        "SELECT payload_hash FROM jobs WHERE project_id = ? AND job_id = ?",
        (project_id, job_id),
    ).fetchone()
    assert row is not None
    return str(row[0])


def _export_graph(database: Path, project_id: str, actor_id: str) -> dict[str, str]:
    stamp = "2026-11-01T00:00:00+00:00"
    case_id, version_id, execution_id, run_id = (str(uuid4()) for _ in range(4))
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO executions (project_id, execution_id, name, purpose, source, suite_version_id, scope_requested_at)
            VALUES (?, ?, '진행', 'regression', 'selection', NULL, ?)
            """,
            (project_id, execution_id, stamp),
        )
        connection.execute(
            """
            INSERT INTO automation_cases (
                project_id, case_id, name, folder_id, tc_reference, next_revision,
                latest_draft_version_id, current_approval_id, lock_version, archived_at
            ) VALUES (?, ?, '내보내기 케이스', NULL, NULL, 2, NULL, NULL, 0, NULL)
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
    return {"execution": execution_id, "run": run_id}


def _late_facts(database: Path, project_id: str, run_id: str) -> None:
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO item_finalizations (
                project_id, case_run_id, created_seq, finalized_seq, release_label, content_hash, core_result, denominator
            ) VALUES (?, ?, 10, 20, '', 'later-fail', 'FAIL', 1)
            """,
            (project_id, run_id),
        )
        connection.execute(
            """
            INSERT INTO usage_adjustments (
                project_id, adjustment_id, case_run_id, commit_seq, role, measurement_status, amount, currency
            ) VALUES (?, ?, ?, 30, 'verification', 'measured', '9.00', 'USD')
            """,
            (project_id, str(uuid4()), run_id),
        )


async def _exports(app: object, project_id: str, other_project_id: str, execution_id: str):
    import httpx

    origin = "http://127.0.0.1"
    body = {
        "format": "csv",
        "as_of": 15,
        "criteria_version": "criteria-1",
        "filters": {"purpose": "regression"},
        "cohort": "strict",
        "expires_at": "2026-12-01T00:00:00+00:00",
    }
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        headers = await _session(client, origin, project_id, "w2501")
        first = await client.post(
            f"/api/v1/executions/{execution_id}/exports",
            params={"project_id": project_id},
            headers=headers,
            json=body,
        )
        replay = await client.post(
            f"/api/v1/executions/{execution_id}/exports",
            params={"project_id": project_id},
            headers=headers,
            json=body,
        )
        expired = await client.post(
            f"/api/v1/executions/{execution_id}/exports",
            params={"project_id": project_id},
            headers={**headers, "Idempotency-Key": "w2501-expired"},
            json={**body, "expires_at": "2026-10-01T00:00:00+00:00"},
        )
        other_headers = await _session(client, origin, other_project_id, "w2501-other")
        hidden = await client.post(
            f"/api/v1/executions/{execution_id}/exports",
            params={"project_id": project_id},
            headers=other_headers,
            json=body,
        )
    assert first.status_code == 201, first.text
    assert replay.status_code == 200, replay.text
    assert expired.status_code == 201, expired.text
    return first.json(), replay.json(), hidden.status_code, expired.json()


async def _read_export(app: object, project_id: str, execution_id: str, job_id: str):
    import httpx

    origin = "http://127.0.0.1"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        headers = await _session(client, origin, project_id, "w2501-read")
        stored = await client.get(
            f"/api/v1/executions/{execution_id}/exports/{job_id}",
            params={"project_id": project_id},
            headers=headers,
        )
    assert stored.status_code == 200, stored.text
    return stored.json()


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
