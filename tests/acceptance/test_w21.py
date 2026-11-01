"""An empty suite can be saved, and a running suite snapshot stays in place."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4


def test_w21_01(tmp_path: Path) -> None:
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
        project = create_project(owner, ProjectCreate("묶음", "w2101", "목록", "web"))
        other = create_project(owner, ProjectCreate("다른", "w2101b", "목록", "web"))
    store.close()
    project_id = str(project.project_id)
    database = root / "db" / "aiqa.sqlite"
    created, other_name = asyncio.run(_save(app, project_id, str(other.project_id)))
    execution_id = _attach_run(database, project_id, created["version_id"])
    before = _run_row(database, execution_id)
    cloned, archived, refused, page, foreign, hidden = asyncio.run(
        _flow(app, project_id, str(other.project_id), created["suite_id"], other_name)
    )
    after = _run_row(database, execution_id)
    executions = _count(database, "SELECT COUNT(*) FROM executions WHERE project_id = ?", project_id)
    observed = {
        "empty_suite_saved": created["entry_count"] == 0 and cloned["entry_count"] == 0 and archived["archived_at"] != "",
        "empty_suite_executable": refused == 200,
        "existing_run_unchanged": before == after and executions == 1,
    }
    assert "빈 묶음" in page
    assert "구성 0" in page
    assert "담당 담당자" in page
    assert "보관" in page
    assert "복사 묶음" in page
    assert "이력 1" in page
    assert created["suite_id"] in page
    assert "묶음이 없습니다." in foreign
    assert hidden["items"] == []
    assert "PASS" not in page
    assert observed == {
        "empty_suite_saved": True,
        "empty_suite_executable": False,
        "existing_run_unchanged": True,
    }


def _run_row(database: Path, execution_id: str) -> tuple[object, ...] | None:
    with sqlite3.connect(database) as connection:
        return connection.execute(
            """
            SELECT name, purpose, source, suite_version_id, scope_requested_at
            FROM executions WHERE execution_id = ?
            """,
            (execution_id,),
        ).fetchone()


def _count(database: Path, sql: str, project_id: str) -> int:
    with sqlite3.connect(database) as connection:
        row = connection.execute(sql, (project_id,)).fetchone()
    return 0 if row is None else int(row[0])


def _attach_run(database: Path, project_id: str, version_id: str) -> str:
    execution_id = str(uuid4())
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO executions (
                project_id, execution_id, name, purpose, source, suite_version_id, scope_requested_at
            ) VALUES (?, ?, '진행 묶음', 'regression', 'suite', ?, '2026-11-01T00:00:00+00:00')
            """,
            (project_id, execution_id, version_id),
        )
    return execution_id


async def _save(app: object, project_id: str, other_project_id: str):
    import httpx

    origin = "http://127.0.0.1"
    body = {
        "name": "빈 묶음",
        "description": "설명",
        "target_kind": "web",
        "owner_name": "담당자",
        "classification": "회귀",
    }
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        headers = await _session(client, origin, project_id, "w2101-save")
        headers["Idempotency-Key"] = "w2101-create"
        created = await client.post(f"/api/v1/projects/{project_id}/suites", json=body, headers=headers)
        other_headers = await _session(client, origin, other_project_id, "w2101-other")
        other_headers["Idempotency-Key"] = "w2101-other-create"
        other = await client.post(
            f"/api/v1/projects/{other_project_id}/suites",
            json={"name": "다른 묶음", "description": "", "target_kind": "web", "owner_name": "다른", "classification": "기타"},
            headers=other_headers,
        )
    assert created.status_code == 201, created.text
    assert other.status_code == 201, other.text
    return created.json(), other.json()["name"]


async def _flow(app: object, project_id: str, other_project_id: str, suite_id: str, other_name: str):
    import httpx

    origin = "http://127.0.0.1"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        headers = await _session(client, origin, project_id, "w2101-flow")
        headers["Idempotency-Key"] = "w2101-clone"
        cloned = await client.post(
            f"/api/v1/suites/{suite_id}/clone",
            json={"project_id": project_id, "name": "복사 묶음"},
            headers=headers,
        )
        headers["Idempotency-Key"] = "w2101-archive"
        archived = await client.post(
            f"/api/v1/suites/{suite_id}/archive",
            json={"project_id": project_id},
            headers=headers,
        )
        headers["Idempotency-Key"] = "w2101-run"
        refused = await client.post(
            f"/api/v1/suites/{suite_id}/executions",
            json={"project_id": project_id},
            headers=headers,
        )
        page = await client.get(f"/ui/projects/{project_id}/suites")
        foreign = await client.get(f"/ui/projects/{project_id}/suites?q={other_name}")
        hidden = await client.get(
            f"/api/v1/projects/{project_id}/suites",
            params={"q": other_name},
            headers=headers,
        )
    assert cloned.status_code == 201, cloned.text
    assert archived.status_code == 200, archived.text
    assert page.status_code == 200, page.text
    assert foreign.status_code == 200, foreign.text
    assert hidden.status_code == 200, hidden.text
    return cloned.json(), archived.json(), refused.status_code, page.text, foreign.text, hidden.json()


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


def test_w21_02(tmp_path: Path) -> None:
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
        project = create_project(owner, ProjectCreate("구성", "w2102", "편집", "web"))
    store.close()
    project_id = str(project.project_id)
    database = root / "db" / "aiqa.sqlite"
    created = asyncio.run(_create_suite(app, project_id))
    seed = _seed_revision(database, project_id, str(owner.actor_id))
    first, duplicate, repeated = asyncio.run(_save_revision(app, project_id, created["suite_id"], seed, False))
    before = _revision_rows(database, first["suite_version_id"])
    second, missing, page = asyncio.run(_save_revision(app, project_id, created["suite_id"], seed, True))
    after = _revision_rows(database, first["suite_version_id"])
    saved_ids = [item["entry_id"] for item in first["entries"]]
    web_rows = [item["data_name"] for item in first["entries"] if item["case_id"] == seed["web_case"]]
    targets = {item["target_kind"] for item in first["entries"]}
    observed = {
        "entry_ids_unique": len(saved_ids) == len(set(saved_ids)) == 3 and duplicate == 422,
        "data_rows_distinct": len(set(web_rows)) == 2 and repeated == 422,
        "mixed_resource_required": missing == 422 and targets == {"web", "android"} and all(item["resource_id"] for item in first["entries"]),
        "old_suite_revision_unchanged": before == after and second["suite_version_id"] != first["suite_version_id"],
    }
    assert first["entries"][0]["case_version_id"] == seed["version_a"]
    assert second["entries"][0]["entry_id"] == "entry-android"
    assert seed["version_b"] in {item["case_version_id"] for item in second["entries"]}
    assert seed["version_b"] not in {row[2] for row in before[1]}
    assert len(first["entries"]) == len(second["entries"]) == 3
    assert "승인된 검증 로그인 검증" in page
    assert "행-가" in page
    assert "순서를 바꿀 수 있습니다" in page
    assert "없는 자원은 저장하지 않습니다" in page
    assert "이전 구성은 그대로입니다" in page
    assert "PASS" not in page
    assert observed == {
        "entry_ids_unique": True,
        "data_rows_distinct": True,
        "mixed_resource_required": True,
        "old_suite_revision_unchanged": True,
    }


def _revision_rows(database: Path, version_id: str) -> tuple[object, ...]:
    with sqlite3.connect(database) as connection:
        version = connection.execute(
            "SELECT content_hash FROM suite_versions WHERE suite_version_id = ?",
            (version_id,),
        ).fetchone()
        entries = connection.execute(
            """
            SELECT entry_id, position, case_version_id, data_name, resource_id, target_kind
            FROM suite_entries WHERE suite_version_id = ?
            ORDER BY position, entry_id
            """,
            (version_id,),
        ).fetchall()
    return version, entries


def _seed_revision(database: Path, project_id: str, actor_id: str) -> dict[str, str]:
    web_case, android_case = str(uuid4()), str(uuid4())
    version_a, version_b, version_android = str(uuid4()), str(uuid4()), str(uuid4())
    approval_a, approval_b, approval_android = str(uuid4()), str(uuid4()), str(uuid4())
    review_a, review_b, review_android = str(uuid4()), str(uuid4()), str(uuid4())
    environment_id, revision_id = str(uuid4()), str(uuid4())
    stamp = "2026-11-01T00:00:00+00:00"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        for case_id, name, nxt in ((web_case, "로그인 검증", 3), (android_case, "기기 검증", 2)):
            connection.execute(
                """
                INSERT INTO automation_cases (
                    project_id, case_id, name, folder_id, tc_reference, next_revision,
                    latest_draft_version_id, current_approval_id, lock_version, archived_at
                ) VALUES (?, ?, ?, NULL, NULL, ?, NULL, NULL, 0, NULL)
                """,
                (project_id, case_id, name, nxt),
            )
        _case_version(connection, project_id, web_case, version_a, 1, actor_id, stamp)
        _case_version(connection, project_id, web_case, version_b, 2, actor_id, stamp)
        _case_version(connection, project_id, android_case, version_android, 1, actor_id, stamp)
        for review_id, case_id, version_id, approval_id in (
            (review_a, web_case, version_a, approval_a),
            (review_b, web_case, version_b, approval_b),
            (review_android, android_case, version_android, approval_android),
        ):
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
                INSERT INTO approval_events (
                    project_id, approval_id, case_id, case_version_id, review_id, event_kind,
                    prior_approval_id, version_hash, evidence_set_hash, reason
                ) VALUES (?, ?, ?, ?, ?, 'approved', NULL, 'version-hash', 'evidence-hash', '승인')
                """,
                (project_id, approval_id, case_id, version_id, review_id),
            )
        connection.execute(
            "UPDATE automation_cases SET current_approval_id = ? WHERE project_id = ? AND case_id = ?",
            (approval_b, project_id, web_case),
        )
        connection.execute(
            "UPDATE automation_cases SET current_approval_id = ? WHERE project_id = ? AND case_id = ?",
            (approval_android, project_id, android_case),
        )
        connection.execute(
            """
            INSERT INTO environments (project_id, environment_id, name, next_revision, latest_revision_id)
            VALUES (?, ?, '기본 환경', 2, ?)
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
            "INSERT INTO worker_enrollments (enrollment_id, worker_id, project_id, created_at) VALUES ('enroll-w2102', 'worker-w2102', ?, ?)",
            (project_id, stamp),
        )
        connection.execute(
            "INSERT INTO physical_resource_keys (physical_key_id, worker_id, native_id) VALUES ('key-web-w2102', 'worker-w2102', 'native-web')"
        )
        connection.execute(
            "INSERT INTO physical_resource_keys (physical_key_id, worker_id, native_id) VALUES ('key-android-w2102', 'worker-w2102', 'native-android')"
        )
        connection.execute(
            "INSERT INTO resource_aliases (project_id, physical_key_id, display_name, target_kind) VALUES (?, 'key-web-w2102', '웹 자원', 'web')",
            (project_id,),
        )
        connection.execute(
            "INSERT INTO resource_aliases (project_id, physical_key_id, display_name, target_kind) VALUES (?, 'key-android-w2102', '기기 자원', 'android')",
            (project_id,),
        )
    return {
        "web_case": web_case,
        "android_case": android_case,
        "version_a": version_a,
        "version_b": version_b,
        "version_android": version_android,
        "approval_a": approval_a,
        "approval_b": approval_b,
        "approval_android": approval_android,
        "environment": revision_id,
    }


def _case_version(
    connection: sqlite3.Connection,
    project_id: str,
    case_id: str,
    version_id: str,
    revision: int,
    actor_id: str,
    stamp: str,
    definition: str = "{}",
    settings: str = "{}",
    steps: str = "[]",
) -> None:
    connection.execute(
        """
        INSERT INTO case_versions (
            project_id, case_id, version_id, revision, creation_kind, parent_version_id, base_version_id,
            is_branch, definition_json, settings_json, recorded_steps_json, content_hash, verification_digest,
            source_manifest_id, replay_package_id, readiness_json, actor_id, reason, created_at
        ) VALUES (?, ?, ?, ?, 'recorded', NULL, NULL, 0, ?, ?, ?, 'version-hash', 'digest',
            NULL, NULL, '{}', ?, 'recorded', ?)
        """,
        (project_id, case_id, version_id, revision, definition, settings, steps, actor_id, stamp),
    )


async def _create_suite(app: object, project_id: str):
    import httpx

    origin = "http://127.0.0.1"
    body = {"name": "구성 묶음", "description": "편집", "target_kind": "web", "owner_name": "담당자", "classification": "회귀"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        headers = await _session(client, origin, project_id, "w2102-create")
        created = await client.post(f"/api/v1/projects/{project_id}/suites", json=body, headers=headers)
    assert created.status_code == 201, created.text
    return created.json()


async def _save_revision(app: object, project_id: str, suite_id: str, seed: dict[str, str], reorder: bool):
    import httpx

    origin = "http://127.0.0.1"
    first_entries = _mixed_entries(seed, "key-android-w2102", seed["version_a"], seed["approval_a"])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        headers = await _session(client, origin, project_id, "w2102-edit" if not reorder else "w2102-reorder")
        if not reorder:
            headers["Idempotency-Key"] = "w2102-first"
            saved = await client.post(f"/api/v1/suites/{suite_id}/versions", json={"project_id": project_id, "entries": first_entries}, headers=headers)
            headers["Idempotency-Key"] = "w2102-duplicate"
            duplicated = list(first_entries)
            duplicated[1] = {**duplicated[1], "entry_id": duplicated[0]["entry_id"], "data_name": "다른 행"}
            duplicate = await client.post(f"/api/v1/suites/{suite_id}/versions", json={"project_id": project_id, "entries": duplicated}, headers=headers)
            headers["Idempotency-Key"] = "w2102-repeated"
            repeated_rows = list(first_entries)
            repeated_rows[1] = {**repeated_rows[1], "data_name": repeated_rows[0]["data_name"]}
            repeated = await client.post(f"/api/v1/suites/{suite_id}/versions", json={"project_id": project_id, "entries": repeated_rows}, headers=headers)
            assert saved.status_code == 201, saved.text
            return saved.json(), duplicate.status_code, repeated.status_code
        ordered = [
            _mixed_entries(seed, "key-android-w2102", seed["version_b"], seed["approval_b"])[2],
            first_entries[1],
            {**first_entries[0], "case_version_id": seed["version_b"], "approval_id": seed["approval_b"]},
        ]
        headers["Idempotency-Key"] = "w2102-second"
        saved = await client.post(f"/api/v1/suites/{suite_id}/versions", json={"project_id": project_id, "entries": ordered}, headers=headers)
        headers["Idempotency-Key"] = "w2102-missing"
        missing_rows = _mixed_entries(seed, "absent-key", seed["version_a"], seed["approval_a"])
        missing = await client.post(f"/api/v1/suites/{suite_id}/versions", json={"project_id": project_id, "entries": missing_rows}, headers=headers)
        page = await client.get(f"/ui/projects/{project_id}/suites/{suite_id}")
    assert saved.status_code == 201, saved.text
    assert page.status_code == 200, page.text
    return saved.json(), missing.status_code, page.text


def _mixed_entries(seed: dict[str, str], android_resource: str, web_version: str, web_approval: str) -> list[dict[str, object]]:
    return [
        _entry("entry-web-a", seed["web_case"], web_version, web_approval, "행-가", seed["environment"], "keep", "continue", "key-web-w2102", "web"),
        _entry("entry-web-b", seed["web_case"], web_version, web_approval, "행-나", seed["environment"], "reset", "stop", "key-web-w2102", "web"),
        _entry("entry-android", seed["android_case"], seed["version_android"], seed["approval_android"], "기기 행", seed["environment"], "keep", "stop", android_resource, "android"),
    ]


def test_w21_03(tmp_path: Path) -> None:
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
        project = create_project(owner, ProjectCreate("교체", "w2103", "승인", "web"))
    store.close()
    project_id = str(project.project_id)
    database = root / "db" / "aiqa.sqlite"
    created = asyncio.run(_create_suite(app, project_id))
    seed = _seed_v2(database, project_id, str(owner.actor_id))
    pinned = asyncio.run(_pin_suite(app, project_id, created["suite_id"], seed))
    _approve_v4(database, project_id, str(owner.actor_id), seed)
    execution_id = _attach_run(database, project_id, pinned["suite_version_id"])
    before_run = _run_row(database, execution_id)
    before_rows = _revision_rows(database, pinned["suite_version_id"])
    before_count = _count(database, "SELECT COUNT(*) FROM suite_versions WHERE suite_id = ?", created["suite_id"])
    proposals, rejected = asyncio.run(_reject_upgrade(app, project_id, created["suite_id"], pinned["suite_version_id"]))
    after_reject = _count(database, "SELECT COUNT(*) FROM suite_versions WHERE suite_id = ?", created["suite_id"])
    accepted, accept_status, conflict, page = asyncio.run(
        _accept_upgrade(app, project_id, created["suite_id"], pinned["suite_version_id"])
    )
    after_accept = _count(database, "SELECT COUNT(*) FROM suite_versions WHERE suite_id = ?", created["suite_id"])
    after_run = _run_row(database, execution_id)
    after_rows = _revision_rows(database, pinned["suite_version_id"])
    moved = [item for item in accepted["entries"] if item["case_version_id"] == seed["version_v4"] and item["entry_id"] != "entry-move"]
    observed = {
        "auto_upgraded_entries": len(moved),
        "reject_new_revisions": after_reject - before_count,
        "accepted_upgrade_new_revision": after_accept - after_reject,
        "old_run_unchanged": before_run == after_run and before_rows == after_rows,
    }
    assert rejected == 200
    assert accept_status == 201
    assert conflict == 409
    assert len(proposals["items"]) == 2
    assert proposals["items"][0]["definition_from"] != proposals["items"][0]["definition_to"]
    assert proposals["items"][0]["procedure_from"] != proposals["items"][0]["procedure_to"]
    assert proposals["items"][0]["policy_from"] != proposals["items"][0]["policy_to"]
    assert {item["entry_id"] for item in accepted["entries"] if item["case_version_id"] == seed["version_v2"]} == {"entry-keep"}
    assert "새 승인이 있습니다" in page
    assert "정의" in page and "절차" in page and "정책" in page
    assert "영향 항목" in page
    assert "선택한 항목만" in page
    assert "이전 승인" in page
    assert "PASS" not in page
    assert observed == {
        "auto_upgraded_entries": 0,
        "reject_new_revisions": 0,
        "accepted_upgrade_new_revision": 1,
        "old_run_unchanged": True,
    }


def _seed_v2(database: Path, project_id: str, actor_id: str) -> dict[str, str]:
    case_id, version_id, approval_id, review_id = str(uuid4()), str(uuid4()), str(uuid4()), str(uuid4())
    environment_id, revision_id = str(uuid4()), str(uuid4())
    stamp = "2026-11-01T00:00:00+00:00"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO automation_cases (
                project_id, case_id, name, folder_id, tc_reference, next_revision,
                latest_draft_version_id, current_approval_id, lock_version, archived_at
            ) VALUES (?, ?, '로그인 검증', NULL, NULL, 5, NULL, NULL, 0, NULL)
            """,
            (project_id, case_id),
        )
        _case_version(connection, project_id, case_id, version_id, 2, actor_id, stamp, '{"name":"정의-이전"}', '{"name":"정책-이전"}', '[{"name":"절차-이전"}]')
        _approval(connection, project_id, case_id, version_id, review_id, approval_id)
        connection.execute(
            "UPDATE automation_cases SET current_approval_id = ? WHERE project_id = ? AND case_id = ?",
            (approval_id, project_id, case_id),
        )
        _environment(connection, project_id, environment_id, revision_id, actor_id, stamp)
        _web_resource(connection, project_id, stamp, "w2103")
    return {"case_id": case_id, "version_v2": version_id, "approval_v2": approval_id, "environment": revision_id}


def _approve_v4(database: Path, project_id: str, actor_id: str, seed: dict[str, str]) -> None:
    version_id, approval_id, review_id = str(uuid4()), str(uuid4()), str(uuid4())
    stamp = "2026-11-01T01:00:00+00:00"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        _case_version(
            connection, project_id, seed["case_id"], version_id, 4, actor_id, stamp,
            '{"name":"정의-이후"}', '{"name":"정책-이후"}', '[{"name":"절차-이후"}]',
        )
        _approval(connection, project_id, seed["case_id"], version_id, review_id, approval_id)
        connection.execute(
            "UPDATE automation_cases SET current_approval_id = ? WHERE project_id = ? AND case_id = ?",
            (approval_id, project_id, seed["case_id"]),
        )
    seed["version_v4"] = version_id
    seed["approval_v4"] = approval_id


def _approval(connection: sqlite3.Connection, project_id: str, case_id: str, version_id: str, review_id: str, approval_id: str) -> None:
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
        INSERT INTO approval_events (
            project_id, approval_id, case_id, case_version_id, review_id, event_kind,
            prior_approval_id, version_hash, evidence_set_hash, reason
        ) VALUES (?, ?, ?, ?, ?, 'approved', NULL, 'version-hash', 'evidence-hash', '승인')
        """,
        (project_id, approval_id, case_id, version_id, review_id),
    )


def _environment(connection: sqlite3.Connection, project_id: str, environment_id: str, revision_id: str, actor_id: str, stamp: str) -> None:
    connection.execute(
        """
        INSERT INTO environments (project_id, environment_id, name, next_revision, latest_revision_id)
        VALUES (?, ?, '기본 환경', 2, ?)
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


def _web_resource(connection: sqlite3.Connection, project_id: str, stamp: str, suffix: str) -> None:
    connection.execute(
        "INSERT INTO worker_enrollments (enrollment_id, worker_id, project_id, created_at) VALUES (?, ?, ?, ?)",
        (f"enroll-{suffix}", f"worker-{suffix}", project_id, stamp),
    )
    connection.execute(
        "INSERT INTO physical_resource_keys (physical_key_id, worker_id, native_id) VALUES (?, ?, ?)",
        (f"key-web-{suffix}", f"worker-{suffix}", f"native-{suffix}"),
    )
    connection.execute(
        "INSERT INTO resource_aliases (project_id, physical_key_id, display_name, target_kind) VALUES (?, ?, '웹 자원', 'web')",
        (project_id, f"key-web-{suffix}"),
    )


async def _pin_suite(app: object, project_id: str, suite_id: str, seed: dict[str, str]):
    import httpx

    origin = "http://127.0.0.1"
    entries = [
        _entry("entry-keep", seed["case_id"], seed["version_v2"], seed["approval_v2"], "행-유지", seed["environment"], "keep", "stop", "key-web-w2103", "web"),
        _entry("entry-move", seed["case_id"], seed["version_v2"], seed["approval_v2"], "행-교체", seed["environment"], "keep", "continue", "key-web-w2103", "web"),
    ]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        headers = await _session(client, origin, project_id, "w2103-pin")
        headers["Idempotency-Key"] = "w2103-pin"
        saved = await client.post(f"/api/v1/suites/{suite_id}/versions", json={"project_id": project_id, "entries": entries}, headers=headers)
    assert saved.status_code == 201, saved.text
    return saved.json()


async def _reject_upgrade(app: object, project_id: str, suite_id: str, version_id: str):
    import httpx

    origin = "http://127.0.0.1"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        headers = await _session(client, origin, project_id, "w2103-reject")
        proposals = await client.get(
            f"/api/v1/suites/{suite_id}/upgrade-proposals",
            params={"project_id": project_id},
            headers=headers,
        )
        headers["Idempotency-Key"] = "w2103-reject"
        rejected = await client.post(
            f"/api/v1/suites/{suite_id}/versions",
            json={"project_id": project_id, "decision": "reject", "expected_version_id": version_id},
            headers=headers,
        )
    assert proposals.status_code == 200, proposals.text
    return proposals.json(), rejected.status_code


async def _accept_upgrade(app: object, project_id: str, suite_id: str, version_id: str):
    import httpx

    origin = "http://127.0.0.1"
    body = {"project_id": project_id, "decision": "accept", "expected_version_id": version_id, "entry_ids": ["entry-move"]}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        headers = await _session(client, origin, project_id, "w2103-accept")
        headers["Idempotency-Key"] = "w2103-accept"
        accepted = await client.post(f"/api/v1/suites/{suite_id}/versions", json=body, headers=headers)
        headers["Idempotency-Key"] = "w2103-stale"
        conflict = await client.post(f"/api/v1/suites/{suite_id}/versions", json=body, headers=headers)
        page = await client.get(f"/ui/projects/{project_id}/suites/{suite_id}")
    assert page.status_code == 200, page.text
    return accepted.json(), accepted.status_code, conflict.status_code, page.text


def test_w21_04(tmp_path: Path) -> None:
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
        project = create_project(owner, ProjectCreate("펼침", "w2104", "실행", "web"))
    store.close()
    project_id = str(project.project_id)
    environment_id, resource_id = str(uuid4()), str(uuid4())
    observed, page, extra = asyncio.run(_expand(app, root / "db" / "aiqa.sqlite", project_id, environment_id, resource_id))
    assert extra["accepted_99"] == 99
    assert extra["excluded_status"] == 422
    assert extra["duplicate_status"] == 422
    assert extra["partial_silent"] == 0 and extra["partial_kept"] is True
    assert extra["suite_ids"] == ["suite-a", "suite-b"] and extra["suite_silent"] == 0
    assert extra["empty_suite_status"] == 422
    assert extra["release_floor_runs"] == 30 and extra["proposed_n"] == 100
    assert "케이스 버전과 데이터 행과 대상으로 펼칩니다." in page
    assert "같은 항목 번호는 거절됩니다." in page
    assert "미승인 항목을 자동으로 빼지 않습니다." in page
    assert "월 3000은 release label의 최소 30회 수행으로 집계합니다." in page
    assert "항목이 0이거나 100을 넘으면 시작하지 않습니다." in page
    assert "PASS" not in page
    assert observed == {
        "limit_100_accepted": True,
        "limit_101_status": 422,
        "zero_items_status": 422,
        "silent_exclusions": 0,
    }


async def _expand(app: object, database: Path, project_id: str, environment_id: str, resource_id: str):
    import httpx

    origin = "http://127.0.0.1"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        headers = await _session(client, origin, project_id, "w2104")
        headers["Idempotency-Key"] = "w2104-case"
        created = await client.post(
            f"/api/v1/projects/{project_id}/cases",
            json={"name": "펼침", "tc_reference": None},
            headers=headers,
        )
        headers["Idempotency-Key"] = "w2104-version"
        version = await client.post(
            f"/api/v1/projects/{project_id}/cases/{created.json()['case_id']}/versions",
            json={"definition": {"final_expected": [{"id": "exp-1", "kind": "text", "expected": "보임"}]}, "settings": {"target_kind": "web"}},
            headers=headers,
        )
        assert created.status_code == 201, created.text
        assert version.status_code == 201, version.text
        version_id = version.json()["id"]
        case_id = created.json()["case_id"]
        page = await client.get(f"/ui/projects/{project_id}/cases/{case_id}/execution-setup")
        headers["Idempotency-Key"] = "w2104-99"
        accepted_99 = await client.post(
            f"/api/v1/projects/{project_id}/execution-previews",
            json=_rows(version_id, environment_id, resource_id, 99, "2026-11"),
            headers=headers,
        )
        headers["Idempotency-Key"] = "w2104-100"
        accepted = await client.post(
            f"/api/v1/projects/{project_id}/execution-previews",
            json=_rows(version_id, environment_id, resource_id, 100, "2026-11"),
            headers=headers,
        )
        headers["Idempotency-Key"] = "w2104-101"
        over = await client.post(
            f"/api/v1/projects/{project_id}/execution-previews",
            json=_rows(version_id, environment_id, resource_id, 101, "2026-11"),
            headers=headers,
        )
        headers["Idempotency-Key"] = "w2104-zero"
        zero = await client.post(
            f"/api/v1/projects/{project_id}/execution-previews",
            json=_selection(version_id, environment_id, resource_id, []),
            headers=headers,
        )
        headers["Idempotency-Key"] = "w2104-excluded"
        excluded = await client.post(
            f"/api/v1/projects/{project_id}/execution-previews",
            json=_excluded(version_id, environment_id, resource_id),
            headers=headers,
        )
        headers["Idempotency-Key"] = "w2104-duplicate"
        duplicate = await client.post(
            f"/api/v1/projects/{project_id}/execution-previews",
            json=_duplicate(version_id, environment_id, resource_id),
            headers=headers,
        )
        headers["Idempotency-Key"] = "w2104-partial"
        partial = await client.post(
            f"/api/v1/projects/{project_id}/execution-previews",
            json=_partial_selection(version_id, environment_id, resource_id),
            headers=headers,
        )
    suite_version_id, empty_version_id = _seed_suite(database, project_id, case_id, version_id, environment_id, resource_id)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        headers = await _session(client, origin, project_id, "w2104-suite")
        headers["Idempotency-Key"] = "w2104-suite"
        suite = await client.post(
            f"/api/v1/projects/{project_id}/execution-previews",
            json=_suite_body(suite_version_id),
            headers=headers,
        )
        headers["Idempotency-Key"] = "w2104-empty-suite"
        empty_suite = await client.post(
            f"/api/v1/projects/{project_id}/execution-previews",
            json=_suite_body(empty_version_id),
            headers=headers,
        )
    body = accepted.json()
    partial_body = partial.json()
    suite_body = suite.json()
    kept = {item["entry_id"] for item in partial_body["resolved_items"]}
    observed = {
        "limit_100_accepted": accepted.status_code == 200 and body["proposed_n"] == 100,
        "limit_101_status": over.status_code,
        "zero_items_status": zero.status_code,
        "silent_exclusions": body["silent_exclusions"],
    }
    extra = {
        "accepted_99": accepted_99.json()["proposed_n"],
        "excluded_status": excluded.status_code,
        "duplicate_status": duplicate.status_code,
        "partial_silent": partial_body["silent_exclusions"],
        "partial_kept": "keep" in kept and "unavailable" in kept,
        "suite_ids": [item["entry_id"] for item in suite_body["resolved_items"]],
        "suite_silent": suite_body["silent_exclusions"],
        "empty_suite_status": empty_suite.status_code,
        "release_floor_runs": body["release_floor_runs"],
        "proposed_n": body["proposed_n"],
    }
    assert page.status_code == 200, page.text
    assert accepted_99.status_code == 200, accepted_99.text
    assert suite.status_code == 200, suite.text
    return observed, page.text, extra


def _rows(version_id: str, environment_id: str, resource_id: str, count: int, label: str) -> dict[str, object]:
    return {
        "name": "펼침",
        "purpose": "trial",
        "source": "single",
        "failure_policy": "continue",
        "self_healing_enabled": False,
        "release_label": label,
        "exclusions": [],
        "selection": {
            "items": [
                {
                    "entry_id": "row-base",
                    "case_version_id": version_id,
                    "environment_revision_id": environment_id,
                    "resource_id": resource_id,
                    "install_policy": "none",
                    "data_rows": [f"row-{index}" for index in range(count)],
                    "targets": ["web"],
                }
            ]
        },
    }


def _selection(version_id: str, environment_id: str, resource_id: str, items: list[dict[str, object]]) -> dict[str, object]:
    return {
        "name": "펼침",
        "purpose": "regression",
        "source": "selection",
        "failure_policy": "continue",
        "self_healing_enabled": False,
        "exclusions": [],
        "selection": {"items": items},
    }


def _choice(entry_id: str, version_id: str, environment_id: str, resource_id: str) -> dict[str, object]:
    return {
        "entry_id": entry_id,
        "case_version_id": version_id,
        "environment_revision_id": environment_id,
        "resource_id": resource_id,
        "install_policy": "none",
    }


def _excluded(version_id: str, environment_id: str, resource_id: str) -> dict[str, object]:
    body = _selection(
        version_id,
        environment_id,
        resource_id,
        [_choice("left", version_id, environment_id, resource_id), _choice("right", version_id, environment_id, resource_id)],
    )
    body["exclusions"] = [
        {"entry_id": "left", "reason": "사용자가 확인한 제외", "confirmed": True},
        {"entry_id": "right", "reason": "사용자가 확인한 제외", "confirmed": True},
    ]
    return body


def _duplicate(version_id: str, environment_id: str, resource_id: str) -> dict[str, object]:
    return _selection(
        version_id,
        environment_id,
        resource_id,
        [_choice("same", version_id, environment_id, resource_id), _choice("same", version_id, environment_id, resource_id)],
    )


def _partial_selection(version_id: str, environment_id: str, resource_id: str) -> dict[str, object]:
    unavailable = _choice("unavailable", version_id, environment_id, resource_id)
    unavailable["dataset_version_id"] = str(uuid4())
    return _selection(
        version_id,
        environment_id,
        resource_id,
        [_choice("keep", version_id, environment_id, resource_id), unavailable],
    )


def _suite_body(version_id: str) -> dict[str, object]:
    return {
        "name": "묶음 펼침",
        "purpose": "regression",
        "source": "suite",
        "failure_policy": "continue",
        "self_healing_enabled": False,
        "exclusions": [],
        "selection": {"suite_version_id": version_id},
    }


def _seed_suite(database: Path, project_id: str, case_id: str, version_id: str, environment_id: str, resource_id: str) -> tuple[str, str]:
    suite_id, suite_version_id, empty_version_id = str(uuid4()), str(uuid4()), str(uuid4())
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "INSERT INTO suites (project_id, suite_id, name) VALUES (?, ?, '펼침 묶음')",
            (project_id, suite_id),
        )
        connection.execute(
            """
            INSERT INTO suite_versions (project_id, suite_id, suite_version_id, content_hash)
            VALUES (?, ?, ?, 'suite-hash'), (?, ?, ?, 'empty-hash')
            """,
            (project_id, suite_id, suite_version_id, project_id, suite_id, empty_version_id),
        )
        for position, entry_id, data_name in ((1, "suite-a", "data-a"), (2, "suite-b", "data-b")):
            connection.execute(
                """
                INSERT INTO suite_entries (
                    project_id, suite_version_id, entry_id, position, case_id, case_version_id,
                    approval_id, data_name, environment_revision_id, resource_id, target_kind
                ) VALUES (?, ?, ?, ?, ?, ?, '', ?, ?, ?, 'web')
                """,
                (project_id, suite_version_id, entry_id, position, case_id, version_id, data_name, environment_id, resource_id),
            )
    return suite_version_id, empty_version_id


def test_w21_05(tmp_path: Path) -> None:
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
        project = create_project(owner, ProjectCreate("순차", "w2105", "실행", "web"))
    project_id = project.project_id
    database = root / "db" / "aiqa.sqlite"
    continuing = item_result(FailureLatch().value, True, None)
    key_id = _device(database, str(project_id))
    seeded = _schedule_graph(database, str(project_id), str(owner.actor_id), key_id)
    continued = _advance(store, project_id, seeded["continue"], seeded["continue_items"][0], continuing, "unchanged", False)
    failed = _advance(store, project_id, seeded["continue"], seeded["continue_items"][1], "FAIL", "unchanged", False)
    again = _advance(store, project_id, seeded["continue"], seeded["continue_items"][1], "FAIL", "unchanged", False)
    _advance(store, project_id, seeded["blocked"], seeded["blocked_items"][0], continuing, "unchanged", False)
    blocked = _advance(store, project_id, seeded["blocked"], seeded["blocked_items"][1], "BLOCKED", "unchanged", False)
    _advance(store, project_id, seeded["stop"], seeded["stop_items"][0], continuing, "unchanged", False)
    stopped = _advance(store, project_id, seeded["stop"], seeded["stop_items"][1], "FAIL", "unchanged", False)
    cancelled = _advance(store, project_id, seeded["cancel"], seeded["cancel_items"][0], "CANCELLED", "unchanged", True)
    _advance(store, project_id, seeded["quarantine"], seeded["quarantine_items"][0], "FAIL", "quarantine", False)
    store.close()
    next_claim = _claim(database, project_id)
    _release_slot(database)
    _park(database, str(project_id), seeded["quarantine"])
    quarantined = _claim(database, project_id)
    _restore(database, seeded["slots_jobs"])
    first, second = _claim_pair(database, project_id)
    observed = {
        "parallel_items_max": 1 if first is not None and second is None else 0,
        "stop_remaining": _result(database, str(project_id), seeded["stop_items"][2]),
        "cancel_remaining": _result(database, str(project_id), seeded["cancel_items"][2]),
        "parent_early_terminal": failed.parent_terminal and failed.open_items > 0,
    }
    assert str(continued.next_case_run_id) == seeded["continue_items"][1]
    assert str(failed.next_case_run_id) == seeded["continue_items"][2]
    assert again.open_items == failed.open_items
    assert _count(database, str(project_id), seeded["continue_items"][1]) == 1
    assert blocked.parent_terminal is False and _result(database, str(project_id), seeded["blocked_items"][2]) is None
    assert stopped.remaining[0][1] == "NOT_RUN" and stopped.remaining[0][2] != cancelled.remaining[0][2]
    assert stopped.parent_terminal is True and stopped.completion_rate == 1 and stopped.unverified == 1
    assert next_claim == str(seeded["continue_jobs"][2])
    assert quarantined is None and _result(database, str(project_id), seeded["quarantine_items"][1]) is None
    assert observed == {
        "parallel_items_max": 1,
        "stop_remaining": "NOT_RUN",
        "cancel_remaining": "CANCELLED",
        "parent_early_terminal": False,
    }


def _advance(store: object, project_id: object, execution_id: str, case_run_id: str, result: str, cleanup: str, cancelled: bool):
    from uuid import UUID

    from aiqa.domain.execution_scheduler import CaseRunView, advance_execution
    from aiqa.store.models import Transaction

    with store.transaction() as connection:  # type: ignore[attr-defined]
        return advance_execution(
            Transaction(connection),
            project_id,  # type: ignore[arg-type]
            UUID(execution_id),
            CaseRunView(UUID(case_run_id), result, cleanup, cancelled),
        )


def _device(database: Path, project_id: str) -> str:
    worker_id, enrollment_id, key_id = "worker-w2105", str(uuid4()), str(uuid4())
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "INSERT INTO worker_enrollments (enrollment_id, worker_id, project_id, created_at) VALUES (?, ?, ?, '2026-11-01T00:00:00+00:00')",
            (enrollment_id, worker_id, project_id),
        )
        connection.execute(
            "INSERT INTO physical_resource_keys (physical_key_id, worker_id, native_id) VALUES (?, ?, 'native-w2105')",
            (key_id, worker_id),
        )
        connection.execute(
            "INSERT INTO resource_aliases (project_id, physical_key_id, display_name, target_kind) VALUES (?, ?, '순차 기기', 'web')",
            (project_id, key_id),
        )
    return key_id


def _schedule_graph(database: Path, project_id: str, actor_id: str, key_id: str) -> dict[str, object]:
    import json

    names = ("continue", "blocked", "stop", "cancel", "quarantine", "slots")
    policies = {
        "continue": "continue",
        "blocked": "continue",
        "stop": "stop_on_non_pass",
        "cancel": "continue",
        "quarantine": "continue",
        "slots": "continue",
    }
    counts = {"slots": 2}
    seeded: dict[str, object] = {}
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        for name in names:
            execution_id = str(uuid4())
            connection.execute(
                """
                INSERT INTO executions (project_id, execution_id, name, purpose, source, suite_version_id, scope_requested_at)
                VALUES (?, ?, ?, 'regression', 'selection', NULL, '2026-11-01T00:00:00+00:00')
                """,
                (project_id, execution_id, name),
            )
            items: list[str] = []
            jobs: list[str] = []
            for index in range(counts.get(name, 3)):
                case_id, version_id, run_id, job_id = str(uuid4()), str(uuid4()), str(uuid4()), str(uuid4())
                stamp = "2026-11-01T00:00:00+00:00"
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
                    (project_id, case_id, version_id, f"digest-{name}-{index}", actor_id, stamp),
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
                    ) VALUES (?, ?, 'regression', NULL, ?, 'payload', ?, ?, 'queued')
                    """,
                    (
                        project_id,
                        job_id,
                        run_id,
                        json.dumps([key_id]),
                        json.dumps({"failure_policy": policies[name]}, separators=(",", ":")),
                    ),
                )
                items.append(run_id)
                jobs.append(job_id)
            seeded[name] = execution_id
            seeded[f"{name}_items"] = items
            seeded[f"{name}_jobs"] = jobs
    return seeded


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
    return 0 if row is None else int(row[0])


def _park(database: Path, project_id: str, execution_id: str) -> None:
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            UPDATE jobs SET status = 'error'
            WHERE project_id = ? AND status = 'queued'
              AND case_run_id NOT IN (
                SELECT case_run_id FROM case_runs WHERE project_id = ? AND execution_id = ?
              )
            """,
            (project_id, project_id, execution_id),
        )


def _restore(database: Path, job_ids: object) -> None:
    with sqlite3.connect(database) as connection:
        for job_id in job_ids:  # type: ignore[union-attr]
            connection.execute("UPDATE jobs SET status = 'queued' WHERE job_id = ? AND status = 'error'", (job_id,))


def _claim(database: Path, project_id: object) -> str | None:
    from datetime import datetime, timezone

    from aiqa.store.models import WorkerScope
    from aiqa.store.queue import claim_queued_job

    connection = sqlite3.connect(database)
    try:
        claimed = claim_queued_job(
            connection,
            WorkerScope("worker-w2105", (project_id,), ("regression",)),  # type: ignore[arg-type]
            datetime.now(timezone.utc),
        )
        connection.commit()
    finally:
        connection.close()
    return None if claimed is None else str(claimed.job_id)


def _claim_pair(database: Path, project_id: object) -> tuple[str | None, str | None]:
    from datetime import datetime, timezone

    from aiqa.store.models import WorkerScope
    from aiqa.store.queue import claim_queued_job

    connection = sqlite3.connect(database)
    try:
        worker = WorkerScope("worker-w2105", (project_id,), ("regression",))  # type: ignore[arg-type]
        now = datetime.now(timezone.utc)
        first = claim_queued_job(connection, worker, now)
        second = claim_queued_job(connection, worker, now)
        connection.commit()
    finally:
        connection.close()
    return None if first is None else str(first.job_id), None if second is None else str(second.job_id)


def _release_slot(database: Path) -> None:
    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM leases")
        connection.execute("UPDATE jobs SET status = 'completed' WHERE status = 'preparing'")


def _entry(entry_id: str, case_id: str, version_id: str, approval_id: str, data_name: str, environment: str, reset_policy: str, failure_policy: str, resource_id: str, target_kind: str) -> dict[str, object]:
    return {
        "entry_id": entry_id,
        "case_id": case_id,
        "case_version_id": version_id,
        "approval_id": approval_id,
        "data_name": data_name,
        "environment_revision_id": environment,
        "reset_policy": reset_policy,
        "failure_policy": failure_policy,
        "resource_id": resource_id,
        "target_kind": target_kind,
    }
