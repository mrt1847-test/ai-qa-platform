"""Formal preview pins an exact approval and does not reserve a resource."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from uuid import uuid4


def test_w20_01(tmp_path: Path) -> None:
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
        project = create_project(owner, ProjectCreate("정식", "w2001", "미리보기", "web"))
    store.close()
    project_id = str(project.project_id)
    version_id, case_id = asyncio.run(_case(app, project_id))
    environment_id, resource_id, busy_id = str(uuid4()), str(uuid4()), str(uuid4())
    seeded = _seed(root / "db" / "aiqa.sqlite", project_id, case_id, version_id, environment_id, resource_id, busy_id)
    before = _leases(root / "db" / "aiqa.sqlite")
    unapproved = asyncio.run(_preview(app, project_id, _body(seeded["bare"], environment_id, resource_id, "regression")))
    old = asyncio.run(
        _preview(app, project_id, _body(seeded["old"], environment_id, resource_id, "regression", seeded["old_approval"]))
    )
    revoked = asyncio.run(
        _preview(app, project_id, _body(seeded["revoked_version"], environment_id, resource_id, "regression", seeded["revoked"]))
    )
    partial = asyncio.run(_preview(app, project_id, _partial(seeded["old"], environment_id, resource_id, seeded["old_approval"])))
    mismatched = asyncio.run(
        _preview(app, project_id, _body(seeded["mismatched"], environment_id, resource_id, "regression", seeded["mismatch_approval"]))
    )
    role = asyncio.run(_preview(app, project_id, _body(seeded["role"], environment_id, resource_id, "regression", seeded["role_approval"])))
    busy = asyncio.run(
        _preview(app, project_id, _body(seeded["old"], environment_id, busy_id, "reverification", seeded["old_approval"]))
    )
    page = asyncio.run(_page(app, project_id, case_id))
    after = _leases(root / "db" / "aiqa.sqlite")
    kept = {item["entry_id"] for item in partial["resolved_items"]}
    explicit = {item["entry_id"] for item in partial["exclusions"]}
    silent = sum(1 for entry in ("keep", "drop") if entry not in kept and entry not in explicit)
    observed = {
        "unapproved_formal": unapproved["ready"],
        "valid_old_approval_allowed": old["ready"] is True and old["resolved_items"][0]["approval_id"] == seeded["old_approval"],
        "silent_exclusions": silent,
        "preview_reserves_resource": after > before or old["reserved"] is True,
    }
    assert revoked["ready"] is False
    assert any(item["code"] == "APPROVAL_REVOKED" for item in revoked["blockers"])
    assert any(item["code"] == "HASH_MISSING" for item in mismatched["blockers"])
    assert any(item["code"] == "ROLE_MISSING" for item in role["blockers"])
    assert any(item["code"] == "MODEL_BINDING_UNAVAILABLE" for item in role["blockers"])
    assert any(item["code"] == "RESOURCE_BUSY" for item in busy["blockers"])
    assert "keep" in kept and "drop" in kept
    assert "정확한 승인" in page and "과거 승인" in page and "사용 중" in page and "PASS" not in page
    assert observed == {
        "unapproved_formal": False,
        "valid_old_approval_allowed": True,
        "silent_exclusions": 0,
        "preview_reserves_resource": False,
    }


def _leases(database: Path) -> int:
    with sqlite3.connect(database) as connection:
        row = connection.execute("SELECT COUNT(*) FROM leases").fetchone()
    return 0 if row is None else int(row[0])


def _body(version_id: str, environment_id: str, resource_id: str, purpose: str, approval_id: str | None = None) -> dict[str, object]:
    item: dict[str, object] = {
        "entry_id": "item-1",
        "case_version_id": version_id,
        "environment_revision_id": environment_id,
        "resource_id": resource_id,
        "install_policy": "none",
    }
    if approval_id is not None:
        item["approval_id"] = approval_id
    return {
        "name": "정식",
        "purpose": purpose,
        "source": "single",
        "failure_policy": "stop_on_non_pass",
        "self_healing_enabled": False,
        "exclusions": [],
        "selection": {"items": [item]},
    }


def _partial(version_id: str, environment_id: str, resource_id: str, approval_id: str) -> dict[str, object]:
    return {
        "name": "정식",
        "purpose": "regression",
        "source": "selection",
        "failure_policy": "continue",
        "self_healing_enabled": False,
        "exclusions": [],
        "selection": {
            "items": [
                {
                    "entry_id": "keep",
                    "case_version_id": version_id,
                    "approval_id": approval_id,
                    "environment_revision_id": environment_id,
                    "resource_id": resource_id,
                    "install_policy": "none",
                },
                {
                    "entry_id": "drop",
                    "case_version_id": version_id,
                    "approval_id": approval_id,
                    "environment_revision_id": str(uuid4()),
                    "resource_id": resource_id,
                    "dataset_version_id": str(uuid4()),
                    "install_policy": "none",
                },
            ]
        },
    }


async def _case(app: object, project_id: str) -> tuple[str, str]:
    import httpx

    origin = "http://127.0.0.1"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        headers = await _session(client, origin, project_id, "w2001-case")
        created = await client.post(
            f"/api/v1/projects/{project_id}/cases",
            json={"name": "정식", "tc_reference": None},
            headers=headers,
        )
        headers["Idempotency-Key"] = "w2001-version"
        version = await client.post(
            f"/api/v1/projects/{project_id}/cases/{created.json()['case_id']}/versions",
            json={"definition": {"final_expected": [{"id": "exp-1", "kind": "text", "expected": "보임"}]}, "settings": {"target_kind": "web"}},
            headers=headers,
        )
    assert version.status_code == 201, version.text
    return version.json()["id"], created.json()["case_id"]


async def _preview(app: object, project_id: str, body: dict[str, object]) -> dict[str, object]:
    import httpx

    origin = "http://127.0.0.1"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        headers = await _session(client, origin, project_id, "w2001-preview-" + str(uuid4()))
        response = await client.post(f"/api/v1/projects/{project_id}/execution-previews", json=body, headers=headers)
    assert response.status_code == 200, response.text
    parsed = response.json()
    assert type(parsed) is dict
    return parsed


async def _page(app: object, project_id: str, case_id: str) -> str:
    import httpx

    origin = "http://127.0.0.1"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        await _session(client, origin, project_id, "w2001-page")
        response = await client.get(f"/ui/projects/{project_id}/cases/{case_id}/execution-setup")
    assert response.status_code == 200
    return response.text


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


def _seed(
    database: Path, project_id: str, case_id: str, version_id: str, environment_id: str, resource_id: str, busy_id: str
) -> dict[str, str]:
    old_version, revoked_version, mismatch_version, role_version = str(uuid4()), str(uuid4()), str(uuid4()), str(uuid4())
    old_approval, current_approval, revoked_approval, mismatch_approval, role_approval = (
        str(uuid4()),
        str(uuid4()),
        str(uuid4()),
        str(uuid4()),
        str(uuid4()),
    )
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO worker_enrollments (enrollment_id, worker_id, project_id, created_at)
            VALUES ('enroll-w2001', 'worker-w2001', ?, '2026-11-01T00:00:00+00:00')
            """,
            (project_id,),
        )
        for key, native in ((resource_id, "native-ready"), (busy_id, "native-busy")):
            connection.execute(
                "INSERT INTO physical_resource_keys (physical_key_id, worker_id, native_id) VALUES (?, 'worker-w2001', ?)",
                (key, native),
            )
            connection.execute(
                """
                INSERT INTO resource_aliases (project_id, physical_key_id, display_name, target_kind)
                VALUES (?, ?, '브라우저', 'web')
                """,
                (project_id, key),
            )
        connection.execute(
            """
            INSERT INTO resource_inventory (physical_key_id, state, os_build, geometry, permissions, ime, observed_at)
            VALUES (?, 'busy', 'none', 'none', 'none', 'none', '2026-11-01T00:00:00+00:00')
            """,
            (busy_id,),
        )
        connection.execute(
            """
            INSERT INTO environments (project_id, environment_id, name, next_revision, latest_revision_id)
            VALUES (?, 'env-w2001', '로컬', 2, ?)
            """,
            (project_id, environment_id),
        )
        connection.execute(
            """
            INSERT INTO environment_revisions (
                project_id, environment_id, revision_id, revision, body_json, content_hash, actor_id, created_at
            ) VALUES (?, 'env-w2001', ?, 1, '{}', 'env-hash', 'actor', '2026-11-01T00:00:00+00:00')
            """,
            (project_id, environment_id),
        )
        names = [item[1] for item in connection.execute("PRAGMA table_info(case_versions)")]
        source = connection.execute("SELECT * FROM case_versions WHERE version_id = ?", (version_id,)).fetchone()
        assert source is not None
        values = dict(zip(names, source, strict=True))
        content_hash = str(values["content_hash"])
        manifest_id, recording_id = str(uuid4()), str(uuid4())
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
        role_settings = json.loads(str(values["settings_json"]))
        role_settings["verifier_bindings"] = [{"method": "ai_visual", "binding_id": "", "role": ""}]
        role_settings["build_id"] = "missing-build"
        for version, revision, settings in (
            (old_version, 2, None),
            (revoked_version, 3, None),
            (mismatch_version, 4, None),
            (role_version, 5, json.dumps(role_settings)),
        ):
            package_id = str(uuid4())
            _version(connection, names, values, version, revision, manifest_id, package_id, content_hash, settings)
            _package(connection, project_id, case_id, version, package_id, manifest_id)
        _approval(connection, project_id, case_id, old_version, old_approval, content_hash, "approved", None)
        _approval(connection, project_id, case_id, old_version, current_approval, content_hash, "approved", None)
        _approval(connection, project_id, case_id, revoked_version, revoked_approval, content_hash, "approved", None)
        _approval(connection, project_id, case_id, revoked_version, str(uuid4()), content_hash, "revoked", revoked_approval)
        _approval(connection, project_id, case_id, mismatch_version, mismatch_approval, "other-hash", "approved", None)
        _approval(connection, project_id, case_id, role_version, role_approval, content_hash, "approved", None)
        connection.execute(
            "UPDATE automation_cases SET current_approval_id = ? WHERE project_id = ? AND case_id = ?",
            (current_approval, project_id, case_id),
        )
    return {
        "bare": version_id,
        "old": old_version,
        "old_approval": old_approval,
        "revoked_version": revoked_version,
        "revoked": revoked_approval,
        "mismatched": mismatch_version,
        "mismatch_approval": mismatch_approval,
        "role": role_version,
        "role_approval": role_approval,
    }


def _version(
    connection: sqlite3.Connection,
    names: list[str],
    values: dict[str, object],
    version_id: str,
    revision: int,
    manifest_id: str,
    package_id: str,
    content_hash: str,
    settings_json: str | None,
) -> None:
    copied = dict(values)
    copied["version_id"] = version_id
    copied["revision"] = revision
    copied["source_manifest_id"] = manifest_id
    copied["replay_package_id"] = package_id
    copied["content_hash"] = content_hash
    copied["is_branch"] = 1
    if settings_json is not None:
        copied["settings_json"] = settings_json
    connection.execute(
        f"INSERT INTO case_versions ({', '.join(names)}) VALUES ({', '.join('?' for _ in names)})",
        tuple(copied[name] for name in names),
    )


def _package(connection: sqlite3.Connection, project_id: str, case_id: str, version_id: str, package_id: str, manifest_id: str) -> None:
    connection.execute(
        """
        INSERT INTO replay_packages (
            project_id, package_id, case_id, case_version_id, ready, schema_version,
            source_manifest_id, source_manifest_hash, raw_source_hash, approved_code_hash,
            runtime_ref, compiler_ref, lock_hash, step_mapping_hash, body_hash
        ) VALUES (?, ?, ?, ?, 1, 'replay-package-v1', ?, 'manifest-hash', 'raw', 'code',
            'web', 'web-ipc-subset', 'lock', 'map', ?)
        """,
        (project_id, package_id, case_id, version_id, manifest_id, package_id),
    )
    connection.execute(
        "INSERT INTO package_version_links (project_id, case_id, version_id, package_id) VALUES (?, ?, ?, ?)",
        (project_id, case_id, version_id, package_id),
    )


def _approval(
    connection: sqlite3.Connection,
    project_id: str,
    case_id: str,
    version_id: str,
    approval_id: str,
    version_hash: str,
    kind: str,
    prior: str | None,
) -> None:
    review_id = str(uuid4())
    connection.execute(
        """
        INSERT INTO reviews (
            project_id, review_id, case_id, case_version_id, version_hash,
            evidence_set_hash, created_commit_seq
        ) VALUES (?, ?, ?, ?, ?, 'evidence', 1)
        """,
        (project_id, review_id, case_id, version_id, version_hash),
    )
    connection.execute(
        """
        INSERT INTO approval_events (
            project_id, approval_id, case_id, case_version_id, review_id, event_kind,
            prior_approval_id, version_hash, evidence_set_hash, reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'evidence', '기록')
        """,
        (project_id, approval_id, case_id, version_id, review_id, kind, prior, version_hash),
    )


def test_w20_03(tmp_path: Path) -> None:
    import asyncio
    import sqlite3

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
        project = create_project(owner, ProjectCreate("마법사", "w2003", "수행", "web"))
    store.close()
    project_id = str(project.project_id)
    page, script, empty, over, mixed = asyncio.run(_wizard(app, project_id))
    with sqlite3.connect(root / "db" / "aiqa.sqlite") as connection:
        runs = connection.execute("SELECT COUNT(*) FROM executions").fetchone()
    created = 0 if runs is None else int(runs[0])
    observed = {
        "wizard_steps": page.count('data-step="'),
        "empty_execution_allowed": empty != 422 or created != 0,
        "over_100_allowed": over != 422 or created != 0,
        "mixed_trial_formal_allowed": mixed != 422 or created != 0,
    }
    assert "healing은 꺼져 있습니다." in page
    assert "정확한 승인" in page and "과거 승인" in page and "사용 중" in page
    assert "시범" in page and "정식과 섞지 않습니다." in page
    assert "PASS" not in page and "PASS" not in script
    assert observed == {
        "wizard_steps": 4,
        "empty_execution_allowed": False,
        "over_100_allowed": False,
        "mixed_trial_formal_allowed": False,
    }


async def _wizard(app: object, project_id: str) -> tuple[str, str, int, int, int]:
    import httpx

    origin = "http://127.0.0.1"
    case_id = str(uuid4())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        headers = await _session(client, origin, project_id, "w2003-wizard")
        page = await client.get(f"/ui/projects/{project_id}/cases/{case_id}/execution-setup")
        script = await client.get("/static/execution_setup.js")
        empty = await _start(client, project_id, headers, "w2003-empty", [])
        over = await _start(
            client,
            project_id,
            headers,
            "w2003-over",
            [{"entry_id": f"item-{index}"} for index in range(101)],
        )
        mixed_body = _start_body([{"entry_id": "item-1", "purpose": "regression"}])
        mixed_body["purposes"] = ["trial", "regression"]
        headers["Idempotency-Key"] = "w2003-mixed"
        mixed = await client.post(f"/api/v1/projects/{project_id}/executions", json=mixed_body, headers=headers)
    assert page.status_code == 200, page.text
    assert script.status_code == 200, script.text
    return page.text, script.text, empty, over, mixed.status_code


def _start_body(items: list[object]) -> dict[str, object]:
    return {
        "name": "마법사",
        "purpose": "trial",
        "source": "single",
        "failure_policy": "stop_on_non_pass",
        "self_healing_enabled": False,
        "preview_hash": "stale",
        "exclusions": [],
        "items": items,
    }


def test_w20_04(tmp_path: Path) -> None:
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
        project = create_project(owner, ProjectCreate("수행 목록", "w2004", "진행", "web"))
    store.close()
    project_id = str(project.project_id)
    database = root / "db" / "aiqa.sqlite"
    empty = asyncio.run(_list_page(app, project_id))
    case_id = asyncio.run(_listed_case(app, project_id))
    seeded = _listed_graph(database, project_id, case_id, str(owner.actor_id))
    before = _job_count(database)
    listed, running_page, done_page, waiting_page, filtered, detail, item, restored, stale = asyncio.run(
        _listed_flow(app, project_id, seeded)
    )
    after = _job_count(database)
    observed = {
        "completed_count_equals_pass_count": detail["finished_count"] == detail["pass_count"],
        "phase_is_job_status": detail["phase"] == detail["job_status"],
        "reload_duplicate_jobs": after - before,
        "selected_item_restored": seeded["running_run_id"] in restored and 'data-selected="true"' in restored,
    }
    assert "수행이 없습니다." in empty
    assert "수행이 없습니다." in waiting_page
    assert "진행 수행" in running_page and "완료 수행" not in running_page
    assert "완료 수행" in done_page and "진행 수행" not in done_page
    assert filtered["items"][0]["execution_id"] == seeded["mixed_execution_id"]
    assert listed["page"] == 2 and listed["items"] == []
    assert item["phase"] != item["job_status"]
    assert "다시 연결되었습니다" in restored
    assert "연결이 오래되었습니다" in stale
    assert "현재 화면 로그인 화면" in restored
    assert "이벤트 1" in restored
    assert "경과 기록됨" in restored
    assert "자원 준비 웹" in restored
    assert "종료 1" in restored and "성공 0" in restored
    assert "PASS" not in running_page
    assert "PASS" not in restored
    assert observed == {
        "completed_count_equals_pass_count": False,
        "phase_is_job_status": False,
        "reload_duplicate_jobs": 0,
        "selected_item_restored": True,
    }


def _job_count(database: Path) -> int:
    with sqlite3.connect(database) as connection:
        row = connection.execute("SELECT COUNT(*) FROM jobs").fetchone()
    return 0 if row is None else int(row[0])


async def _list_page(app: object, project_id: str) -> str:
    import httpx

    origin = "http://127.0.0.1"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        await _session(client, origin, project_id, "w2004-empty")
        page = await client.get(f"/ui/projects/{project_id}/executions")
    assert page.status_code == 200, page.text
    return page.text


async def _listed_case(app: object, project_id: str) -> str:
    import httpx

    origin = "http://127.0.0.1"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        headers = await _session(client, origin, project_id, "w2004-case")
        created = await client.post(
            f"/api/v1/projects/{project_id}/cases",
            json={"name": "수행 목록", "tc_reference": None},
            headers=headers,
        )
    assert created.status_code == 201, created.text
    return str(created.json()["case_id"])


async def _listed_flow(app: object, project_id: str, seeded: dict[str, str]):
    import httpx

    origin = "http://127.0.0.1"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        headers = await _session(client, origin, project_id, "w2004-read")
        running_page = await client.get(f"/ui/projects/{project_id}/executions?status=running")
        done_page = await client.get(f"/ui/projects/{project_id}/executions?status=done")
        waiting_page = await client.get(f"/ui/projects/{project_id}/executions?status=waiting")
        filtered = await client.get(
            f"/api/v1/projects/{project_id}/executions",
            params={"status": "running", "purpose": "trial", "requester": "요청자-진행", "env": "env-web", "result": "failure"},
            headers=headers,
        )
        later = await client.get(
            f"/api/v1/projects/{project_id}/executions",
            params={"page": "2"},
            headers=headers,
        )
        detail = await client.get(
            f"/api/v1/executions/{seeded['mixed_execution_id']}",
            params={"project_id": project_id},
            headers=headers,
        )
        item = await client.get(
            f"/api/v1/case-runs/{seeded['running_run_id']}",
            params={"project_id": project_id},
            headers=headers,
        )
        down = await client.get(
            f"/ui/projects/{project_id}/executions/{seeded['mixed_execution_id']}?link=down&item={seeded['running_run_id']}"
        )
        restored = await client.get(
            f"/ui/projects/{project_id}/executions/{seeded['mixed_execution_id']}?link=restored&item={seeded['running_run_id']}"
        )
        stale = await client.get(
            f"/ui/projects/{project_id}/executions/{seeded['mixed_execution_id']}?link=stale&item={seeded['running_run_id']}"
        )
    assert running_page.status_code == 200, running_page.text
    assert filtered.status_code == 200, filtered.text
    assert later.status_code == 200, later.text
    assert detail.status_code == 200, detail.text
    assert item.status_code == 200, item.text
    assert down.status_code == 200, down.text
    assert restored.status_code == 200, restored.text
    assert stale.status_code == 200, stale.text
    assert "연결이 끊겼습니다" in down.text
    return (
        later.json(),
        running_page.text,
        done_page.text,
        waiting_page.text,
        filtered.json(),
        detail.json(),
        item.json(),
        restored.text,
        stale.text,
    )


def _listed_graph(database: Path, project_id: str, case_id: str, actor_id: str) -> dict[str, str]:
    version_id = str(uuid4())
    mixed_execution, done_execution = str(uuid4()), str(uuid4())
    running_run, failed_run, done_run = str(uuid4()), str(uuid4()), str(uuid4())
    running_job, failed_job, done_job = str(uuid4()), str(uuid4()), str(uuid4())
    running_attempt = str(uuid4())
    settings = json.dumps({"target_kind": "web", "limits": {"timeout_seconds": 30}}, sort_keys=True)
    early, later = "2026-11-01T00:00:00+00:00", "2026-11-01T01:00:00+00:00"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO case_versions (
                project_id, case_id, version_id, revision, creation_kind, parent_version_id, base_version_id,
                is_branch, definition_json, settings_json, recorded_steps_json, content_hash, verification_digest,
                source_manifest_id, replay_package_id, readiness_json, actor_id, reason, created_at
            ) VALUES (?, ?, ?, 1, 'recorded', NULL, NULL, 0, '{}', ?, '[]', 'script-hash', 'digest',
                NULL, NULL, '{}', ?, 'recorded', ?)
            """,
            (project_id, case_id, version_id, settings, actor_id, early),
        )
        connection.execute(
            "INSERT INTO worker_enrollments (enrollment_id, worker_id, project_id, created_at) VALUES ('enroll-w2004', 'worker-w2004', ?, ?)",
            (project_id, early),
        )
        connection.execute(
            "INSERT INTO physical_resource_keys (physical_key_id, worker_id, native_id) VALUES ('key-w2004', 'worker-w2004', 'native-w2004')"
        )
        connection.execute(
            "INSERT INTO resource_aliases (project_id, physical_key_id, display_name, target_kind) VALUES (?, 'key-w2004', '준비 웹', 'web')",
            (project_id,),
        )
        _listed_execution(
            connection, project_id, case_id, version_id, mixed_execution, "진행 수행", "trial", "single", early,
            [
                (running_run, running_job, "running", '{"environment_revision_id":"env-web","build_id":"build-1"}', running_attempt),
                (failed_run, failed_job, "completed", '{"environment_revision_id":"env-web","build_id":"build-1"}', None),
            ],
        )
        _listed_execution(
            connection, project_id, case_id, version_id, done_execution, "완료 수행", "regression", "selection", later,
            [(done_run, done_job, "completed", '{"environment_revision_id":"env-other","build_id":"build-2"}', None)],
        )
        connection.execute(
            """
            INSERT INTO attempt_events (
                project_id, event_id, attempt_id, local_seq, captured_at, event_type,
                minimum_facts, payload_hash, body_hash, detail_payload, sealed
            ) VALUES (?, ?, ?, 1, ?, '로그인 화면', '{}', 'payload', 'body', NULL, 0)
            """,
            (project_id, str(uuid4()), running_attempt, early),
        )
        connection.execute(
            """
            INSERT INTO job_finish_facts (
                project_id, job_id, verdict, finish_reason, cleanup_failed, resource_state, created_at
            ) VALUES (?, ?, 'FAIL', 'crash', 0, 'unchanged', ?)
            """,
            (project_id, failed_job, early),
        )
        connection.execute(
            """
            INSERT INTO job_receipts (
                project_id, actor_id, operation, request_key, body_hash, job_id, purpose,
                recording_id, execution_id, case_run_id, status, created_at
            ) VALUES (?, '요청자-진행', 'enqueue_execution', 'w2004-mixed', 'hash', ?, 'trial', NULL, ?, ?, 'queued', ?)
            """,
            (project_id, running_job, mixed_execution, running_run, early),
        )
        connection.execute(
            """
            INSERT INTO job_receipts (
                project_id, actor_id, operation, request_key, body_hash, job_id, purpose,
                recording_id, execution_id, case_run_id, status, created_at
            ) VALUES (?, '요청자-완료', 'enqueue_execution', 'w2004-done', 'hash', ?, 'regression', NULL, ?, ?, 'queued', ?)
            """,
            (project_id, done_job, done_execution, done_run, later),
        )
    return {
        "mixed_execution_id": mixed_execution,
        "running_run_id": running_run,
    }


def _listed_execution(
    connection: sqlite3.Connection,
    project_id: str,
    case_id: str,
    version_id: str,
    execution_id: str,
    name: str,
    purpose: str,
    source: str,
    stamp: str,
    items: list[tuple[str, str, str, str, str | None]],
) -> None:
    connection.execute(
        """
        INSERT INTO executions (project_id, execution_id, name, purpose, source, suite_version_id, scope_requested_at)
        VALUES (?, ?, ?, ?, ?, NULL, ?)
        """,
        (project_id, execution_id, name, purpose, source, stamp),
    )
    for run_id, job_id, status, limits, attempt_id in items:
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
            ) VALUES (?, ?, ?, NULL, ?, 'payload', '[]', ?, ?)
            """,
            (project_id, job_id, purpose, run_id, limits, status),
        )
        if attempt_id is not None:
            connection.execute(
                """
                INSERT INTO attempts (project_id, attempt_id, job_id, generation, physical_key_id)
                VALUES (?, ?, ?, 1, 'key-w2004')
                """,
                (project_id, attempt_id, job_id),
            )


async def _start(client: object, project_id: str, headers: dict[str, str], key: str, items: list[object]) -> int:
    headers["Idempotency-Key"] = key
    response = await client.post(  # type: ignore[attr-defined]
        f"/api/v1/projects/{project_id}/executions",
        json=_start_body(items),
        headers=headers,
    )
    return response.status_code
