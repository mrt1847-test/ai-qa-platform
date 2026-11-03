"""Formal enqueue is atomic, and a revoked snapshot cannot be claimed."""

from __future__ import annotations

from worker_presence_support import seed_presence

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4


def test_w20_02(tmp_path: Path) -> None:
    import asyncio

    from aiqa.api.app import create_app
    from aiqa.config import load_settings
    from aiqa.contracts.jobs import IdempotencyKey
    from aiqa.domain.executions import enqueue_execution, validate_claim_snapshot
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.store.database import migrate_store
    from aiqa.store.models import Actor, JobSpec, ProjectCreate, Transaction, WorkerScope
    from aiqa.store.queue import claim_queued_job

    root = tmp_path / "runtime"
    app = create_app(load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}))
    owner = Actor(uuid4(), None, True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("정식", "w2002", "접수", "web"))
    store.close()
    project_id = str(project.project_id)
    version_id, case_id = asyncio.run(_case(app, project_id))
    environment_id, resource_id = str(uuid4()), str(uuid4())
    seeded = _seed(root / "db" / "aiqa.sqlite", project_id, case_id, version_id, environment_id, resource_id)
    preview = asyncio.run(_preview(app, project_id, seeded, environment_id, resource_id))
    created, replayed, conflict = asyncio.run(_enqueue(app, project_id, preview))
    store = app.state.open_store()
    actor = Actor(owner.actor_id, project.project_id, True)
    try:
        with store.transaction() as connection:
            enqueue_execution(
                Transaction(connection),
                actor,
                project.project_id,
                _enqueue_body(preview, "중단"),
                IdempotencyKey(actor.actor_id, project.project_id, "enqueue_execution", "w2002-crash"),
            )
            raise RuntimeError("crash")
    except RuntimeError:
        pass
    with sqlite3.connect(root / "db" / "aiqa.sqlite") as connection:
        runs = connection.execute("SELECT COUNT(*) FROM executions WHERE name = '정식'").fetchone()
        crashed = connection.execute("SELECT COUNT(*) FROM executions WHERE name = '중단'").fetchone()
        job = connection.execute(
            "SELECT job_id, purpose, recording_id, case_run_id, payload_hash, source_refs, limits, status FROM jobs WHERE payload_hash IS NOT NULL"
        ).fetchone()
    assert job is not None
    spec = JobSpec(
        project.project_id,
        UUID(str(job[0])),
        str(job[1]),
        None,
        None if job[3] is None else UUID(str(job[3])),
        str(job[4]),
        str(job[5]),
        str(job[6]),
        str(job[7]),
    )
    with sqlite3.connect(root / "db" / "aiqa.sqlite") as claim_connection:
        held = validate_claim_snapshot(spec, claim_connection)
        claim_connection.execute("UPDATE app_builds SET content_hash = 'changed' WHERE build_id = 'build-w2002'")
        claim_connection.commit()
        changed = validate_claim_snapshot(spec, claim_connection)
        claim_connection.execute("UPDATE app_builds SET content_hash = 'build-hash' WHERE build_id = 'build-w2002'")
        claim_connection.commit()
    _revoke(root / "db" / "aiqa.sqlite", project_id, seeded["case_id"], seeded["version_id"], seeded["approval_id"])
    claim_connection = sqlite3.connect(root / "db" / "aiqa.sqlite")
    try:
        revoked = validate_claim_snapshot(spec, claim_connection)
        claimed = claim_queued_job(
            claim_connection,
            WorkerScope("worker-w2002", (project.project_id,), ("regression",)),
            datetime.now(timezone.utc),
        )
        claim_connection.commit()
        status = claim_connection.execute("SELECT status FROM jobs WHERE job_id = ?", (str(job[0]),)).fetchone()
    finally:
        claim_connection.close()
    assert claimed is None and status is not None and status[0] == "queued"
    observed = {
        "partial_run_rows": 0 if crashed is None else int(crashed[0]),
        "duplicate_run_count": 0 if runs is None else int(runs[0]),
        "revoked_claim": revoked.status,
        "snapshot_uses_latest": held.uses_latest,
    }
    assert created["replayed"] is False and replayed["replayed"] is True
    assert created["execution_id"] == replayed["execution_id"]
    assert conflict == 409
    assert held.status == "ALLOWED" and held.approval_id == seeded["approval_id"]
    assert changed.status == "BLOCKED"
    assert observed == {
        "partial_run_rows": 0,
        "duplicate_run_count": 1,
        "revoked_claim": "BLOCKED",
        "snapshot_uses_latest": False,
    }


def _enqueue_body(preview: dict[str, object], name: str) -> dict[str, object]:
    return {
        "name": name,
        "purpose": "regression",
        "source": "single",
        "failure_policy": "stop_on_non_pass",
        "self_healing_enabled": False,
        "preview_hash": preview["preview_hash"],
        "exclusions": [],
        "items": preview["resolved_items"],
    }


async def _case(app: object, project_id: str) -> tuple[str, str]:
    import httpx

    origin = "http://127.0.0.1"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        headers = await _session(client, origin, project_id, "w2002-case")
        created = await client.post(
            f"/api/v1/projects/{project_id}/cases",
            json={"name": "정식", "tc_reference": None},
            headers=headers,
        )
        headers["Idempotency-Key"] = "w2002-version"
        version = await client.post(
            f"/api/v1/projects/{project_id}/cases/{created.json()['case_id']}/versions",
            json={"definition": {"final_expected": [{"id": "exp-1", "kind": "text", "expected": "보임"}]}, "settings": {"target_kind": "web", "build_id": "build-w2002"}},
            headers=headers,
        )
    assert version.status_code == 201, version.text
    return version.json()["id"], created.json()["case_id"]


async def _preview(app: object, project_id: str, seeded: dict[str, str], environment_id: str, resource_id: str) -> dict[str, object]:
    import httpx

    origin = "http://127.0.0.1"
    body = {
        "name": "정식",
        "purpose": "regression",
        "source": "single",
        "failure_policy": "stop_on_non_pass",
        "self_healing_enabled": False,
        "exclusions": [],
        "selection": {
            "items": [
                {
                    "entry_id": "item-1",
                    "case_version_id": seeded["version_id"],
                    "approval_id": seeded["approval_id"],
                    "environment_revision_id": environment_id,
                    "resource_id": resource_id,
                    "install_policy": "none",
                }
            ]
        },
    }
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        headers = await _session(client, origin, project_id, "w2002-preview")
        response = await client.post(f"/api/v1/projects/{project_id}/execution-previews", json=body, headers=headers)
    assert response.status_code == 200, response.text
    parsed = response.json()
    assert type(parsed) is dict
    return parsed


async def _enqueue(app: object, project_id: str, preview: dict[str, object]) -> tuple[dict[str, object], dict[str, object], int]:
    import httpx

    origin = "http://127.0.0.1"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        headers = await _session(client, origin, project_id, "w2002-enqueue")
        headers["Idempotency-Key"] = "w2002-run"
        first = await client.post(
            f"/api/v1/projects/{project_id}/executions",
            json=_enqueue_body(preview, "정식"),
            headers=headers,
        )
        second = await client.post(
            f"/api/v1/projects/{project_id}/executions",
            json=_enqueue_body(preview, "정식"),
            headers=headers,
        )
        other = await client.post(
            f"/api/v1/projects/{project_id}/executions",
            json=_enqueue_body(preview, "다른이름"),
            headers=headers,
        )
    assert first.status_code == 201, first.text
    assert second.status_code == 200, second.text
    created, replayed = first.json(), second.json()
    assert type(created) is dict and type(replayed) is dict
    return created, replayed, other.status_code


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


def _seed(database: Path, project_id: str, case_id: str, version_id: str, environment_id: str, resource_id: str) -> dict[str, str]:
    old_version, old_approval, current_approval = str(uuid4()), str(uuid4()), str(uuid4())
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "INSERT INTO app_builds (project_id, build_id, content_hash) VALUES (?, 'build-w2002', 'build-hash')",
            (project_id,),
        )
        connection.execute(
            "INSERT INTO worker_enrollments (enrollment_id, worker_id, project_id, created_at) VALUES ('enroll-w2002', 'worker-w2002', ?, '2026-11-01T00:00:00+00:00')",
            (project_id,),
        )
        seed_presence(connection, project_id, "worker-w2002")
        connection.execute(
            "INSERT INTO physical_resource_keys (physical_key_id, worker_id, native_id) VALUES (?, 'worker-w2002', 'native-w2002')",
            (resource_id,),
        )
        connection.execute(
            "INSERT INTO resource_aliases (project_id, physical_key_id, display_name, target_kind) VALUES (?, ?, '브라우저', 'web')",
            (project_id, resource_id),
        )
        connection.execute(
            """
            INSERT INTO resource_inventory (physical_key_id, state, os_build, geometry, permissions, ime, observed_at)
            VALUES (?, 'ready', 'none', 'none', '[]', 'none', '2026-11-01T00:00:00+00:00')
            """,
            (resource_id,),
        )
        connection.execute(
            "INSERT INTO environments (project_id, environment_id, name, next_revision, latest_revision_id) VALUES (?, 'env-w2002', '로컬', 2, ?)",
            (project_id, environment_id),
        )
        connection.execute(
            """
            INSERT INTO environment_revisions (
                project_id, environment_id, revision_id, revision, body_json, content_hash, actor_id, created_at
            ) VALUES (?, 'env-w2002', ?, 1, '{}', 'env-hash', 'actor', '2026-11-01T00:00:00+00:00')
            """,
            (project_id, environment_id),
        )
        names = [item[1] for item in connection.execute("PRAGMA table_info(case_versions)")]
        source = connection.execute("SELECT * FROM case_versions WHERE version_id = ?", (version_id,)).fetchone()
        assert source is not None
        values = dict(zip(names, source, strict=True))
        content_hash = str(values["content_hash"])
        manifest_id, recording_id, package_id = str(uuid4()), str(uuid4()), str(uuid4())
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
        copied = dict(values)
        copied["version_id"] = old_version
        copied["revision"] = 2
        copied["source_manifest_id"] = manifest_id
        copied["replay_package_id"] = package_id
        copied["content_hash"] = content_hash
        copied["is_branch"] = 1
        settings = json.loads(str(values["settings_json"]))
        settings["build_id"] = "build-w2002"
        copied["settings_json"] = json.dumps(settings, ensure_ascii=False, separators=(",", ":"))
        connection.execute(
            f"INSERT INTO case_versions ({', '.join(names)}) VALUES ({', '.join('?' for _ in names)})",
            tuple(copied[name] for name in names),
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
            (project_id, package_id, case_id, old_version, manifest_id, package_id),
        )
        connection.execute(
            "INSERT INTO package_version_links (project_id, case_id, version_id, package_id) VALUES (?, ?, ?, ?)",
            (project_id, case_id, old_version, package_id),
        )
        for approval_id in (old_approval, current_approval):
            review_id = str(uuid4())
            connection.execute(
                """
                INSERT INTO reviews (
                    project_id, review_id, case_id, case_version_id, version_hash, evidence_set_hash, created_commit_seq
                ) VALUES (?, ?, ?, ?, ?, 'evidence', 1)
                """,
                (project_id, review_id, case_id, old_version, content_hash),
            )
            connection.execute(
                """
                INSERT INTO approval_events (
                    project_id, approval_id, case_id, case_version_id, review_id, event_kind,
                    prior_approval_id, version_hash, evidence_set_hash, reason
                ) VALUES (?, ?, ?, ?, ?, 'approved', NULL, ?, 'evidence', '기록')
                """,
                (project_id, approval_id, case_id, old_version, review_id, content_hash),
            )
        connection.execute(
            "UPDATE automation_cases SET current_approval_id = ? WHERE project_id = ? AND case_id = ?",
            (current_approval, project_id, case_id),
        )
    return {"version_id": old_version, "approval_id": old_approval, "case_id": case_id}


def _revoke(database: Path, project_id: str, case_id: str, version_id: str, approval_id: str) -> None:
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        review_id = str(uuid4())
        connection.execute(
            """
            INSERT INTO reviews (
                project_id, review_id, case_id, case_version_id, version_hash, evidence_set_hash, created_commit_seq
            ) VALUES (?, ?, ?, ?, 'hash', 'evidence', 1)
            """,
            (project_id, review_id, case_id, version_id),
        )
        connection.execute(
            """
            INSERT INTO approval_events (
                project_id, approval_id, case_id, case_version_id, review_id, event_kind,
                prior_approval_id, version_hash, evidence_set_hash, reason
            ) VALUES (?, ?, ?, ?, ?, 'revoked', ?, 'hash', 'evidence', '철회')
            """,
            (project_id, str(uuid4()), case_id, version_id, review_id, approval_id),
        )
