"""Integration coverage for the recording wizard."""

from __future__ import annotations

from pathlib import Path


def test_w16_08(tmp_path: Path) -> None:
    import asyncio
    import sqlite3
    from uuid import uuid4

    from aiqa.api.app import create_app
    from aiqa.config import load_settings
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.store.database import migrate_store
    from aiqa.store.models import Actor, ProjectCreate

    root = tmp_path / "runtime"
    app = create_app(
        load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)})
    )
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("재녹화", "w1608", "녹화", "web"))
    store.close()
    project_id = str(project.project_id)
    database = root / "db" / "aiqa.sqlite"
    _resource(database, project_id)
    _binding(database, project_id, str(owner.actor_id))
    started, stopped, page, before_approval = asyncio.run(_rerecord(app, project_id, database))
    with sqlite3.connect(database) as connection:
        case_id, base_id, recording_id = started
        head, approval = connection.execute(
            "SELECT latest_draft_version_id, current_approval_id FROM automation_cases WHERE case_id = ?",
            (case_id,),
        ).fetchone()
        produced = connection.execute(
            """
            SELECT receipts.produced_version_id
            FROM recordings
            JOIN recording_manifests AS manifests
              ON manifests.project_id = recordings.project_id AND manifests.recording_id = recordings.recording_id
            JOIN materialization_receipts AS receipts
              ON receipts.project_id = manifests.project_id AND receipts.manifest_id = manifests.manifest_id
            WHERE recordings.recording_id = ?
            """,
            (recording_id,),
        ).fetchone()
        base = connection.execute(
            "SELECT case_id, base_case_version_id FROM recordings WHERE recording_id = ?",
            (recording_id,),
        ).fetchone()
        interrupted = connection.execute(
            "SELECT case_id, completion_status FROM recordings WHERE recording_id = ?",
            (stopped,),
        ).fetchone()
    observed = {
        "same_case": base is not None and str(base[0]) == case_id and str(interrupted[0]) == case_id,
        "base_preserved": base is not None and str(base[1]) == base_id,
        "current_approval_changed": approval != before_approval,
        "late_finish_overwrites_head": produced is not None and str(head) == str(produced[0]),
    }
    assert interrupted[1] == "interrupted"
    assert "중간 재개와 일부 합치기는 없습니다." in page.text
    assert "<button" not in page.text and "PASS" not in page.text
    assert observed == {
        "same_case": True,
        "base_preserved": True,
        "current_approval_changed": False,
        "late_finish_overwrites_head": False,
    }


def test_w16_06(tmp_path: Path) -> None:
    import asyncio
    import sqlite3
    from uuid import uuid4

    from aiqa.api.app import create_app
    from aiqa.config import load_settings
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.store.database import migrate_store
    from aiqa.store.models import Actor, ProjectCreate

    root = tmp_path / "runtime"
    app = create_app(
        load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)})
    )
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("이력", "w1606", "녹화", "web"))
    store.close()
    project_id = str(project.project_id)
    listed, manifests, page, detail = asyncio.run(_history(app, project_id, root / "db" / "aiqa.sqlite"))
    rows = {item["recording_id"]: item for item in listed.json()["items"]}
    stored = rows["11111111-1111-4111-8111-111111111111"]
    local = rows["22222222-2222-4222-8222-222222222222"]
    rejected = rows["44444444-4444-4444-8444-444444444444"]
    receipt = manifests.json()["items"][0]
    observed = {
        "stored_implies_completed": stored["storage_status"] == "stored" and stored["outcome"] == "completed",
        "rejected_hidden": "44444444-4444-4444-8444-444444444444" not in rows or rejected["review_status"] != "rejected",
        "receipt_versions_visible": receipt["kind"] == "recovery" and receipt["produced_version_id"] is not None,
        "local_as_server_saved": local["server_saved"],
    }
    assert listed.status_code == 200, listed.text
    assert rows["33333333-3333-4333-8333-333333333333"]["server_saved"] is False
    assert stored["outcome"] == "error"
    assert "재전송 대기는 저장 완료가 아닙니다." in page.text
    assert "선택 action tap-1" in page.text
    assert "녹화 이력" in detail.text
    assert "<button" not in page.text and "PASS" not in page.text
    assert observed == {
        "stored_implies_completed": False,
        "rejected_hidden": False,
        "receipt_versions_visible": True,
        "local_as_server_saved": False,
    }


def test_w16_05(tmp_path: Path) -> None:
    import asyncio
    import sqlite3
    from uuid import uuid4

    from aiqa.api.app import create_app
    from aiqa.config import load_settings
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.store.database import migrate_store
    from aiqa.store.models import Actor, ProjectCreate

    root = tmp_path / "runtime"
    app = create_app(
        load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)})
    )
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("완료", "w1605", "녹화", "web"))
    store.close()
    project_id = str(project.project_id)
    database = root / "db" / "aiqa.sqlite"
    _resource(database, project_id)
    _binding(database, project_id, str(owner.actor_id))
    finished, failed, page = asyncio.run(_seal(app, project_id, database))
    with sqlite3.connect(database) as connection:
        receipts = connection.execute(
            "SELECT COUNT(*) FROM materialization_receipts WHERE manifest_id = ?",
            (finished.json()["manifest_id"],),
        ).fetchone()[0]
        package = connection.execute(
            "SELECT replay_package_id FROM case_versions WHERE reason = 'compiler is missing' ORDER BY revision LIMIT 1"
        ).fetchone()
        approval = connection.execute("SELECT current_approval_id FROM automation_cases").fetchone()[0]
        error_status = connection.execute(
            "SELECT completion_status FROM recordings WHERE completion_status = 'error'"
        ).fetchone()
    observed = {
        "unapproved_saved": finished.status_code == 201 and approval is None and "승인되지 않음" in page.text,
        "failed_saved": error_status is not None and str(error_status[0]) == "error",
        "duplicate_materializations": receipts,
        "missing_compiler_package": None if package is not None and package[0] is None else "present",
    }
    assert failed.status_code == 201, failed.text
    assert "<button" not in page.text and "PASS" not in page.text
    assert observed == {
        "unapproved_saved": True,
        "failed_saved": True,
        "duplicate_materializations": 1,
        "missing_compiler_package": None,
    }


def _resource(database: Path, project_id: str) -> None:
    import sqlite3

    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO worker_enrollments (enrollment_id, worker_id, project_id, created_at)
            VALUES ('enroll-w1605', 'worker-w1605', ?, '2026-11-01T00:00:00+00:00')
            """,
            (project_id,),
        )
        connection.execute(
            """
            INSERT INTO physical_resource_keys (physical_key_id, worker_id, native_id)
            VALUES ('key-w1605', 'worker-w1605', 'native-w1605')
            """
        )
        connection.execute(
            """
            INSERT INTO resource_aliases (project_id, physical_key_id, display_name, target_kind)
            VALUES (?, 'key-w1605', '준비 웹', 'web')
            """,
            (project_id,),
        )
        connection.execute(
            """
            INSERT INTO resource_inventory (
                physical_key_id, state, os_build, geometry, permissions, ime, observed_at
            ) VALUES ('key-w1605', 'ready', 'build-1', '100x100', '[]', 'none', '2026-11-01T00:00:00+00:00')
            """
        )


def _binding(database: Path, project_id: str, actor_id: str) -> None:
    import sqlite3

    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO model_bindings (project_id, binding_id, name, next_revision, latest_revision_id)
            VALUES (?, 'bind-w1605', '작성', 2, 'rev-w1605')
            """,
            (project_id,),
        )
        connection.execute(
            """
            INSERT INTO binding_revisions (
                project_id, binding_id, revision_id, revision, role, provider, endpoint_kind,
                endpoint, model, key_ref_id, key_revision, prompt_hash, tariff_id,
                compatibility_status, content_hash, actor_id, created_at
            ) VALUES (?, 'bind-w1605', 'rev-w1605', 1, 'authoring', 'fixture', 'loopback',
                'http://127.0.0.1', 'author-model', 'ref-w1605', 1, 'prompt', 'tariff',
                'compatible', 'hash', ?, '2026-11-01T00:00:00+00:00')
            """,
            (project_id, actor_id),
        )


def test_w16_03(tmp_path: Path) -> None:
    import asyncio
    import sqlite3
    from uuid import uuid4

    from aiqa.api.app import create_app
    from aiqa.config import load_settings
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.store.database import migrate_store
    from aiqa.store.models import Actor, ProjectCreate

    root = tmp_path / "runtime"
    app = create_app(
        load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)})
    )
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("접수", "w1603", "녹화", "web"))
    store.close()
    project_id = str(project.project_id)
    database = root / "db" / "aiqa.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        for key, name in (("key-a", "준비 웹"), ("key-b", "다른 웹")):
            connection.execute(
                """
                INSERT INTO worker_enrollments (enrollment_id, worker_id, project_id, created_at)
                VALUES (?, ?, ?, '2026-11-01T00:00:00+00:00')
                """,
                (f"enroll-{key}", f"worker-{key}", project_id),
            )
            connection.execute(
                """
                INSERT INTO physical_resource_keys (physical_key_id, worker_id, native_id)
                VALUES (?, ?, ?)
                """,
                (key, f"worker-{key}", f"native-{key}"),
            )
            connection.execute(
                """
                INSERT INTO resource_aliases (project_id, physical_key_id, display_name, target_kind)
                VALUES (?, ?, ?, 'web')
                """,
                (project_id, key, name),
            )
            connection.execute(
                """
                INSERT INTO resource_inventory (
                    physical_key_id, state, os_build, geometry, permissions, ime, observed_at
                ) VALUES (?, 'ready', 'build-1', '100x100', '[]', 'none', '2026-11-01T00:00:00+00:00')
                """,
                (key,),
            )
    blocked, saved, replay, conflict, mismatch, page = asyncio.run(_start(app, project_id, database, str(owner.actor_id)))
    with sqlite3.connect(database) as connection:
        count = connection.execute("SELECT COUNT(*) FROM recordings").fetchone()[0]
        tc = connection.execute("SELECT tc_reference FROM automation_cases").fetchone()[0]
    observed = {
        "same_key_rec_count": count,
        "different_body_status": conflict.status_code,
        "hash_mismatch_status": mismatch.status_code,
        "tc_null_accepted": tc is None and saved.status_code == 201,
    }
    assert blocked.status_code == 422 and "authoring binding" in blocked.text
    assert replay.status_code == 200 and replay.json()["recording_id"] == saved.json()["recording_id"]
    assert "시작 검사는 예약을 만들지 않습니다." in page.text
    assert "<button" not in page.text and "PASS" not in page.text
    assert observed == {
        "same_key_rec_count": 1,
        "different_body_status": 409,
        "hash_mismatch_status": 409,
        "tc_null_accepted": True,
    }


def test_w16_01(tmp_path: Path) -> None:
    import asyncio
    import json
    import sqlite3
    from uuid import uuid4

    from aiqa.api.app import create_app
    from aiqa.config import load_settings
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.store.database import migrate_store
    from aiqa.store.models import Actor, ProjectCreate

    root = tmp_path / "runtime"
    app = create_app(
        load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)})
    )
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("녹화", "w1601", "초안", "web"))
    store.close()
    project_id = str(project.project_id)
    with sqlite3.connect(root / "db" / "aiqa.sqlite") as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO worker_enrollments (enrollment_id, worker_id, project_id, created_at)
            VALUES ('enroll-w1601', 'worker-w1601', ?, '2026-11-01T00:00:00+00:00')
            """,
            (project_id,),
        )
        connection.execute(
            """
            INSERT INTO physical_resource_keys (physical_key_id, worker_id, native_id)
            VALUES ('key-w1601', 'worker-w1601', 'native-w1601')
            """
        )
        connection.execute(
            """
            INSERT INTO resource_aliases (project_id, physical_key_id, display_name, target_kind)
            VALUES (?, 'key-w1601', '끊긴 웹', 'web')
            """,
            (project_id,),
        )
        connection.execute(
            """
            INSERT INTO resource_inventory (
                physical_key_id, state, os_build, geometry, permissions, ime, observed_at
            ) VALUES ('key-w1601', 'offline', 'build-1', '100x100', '[]', 'none', '2026-11-01T00:00:00+00:00')
            """
        )
    page, saved, switched, missing = asyncio.run(_wizard(app, project_id))
    with sqlite3.connect(root / "db" / "aiqa.sqlite") as connection:
        rows = connection.execute(
            "SELECT settings_json, definition_json FROM case_versions ORDER BY revision"
        ).fetchall()
    first = json.loads(rows[0][0])
    second = json.loads(rows[1][0])
    steps = json.loads(rows[0][1])["steps"]
    observed = {
        "device_first": page.text.find('data-wizard-step="1"') < page.text.find('data-wizard-step="2"'),
        "tc_required": steps != [],
        "incomplete_draft_saved": saved.status_code == 201 and steps == [],
        "wrong_target_fields_retained": first["android_package"] != "" or second["web_url"] != "",
    }
    assert missing.status_code == 422
    assert "오프라인" in page.text
    assert "로그인 확인" in page.text
    assert "com.example.app" in page.text
    assert "http://127.0.0.1/old" not in page.text
    assert "<button" not in page.text and "PASS" not in page.text
    assert switched.status_code == 201
    assert observed == {
        "device_first": True,
        "tc_required": False,
        "incomplete_draft_saved": True,
        "wrong_target_fields_retained": False,
    }


async def _rerecord(app: object, project_id: str, database: Path):
    import sqlite3

    import httpx

    origin = "http://127.0.0.1"
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=origin) as client:
        issued = await client.post(
            "/api/v1/session/nonces",
            json={"origin": origin, "project_id": project_id},
            headers={"Idempotency-Key": "w1608-nonce", "Origin": origin},
        )
        booted = await client.post(
            "/api/v1/session/bootstrap",
            json={"nonce": issued.json()["nonce"]},
            headers={"Idempotency-Key": "w1608-boot", "Origin": origin},
        )
        client.cookies.set("aiqa_session", booted.cookies["aiqa_session"])
        headers = {"Origin": origin, "X-CSRF-Token": booted.json()["csrf_token"], "Idempotency-Key": "w1608-case"}
        created = await client.post(
            f"/api/v1/projects/{project_id}/cases",
            json={"name": "로그인", "tc_reference": None},
            headers=headers,
        )
        case_id = created.json()["case_id"]
        with sqlite3.connect(database) as connection:
            before_approval = connection.execute(
                "SELECT current_approval_id FROM automation_cases WHERE case_id = ?",
                (case_id,),
            ).fetchone()[0]
        body = {"definition": _draft("web", "", "")["definition"], "settings": {"target_kind": "web"}}
        headers["Idempotency-Key"] = "w1608-v1"
        first = await client.post(f"/api/v1/projects/{project_id}/cases/{case_id}/versions", json=body, headers=headers)
        headers["Idempotency-Key"] = "w1608-v2"
        second_body = dict(body)
        second_body["expected_head"] = first.json()["id"]
        second = await client.post(
            f"/api/v1/projects/{project_id}/cases/{case_id}/versions",
            json=second_body,
            headers=headers,
        )
        base_id = second.json()["id"]
        request = {
            "project_id": project_id,
            "base_version_id": base_id,
            "expected_head": base_id,
            "reason": "전체를 다시 찍습니다",
            "resource_id": "key-w1605",
            "web_url": "http://127.0.0.1/",
            "data_name": "dataset-1",
            "reset_policy": "keep",
            "confirm_device": True,
            "confirm_target": True,
            "confirm_data": True,
            "confirm_reset": True,
        }
        refused = dict(request)
        refused["confirm_reset"] = False
        headers["Idempotency-Key"] = "w1608-refuse"
        missing = await client.post(f"/api/v1/cases/{case_id}/rerecordings", json=refused, headers=headers)
        headers["Idempotency-Key"] = "w1608-again"
        started = await client.post(f"/api/v1/cases/{case_id}/rerecordings", json=request, headers=headers)
        headers["Idempotency-Key"] = "w1608-stop"
        other = await client.post(f"/api/v1/cases/{case_id}/rerecordings", json=request, headers=headers)
        with sqlite3.connect(database) as connection:
            head = connection.execute(
                "SELECT latest_draft_version_id FROM automation_cases WHERE case_id = ?",
                (case_id,),
            ).fetchone()[0]
        headers["Idempotency-Key"] = "w1608-head"
        moved = dict(body)
        moved["expected_head"] = head
        await client.post(f"/api/v1/projects/{project_id}/cases/{case_id}/versions", json=moved, headers=headers)
        recording_id = started.json()["recording_id"]
        with sqlite3.connect(database) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            job_id = started.json()["job_id"]
            connection.execute(
                """
                INSERT INTO attempts (project_id, attempt_id, job_id, generation, physical_key_id)
                VALUES (?, 'attempt-w1608', ?, 1, NULL)
                """,
                (project_id, job_id),
            )
            connection.execute(
                """
                INSERT INTO artifact_refs (project_id, artifact_id, attempt_id, recording_id)
                VALUES (?, 'art-w1608', 'attempt-w1608', ?)
                """,
                (project_id, recording_id),
            )
            connection.execute(
                """
                INSERT INTO artifact_objects (
                    project_id, artifact_id, object_key, content_hash, byte_length, media_type,
                    owner_id, status, acked, owner_kind, attempt_id, role, job_id, generation
                ) VALUES (?, 'art-w1608', 'art-w1608', 'hash-w1608', 4, 'image/png', ?, 'ready', 1,
                    'REC', 'attempt-w1608', 'source', ?, 1)
                """,
                (project_id, recording_id, job_id),
            )
        headers["Idempotency-Key"] = "w1608-finish"
        finished = await client.post(
            f"/api/v1/recordings/{recording_id}/finish",
            json={"project_id": project_id, "outcome": "error", "final_seq": 1, "artifact_ids": ["art-w1608"]},
            headers=headers,
        )
        headers["Idempotency-Key"] = "w1608-interrupt"
        stopped = await client.post(
            f"/api/v1/recordings/{other.json()['recording_id']}/stop",
            json={"project_id": project_id},
            headers=headers,
        )
        page = await client.get(f"/ui/projects/{project_id}/cases/{case_id}/rerecord?base={base_id}")
    assert created.json()["tc_reference"] is None
    assert missing.status_code == 422, missing.text
    assert started.status_code == 201, started.text
    assert finished.status_code == 201, finished.text
    assert stopped.status_code == 201, stopped.text
    return (case_id, base_id, recording_id), other.json()["recording_id"], page, before_approval


async def _history(app: object, project_id: str, database: Path):
    import sqlite3
    from uuid import uuid4

    import httpx

    origin = "http://127.0.0.1"
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=origin) as client:
        issued = await client.post(
            "/api/v1/session/nonces",
            json={"origin": origin, "project_id": project_id},
            headers={"Idempotency-Key": "w1606-nonce", "Origin": origin},
        )
        booted = await client.post(
            "/api/v1/session/bootstrap",
            json={"nonce": issued.json()["nonce"]},
            headers={"Idempotency-Key": "w1606-boot", "Origin": origin},
        )
        client.cookies.set("aiqa_session", booted.cookies["aiqa_session"])
        headers = {"Origin": origin, "X-CSRF-Token": booted.json()["csrf_token"], "Idempotency-Key": "w1606-case"}
        created = await client.post(
            f"/api/v1/projects/{project_id}/cases",
            json={"name": "로그인", "tc_reference": None},
            headers=headers,
        )
        case_id = created.json()["case_id"]
        headers["Idempotency-Key"] = "w1606-version"
        version = await client.post(
            f"/api/v1/projects/{project_id}/cases/{case_id}/versions",
            json={"definition": _draft("web", "", "")["definition"], "settings": {"target_kind": "web"}},
            headers=headers,
        )
        version_id = version.json()["id"]
        content_hash = version.json()["content_hash"]
        produced_id = str(uuid4())
        with sqlite3.connect(database) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            source = connection.execute(
                "SELECT * FROM case_versions WHERE version_id = ?",
                (version_id,),
            ).fetchone()
            names = [item[1] for item in connection.execute("PRAGMA table_info(case_versions)")]
            values = dict(zip(names, source, strict=True))
            case_row = connection.execute(
                "SELECT next_revision FROM automation_cases WHERE case_id = ?",
                (case_id,),
            ).fetchone()
            for recording_id, storage, completion, evidence in (
                ("11111111-1111-4111-8111-111111111111", "stored", "error", "incomplete"),
                ("22222222-2222-4222-8222-222222222222", "local", "open", "incomplete"),
                ("33333333-3333-4333-8333-333333333333", "spooling", "open", "incomplete"),
                ("44444444-4444-4444-8444-444444444444", "stored", "interrupted", "incomplete"),
            ):
                connection.execute(
                    """
                    INSERT INTO recordings (
                        project_id, case_id, recording_id, creation_kind, input_case_version_id,
                        base_case_version_id, parent_recording_id, source_recording_id,
                        storage_status, stop_status, completion_status, evidence_status
                    ) VALUES (?, ?, ?, 'recorded', ?, NULL, NULL, NULL, ?, 'stopped', ?, ?)
                    """,
                    (project_id, case_id, recording_id, version_id, storage, completion, evidence),
                )
            connection.execute(
                """
                INSERT INTO recording_manifests (
                    project_id, case_id, recording_id, manifest_id, revision, kind, prior_manifest_id,
                    input_version_hash, source_artifact_hashes, action_mapping, evidence_completeness,
                    request_key, body_hash
                ) VALUES (?, ?, '44444444-4444-4444-8444-444444444444', '55555555-5555-4555-8555-555555555555',
                    1, 'recovery', NULL, ?, '[]', '{}', 'incomplete', 'w1606-manifest', 'hash-w1606')
                """,
                (project_id, case_id, content_hash),
            )
            values["version_id"] = produced_id
            values["revision"] = int(case_row[0])
            values["source_manifest_id"] = "55555555-5555-4555-8555-555555555555"
            values["replay_package_id"] = None
            values["reason"] = "compiler is missing"
            columns = ", ".join(names)
            connection.execute(
                f"INSERT INTO case_versions ({columns}) VALUES ({', '.join('?' for _ in names)})",
                tuple(values[name] for name in names),
            )
            connection.execute(
                """
                INSERT INTO materialization_receipts (
                    project_id, receipt_id, manifest_id, produced_version_id, body_hash
                ) VALUES (?, '66666666-6666-4666-8666-666666666666',
                    '55555555-5555-4555-8555-555555555555', ?, 'hash-w1606')
                """,
                (project_id, produced_id),
            )
            connection.execute(
                """
                INSERT INTO reviews (
                    project_id, review_id, case_id, case_version_id, version_hash,
                    source_manifest_id, trial_case_run_id, evidence_set_hash,
                    expected_current_approval_id, created_commit_seq
                ) VALUES (?, '77777777-7777-4777-8777-777777777777', ?, ?, ?, NULL, NULL, 'evidence', NULL, 1)
                """,
                (project_id, case_id, produced_id, content_hash),
            )
            connection.execute(
                """
                INSERT INTO review_decisions (
                    project_id, review_id, decision_id, state, actor_id, created_at, reason, version_hash
                ) VALUES (?, '77777777-7777-4777-8777-777777777777', '88888888-8888-4888-8888-888888888888',
                    'rejected', ?, '2026-11-01T00:00:00+00:00', '범위가 부족합니다', ?)
                """,
                (project_id, str(uuid4()), content_hash),
            )
        headers["Idempotency-Key"] = "w1606-read"
        listed = await client.get(f"/api/v1/cases/{case_id}/recordings", headers=headers)
        manifests = await client.get(
            "/api/v1/recordings/44444444-4444-4444-8444-444444444444/manifests",
            headers=headers,
        )
        page = await client.get(f"/ui/projects/{project_id}/cases/{case_id}/recordings?action=tap-1")
        again = await client.get(f"/ui/projects/{project_id}/cases/{case_id}/recordings?action=tap-1")
        detail = await client.get(f"/ui/projects/{project_id}/cases/{case_id}/definition")
    assert again.text == page.text
    return listed, manifests, page, detail


async def _seal(app: object, project_id: str, database: Path):
    import sqlite3

    import httpx

    origin = "http://127.0.0.1"
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=origin) as client:
        issued = await client.post(
            "/api/v1/session/nonces",
            json={"origin": origin, "project_id": project_id},
            headers={"Idempotency-Key": "w1605-nonce", "Origin": origin},
        )
        booted = await client.post(
            "/api/v1/session/bootstrap",
            json={"nonce": issued.json()["nonce"]},
            headers={"Idempotency-Key": "w1605-boot", "Origin": origin},
        )
        client.cookies.set("aiqa_session", booted.cookies["aiqa_session"])
        headers = {"Origin": origin, "X-CSRF-Token": booted.json()["csrf_token"], "Idempotency-Key": "w1605-case"}
        created = await client.post(
            f"/api/v1/projects/{project_id}/cases",
            json={"name": "로그인", "tc_reference": None},
            headers=headers,
        )
        case_id = created.json()["case_id"]
        draft = _draft("web", "http://127.0.0.1/", "")
        draft["settings"]["resource_id"] = "key-w1605"
        headers["Idempotency-Key"] = "w1605-version"
        version = await client.post(
            f"/api/v1/projects/{project_id}/cases/{case_id}/versions",
            json=draft,
            headers=headers,
        )
        start_body = {
            "case_id": case_id,
            "input_case_version_id": version.json()["id"],
            "input_version_hash": version.json()["content_hash"],
            "resource_id": "key-w1605",
        }
        recordings = []
        for key in ("w1605-rec-a", "w1605-rec-b", "w1605-rec-c"):
            headers["Idempotency-Key"] = key
            started = await client.post(f"/api/v1/projects/{project_id}/recordings", json=start_body, headers=headers)
            assert started.status_code == 201, started.text
            recordings.append(started.json())
        first = recordings[0]
        with sqlite3.connect(database) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute(
                """
                INSERT INTO attempts (project_id, attempt_id, job_id, generation, physical_key_id)
                VALUES (?, 'attempt-w1605', ?, 1, NULL)
                """,
                (project_id, first["job_id"]),
            )
            connection.execute(
                """
                INSERT INTO artifact_refs (project_id, artifact_id, attempt_id, recording_id)
                VALUES (?, 'art-1', 'attempt-w1605', ?)
                """,
                (project_id, first["recording_id"]),
            )
            connection.execute(
                """
                INSERT INTO artifact_objects (
                    project_id, artifact_id, object_key, content_hash, byte_length, media_type,
                    owner_id, status, acked, owner_kind, attempt_id, role, job_id, generation
                ) VALUES (?, 'art-1', 'art-1', 'hash-art-1', 4, 'image/png', ?, 'ready', 1,
                    'REC', 'attempt-w1605', 'source', ?, 1)
                """,
                (project_id, first["recording_id"], first["job_id"]),
            )
        recordings = [item["recording_id"] for item in recordings]
        finish = {"project_id": project_id, "outcome": "completed", "final_seq": 1, "artifact_ids": ["art-1"]}
        headers["Idempotency-Key"] = "w1605-finish"
        finished = await client.post(f"/api/v1/recordings/{recordings[0]}/finish", json=finish, headers=headers)
        replay = await client.post(f"/api/v1/recordings/{recordings[0]}/finish", json=finish, headers=headers)
        other = dict(finish)
        other["final_seq"] = 2
        conflict = await client.post(f"/api/v1/recordings/{recordings[0]}/finish", json=other, headers=headers)
        failed_body = dict(finish)
        failed_body["outcome"] = "error"
        headers["Idempotency-Key"] = "w1605-error"
        failed = await client.post(f"/api/v1/recordings/{recordings[1]}/finish", json=failed_body, headers=headers)
        headers["Idempotency-Key"] = "w1605-stop"
        stopped = await client.post(
            f"/api/v1/recordings/{recordings[2]}/stop",
            json={"project_id": project_id},
            headers=headers,
        )
        page = await client.get(f"/ui/projects/{project_id}/recordings/{recordings[0]}")
    assert stopped.status_code == 201 and stopped.json()["completion_status"] == "interrupted"
    assert finished.status_code == 201, finished.text
    assert replay.status_code == 200 and replay.json()["manifest_id"] == finished.json()["manifest_id"]
    assert conflict.status_code == 409
    assert finished.json()["replay_package_id"] is None
    return finished, failed, page


async def _start(app: object, project_id: str, database: Path, actor_id: str):
    import sqlite3

    import httpx

    origin = "http://127.0.0.1"
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=origin) as client:
        issued = await client.post(
            "/api/v1/session/nonces",
            json={"origin": origin, "project_id": project_id},
            headers={"Idempotency-Key": "w1603-nonce", "Origin": origin},
        )
        booted = await client.post(
            "/api/v1/session/bootstrap",
            json={"nonce": issued.json()["nonce"]},
            headers={"Idempotency-Key": "w1603-boot", "Origin": origin},
        )
        client.cookies.set("aiqa_session", booted.cookies["aiqa_session"])
        headers = {"Origin": origin, "X-CSRF-Token": booted.json()["csrf_token"], "Idempotency-Key": "w1603-case"}
        created = await client.post(
            f"/api/v1/projects/{project_id}/cases",
            json={"name": "로그인", "tc_reference": None},
            headers=headers,
        )
        case_id = created.json()["case_id"]
        draft = _draft("web", "http://127.0.0.1/", "com.example.app")
        draft["settings"]["resource_id"] = "key-a"
        headers["Idempotency-Key"] = "w1603-version"
        version = await client.post(
            f"/api/v1/projects/{project_id}/cases/{case_id}/versions",
            json=draft,
            headers=headers,
        )
        body = {
            "case_id": case_id,
            "input_case_version_id": version.json()["id"],
            "input_version_hash": version.json()["content_hash"],
            "resource_id": "key-a",
        }
        headers["Idempotency-Key"] = "w1603-start"
        blocked = await client.post(f"/api/v1/projects/{project_id}/recordings", json=body, headers=headers)
        with sqlite3.connect(database) as connection:
            connection.execute(
                """
                INSERT INTO model_bindings (project_id, binding_id, name, next_revision, latest_revision_id)
                VALUES (?, 'bind-1', '작성', 2, 'rev-1')
                """,
                (project_id,),
            )
            connection.execute(
                """
                INSERT INTO binding_revisions (
                    project_id, binding_id, revision_id, revision, role, provider, endpoint_kind,
                    endpoint, model, key_ref_id, key_revision, prompt_hash, tariff_id,
                    compatibility_status, content_hash, actor_id, created_at
                ) VALUES (?, 'bind-1', 'rev-1', 1, 'authoring', 'fixture', 'loopback',
                    'http://127.0.0.1', 'author-model', 'ref-1', 1, 'prompt', 'tariff',
                    'compatible', 'hash', ?, '2026-11-01T00:00:00+00:00')
                """,
                (project_id, actor_id),
            )
        saved = await client.post(f"/api/v1/projects/{project_id}/recordings", json=body, headers=headers)
        with sqlite3.connect(database) as connection:
            connection.execute("UPDATE resource_inventory SET state = 'busy' WHERE physical_key_id = 'key-a'")
        replay = await client.post(f"/api/v1/projects/{project_id}/recordings", json=body, headers=headers)
        other = dict(body)
        other["resource_id"] = "key-b"
        conflict = await client.post(f"/api/v1/projects/{project_id}/recordings", json=other, headers=headers)
        mismatched = dict(body)
        mismatched["input_version_hash"] = "different-hash"
        headers["Idempotency-Key"] = "w1603-hash"
        mismatch = await client.post(f"/api/v1/projects/{project_id}/recordings", json=mismatched, headers=headers)
        with sqlite3.connect(database) as connection:
            connection.execute("UPDATE resource_inventory SET state = 'busy' WHERE physical_key_id = 'key-b'")
        headers["Idempotency-Key"] = "w1603-busy"
        busy = await client.post(f"/api/v1/projects/{project_id}/recordings", json=other, headers=headers)
        page = await client.get(f"/ui/projects/{project_id}/recordings/wizard", params={"case": case_id})
    assert saved.status_code == 201, saved.text
    assert busy.status_code == 409 and "resource is busy" in busy.text
    return blocked, saved, replay, conflict, mismatch, page


async def _wizard(app: object, project_id: str):
    import httpx

    origin = "http://127.0.0.1"
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=origin) as client:
        issued = await client.post(
            "/api/v1/session/nonces",
            json={"origin": origin, "project_id": project_id},
            headers={"Idempotency-Key": "w1601-nonce", "Origin": origin},
        )
        booted = await client.post(
            "/api/v1/session/bootstrap",
            json={"nonce": issued.json()["nonce"]},
            headers={"Idempotency-Key": "w1601-boot", "Origin": origin},
        )
        client.cookies.set("aiqa_session", booted.cookies["aiqa_session"])
        headers = {"Origin": origin, "X-CSRF-Token": booted.json()["csrf_token"], "Idempotency-Key": "w1601-case"}
        created = await client.post(
            f"/api/v1/projects/{project_id}/cases",
            json={"name": "로그인", "tc_reference": None},
            headers=headers,
        )
        case_id = created.json()["case_id"]
        body = _draft("web", "://bad", "com.wrong")
        headers["Idempotency-Key"] = "w1601-draft"
        saved = await client.post(f"/api/v1/projects/{project_id}/cases/{case_id}/versions", json=body, headers=headers)
        android = _draft("android", "http://127.0.0.1/old", "com.example.app")
        android["expected_head"] = saved.json()["id"]
        headers["Idempotency-Key"] = "w1601-switch"
        switched = await client.post(
            f"/api/v1/projects/{project_id}/cases/{case_id}/versions",
            json=android,
            headers=headers,
        )
        bare = _draft("web", "", "")
        bare["settings"].pop("resource_id")
        headers["Idempotency-Key"] = "w1601-missing"
        missing = await client.post(
            f"/api/v1/projects/{project_id}/cases/{case_id}/versions",
            json=bare,
            headers=headers,
        )
        page = await client.get(f"/ui/projects/{project_id}/recordings/wizard", params={"case": case_id, "step": "1"})
    return page, saved, switched, missing


def _draft(target: str, web_url: str, package: str) -> dict[str, object]:
    return {
        "definition": {
            "raw_text": "",
            "objective": "",
            "preconditions": [],
            "variables": {},
            "secret_refs": {},
            "steps": [],
            "final_expected": [{"id": "exp-1", "kind": "text", "expected": ""}],
            "path_policy": {"must_use": [], "forbidden": []},
        },
        "settings": {
            "wizard": True,
            "target_kind": target,
            "resource_id": "key-w1601",
            "environment_revision_id": "",
            "definition_buffer": "로그인 확인",
            "web_url": web_url,
            "android_package": package,
            "build": "build-1",
            "account_ref": "account-1",
            "execution_mode": "recorded_replay",
        },
    }
