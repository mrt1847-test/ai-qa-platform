"""An immutable repair proposal adopts a new full recording and leaves the source in place."""

from __future__ import annotations

from worker_presence_support import seed_presence

import json
import sqlite3
from pathlib import Path
from uuid import uuid4


def test_w31_05(tmp_path: Path) -> None:
    import asyncio

    from aiqa.api.app import create_app
    from aiqa.config import load_settings
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.store.database import migrate_store
    from aiqa.store.models import Actor, ProjectCreate

    root = tmp_path / "runtime"
    app = create_app(load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}))
    owner = Actor(uuid4(), None, True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("제안", "w3105", "치유", "web"))
    store.close()
    project_id = str(project.project_id)
    database = root / "db" / "aiqa.sqlite"
    seeded = asyncio.run(_prepare(app, project_id, database, str(owner.actor_id)))
    before = _facts(database, seeded["case_id"], seeded["version_id"])
    saved, replayed, failed, foreign, adopted, page = asyncio.run(_flow(app, project_id, seeded))
    after = _facts(database, seeded["case_id"], seeded["version_id"])
    with sqlite3.connect(database) as connection:
        adoptions = connection.execute("SELECT COUNT(*) FROM repair_adoptions").fetchone()
        recording = connection.execute(
            "SELECT case_id, base_case_version_id FROM recordings WHERE recording_id = ?",
            (adopted["recording_id"],),
        ).fetchone()
    observed = {
        "duplicate_proposal_same": saved["proposal_id"] == replayed["proposal_id"] and replayed["replayed"] is True,
        "foreign_proposal_rejected": foreign == 422,
        "inplace_source_changes": 0 if before == after else 1,
        "new_full_recording": (
            adopted["replayed"] is False
            and recording is not None
            and str(recording[0]) == seeded["case_id"]
            and str(recording[1]) == seeded["version_id"]
            and adoptions is not None
            and int(adoptions[0]) == 1
        ),
    }
    assert failed == 422
    assert "불변 수정 제안" in page
    assert "이전 탭을 입력으로 바꿉니다" in page
    assert "새 전체 녹화" in page
    assert "일부 합치기는 없습니다." in page
    assert "PASS" not in page
    assert observed == {
        "duplicate_proposal_same": True,
        "foreign_proposal_rejected": True,
        "inplace_source_changes": 0,
        "new_full_recording": True,
    }


def test_w31_06(tmp_path: Path) -> None:
    import asyncio

    from aiqa.api.app import create_app
    from aiqa.config import load_settings
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.store.database import migrate_store
    from aiqa.store.models import Actor, ProjectCreate

    root = tmp_path / "runtime"
    app = create_app(load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}))
    owner = Actor(uuid4(), None, True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("치유 화면", "w3106", "치유", "web"))
    store.close()
    project_id = str(project.project_id)
    database = root / "db" / "aiqa.sqlite"
    setup, settings, running, healed, failed, timeline = asyncio.run(_screens(app, project_id, database, str(owner.actor_id)))
    toggle = next(line for line in setup.splitlines() if 'id="healing-toggle"' in line)
    running_toggle = next(line for line in running.splitlines() if 'id="running-healing-toggle"' in line)
    observed = {
        "default_toggle_off": 'data-default="off"' in toggle and "checked" not in toggle,
        "running_toggle_enabled": "disabled" not in running_toggle,
        "healed_pass_badge": 'data-healing-badge="used"' in healed,
        "original_error_hidden": "대상을 찾지 못했습니다" not in healed,
    }
    assert "healing은 꺼져 있습니다." in setup
    assert "항목당 episode는 1개, 호출은 2회, 시간은 30초입니다." in setup
    assert "승인된 healing 범위와 수행에서 켜기는 다릅니다." in settings
    assert "단계 재생" in running
    assert "호출 0" in running
    assert "진행 중에는 바꿀 수 없습니다." in running
    assert timeline["call_count"] == 0
    assert timeline["episode_count"] == 1
    assert timeline["default_enabled"] is False
    assert timeline["original_error"] == "대상을 찾지 못했습니다"
    assert timeline["same_target"] is True
    assert timeline["badge"] is True
    assert "정책과 같은 대상" in healed
    assert "override" in healed
    assert "dispatch" in healed
    assert "QA 만족" in healed
    assert "새 수행" in failed
    assert "화면이 바뀌었습니다" in failed
    assert 'data-healing-badge="used"' not in failed
    assert "PASS" not in setup
    assert "PASS" not in running
    assert "PASS" not in healed
    assert "PASS" not in failed
    assert observed == {
        "default_toggle_off": True,
        "running_toggle_enabled": False,
        "healed_pass_badge": True,
        "original_error_hidden": False,
    }


def _facts(database: Path, case_id: str, version_id: str) -> tuple[object, ...]:
    with sqlite3.connect(database) as connection:
        version = connection.execute(
            "SELECT content_hash, recorded_steps_json FROM case_versions WHERE version_id = ?",
            (version_id,),
        ).fetchone()
        package = connection.execute(
            "SELECT approved_code_hash, body_hash FROM replay_packages WHERE case_version_id = ?",
            (version_id,),
        ).fetchone()
        approval = connection.execute(
            "SELECT current_approval_id FROM automation_cases WHERE case_id = ?",
            (case_id,),
        ).fetchone()
        suites = connection.execute("SELECT COUNT(*), COALESCE(GROUP_CONCAT(suite_version_id), '') FROM suite_versions").fetchone()
        exports = connection.execute("SELECT COUNT(*) FROM jobs WHERE purpose = 'export'").fetchone()
    return (version, package, approval, suites, exports)


async def _prepare(app: object, project_id: str, database: Path, actor_id: str) -> dict[str, str]:
    import httpx

    origin = "http://127.0.0.1"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        headers = await _session(client, origin, project_id, "w3105-case")
        created = await client.post(
            f"/api/v1/projects/{project_id}/cases",
            json={"name": "제안", "tc_reference": None},
            headers=headers,
        )
        headers["Idempotency-Key"] = "w3105-other"
        other = await client.post(
            f"/api/v1/projects/{project_id}/cases",
            json={"name": "다른", "tc_reference": None},
            headers=headers,
        )
    assert created.status_code == 201, created.text
    case_id = created.json()["case_id"]
    seeded = _graph(database, project_id, case_id, actor_id)
    seeded["other_case_id"] = other.json()["case_id"]
    return seeded


async def _flow(app: object, project_id: str, seeded: dict[str, str]):
    import httpx

    origin = "http://127.0.0.1"
    proposal = {
        "project_id": project_id,
        "package_id": seeded["package_id"],
        "accepted_target": {"role": "button", "name": "로그인"},
        "diff": {"text": "이전 탭을 입력으로 바꿉니다"},
        "evidence_hash": "evidence-w3105",
    }
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        headers = await _session(client, origin, project_id, "w3105-flow")
        headers["Idempotency-Key"] = "w3105-proposal"
        first = await client.post(
            f"/api/v1/healing-episodes/{seeded['episode_id']}/repair-proposals",
            json=proposal,
            headers=headers,
        )
        second = await client.post(
            f"/api/v1/healing-episodes/{seeded['episode_id']}/repair-proposals",
            json=proposal,
            headers=headers,
        )
        body = _rerecord(project_id, seeded["version_id"], first.json()["proposal_id"])
        refused = dict(body)
        refused["confirm_reset"] = False
        headers["Idempotency-Key"] = "w3105-refuse"
        failed = await client.post(f"/api/v1/cases/{seeded['case_id']}/rerecordings", json=refused, headers=headers)
        foreign_body = dict(body)
        headers["Idempotency-Key"] = "w3105-foreign"
        foreign = await client.post(
            f"/api/v1/cases/{seeded['other_case_id']}/rerecordings",
            json=foreign_body,
            headers=headers,
        )
        headers["Idempotency-Key"] = "w3105-adopt"
        adopted = await client.post(f"/api/v1/cases/{seeded['case_id']}/rerecordings", json=body, headers=headers)
        page = await client.get(f"/ui/projects/{project_id}/repair-proposals/{first.json()['proposal_id']}")
    assert first.status_code == 201, first.text
    assert second.status_code == 200, second.text
    assert adopted.status_code == 201, adopted.text
    assert page.status_code == 200, page.text
    return first.json(), second.json(), failed.status_code, foreign.status_code, adopted.json(), page.text


def _rerecord(project_id: str, version_id: str, proposal_id: str) -> dict[str, object]:
    return {
        "project_id": project_id,
        "base_version_id": version_id,
        "expected_head": version_id,
        "reason": "전체를 다시 찍습니다",
        "resource_id": "key-w3105",
        "web_url": "http://127.0.0.1/",
        "data_name": "dataset-1",
        "reset_policy": "keep",
        "confirm_device": True,
        "confirm_target": True,
        "confirm_data": True,
        "confirm_reset": True,
        "confirm_diff": True,
        "repair_proposal_id": proposal_id,
    }


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


def _graph(database: Path, project_id: str, case_id: str, actor_id: str) -> dict[str, str]:
    from aiqa.domain.hashing import canonical_hash
    version_id, recording_id, manifest_id = str(uuid4()), str(uuid4()), str(uuid4())
    package_id, episode_id = str(uuid4()), str(uuid4())
    execution_id, run_id, job_id, attempt_id = str(uuid4()), str(uuid4()), str(uuid4()), str(uuid4())
    settings = json.dumps({"target_kind": "web", "limits": {"timeout_seconds": 30}}, sort_keys=True)
    version_hash = canonical_hash({"definition": {}, "settings": json.loads(settings), "recorded_steps": []}, "canon-json-v1")
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "INSERT INTO worker_enrollments (enrollment_id, worker_id, project_id, created_at) VALUES ('enroll-w3105', 'worker-w3105', ?, '2026-11-01T00:00:00+00:00')",
            (project_id,),
        )
        connection.execute(
            "INSERT INTO physical_resource_keys (physical_key_id, worker_id, native_id) VALUES ('key-w3105', 'worker-w3105', 'native-w3105')"
        )
        seed_presence(connection, project_id, "worker-w3105")
        connection.execute(
            "INSERT INTO resource_aliases (project_id, physical_key_id, display_name, target_kind) VALUES (?, 'key-w3105', '준비 웹', 'web')",
            (project_id,),
        )
        connection.execute(
            """
            INSERT INTO resource_inventory (physical_key_id, state, os_build, geometry, permissions, ime, observed_at)
            VALUES ('key-w3105', 'ready', 'build-1', '100x100', '[]', 'none', '2026-11-01T00:00:00+00:00')
            """
        )
        connection.execute(
            "INSERT INTO model_bindings (project_id, binding_id, name, next_revision, latest_revision_id) VALUES (?, 'bind-w3105', '작성', 2, 'rev-w3105')",
            (project_id,),
        )
        connection.execute(
            """
            INSERT INTO binding_revisions (
                project_id, binding_id, revision_id, revision, role, provider, endpoint_kind,
                endpoint, model, key_ref_id, key_revision, prompt_hash, tariff_id,
                compatibility_status, content_hash, actor_id, created_at
            ) VALUES (?, 'bind-w3105', 'rev-w3105', 1, 'authoring', 'fixture', 'loopback',
                'http://127.0.0.1', 'author-model', 'ref-w3105', 1, 'prompt', 'tariff',
                'compatible', 'hash', ?, '2026-11-01T00:00:00+00:00')
            """,
            (project_id, actor_id),
        )
        connection.execute(
            """
            INSERT INTO case_versions (
                project_id, case_id, version_id, revision, creation_kind, parent_version_id, base_version_id,
                is_branch, definition_json, settings_json, recorded_steps_json, content_hash, verification_digest,
                source_manifest_id, replay_package_id, readiness_json, actor_id, reason, created_at
            ) VALUES (?, ?, ?, 1, 'recorded', NULL, NULL, 0, '{}', ?, '[]', ?, 'digest',
                ?, ?, '{}', ?, 'recorded', '2026-11-01T00:00:00+00:00')
            """,
            (project_id, case_id, version_id, settings, version_hash, manifest_id, package_id, actor_id),
        )
        connection.execute(
            "UPDATE automation_cases SET latest_draft_version_id = ?, next_revision = 2 WHERE project_id = ? AND case_id = ?",
            (version_id, project_id, case_id),
        )
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
            ) VALUES (?, ?, ?, ?, 1, 'original', 'script-hash', '[]', '[]', 'complete', ?, 'hash')
            """,
            (project_id, case_id, recording_id, manifest_id, manifest_id),
        )
        connection.execute(
            """
            INSERT INTO replay_packages (
                project_id, package_id, case_id, case_version_id, ready, schema_version, source_manifest_id,
                source_manifest_hash, raw_source_hash, approved_code_hash, runtime_ref, compiler_ref,
                lock_hash, step_mapping_hash, body_hash
            ) VALUES (?, ?, ?, ?, 1, 'v1', ?, 'hash', 'hash', 'code-hash', 'runtime', 'compiler', 'lock', 'map', 'hash')
            """,
            (project_id, package_id, case_id, version_id, manifest_id),
        )
        connection.execute(
            "INSERT INTO package_version_links (project_id, case_id, version_id, package_id) VALUES (?, ?, ?, ?)",
            (project_id, case_id, version_id, package_id),
        )
        connection.execute(
            """
            INSERT INTO executions (project_id, execution_id, name, purpose, source, suite_version_id, scope_requested_at)
            VALUES (?, ?, '수행', 'regression', 'single', NULL, '2026-11-01T00:00:00+00:00')
            """,
            (project_id, execution_id),
        )
        connection.execute(
            """
            INSERT INTO case_runs (
                project_id, execution_id, case_run_id, case_id, case_version_id, purpose, requested_at
            ) VALUES (?, ?, ?, ?, ?, 'regression', '2026-11-01T00:00:00+00:00')
            """,
            (project_id, execution_id, run_id, case_id, version_id),
        )
        connection.execute(
            """
            INSERT INTO jobs (
                project_id, job_id, purpose, recording_id, case_run_id, payload_hash, source_refs, limits, status
            ) VALUES (?, ?, 'regression', NULL, ?, 'payload', '[]', '{}', 'running')
            """,
            (project_id, job_id, run_id),
        )
        connection.execute(
            "INSERT INTO attempts (project_id, attempt_id, job_id, generation, physical_key_id) VALUES (?, ?, ?, 1, NULL)",
            (project_id, attempt_id, job_id),
        )
        connection.execute(
            """
            INSERT INTO healing_episodes (project_id, episode_id, case_run_id, attempt_id, package_id, request_key)
            VALUES (?, ?, ?, ?, ?, 'episode-w3105')
            """,
            (project_id, episode_id, run_id, attempt_id, package_id),
        )
    return {"case_id": case_id, "version_id": version_id, "package_id": package_id, "episode_id": episode_id}


async def _screens(app: object, project_id: str, database: Path, actor_id: str):
    import httpx

    origin = "http://127.0.0.1"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        headers = await _session(client, origin, project_id, "w3106-case")
        created = await client.post(
            f"/api/v1/projects/{project_id}/cases",
            json={"name": "치유 화면", "tc_reference": None},
            headers=headers,
        )
    assert created.status_code == 201, created.text
    seeded = _screen_graph(database, project_id, created.json()["case_id"], actor_id)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        headers = await _session(client, origin, project_id, "w3106-read")
        setup = await client.get(f"/ui/projects/{project_id}/cases/{seeded['case_id']}/execution-setup")
        settings = await client.get(f"/ui/projects/{project_id}/cases/{seeded['case_id']}/definition?tab=settings")
        running = await client.get(f"/ui/projects/{project_id}/executions/{seeded['running_execution_id']}")
        healed = await client.get(f"/ui/projects/{project_id}/case-runs/{seeded['healed_run_id']}")
        failed = await client.get(f"/ui/projects/{project_id}/case-runs/{seeded['failed_run_id']}")
        timeline = await client.get(
            f"/api/v1/case-runs/{seeded['healed_run_id']}/healing-episodes",
            params={"project_id": project_id},
            headers=headers,
        )
    assert setup.status_code == 200, setup.text
    assert settings.status_code == 200, settings.text
    assert running.status_code == 200, running.text
    assert healed.status_code == 200, healed.text
    assert failed.status_code == 200, failed.text
    assert timeline.status_code == 200, timeline.text
    return setup.text, settings.text, running.text, healed.text, failed.text, timeline.json()


def _screen_graph(database: Path, project_id: str, case_id: str, actor_id: str) -> dict[str, str]:
    version_id, recording_id, manifest_id, package_id = str(uuid4()), str(uuid4()), str(uuid4()), str(uuid4())
    healed = _run_ids()
    running = _run_ids()
    failed = _run_ids()
    settings = json.dumps({"target_kind": "web", "limits": {"timeout_seconds": 30}}, sort_keys=True)
    stamp = "2026-11-01T00:00:00+00:00"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO case_versions (
                project_id, case_id, version_id, revision, creation_kind, parent_version_id, base_version_id,
                is_branch, definition_json, settings_json, recorded_steps_json, content_hash, verification_digest,
                source_manifest_id, replay_package_id, readiness_json, actor_id, reason, created_at
            ) VALUES (?, ?, ?, 1, 'recorded', NULL, NULL, 0, '{}', ?, '[]', 'script-hash', 'digest',
                ?, ?, '{}', ?, 'recorded', ?)
            """,
            (project_id, case_id, version_id, settings, manifest_id, package_id, actor_id, stamp),
        )
        connection.execute(
            "UPDATE automation_cases SET latest_draft_version_id = ?, next_revision = 2 WHERE project_id = ? AND case_id = ?",
            (version_id, project_id, case_id),
        )
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
            ) VALUES (?, ?, ?, ?, 1, 'original', 'script-hash', '[]', '[]', 'complete', ?, 'hash')
            """,
            (project_id, case_id, recording_id, manifest_id, manifest_id),
        )
        connection.execute(
            """
            INSERT INTO replay_packages (
                project_id, package_id, case_id, case_version_id, ready, schema_version, source_manifest_id,
                source_manifest_hash, raw_source_hash, approved_code_hash, runtime_ref, compiler_ref,
                lock_hash, step_mapping_hash, body_hash
            ) VALUES (?, ?, ?, ?, 1, 'v1', ?, 'hash', 'hash', 'code-hash', 'runtime', 'compiler', 'lock', 'map', 'hash')
            """,
            (project_id, package_id, case_id, version_id, manifest_id),
        )
        connection.execute(
            "INSERT INTO package_version_links (project_id, case_id, version_id, package_id) VALUES (?, ?, ?, ?)",
            (project_id, case_id, version_id, package_id),
        )
        _insert_run(connection, project_id, case_id, version_id, healed, "completed", stamp)
        _insert_run(connection, project_id, case_id, version_id, running, "running", stamp)
        _insert_run(connection, project_id, case_id, version_id, failed, "completed", stamp)
        _insert_episode(connection, project_id, healed, package_id, "heal-w3106", "target_not_found", True, "satisfied", "observed")
        _insert_episode(connection, project_id, failed, package_id, "fail-w3106", "layout_shift", False, "violated", "lookup_failed")
    return {
        "case_id": case_id,
        "running_execution_id": running["execution_id"],
        "healed_run_id": healed["run_id"],
        "failed_run_id": failed["run_id"],
    }


def _run_ids() -> dict[str, str]:
    return {
        "execution_id": str(uuid4()),
        "run_id": str(uuid4()),
        "job_id": str(uuid4()),
        "attempt_id": str(uuid4()),
        "episode_id": str(uuid4()),
    }


def _insert_run(
    connection: sqlite3.Connection,
    project_id: str,
    case_id: str,
    version_id: str,
    ids: dict[str, str],
    status: str,
    stamp: str,
) -> None:
    connection.execute(
        """
        INSERT INTO executions (project_id, execution_id, name, purpose, source, suite_version_id, scope_requested_at)
        VALUES (?, ?, '수행', 'trial', 'single', NULL, ?)
        """,
        (project_id, ids["execution_id"], stamp),
    )
    connection.execute(
        """
        INSERT INTO case_runs (
            project_id, execution_id, case_run_id, case_id, case_version_id, purpose, requested_at
        ) VALUES (?, ?, ?, ?, ?, 'trial', ?)
        """,
        (project_id, ids["execution_id"], ids["run_id"], case_id, version_id, stamp),
    )
    connection.execute(
        """
        INSERT INTO jobs (
            project_id, job_id, purpose, recording_id, case_run_id, payload_hash, source_refs, limits, status
        ) VALUES (?, ?, 'trial', NULL, ?, 'payload', '[]', '{}', ?)
        """,
        (project_id, ids["job_id"], ids["run_id"], status),
    )
    connection.execute(
        "INSERT INTO attempts (project_id, attempt_id, job_id, generation, physical_key_id) VALUES (?, ?, ?, 1, NULL)",
        (project_id, ids["attempt_id"], ids["job_id"]),
    )


def _insert_episode(
    connection: sqlite3.Connection,
    project_id: str,
    ids: dict[str, str],
    package_id: str,
    request_key: str,
    reason: str,
    recovered: bool,
    qa_status: str,
    dispatch_state: str,
) -> None:
    connection.execute(
        """
        INSERT INTO healing_episodes (project_id, episode_id, case_run_id, attempt_id, package_id, request_key)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (project_id, ids["episode_id"], ids["run_id"], ids["attempt_id"], package_id, request_key),
    )
    connection.execute(
        """
        INSERT INTO healing_reservations (
            project_id, reservation_id, episode_id, case_run_id, request_key, reason,
            reserved_calls, reserved_seconds, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, 2, 30, '2026-11-01T00:00:00+00:00')
        """,
        (project_id, str(uuid4()), ids["episode_id"], ids["run_id"], request_key, reason),
    )
    if recovered:
        connection.execute(
            """
            INSERT INTO repair_proposals (
                project_id, proposal_id, episode_id, case_run_id, attempt_id, package_id, request_key, diff_hash,
                accepted_target_json, diff_json, evidence_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'diff-hash', '{"same_target": true}', '{"text":"화면"}', 'evidence')
            """,
            (project_id, str(uuid4()), ids["episode_id"], ids["run_id"], ids["attempt_id"], package_id, request_key),
        )
        connection.execute(
            """
            INSERT INTO runtime_overrides (
                project_id, override_id, episode_id, case_run_id, attempt_id, package_id, request_key, body_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'override-hash')
            """,
            (project_id, str(uuid4()), ids["episode_id"], ids["run_id"], ids["attempt_id"], package_id, request_key),
        )
    connection.execute(
        """
        INSERT INTO actions (
            project_id, attempt_id, action_seq, step_id, action_id, proposal_hash,
            dispatch_state, case_id, case_version_id, outcome_known
        )
        SELECT ?, ?, 1, 'step-1', ?, 'proposal-hash', ?, case_id, case_version_id, 1
        FROM case_runs
        WHERE project_id = ? AND case_run_id = ?
        """,
        (project_id, ids["attempt_id"], request_key, dispatch_state, project_id, ids["run_id"]),
    )
    connection.execute(
        """
        INSERT INTO check_results (
            project_id, attempt_id, action_id, check_id, status, method, expected_snapshot,
            sanitized_observed, reason, artifact_refs, observed_at
        ) VALUES (?, ?, ?, ?, ?, 'deterministic', '보임', '보임', '확인', '', '2026-11-01T00:00:00+00:00')
        """,
        (project_id, ids["attempt_id"], request_key, request_key, qa_status),
    )
