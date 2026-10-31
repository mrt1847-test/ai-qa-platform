"""W10-01: shared management shell, query restore, and keyboard entry."""

from __future__ import annotations

from pathlib import Path


def test_w10_01(tmp_path: Path) -> None:
    import asyncio

    import httpx

    from aiqa.api.app import create_app
    from aiqa.config import load_settings
    from aiqa.web.routes import PageContext, UiQueryState, render_page

    assert callable(render_page)
    assert UiQueryState.__dataclass_fields__.keys() == {
        "filter",
        "sort",
        "cursor",
        "selected_id",
        "scroll",
    }
    root = tmp_path / "runtime"
    app = create_app(
        load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)})
    )
    query = "filter=pay&sort=name&page=2&selected=item-1"
    pages = asyncio.run(_read(app, query))
    listed = pages["list"]
    detail = pages["detail"]
    again = pages["reload"]
    script = pages["script"]
    style = pages["style"]
    home = pages["home"]
    assert listed.status_code == 200
    assert detail.status_code == 200
    assert again.status_code == 200
    text = listed.text
    restored = (
        'data-query="filter" value="pay"' in text
        and 'data-query="sort" value="name"' in text
        and 'data-query="page" value="2"' in text
        and 'data-query="selected" value="item-1"' in text
        and f"/ui/shell/items/item-1?{query.replace('&', '&amp;')}" in detail.text
        and f"/ui/shell?{query.replace('&', '&amp;')}" in detail.text
    )
    posts = text.lower().count('method="post"') + again.text.lower().count('method="post"')
    stored = script.text
    secret_stored = any(
        token in stored
        for token in ("secret", "password", "csrf", "token", "localStorage")
    ) or "sessionStorage.setItem" not in stored
    keyboard = 'href="#content"' in text and 'aria-current="page"' in text and ":focus-visible" in style.text
    assert "입력을 다시 확인해 주세요." in pages["invalid"].text
    assert "이 화면을 볼 권한이 없습니다." in pages["forbidden"].text
    assert "서버의 최신 상태와 다릅니다." in pages["conflict"].text
    assert "마지막 수신 이후 연결을 확인하지 못했습니다." in pages["stale"].text
    assert "@media (min-width: 1024px)" in style.text
    assert "@media (min-width: 1440px)" in style.text
    assert _fake_count(home.text) == 0
    assert _fake_count(style.text) == 0
    observed = {
        "restored_query": restored,
        "duplicate_mutation_on_reload": posts,
        "secret_in_browser_storage": secret_stored,
        "keyboard_usable": keyboard,
    }
    assert observed == {
        "restored_query": True,
        "duplicate_mutation_on_reload": 0,
        "secret_in_browser_storage": False,
        "keyboard_usable": True,
    }


_FAKE_MARKERS = (
    "localStorage",
    "sessionStorage",
    "PASS",
    "<button",
    "승인됨",
    "승인 완료",
    "녹화 완료",
    "dashboard",
    "prototype",
)


def _fake_count(text: str) -> int:
    return sum(text.count(marker) for marker in _FAKE_MARKERS)


def test_w10_02(tmp_path: Path) -> None:
    import asyncio
    import sqlite3

    from aiqa.api.app import create_app
    from aiqa.config import load_settings

    root = tmp_path / "runtime"
    settings = load_settings(
        {"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}
    )
    app = create_app(settings)
    body = {
        "name": "결제",
        "key": "pay",
        "description": "카드 결제",
        "target": "web",
        "actor": {
            "actor_id": "11111111-1111-4111-8111-111111111111",
            "project_scope": None,
            "is_local_owner": True,
        },
    }

    async def run() -> dict[str, object]:
        import httpx

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            empty = await client.get("/api/v1/projects")
            blank = await client.get("/ui/projects")
            created = await client.post("/api/v1/projects", json=body, headers={"Origin":"http://127.0.0.1", "Idempotency-Key": "create-pay"})
            session = await _ui_session(client,created.json()["project_id"],"project-session")
            duplicate = await client.post(
                "/api/v1/projects", json=body, headers={**session["headers"], "Idempotency-Key": "create-pay-again"}
            )
            project_id = created.json()["project_id"]
            listed = await client.get("/ui/projects")
            return {
                "empty": empty,
                "blank": blank,
                "created": created,
                "duplicate": duplicate,
                "project_id": project_id,
                "listed": listed,
                "session": session,
            }

    first = asyncio.run(run())
    database = root / "db" / "aiqa.sqlite"
    project_id = str(first["project_id"])
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO jobs (
                project_id, job_id, purpose, recording_id, case_run_id,
                payload_hash, source_refs, limits, status
            ) VALUES (?, ?, 'structure', NULL, NULL, 'hash', '["ref"]', '{}', 'running')
            """,
            (project_id, "job-1"),
        )

    async def finish(project: str) -> dict[str, object]:
        import httpx

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            client.cookies.set("aiqa_session", first["session"]["cookie"])
            blocked = await client.post(
                f"/api/v1/projects/{project}/archive",
                json=body,
                headers={**first["session"]["headers"], "Idempotency-Key": "archive-busy"},
            )
            return {"blocked": blocked}

    busy = asyncio.run(finish(project_id))
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE jobs SET status = 'cancelled' WHERE project_id = ? AND job_id = 'job-1'",
            (project_id,),
        )

    async def settle(project: str) -> dict[str, object]:
        import httpx

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            client.cookies.set("aiqa_session", first["session"]["cookie"])
            archived = await client.post(
                f"/api/v1/projects/{project}/archive",
                json=body,
                headers={**first["session"]["headers"], "Idempotency-Key": "archive-done"},
            )
            history = await client.get(f"/api/v1/projects/{project}/audits/{first['created'].json()['audit_id']}")
            stored = await client.get("/api/v1/projects?archived=true")
            active = await client.get("/api/v1/projects")
            restored = await client.post(
                f"/api/v1/projects/{project}/restore",
                json=body,
                headers={**first["session"]["headers"], "Idempotency-Key": "restore-pay"},
            )
            audit = await client.get(
                f"/api/v1/projects/{project}/audits/{restored.json()['audit_id']}"
            )
            return {
                "archived": archived,
                "history": history,
                "stored": stored,
                "active": active,
                "restored": restored,
                "audit": audit,
            }

    done = asyncio.run(settle(project_id))
    created = first["created"]
    assert first["empty"].status_code == 200
    assert first["empty"].json() == {"items": []}
    assert "표시할 항목이 없습니다." in first["blank"].text
    assert created.status_code == 201
    assert created.json()["case_count"] == 0
    assert created.json()["review_count"] == 0
    assert created.json()["run_count"] == 0
    assert "결제" in first["listed"].text
    assert "/ui/projects/" in first["listed"].text and "/environment" in first["listed"].text
    assert done["history"].status_code == 200
    assert done["history"].json()["action"] == "create"
    assert done["stored"].json()["items"][0]["project_id"] == project_id
    assert done["active"].json()["items"] == []
    assert done["audit"].json()["action"] == "restore"
    observed = {
        "duplicate_key_status": first["duplicate"].status_code,
        "active_job_archive_status": busy["blocked"].status_code,
        "archived_history_readable": done["history"].status_code == 200 and done["stored"].status_code == 200,
        "restore_audited": done["restored"].status_code == 200 and done["audit"].json()["action"] == "restore",
    }
    assert observed == {
        "duplicate_key_status": 409,
        "active_job_archive_status": 409,
        "archived_history_readable": True,
        "restore_audited": True,
    }


def test_w10_03(tmp_path: Path) -> None:
    import asyncio
    import json
    import sqlite3

    from aiqa.api.app import create_app
    from aiqa.config import load_settings

    root = tmp_path / "runtime"
    settings = load_settings(
        {"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}
    )
    bare = create_app(settings)
    assert "/api/v1/projects/{project_id}/overview" not in {
        getattr(route, "path", None) for route in bare.routes
    }
    app = create_app(settings)
    body = {
        "name": "결제",
        "key": "pay",
        "description": "카드 결제",
        "target": "web",
        "actor": {
            "actor_id": "11111111-1111-4111-8111-111111111111",
            "project_scope": None,
            "is_local_owner": True,
        },
    }
    empty_body = {**body, "name": "빈 프로젝트", "key": "empty"}

    async def create() -> tuple[str, str]:
        import httpx

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            filled = await client.post("/api/v1/projects", json=body, headers={"Origin":"http://127.0.0.1", "Idempotency-Key": "overview-pay"})
            session = await _ui_session(client,filled.json()["project_id"],"overview-session")
            blank = await client.post(
                "/api/v1/projects", json=empty_body, headers={**session["headers"], "Idempotency-Key": "overview-empty"}
            )
            return filled.json()["project_id"], blank.json()["project_id"]

    project_id, empty_id = asyncio.run(create())
    _seed_overview(root / "db" / "aiqa.sqlite", project_id)

    async def read() -> dict[str, object]:
        import httpx

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            filled = await client.get(f"/api/v1/projects/{project_id}/overview")
            blank = await client.get(f"/api/v1/projects/{empty_id}/overview")
            page = await client.get(f"/ui/projects/{empty_id}/overview")
            device = await client.get(f"/ui/projects/{empty_id}/recordings/new")
            return {"filled": filled, "blank": blank, "page": page, "device": device}

    pages = asyncio.run(read())
    filled = pages["filled"].json()
    blank = pages["blank"].json()
    with sqlite3.connect(root / "db" / "aiqa.sqlite") as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        stored = _overview_sql(connection, project_id)
        empty_stored = _overview_sql(connection, empty_id)
    counts_match = all(filled[name] == stored[name] for name in stored) and all(
        blank[name] == empty_stored[name] for name in empty_stored
    )
    fake = json.dumps(blank).count("PASS") + pages["page"].text.count("PASS")
    device_text = pages["device"].text
    observed = {
        "counts_match_db": counts_match and filled["draft_cases"] == 1 and filled["approved_cases"] == 1,
        "empty_fake_passes": fake,
        "new_recording_opens_device_step": (
            blank["new_recording_href"] in pages["page"].text
            and pages["device"].status_code == 200
            and "기기 단계" in device_text
            and "기기를 열지 않습니다." in device_text
        ),
    }
    assert observed == {
        "counts_match_db": True,
        "empty_fake_passes": 0,
        "new_recording_opens_device_step": True,
    }


def _seed_overview(database: Path, project_id: str) -> None:
    import sqlite3

    actor = "11111111-1111-4111-8111-111111111111"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        _case(connection, project_id, "case-draft", "초안 케이스", actor, "2020-01-02T00:00:00+00:00")
        _case(connection, project_id, "case-ok", "승인 케이스", actor, "2020-01-01T00:00:00+00:00")
        _recording(connection, project_id, "case-draft", "version-case-draft", "rec-open", "stopped", "open", "incomplete")
        _recording(connection, project_id, "case-ok", "version-case-ok", "rec-error", "stopped", "error", "incomplete")
        connection.execute(
            """
            INSERT INTO reviews (
                project_id, review_id, case_id, case_version_id, version_hash,
                source_manifest_id, trial_case_run_id, evidence_set_hash,
                expected_current_approval_id, created_commit_seq
            ) VALUES (?, 'review-wait', 'case-draft', 'version-case-draft', 'hash', NULL, NULL, 'hash', NULL, 1)
            """,
            (project_id,),
        )
        connection.execute(
            """
            INSERT INTO reviews (
                project_id, review_id, case_id, case_version_id, version_hash,
                source_manifest_id, trial_case_run_id, evidence_set_hash,
                expected_current_approval_id, created_commit_seq
            ) VALUES (?, 'review-ok', 'case-ok', 'version-case-ok', 'hash', NULL, NULL, 'hash', NULL, 1)
            """,
            (project_id,),
        )
        connection.execute(
            """
            INSERT INTO approval_events (
                project_id, approval_id, case_id, case_version_id, review_id, event_kind,
                prior_approval_id, version_hash, evidence_set_hash, reason
            ) VALUES (?, 'approval-ok', 'case-ok', 'version-case-ok', 'review-ok', 'approved', NULL, 'hash', 'hash', 'ready')
            """,
            (project_id,),
        )
        connection.execute(
            """
            UPDATE automation_cases SET current_approval_id = 'approval-ok'
            WHERE project_id = ? AND case_id = 'case-ok'
            """,
            (project_id,),
        )
        for job_id, status in (("job-run", "running"), ("job-wait", "queued"), ("job-done", "error")):
            connection.execute(
                """
                INSERT INTO jobs (
                    project_id, job_id, purpose, recording_id, case_run_id,
                    payload_hash, source_refs, limits, status
                ) VALUES (?, ?, 'structure', NULL, NULL, 'hash', '["ref"]', '{}', ?)
                """,
                (project_id, job_id, status),
            )
        connection.execute(
            """
            INSERT INTO environments (
                project_id, environment_id, name, next_revision, latest_revision_id
            ) VALUES (?, 'env-blocked', '막힌 환경', 1, NULL)
            """,
            (project_id,),
        )


def _case(connection: object, project_id: str, case_id: str, name: str, actor: str, created_at: str) -> None:
    version_id = f"version-{case_id}"
    connection.execute(
        """
        INSERT INTO automation_cases (
            project_id, case_id, name, folder_id, tc_reference, next_revision,
            latest_draft_version_id, current_approval_id, lock_version, archived_at
        ) VALUES (?, ?, ?, NULL, NULL, 2, NULL, NULL, 1, NULL)
        """,
        (project_id, case_id, name),
    )
    connection.execute(
        """
        INSERT INTO case_versions (
            project_id, case_id, version_id, revision, creation_kind, parent_version_id,
            base_version_id, is_branch, definition_json, settings_json, recorded_steps_json,
            content_hash, verification_digest, source_manifest_id, replay_package_id,
            readiness_json, actor_id, reason, created_at
        ) VALUES (?, ?, ?, 1, 'input', NULL, NULL, 0, '{}', '{}', '[]', 'hash', 'hash', NULL, NULL, '{}', ?, 'seed', ?)
        """,
        (project_id, case_id, version_id, actor, created_at),
    )
    connection.execute(
        """
        UPDATE automation_cases SET latest_draft_version_id = ?
        WHERE project_id = ? AND case_id = ?
        """,
        (version_id, project_id, case_id),
    )


def _recording(
    connection: object,
    project_id: str,
    case_id: str,
    version_id: str,
    recording_id: str,
    stop_status: str,
    completion_status: str,
    evidence_status: str,
) -> None:
    connection.execute(
        """
        INSERT INTO recordings (
            project_id, case_id, recording_id, creation_kind, input_case_version_id,
            base_case_version_id, parent_recording_id, source_recording_id,
            storage_status, stop_status, completion_status, evidence_status
        ) VALUES (?, ?, ?, 'recorded', ?, NULL, NULL, NULL, 'local', ?, ?, ?)
        """,
        (project_id, case_id, recording_id, version_id, stop_status, completion_status, evidence_status),
    )


def _overview_sql(connection: object, project_id: str) -> dict[str, object]:
    def one(sql: str) -> int:
        row = connection.execute(sql, (project_id,)).fetchone()
        return 0 if row is None else int(row[0])

    scope = connection.execute(
        """
        SELECT automation_cases.name
        FROM case_versions
        JOIN automation_cases
          ON automation_cases.project_id = case_versions.project_id
         AND automation_cases.case_id = case_versions.case_id
        WHERE case_versions.project_id = ?
        ORDER BY case_versions.created_at DESC, case_versions.version_id DESC
        LIMIT 1
        """,
        (project_id,),
    ).fetchone()
    result = connection.execute(
        """
        SELECT status FROM jobs
        WHERE project_id = ? AND status IN ('completed', 'error', 'cancelled', 'lost')
        ORDER BY rowid DESC LIMIT 1
        """,
        (project_id,),
    ).fetchone()
    return {
        "incomplete_recordings": one(
            "SELECT COUNT(*) FROM recordings WHERE project_id = ? AND (completion_status = 'open' OR stop_status = 'running')"
        ),
        "reviews_waiting": one(
            """
            SELECT COUNT(*) FROM reviews
            WHERE project_id = ? AND NOT EXISTS (
                SELECT 1 FROM approval_events
                WHERE approval_events.project_id = reviews.project_id
                  AND approval_events.review_id = reviews.review_id
            )
            """
        ),
        "unclassified_failures": one(
            "SELECT COUNT(*) FROM recordings WHERE project_id = ? AND completion_status = 'error'"
        ),
        "running_runs": one(
            """
            SELECT COUNT(*) FROM jobs
            WHERE project_id = ? AND status IN ('preparing', 'running', 'finalizing', 'cancel_requested')
            """
        ),
        "queued_runs": one("SELECT COUNT(*) FROM jobs WHERE project_id = ? AND status = 'queued'"),
        "blocked_environments": one(
            "SELECT COUNT(*) FROM environments WHERE project_id = ? AND latest_revision_id IS NULL"
        ),
        "draft_cases": one(
            """
            SELECT COUNT(*) FROM automation_cases
            WHERE project_id = ? AND archived_at IS NULL
              AND latest_draft_version_id IS NOT NULL AND current_approval_id IS NULL
            """
        ),
        "approved_cases": one(
            """
            SELECT COUNT(*) FROM automation_cases
            WHERE project_id = ? AND archived_at IS NULL AND current_approval_id IS NOT NULL
            """
        ),
        "recent_scope": None if scope is None else str(scope[0]),
        "recent_result": None if result is None else str(result[0]),
    }


def test_w10_04(tmp_path: Path) -> None:
    import asyncio
    import sqlite3
    from uuid import uuid4

    from aiqa.api.app import create_app
    from aiqa.config import load_settings
    from aiqa.store.models import CaseListQuery

    root = tmp_path / "runtime"
    settings = load_settings(
        {"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}
    )
    app = create_app(settings)
    origin = "http://127.0.0.1"
    body = {
        "name": "결제",
        "key": "pay",
        "description": "카드 결제",
        "target": "web",
        "actor": {
            "actor_id": "11111111-1111-4111-8111-111111111111",
            "project_scope": None,
            "is_local_owner": True,
        },
    }
    other_body = {**body, "name": "다른", "key": "other"}

    async def create() -> tuple[str, str]:
        import httpx

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            first = await client.post("/api/v1/projects", json=body, headers={"Origin":"http://127.0.0.1", "Idempotency-Key": "cases-pay"})
            session = await _ui_session(client,first.json()["project_id"],"cases-session")
            second = await client.post("/api/v1/projects", json=other_body, headers={**session["headers"], "Idempotency-Key": "cases-other"})
            return first.json()["project_id"], second.json()["project_id"]

    project_id, other_id = asyncio.run(create())
    foreign_id = str(uuid4())
    target_id = str(uuid4())
    with sqlite3.connect(root / "db" / "aiqa.sqlite") as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        for index in range(1, 27):
            case_id = target_id if index == 26 else str(uuid4())
            name = "find-me" if index == 26 else f"Case {index:02d}"
            connection.execute(
                """
                INSERT INTO automation_cases (
                    project_id, case_id, name, folder_id, tc_reference, next_revision,
                    latest_draft_version_id, current_approval_id, lock_version, archived_at
                ) VALUES (?, ?, ?, NULL, NULL, 1, NULL, NULL, 1, NULL)
                """,
                (project_id, case_id, name),
            )
        connection.execute(
            """
            INSERT INTO automation_cases (
                project_id, case_id, name, folder_id, tc_reference, next_revision,
                latest_draft_version_id, current_approval_id, lock_version, archived_at
            ) VALUES (?, ?, 'archived-one', NULL, NULL, 1, NULL, NULL, 1, '2020-01-01T00:00:00+00:00')
            """,
            (project_id, str(uuid4())),
        )
        connection.execute(
            """
            INSERT INTO automation_cases (
                project_id, case_id, name, folder_id, tc_reference, next_revision,
                latest_draft_version_id, current_approval_id, lock_version, archived_at
            ) VALUES (?, ?, 'foreign', NULL, NULL, 1, NULL, NULL, 1, NULL)
            """,
            (other_id, foreign_id),
        )

    async def read() -> dict[str, object]:
        import httpx

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            issued = await client.post(
                "/api/v1/session/nonces",
                json={"origin": origin, "project_id": project_id},
                headers={"Idempotency-Key": "case-nonce", "Origin": origin},
            )
            booted = await client.post(
                "/api/v1/session/bootstrap",
                json={"nonce": issued.json()["nonce"]},
                headers={"Idempotency-Key": "case-boot", "Origin": origin},
            )
            client.cookies.set("aiqa_session", booted.cookies["aiqa_session"])
            headers = {"Origin": origin, "X-CSRF-Token": booted.json()["csrf_token"]}
            first = await client.get(f"/api/v1/projects/{project_id}/cases", headers=headers)
            cursor = first.json()["next_cursor"]
            second = await client.get(
                f"/api/v1/projects/{project_id}/cases?cursor={cursor}",
                headers=headers,
            )
            found = await client.get(f"/api/v1/projects/{project_id}/cases?q=find", headers=headers)
            page = await client.get(
                f"/ui/projects/{project_id}/cases?q=find&sort=name&selected={target_id}",
                headers=headers,
            )
            detail = await client.get(
                f"/ui/projects/{project_id}/cases/{target_id}?q=find&sort=name&selected={target_id}",
                headers=headers,
            )
            return {"first": first, "second": second, "found": found, "page": page, "detail": detail}

    pages = asyncio.run(read())
    first = pages["first"].json()
    second = pages["second"].json()
    found = pages["found"].json()
    listed = pages["page"].text
    detail = pages["detail"].text
    leaked = sum(item["case_id"] == foreign_id for item in first["items"] + second["items"] + found["items"])
    observed = {
        "default_page_size": CaseListQuery.__dataclass_fields__["limit"].default,
        "query_restore": "q=find" in detail and "sort=name" in detail and f"selected={target_id}" in detail,
        "cross_project_rows": leaked,
        "null_tc_selectable": (
            len(first["items"]) == 25
            and first["next_cursor"] is not None
            and len(second["items"]) == 1
            and found["items"][0]["case_id"] == target_id
            and found["items"][0]["tc_reference"] is None
            and f'value="{target_id}"' in listed
            and "disabled" not in listed
        ),
    }
    assert observed == {
        "default_page_size": 25,
        "query_restore": True,
        "cross_project_rows": 0,
        "null_tc_selectable": True,
    }


def test_w10_05(tmp_path: Path) -> None:
    import asyncio
    import sqlite3
    from uuid import uuid4

    from aiqa.api.app import create_app
    from aiqa.config import load_settings

    root = tmp_path / "runtime"
    settings = load_settings(
        {"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}
    )
    app = create_app(settings)
    origin = "http://127.0.0.1"
    body = {
        "name": "결제",
        "key": "pay",
        "description": "카드 결제",
        "target": "web",
        "actor": {
            "actor_id": "11111111-1111-4111-8111-111111111111",
            "project_scope": None,
            "is_local_owner": True,
        },
    }

    async def create() -> str:
        import httpx

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            created = await client.post("/api/v1/projects", json=body, headers={"Origin":"http://127.0.0.1", "Idempotency-Key": "bulk-pay"})
            return str(created.json()["project_id"])

    project_id = asyncio.run(create())
    approved = str(uuid4())
    plain = str(uuid4())
    blocked = str(uuid4())
    approval_id = str(uuid4())
    actor = "11111111-1111-4111-8111-111111111111"
    database = root / "db" / "aiqa.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        _case(connection, project_id, approved, "승인 케이스", actor, "2020-01-01T00:00:00+00:00")
        _case(connection, project_id, plain, "초안 케이스", actor, "2020-01-02T00:00:00+00:00")
        _case(connection, project_id, blocked, "녹화 케이스", actor, "2020-01-03T00:00:00+00:00")
        connection.execute(
            """
            INSERT INTO reviews (
                project_id, review_id, case_id, case_version_id, version_hash,
                source_manifest_id, trial_case_run_id, evidence_set_hash,
                expected_current_approval_id, created_commit_seq
            ) VALUES (?, ?, ?, ?, 'hash', NULL, NULL, 'hash', NULL, 1)
            """,
            (project_id, "review-ok", approved, f"version-{approved}"),
        )
        connection.execute(
            """
            INSERT INTO approval_events (
                project_id, approval_id, case_id, case_version_id, review_id, event_kind,
                prior_approval_id, version_hash, evidence_set_hash, reason
            ) VALUES (?, ?, ?, ?, 'review-ok', 'approved', NULL, 'hash', 'hash', 'ready')
            """,
            (project_id, approval_id, approved, f"version-{approved}"),
        )
        connection.execute(
            "UPDATE automation_cases SET current_approval_id = ? WHERE case_id = ?",
            (approval_id, approved),
        )
        connection.execute(
            "UPDATE automation_cases SET latest_draft_version_id = NULL WHERE case_id = ?",
            (plain,),
        )
        connection.execute(
            """
            INSERT INTO case_open_recordings (project_id, recording_id, case_id, status)
            VALUES (?, 'rec-open', ?, 'active')
            """,
            (project_id, blocked),
        )
        before = connection.execute("SELECT COUNT(*) FROM case_versions").fetchone()
        approvals_before = connection.execute("SELECT COUNT(*) FROM approval_events").fetchone()
    assert before is not None and approvals_before is not None

    async def run() -> dict[str, object]:
        import httpx

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            issued = await client.post(
                "/api/v1/session/nonces",
                json={"origin": origin, "project_id": project_id},
                headers={"Idempotency-Key": "bulk-nonce", "Origin": origin},
            )
            booted = await client.post(
                "/api/v1/session/bootstrap",
                json={"nonce": issued.json()["nonce"]},
                headers={"Idempotency-Key": "bulk-boot", "Origin": origin},
            )
            client.cookies.set("aiqa_session", booted.cookies["aiqa_session"])
            headers = {
                "Origin": origin,
                "X-CSRF-Token": booted.json()["csrf_token"],
                "Idempotency-Key": "bulk-1",
            }
            listed = await client.get(f"/ui/projects/{project_id}/cases", headers=headers)
            single = await client.get(f"/ui/projects/{project_id}/cases/{approved}/run", headers=headers)
            review = await client.get(f"/ui/projects/{project_id}/cases/{approved}/review", headers=headers)
            chosen = await client.get(f"/ui/projects/{project_id}/cases/run?selected={approved}", headers=headers)
            bulk = await client.post(
                f"/api/v1/projects/{project_id}/cases/bulk",
                headers=headers,
                json={
                    "items": [
                        {"case_id": approved, "action": "clone", "name": "승인 복사", "expected_revision": 1},
                        {"case_id": plain, "action": "archive", "expected_revision": 1},
                        {"case_id": blocked, "action": "archive", "expected_revision": 1},
                    ]
                },
            )
            return {"listed": listed, "single": single, "review": review, "chosen": chosen, "bulk": bulk}

    pages = asyncio.run(run())
    listed = pages["listed"].text
    bulk = pages["bulk"].json()
    rows = {item["case_id"]: item for item in bulk["items"]}
    with sqlite3.connect(database) as connection:
        after = connection.execute("SELECT COUNT(*) FROM case_versions").fetchone()
        approvals_after = connection.execute("SELECT COUNT(*) FROM approval_events").fetchone()
        cloned = connection.execute(
            "SELECT current_approval_id FROM automation_cases WHERE name = ?",
            ("승인 복사",),
        ).fetchone()
        kept = connection.execute(
            "SELECT archived_at FROM automation_cases WHERE case_id = ?",
            (blocked,),
        ).fetchone()
    assert after is not None and approvals_after is not None and cloned is not None and kept is not None
    requested = {approved, plain, blocked}
    observed = {
        "silent_exclusions": len(requested - set(rows)),
        "clone_approvals": 0 if rows[approved]["approval_id"] is None and cloned[0] is None else 1,
        "history_deleted": max(0, int(before[0]) - int(after[0])) + max(0, int(approvals_before[0]) - int(approvals_after[0])),
        "blocked_rows_identified": rows[blocked]["outcome"] == "blocked" and bool(rows[blocked]["reason"]) and kept[0] is None,
    }
    assert pages["listed"].status_code == 200
    assert pages["single"].status_code == 200
    assert "이 화면은 실행을 시작하지 않습니다." in pages["single"].text
    assert pages["review"].status_code == 200
    assert "이 화면은 승인하지 않습니다." in pages["review"].text
    assert pages["chosen"].status_code == 200
    assert f"/cases/{approved}/run" in listed
    assert f"/cases/{approved}/review" in listed
    assert f"/cases/{approved}" in listed
    assert "/cases/run?selected=" in listed
    assert "/bundles?selected=" in listed
    assert "/recordings/new" in listed
    assert 'value="복제"' in listed
    assert 'value="보관"' in listed
    assert rows[plain]["outcome"] == "archived"
    assert rows[approved]["outcome"] == "cloned"
    assert observed == {
        "silent_exclusions": 0,
        "clone_approvals": 0,
        "history_deleted": 0,
        "blocked_rows_identified": True,
    }


def test_w10_06(tmp_path: Path) -> None:
    import asyncio

    from aiqa.api.app import create_app
    from aiqa.config import load_settings

    root = tmp_path / "runtime"
    settings = load_settings(
        {"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}
    )
    app = create_app(settings)
    origin = "http://127.0.0.1"
    secret = "plain-secret-not-shown"
    project_body = {
        "name": "결제",
        "key": "pay",
        "description": "카드 결제",
        "target": "web",
        "actor": {
            "actor_id": "11111111-1111-4111-8111-111111111111",
            "project_scope": None,
            "is_local_owner": True,
        },
    }

    async def run() -> dict[str, object]:
        import httpx

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            created = await client.post(
                "/api/v1/projects",
                json=project_body,
                headers={"Origin":"http://127.0.0.1", "Idempotency-Key": "def-pay"},
            )
            project_id = created.json()["project_id"]
            issued = await client.post(
                "/api/v1/session/nonces",
                json={"origin": origin, "project_id": project_id},
                headers={"Idempotency-Key": "def-nonce", "Origin": origin},
            )
            booted = await client.post(
                "/api/v1/session/bootstrap",
                json={"nonce": issued.json()["nonce"]},
                headers={"Idempotency-Key": "def-boot", "Origin": origin},
            )
            client.cookies.set("aiqa_session", booted.cookies["aiqa_session"])
            headers = {
                "Origin": origin,
                "X-CSRF-Token": booted.json()["csrf_token"],
                "Idempotency-Key": "def-case",
            }
            case = await client.post(
                f"/api/v1/projects/{project_id}/cases",
                json={"name": "결제 확인", "tc_reference": None},
                headers=headers,
            )
            case_id = case.json()["case_id"]
            headers["Idempotency-Key"] = "def-save"
            saved = await client.post(
                f"/api/v1/projects/{project_id}/cases/{case_id}/versions",
                json=_definition_body("다시 볼 문장", "", {}, None),
                headers=headers,
            )
            headers["Idempotency-Key"] = "def-stale"
            stale = await client.post(
                f"/api/v1/projects/{project_id}/cases/{case_id}/versions",
                json=_definition_body("유지되는 입력", "pay", {}, "00000000-0000-4000-8000-000000000000"),
                headers=headers,
            )
            headers["Idempotency-Key"] = "def-var"
            invalid = await client.post(
                f"/api/v1/projects/{project_id}/cases/{case_id}/versions",
                json=_definition_body("변수", "pay", {"amount": 1.1}, saved.json()["id"]),
                headers=headers,
            )
            headers["Idempotency-Key"] = "def-secret"
            leaked = await client.post(
                f"/api/v1/projects/{project_id}/cases/{case_id}/versions",
                json=_secret_body(project_id, secret, saved.json()["id"]),
                headers=headers,
            )
            page = await client.get(
                f"/ui/projects/{project_id}/cases/{case_id}/definition",
                headers=headers,
            )
            return {
                "saved": saved,
                "stale": stale,
                "invalid": invalid,
                "leaked": leaked,
                "page": page,
            }

    pages = asyncio.run(run())
    saved = pages["saved"].json()
    stale = pages["stale"].json()
    leaked = pages["leaked"].text
    page = pages["page"].text
    observed = {
        "incomplete_draft_saved": (
            pages["saved"].status_code == 201
            and saved["readiness"]["saved"] is True
            and any(item["code"] == "DEFINITION_AMBIGUOUS" for item in saved["readiness"]["reasons"])
        ),
        "formal_runnable": saved["readiness"]["formal_runnable"],
        "stale_edit_status": pages["stale"].status_code,
        "secret_echo": secret in leaked or secret in pages["stale"].text or secret in page,
    }
    assert pages["invalid"].status_code == 422
    assert stale["submitted"]["raw_text"] == "유지되는 입력"
    assert stale["server"]["version_id"] == saved["id"]
    assert stale["server"]["raw_text"] == "다시 볼 문장"
    assert "다시 볼 문장" in page
    assert "자연어" in page and "목적" in page and "기대" in page and "필수 경로" in page
    assert observed == {
        "incomplete_draft_saved": True,
        "formal_runnable": False,
        "stale_edit_status": 409,
        "secret_echo": False,
    }


def _definition_body(raw_text: str, objective: str, variables: object, expected_head: str | None) -> dict[str, object]:
    return {
        "definition": {
            "raw_text": raw_text,
            "objective": objective,
            "preconditions": [],
            "variables": variables,
            "secret_refs": {},
            "steps": [],
            "final_expected": [],
            "path_policy": {"must_use": [], "forbidden": []},
        },
        "settings": {"target_kind": "web"},
        "recorded_steps": [],
        "parent_version_id": None,
        "base_version_id": None,
        "reason": "draft",
        "expected_head": expected_head,
        "branch": False,
    }


def _secret_body(project_id: str, secret: str, expected_head: str) -> dict[str, object]:
    body = _definition_body("비밀", "pay", {}, expected_head)
    definition = body["definition"]
    assert isinstance(definition, dict)
    definition["secret_refs"] = {
        "login": {
            "project_id": "22222222-2222-4222-8222-222222222222",
            "ref_id": "33333333-3333-4333-8333-333333333333",
            "revision": 1,
            "value": secret,
        }
    }
    definition["project_id"] = project_id
    return body


def test_w10_07(tmp_path: Path) -> None:
    import asyncio
    import json
    import sqlite3
    from uuid import uuid4

    from aiqa.api.app import create_app
    from aiqa.config import load_settings

    root = tmp_path / "runtime"
    settings = load_settings(
        {"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}
    )
    app = create_app(settings)
    origin = "http://127.0.0.1"
    project_body = {
        "name": "결제",
        "key": "pay",
        "description": "카드 결제",
        "target": "web",
        "actor": {
            "actor_id": "11111111-1111-4111-8111-111111111111",
            "project_scope": None,
            "is_local_owner": True,
        },
    }
    definition = {
        "raw_text": "결제",
        "objective": "pay",
        "preconditions": [],
        "variables": {},
        "secret_refs": {},
        "steps": [
            {
                "id": "step-1",
                "instruction": "결제 누르기",
                "expected": [{"id": "check-1", "kind": "text", "expected": "완료"}],
            }
        ],
        "final_expected": [],
        "path_policy": {"must_use": [], "forbidden": []},
    }

    async def prepare() -> dict[str, str]:
        import httpx

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            created = await client.post("/api/v1/projects", json=project_body, headers={"Origin":"http://127.0.0.1", "Idempotency-Key": "step-pay"})
            project_id = created.json()["project_id"]
            issued = await client.post(
                "/api/v1/session/nonces",
                json={"origin": origin, "project_id": project_id},
                headers={"Idempotency-Key": "step-nonce", "Origin": origin},
            )
            booted = await client.post(
                "/api/v1/session/bootstrap",
                json={"nonce": issued.json()["nonce"]},
                headers={"Idempotency-Key": "step-boot", "Origin": origin},
            )
            client.cookies.set("aiqa_session", booted.cookies["aiqa_session"])
            headers = {"Origin": origin, "X-CSRF-Token": booted.json()["csrf_token"], "Idempotency-Key": "step-case"}
            case = await client.post(
                f"/api/v1/projects/{project_id}/cases",
                json={"name": "결제 확인", "tc_reference": None},
                headers=headers,
            )
            case_id = case.json()["case_id"]
            headers["Idempotency-Key"] = "step-version"
            saved = await client.post(
                f"/api/v1/projects/{project_id}/cases/{case_id}/versions",
                json={
                    "definition": definition,
                    "settings": {"target_kind": "web"},
                    "recorded_steps": [],
                    "parent_version_id": None,
                    "base_version_id": None,
                    "reason": "draft",
                    "expected_head": None,
                    "branch": False,
                },
                headers=headers,
            )
            return {
                "project_id": project_id,
                "case_id": case_id,
                "version_id": saved.json()["id"],
                "content_hash": saved.json()["content_hash"],
                "csrf": booted.json()["csrf_token"],
                "cookie": booted.cookies["aiqa_session"],
            }

    seeded = asyncio.run(prepare())
    database = root / "db" / "aiqa.sqlite"
    job_id = str(uuid4())
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO jobs (
                project_id, job_id, purpose, recording_id, case_run_id,
                payload_hash, source_refs, limits, status
            ) VALUES (?, ?, 'structure', NULL, NULL, 'hash', ?, '{}', 'queued')
            """,
            (seeded["project_id"], job_id, json.dumps([seeded["case_id"]])),
        )
        before_hash = connection.execute(
            "SELECT content_hash FROM case_versions WHERE version_id = ?",
            (seeded["version_id"],),
        ).fetchone()

    async def edit() -> dict[str, object]:
        import httpx

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            client.cookies.set("aiqa_session", seeded["cookie"])
            headers = {"Origin": origin, "X-CSRF-Token": seeded["csrf"], "Idempotency-Key": "step-copy"}
            project_id = seeded["project_id"]
            case_id = seeded["case_id"]
            copied = await client.post(
                f"/api/v1/projects/{project_id}/cases/{case_id}/step-edits",
                json={"action": "duplicate", "step_id": "step-1", "expected_head": seeded["version_id"]},
                headers=headers,
            )
            proposed = {**definition, "steps": [{**definition["steps"][0], "instruction": "제안된 단계"}]}
            common = {
                "base_version_id": copied.json()["id"],
                "base_hash": copied.json()["content_hash"],
                "body": proposed,
                "kind": "structure",
                "source_job_id": job_id,
                "tc_version_id": None,
            }
            headers["Idempotency-Key"] = "step-reject-proposal"
            rejected_proposal = await client.post(
                f"/api/v1/projects/{project_id}/cases/{case_id}/proposals",
                json=common,
                headers=headers,
            )
            with sqlite3.connect(database) as connection:
                before = connection.execute(
                    "SELECT COUNT(*) FROM case_versions WHERE case_id = ?",
                    (case_id,),
                ).fetchone()
            headers["Idempotency-Key"] = "step-reject"
            refused = await client.post(
                f"/api/v1/projects/{project_id}/cases/{case_id}/proposal-rejections",
                json={"proposal_id": rejected_proposal.json()["proposal_id"]},
                headers=headers,
            )
            with sqlite3.connect(database) as connection:
                after_reject = connection.execute(
                    "SELECT COUNT(*) FROM case_versions WHERE case_id = ?",
                    (case_id,),
                ).fetchone()
            headers["Idempotency-Key"] = "step-accept-proposal"
            accepted_proposal = await client.post(
                f"/api/v1/projects/{project_id}/cases/{case_id}/proposals",
                json=common,
                headers=headers,
            )
            page = await client.get(f"/ui/projects/{project_id}/cases/{case_id}/steps", headers=headers)
            headers["Idempotency-Key"] = "step-accept"
            accepted = await client.post(
                f"/api/v1/projects/{project_id}/cases/{case_id}/proposal-acceptances",
                json={"proposal_id": accepted_proposal.json()["proposal_id"], "expected_head": copied.json()["id"]},
                headers=headers,
            )
            with sqlite3.connect(database) as connection:
                after_accept = connection.execute(
                    "SELECT COUNT(*) FROM case_versions WHERE case_id = ?",
                    (case_id,),
                ).fetchone()
                source = connection.execute(
                    "SELECT content_hash FROM case_versions WHERE version_id = ?",
                    (seeded["version_id"],),
                ).fetchone()
            return {
                "copied": copied,
                "refused": refused,
                "accepted": accepted,
                "page": page,
                "before": before,
                "after_reject": after_reject,
                "after_accept": after_accept,
                "source": source,
            }

    result = asyncio.run(edit())
    copied = result["copied"].json()
    assert before_hash is not None
    assert result["before"] is not None and result["after_reject"] is not None
    assert result["after_accept"] is not None and result["source"] is not None
    page = result["page"].text
    observed = {
        "duplicate_step_new_id": "step-1" in copied["step_ids"] and any(item != "step-1" for item in copied["step_ids"]),
        "rejected_proposal_versions": int(result["after_reject"][0]) - int(result["before"][0]),
        "accepted_proposal_versions": int(result["after_accept"][0]) - int(result["after_reject"][0]),
        "approved_source_unchanged": result["source"][0] == before_hash[0] == seeded["content_hash"],
    }
    assert result["copied"].status_code == 201, result["copied"].text
    assert result["refused"].status_code == 200
    assert result["accepted"].status_code == 201, result["accepted"].text
    assert "결제 누르기" in page
    assert "복제" in page and "삭제" in page and "위로" in page and "아래로" in page and "변수화" in page and "추가" in page
    assert "제안은 차이를 확인한 뒤에만 수락합니다." in page
    assert "제안 차이 제안된 단계" in page
    assert "<textarea" not in page
    assert observed == {
        "duplicate_step_new_id": True,
        "rejected_proposal_versions": 0,
        "accepted_proposal_versions": 1,
        "approved_source_unchanged": True,
    }


def test_w10_08(tmp_path: Path) -> None:
    import asyncio
    import sqlite3
    from uuid import uuid4

    from aiqa.api.app import create_app
    from aiqa.config import load_settings

    root = tmp_path / "runtime"
    settings = load_settings(
        {"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}
    )
    app = create_app(settings)
    origin = "http://127.0.0.1"
    project_body = {
        "name": "결제",
        "key": "pay",
        "description": "카드 결제",
        "target": "web",
        "actor": {
            "actor_id": "11111111-1111-4111-8111-111111111111",
            "project_scope": None,
            "is_local_owner": True,
        },
    }

    def definition(text: str, objective: str) -> dict[str, object]:
        return {
            "raw_text": text,
            "objective": objective,
            "preconditions": [],
            "variables": {},
            "secret_refs": {},
            "steps": [{"id": "step-1", "instruction": text, "expected": []}],
            "final_expected": [],
            "path_policy": {"must_use": [], "forbidden": []},
        }

    async def prepare() -> dict[str, str]:
        import httpx

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            created = await client.post("/api/v1/projects", json=project_body, headers={"Origin":"http://127.0.0.1", "Idempotency-Key": "board-pay"})
            project_id = created.json()["project_id"]
            issued = await client.post(
                "/api/v1/session/nonces",
                json={"origin": origin, "project_id": project_id},
                headers={"Idempotency-Key": "board-nonce", "Origin": origin},
            )
            booted = await client.post(
                "/api/v1/session/bootstrap",
                json={"nonce": issued.json()["nonce"]},
                headers={"Idempotency-Key": "board-boot", "Origin": origin},
            )
            client.cookies.set("aiqa_session", booted.cookies["aiqa_session"])
            headers = {"Origin": origin, "X-CSRF-Token": booted.json()["csrf_token"], "Idempotency-Key": "board-case"}
            case = await client.post(
                f"/api/v1/projects/{project_id}/cases",
                json={"name": "결제 확인", "tc_reference": None},
                headers=headers,
            )
            case_id = case.json()["case_id"]
            headers["Idempotency-Key"] = "board-approved"
            approved = await client.post(
                f"/api/v1/projects/{project_id}/cases/{case_id}/versions",
                json=_version_body(definition("승인 문장", "approved")),
                headers=headers,
            )
            headers["Idempotency-Key"] = "board-draft"
            draft = await client.post(
                f"/api/v1/projects/{project_id}/cases/{case_id}/versions",
                json=_version_body(definition("새 초안", "draft"), approved.json()["id"]),
                headers=headers,
            )
            return {
                "project_id": project_id,
                "case_id": case_id,
                "approved_id": approved.json()["id"],
                "draft_id": draft.json()["id"],
                "csrf": booted.json()["csrf_token"],
                "cookie": booted.cookies["aiqa_session"],
            }

    seeded = asyncio.run(prepare())
    approval_id = str(uuid4())
    with sqlite3.connect(root / "db" / "aiqa.sqlite") as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO reviews (
                project_id, review_id, case_id, case_version_id, version_hash,
                source_manifest_id, trial_case_run_id, evidence_set_hash,
                expected_current_approval_id, created_commit_seq
            ) VALUES (?, ?, ?, ?, 'hash', NULL, NULL, 'hash', NULL, 1)
            """,
            (seeded["project_id"], str(uuid4()), seeded["case_id"], seeded["approved_id"]),
        )
        connection.execute(
            """
            INSERT INTO approval_events (
                project_id, approval_id, case_id, case_version_id, review_id, event_kind,
                prior_approval_id, version_hash, evidence_set_hash, reason
            ) VALUES (?, ?, ?, ?, ?, 'approved', NULL, 'hash', 'hash', 'ready')
            """,
            (
                seeded["project_id"],
                approval_id,
                seeded["case_id"],
                seeded["approved_id"],
                connection.execute("SELECT review_id FROM reviews").fetchone()[0],
            ),
        )
        connection.execute(
            "UPDATE automation_cases SET current_approval_id = ? WHERE case_id = ?",
            (approval_id, seeded["case_id"]),
        )
        history = connection.execute(
            "SELECT COUNT(*) FROM case_runs WHERE case_id = ?",
            (seeded["case_id"],),
        ).fetchone()

    async def read() -> dict[str, object]:
        import httpx

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            client.cookies.set("aiqa_session", seeded["cookie"])
            headers = {"Origin": origin, "X-CSRF-Token": seeded["csrf"]}
            case_id = seeded["case_id"]
            document = await client.get(f"/api/v1/cases/{case_id}", headers=headers)
            versions = await client.get(f"/api/v1/cases/{case_id}/versions", headers=headers)
            diff = await client.get(
                f"/api/v1/case-versions/{seeded['draft_id']}/diff",
                params={"base": seeded["approved_id"]},
                headers=headers,
            )
            page = await client.get(
                f"/ui/projects/{seeded['project_id']}/cases/{case_id}/definition",
                params={"tab": "versions", "version": seeded["draft_id"]},
                headers=headers,
            )
            history_page = await client.get(
                f"/ui/projects/{seeded['project_id']}/cases/{case_id}/definition",
                params={"tab": "history"},
                headers=headers,
            )
            return {
                "document": document,
                "versions": versions,
                "diff": diff,
                "page": page,
                "history_page": history_page,
            }

    result = asyncio.run(read())
    document = result["document"].json()
    diff = result["diff"].json()
    page = result["page"].text
    history_page = result["history_page"].text
    assert history is not None
    assert result["document"].status_code == 200, result["document"].text
    assert result["versions"].status_code == 200
    assert result["diff"].status_code == 200, result["diff"].text
    snapshot = page.split('id="snapshot"', 1)[1].split("</section>", 1)[0]
    observed = {
        "draft_approved_distinct": document["latest_draft_version_id"] != document["approved_version_id"]
        and document["draft_text"] != document["approved_text"]
        and diff["raw_text"]["selected"] != diff["raw_text"]["base"],
        "missing_package_reason": document["package_reason"] == "패키지가 없습니다." and "패키지가 없습니다." in page,
        "fabricated_history_rows": len(document["history"]) - int(history[0]),
        "snapshot_editable": document["snapshot_editable"] or "<input" in snapshot or "<textarea" in snapshot,
    }
    assert "최신 초안 새 초안" in page
    assert "승인본 승인 문장" in page
    assert "선택 버전 새 초안" in page
    assert "검증" in page and "단계" in page and "code" in page and "설정" in page and "실행이력" in page and "검토" in page and "버전" in page
    assert "실행 이력이 없습니다." in history_page
    assert document["revoked_approval_id"] is None
    assert len(result["versions"].json()["items"]) == 2
    assert observed == {
        "draft_approved_distinct": True,
        "missing_package_reason": True,
        "fabricated_history_rows": 0,
        "snapshot_editable": False,
    }


def test_w10_11(tmp_path: Path) -> None:
    import asyncio
    import json
    import sqlite3
    from uuid import uuid4

    from aiqa.api.app import create_app
    from aiqa.config import load_settings

    root = tmp_path / "runtime"
    settings = load_settings(
        {"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}
    )
    app = create_app(settings)
    origin = "http://127.0.0.1"
    project_body = {
        "name": "결제",
        "key": "pay",
        "description": "카드 결제",
        "target": "web",
        "actor": {
            "actor_id": "11111111-1111-4111-8111-111111111111",
            "project_scope": None,
            "is_local_owner": True,
        },
    }
    definition = {
        "raw_text": "결제",
        "objective": "pay",
        "preconditions": [],
        "variables": {},
        "secret_refs": {},
        "steps": [{"id": "step-1", "instruction": "결제 누르기", "expected": []}],
        "final_expected": [],
        "path_policy": {"must_use": [], "forbidden": []},
    }

    async def prepare() -> dict[str, str]:
        import httpx

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            created = await client.post("/api/v1/projects", json=project_body, headers={"Origin":"http://127.0.0.1", "Idempotency-Key": "set-pay"})
            project_id = created.json()["project_id"]
            issued = await client.post(
                "/api/v1/session/nonces",
                json={"origin": origin, "project_id": project_id},
                headers={"Idempotency-Key": "set-nonce", "Origin": origin},
            )
            booted = await client.post(
                "/api/v1/session/bootstrap",
                json={"nonce": issued.json()["nonce"]},
                headers={"Idempotency-Key": "set-boot", "Origin": origin},
            )
            client.cookies.set("aiqa_session", booted.cookies["aiqa_session"])
            headers = {"Origin": origin, "X-CSRF-Token": booted.json()["csrf_token"], "Idempotency-Key": "set-case"}
            case = await client.post(
                f"/api/v1/projects/{project_id}/cases",
                json={"name": "결제 확인", "tc_reference": None},
                headers=headers,
            )
            case_id = case.json()["case_id"]
            headers["Idempotency-Key"] = "set-version"
            saved = await client.post(
                f"/api/v1/projects/{project_id}/cases/{case_id}/versions",
                json=_version_body(definition),
                headers=headers,
            )
            return {
                "project_id": project_id,
                "case_id": case_id,
                "version_id": saved.json()["id"],
                "csrf": booted.json()["csrf_token"],
                "cookie": booted.cookies["aiqa_session"],
            }

    seeded = asyncio.run(prepare())
    approval_id = str(uuid4())
    review_id = str(uuid4())
    database = root / "db" / "aiqa.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO reviews (
                project_id, review_id, case_id, case_version_id, version_hash,
                source_manifest_id, trial_case_run_id, evidence_set_hash,
                expected_current_approval_id, created_commit_seq
            ) VALUES (?, ?, ?, ?, 'hash', NULL, NULL, 'hash', NULL, 1)
            """,
            (seeded["project_id"], review_id, seeded["case_id"], seeded["version_id"]),
        )
        connection.execute(
            """
            INSERT INTO approval_events (
                project_id, approval_id, case_id, case_version_id, review_id, event_kind,
                prior_approval_id, version_hash, evidence_set_hash, reason
            ) VALUES (?, ?, ?, ?, ?, 'approved', NULL, 'hash', 'hash', 'ready')
            """,
            (seeded["project_id"], approval_id, seeded["case_id"], seeded["version_id"], review_id),
        )
        connection.execute(
            "UPDATE automation_cases SET current_approval_id = ? WHERE case_id = ?",
            (approval_id, seeded["case_id"]),
        )
        approved_settings = connection.execute(
            "SELECT settings_json FROM case_versions WHERE version_id = ?",
            (seeded["version_id"],),
        ).fetchone()

    changed = {
        "target_kind": "web",
        "web_url": "https://pay.example",
        "environment_revision_id": "env-1",
        "verifier_method": "deterministic",
        "healing_policy": {
            "allowed": False,
            "default_enabled": False,
            "scope": "navigation",
            "max_episodes_per_item": 1,
            "max_model_calls_per_item": 2,
            "max_seconds": 30,
        },
    }

    async def edit() -> dict[str, object]:
        import httpx

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            client.cookies.set("aiqa_session", seeded["cookie"])
            headers = {"Origin": origin, "X-CSRF-Token": seeded["csrf"], "Idempotency-Key": "set-save"}
            project_id = seeded["project_id"]
            case_id = seeded["case_id"]
            saved = await client.post(
                f"/api/v1/projects/{project_id}/cases/{case_id}/versions",
                json=_version_body(definition, seeded["version_id"], changed),
                headers=headers,
            )
            headers["Idempotency-Key"] = "set-missing-key"
            missing = await client.post(
                f"/api/v1/projects/{project_id}/cases/{case_id}/versions",
                json=_version_body(
                    definition,
                    saved.json()["id"],
                    {**changed, "web_url": "https://keep.example", "verifier_method": "ai_visual", "verifier_binding_id": ""},
                ),
                headers=headers,
            )
            headers["Idempotency-Key"] = "set-foreign"
            foreign = await client.post(
                f"/api/v1/projects/{project_id}/cases/{case_id}/versions",
                json=_version_body(
                    definition,
                    saved.json()["id"],
                    {
                        **changed,
                        "secret_refs": {
                            "login": {
                                "project_id": "22222222-2222-4222-8222-222222222222",
                                "ref_id": "33333333-3333-4333-8333-333333333333",
                                "revision": 1,
                                "value": "plain-secret-not-shown",
                            }
                        },
                    },
                ),
                headers=headers,
            )
            page = await client.get(f"/ui/projects/{project_id}/cases/{case_id}/settings", headers=headers)
            return {"saved": saved, "missing": missing, "foreign": foreign, "page": page}

    result = asyncio.run(edit())
    saved = result["saved"].json()
    missing = result["missing"].json()
    foreign = result["foreign"]
    with sqlite3.connect(database) as connection:
        current_approved = connection.execute(
            "SELECT settings_json FROM case_versions WHERE version_id = ?",
            (seeded["version_id"],),
        ).fetchone()
        created = connection.execute(
            "SELECT settings_json, replay_package_id FROM case_versions WHERE version_id = ?",
            (saved["id"],),
        ).fetchone()
    assert approved_settings is not None and current_approved is not None and created is not None
    stored = json.loads(str(created[0]))
    page = result["page"].text
    observed = {
        "new_case_revision": result["saved"].status_code == 201 and saved["id"] != seeded["version_id"],
        "old_approval_scope_changed": current_approved[0] != approved_settings[0],
        "new_package": None if created[1] is None else str(created[1]),
        "healing_default_enabled": stored["healing_policy"]["default_enabled"],
        "field_errors_preserve_input": result["missing"].status_code == 422
        and missing["submitted"]["web_url"] == "https://keep.example",
    }
    assert result["saved"].status_code == 201, result["saved"].text
    assert foreign.status_code == 422
    assert "plain-secret-not-shown" not in foreign.text
    assert stored["healing_policy"]["allowed"] is False
    assert stored["environment_revision_id"] == "env-1"
    assert "전역 기본" in page and "기본 OFF" in page and "Web URL" in page
    assert "실행은 여기서 시작하지 않습니다." in page
    assert observed == {
        "new_case_revision": True,
        "old_approval_scope_changed": False,
        "new_package": None,
        "healing_default_enabled": False,
        "field_errors_preserve_input": True,
    }


def test_w10_10(tmp_path: Path) -> None:
    import asyncio
    import sqlite3
    from uuid import uuid4

    from aiqa.api.app import create_app
    from aiqa.config import load_settings

    root = tmp_path / "runtime"
    settings = load_settings(
        {"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}
    )
    app = create_app(settings)
    origin = "http://127.0.0.1"
    definition = {
        "raw_text": "결제",
        "objective": "pay",
        "preconditions": [],
        "variables": {},
        "secret_refs": {},
        "steps": [{"id": "step-1", "instruction": "결제 누르기", "expected": []}],
        "final_expected": [],
        "path_policy": {"must_use": [], "forbidden": []},
    }
    tc_body = {"raw_text": "결제 단계", "steps": [{"instruction": "금액 확인", "expected": "금액이 보인다"}]}

    async def project(client: object, key: str, marker: str, auth=None) -> dict[str, str]:
        created = await client.post(
            "/api/v1/projects",
            json={
                "name": "결제",
                "key": key,
                "description": "카드 결제",
                "target": "web",
                "actor": {
                    "actor_id": "11111111-1111-4111-8111-111111111111",
                    "project_scope": None,
                    "is_local_owner": True,
                },
            },
            headers={**(auth or {}), "Origin":"http://127.0.0.1", "Idempotency-Key": marker + "-pay"},
        )
        project_id = created.json()["project_id"]
        issued = await client.post(
            "/api/v1/session/nonces",
            json={"origin": origin, "project_id": project_id},
            headers={"Idempotency-Key": marker + "-nonce", "Origin": origin},
        )
        booted = await client.post(
            "/api/v1/session/bootstrap",
            json={"nonce": issued.json()["nonce"]},
            headers={"Idempotency-Key": marker + "-boot", "Origin": origin},
        )
        return {
            "project_id": project_id,
            "csrf": booted.json()["csrf_token"],
            "cookie": booted.cookies["aiqa_session"],
        }

    async def prepare() -> dict[str, str]:
        import httpx

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            first = await project(client, "pay", "tc")
            client.cookies.set("aiqa_session", first["cookie"])
            headers = {"Origin": origin, "X-CSRF-Token": first["csrf"], "Idempotency-Key": "tc-case"}
            case = await client.post(
                f"/api/v1/projects/{first['project_id']}/cases",
                json={"name": "결제 확인", "tc_reference": None},
                headers=headers,
            )
            headers["Idempotency-Key"] = "tc-version"
            saved = await client.post(
                f"/api/v1/projects/{first['project_id']}/cases/{case.json()['case_id']}/versions",
                json=_version_body(definition),
                headers=headers,
            )
            empty = await client.get(f"/ui/projects/{first['project_id']}/tcs", headers=headers)
            return {
                **first,
                "case_id": case.json()["case_id"],
                "version_id": saved.json()["id"],
                "content_hash": saved.json()["content_hash"],
                "empty": empty.text,
            }

    seeded = asyncio.run(prepare())
    review_id = str(uuid4())
    approval_id = str(uuid4())
    database = root / "db" / "aiqa.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO reviews (
                project_id, review_id, case_id, case_version_id, version_hash,
                source_manifest_id, trial_case_run_id, evidence_set_hash,
                expected_current_approval_id, created_commit_seq
            ) VALUES (?, ?, ?, ?, 'hash', NULL, NULL, 'hash', NULL, 1)
            """,
            (seeded["project_id"], review_id, seeded["case_id"], seeded["version_id"]),
        )
        connection.execute(
            """
            INSERT INTO approval_events (
                project_id, approval_id, case_id, case_version_id, review_id, event_kind,
                prior_approval_id, version_hash, evidence_set_hash, reason
            ) VALUES (?, ?, ?, ?, ?, 'approved', NULL, 'hash', 'hash', 'ready')
            """,
            (seeded["project_id"], approval_id, seeded["case_id"], seeded["version_id"], review_id),
        )
        connection.execute(
            "UPDATE automation_cases SET current_approval_id = ? WHERE case_id = ?",
            (approval_id, seeded["case_id"]),
        )

    async def exercise() -> dict[str, object]:
        import httpx

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            client.cookies.set("aiqa_session", seeded["cookie"])
            headers = {"Origin": origin, "X-CSRF-Token": seeded["csrf"], "Idempotency-Key": "tc-doc"}
            project_id = seeded["project_id"]
            created = await client.post(
                f"/api/v1/projects/{project_id}/tcs",
                json={"name": "결제 TC", "reason": "draft", "body": tc_body},
                headers=headers,
            )
            version_id = created.json()["id"]
            headers["Idempotency-Key"] = "tc-link"
            linked = await client.put(
                f"/api/v1/projects/{project_id}/cases/{seeded['case_id']}/tc-reference",
                json={"tc_version_id": version_id},
                headers=headers,
            )
            headers["Idempotency-Key"] = "tc-clear"
            cleared = await client.delete(
                f"/api/v1/projects/{project_id}/cases/{seeded['case_id']}/tc-reference",
                headers=headers,
            )
            headers["Idempotency-Key"] = "tc-import"
            proposal = await client.post(
                f"/api/v1/projects/{project_id}/cases/{seeded['case_id']}/tc-import-proposals",
                json={
                    "base_version_id": seeded["version_id"],
                    "base_hash": seeded["content_hash"],
                    "body": definition,
                    "source_job_id": None,
                    "tc_version_id": version_id,
                },
                headers=headers,
            )
            headers["Idempotency-Key"] = "tc-accept"
            accepted = await client.post(
                f"/api/v1/projects/{project_id}/cases/{seeded['case_id']}/proposal-acceptances",
                json={"proposal_id": proposal.json()["proposal_id"], "expected_head": seeded["version_id"]},
                headers=headers,
            )
            headers["Idempotency-Key"] = "tc-edit"
            edited = await client.post(
                f"/api/v1/projects/{project_id}/tcs/{created.json()['tc_id']}/versions",
                json={"name": "결제 TC", "reason": "edit", "body": tc_body},
                headers=headers,
            )
            headers["Idempotency-Key"] = "tc-archive"
            archived = await client.post(
                f"/api/v1/projects/{project_id}/tcs/{created.json()['tc_id']}/archive",
                headers=headers,
            )
            headers["Idempotency-Key"] = "tc-reject-proposal"
            declined = await client.post(
                f"/api/v1/projects/{project_id}/cases/{seeded['case_id']}/tc-import-proposals",
                json={
                    "base_version_id": accepted.json()["id"],
                    "base_hash": accepted.json()["content_hash"],
                    "body": definition,
                    "source_job_id": None,
                    "tc_version_id": version_id,
                },
                headers=headers,
            )
            headers["Idempotency-Key"] = "tc-reject"
            turned_down = await client.post(
                f"/api/v1/projects/{project_id}/cases/{seeded['case_id']}/proposal-rejections",
                json={"proposal_id": declined.json()["proposal_id"]},
                headers=headers,
            )
            other = await project(client, "other", "foreign", headers)
            client.cookies.clear()
            client.cookies.set("aiqa_session", other["cookie"])
            foreign_headers = {"Origin": origin, "X-CSRF-Token": other["csrf"], "Idempotency-Key": "foreign-tc"}
            foreign_tc = await client.post(
                f"/api/v1/projects/{other['project_id']}/tcs",
                json={"name": "다른 TC", "reason": "draft", "body": tc_body},
                headers=foreign_headers,
            )
            client.cookies.clear()
            client.cookies.set("aiqa_session", seeded["cookie"])
            headers["Idempotency-Key"] = "tc-cross"
            denied = await client.put(
                f"/api/v1/projects/{project_id}/cases/{seeded['case_id']}/tc-reference",
                json={"tc_version_id": foreign_tc.json()["id"]},
                headers=headers,
            )
            return {
                "created": created,
                "linked": linked,
                "cleared": cleared,
                "proposal": proposal,
                "accepted": accepted,
                "denied": denied,
                "foreign_tc": foreign_tc,
                "edited": edited,
                "archived": archived,
                "turned_down": turned_down,
            }

    result = asyncio.run(exercise())
    with sqlite3.connect(database) as connection:
        approved = connection.execute(
            "SELECT current_approval_id, content_hash FROM automation_cases JOIN case_versions ON case_versions.version_id = ?",
            (seeded["version_id"],),
        ).fetchone()
        source = connection.execute(
            "SELECT content_hash FROM case_versions WHERE version_id = ?",
            (seeded["version_id"],),
        ).fetchone()
    assert approved is not None and source is not None
    accepted = result["accepted"].json()
    assert result["linked"].status_code == 200, result["linked"].text
    assert result["cleared"].status_code == 200, result["cleared"].text
    observed = {
        "tc_required": "필수 TC" in seeded["empty"],
        "reference_changes_approval": str(approved[0]) != approval_id or source[0] != seeded["content_hash"],
        "import_accept_new_version": result["accepted"].status_code == 201 and accepted["id"] != seeded["version_id"],
        "cross_project_tc_denied": result["denied"].status_code == 404,
    }
    assert result["created"].status_code == 201, result["created"].text
    assert result["proposal"].status_code == 201, result["proposal"].text
    assert result["denied"].status_code == 404, result["denied"].text
    assert result["edited"].status_code == 201, result["edited"].text
    assert result["archived"].status_code == 200 and result["archived"].json()["archived_at"] is not None
    assert result["turned_down"].status_code == 200 and result["turned_down"].json()["produced_version_id"] is None
    assert result["foreign_tc"].status_code == 201, result["foreign_tc"].text
    assert "TC 없이도 케이스를 둘 수 있습니다." in seeded["empty"]
    assert "선택 TC가 없습니다." in seeded["empty"]
    assert "가져오기는 차이를 확인한 뒤에만 수락합니다." in seeded["empty"]
    assert observed == {
        "tc_required": False,
        "reference_changes_approval": False,
        "import_accept_new_version": True,
        "cross_project_tc_denied": True,
    }


def test_w10_09(tmp_path: Path) -> None:
    import asyncio
    import sqlite3
    from uuid import uuid4

    from aiqa.api.app import create_app
    from aiqa.config import load_settings

    root = tmp_path / "runtime"
    settings = load_settings(
        {"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}
    )
    app = create_app(settings)
    origin = "http://127.0.0.1"
    project_body = {
        "name": "결제",
        "key": "pay",
        "description": "카드 결제",
        "target": "web",
        "actor": {
            "actor_id": "11111111-1111-4111-8111-111111111111",
            "project_scope": None,
            "is_local_owner": True,
        },
    }
    definition = {
        "raw_text": "결제",
        "objective": "pay",
        "preconditions": [],
        "variables": {},
        "secret_refs": {},
        "steps": [{"id": "step-1", "instruction": "결제 누르기", "expected": []}],
        "final_expected": [],
        "path_policy": {"must_use": [], "forbidden": []},
    }
    secret_value = "one-time-key-not-shown"
    prompt = "sha256:" + ("ab" * 32)

    async def prepare() -> dict[str, str]:
        import httpx

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            created = await client.post("/api/v1/projects", json=project_body, headers={"Origin":"http://127.0.0.1", "Idempotency-Key": "cfg-pay"})
            project_id = created.json()["project_id"]
            issued = await client.post(
                "/api/v1/session/nonces",
                json={"origin": origin, "project_id": project_id},
                headers={"Idempotency-Key": "cfg-nonce", "Origin": origin},
            )
            booted = await client.post(
                "/api/v1/session/bootstrap",
                json={"nonce": issued.json()["nonce"]},
                headers={"Idempotency-Key": "cfg-boot", "Origin": origin},
            )
            client.cookies.set("aiqa_session", booted.cookies["aiqa_session"])
            headers = {"Origin": origin, "X-CSRF-Token": booted.json()["csrf_token"], "Idempotency-Key": "cfg-case"}
            case = await client.post(
                f"/api/v1/projects/{project_id}/cases",
                json={"name": "결제 확인", "tc_reference": None},
                headers=headers,
            )
            headers["Idempotency-Key"] = "cfg-version"
            saved = await client.post(
                f"/api/v1/projects/{project_id}/cases/{case.json()['case_id']}/versions",
                json=_version_body(definition),
                headers=headers,
            )
            return {
                "project_id": project_id,
                "case_id": case.json()["case_id"],
                "version_id": saved.json()["id"],
                "csrf": booted.json()["csrf_token"],
                "cookie": booted.cookies["aiqa_session"],
            }

    seeded = asyncio.run(prepare())
    review_id = str(uuid4())
    approval_id = str(uuid4())
    database = root / "db" / "aiqa.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO reviews (
                project_id, review_id, case_id, case_version_id, version_hash,
                source_manifest_id, trial_case_run_id, evidence_set_hash,
                expected_current_approval_id, created_commit_seq
            ) VALUES (?, ?, ?, ?, 'hash', NULL, NULL, 'hash', NULL, 1)
            """,
            (seeded["project_id"], review_id, seeded["case_id"], seeded["version_id"]),
        )
        connection.execute(
            """
            INSERT INTO approval_events (
                project_id, approval_id, case_id, case_version_id, review_id, event_kind,
                prior_approval_id, version_hash, evidence_set_hash, reason
            ) VALUES (?, ?, ?, ?, ?, 'approved', NULL, 'hash', 'hash', 'ready')
            """,
            (seeded["project_id"], approval_id, seeded["case_id"], seeded["version_id"], review_id),
        )
        connection.execute(
            "UPDATE automation_cases SET current_approval_id = ? WHERE case_id = ?",
            (approval_id, seeded["case_id"]),
        )
        approved = connection.execute(
            "SELECT settings_json FROM case_versions WHERE version_id = ?",
            (seeded["version_id"],),
        ).fetchone()

    async def configure() -> dict[str, object]:
        import httpx

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            client.cookies.set("aiqa_session", seeded["cookie"])
            headers = {"Origin": origin, "X-CSRF-Token": seeded["csrf"], "Idempotency-Key": "cfg-secret"}
            project_id = seeded["project_id"]
            secret = await client.post(
                f"/api/v1/projects/{project_id}/secret-refs",
                json={"name": "model-key", "value": secret_value},
                headers=headers,
            )
            ref = secret.json()
            created_bindings = []
            for role, model in (("authoring", "author-model"), ("verification", "verify-model")):
                headers["Idempotency-Key"] = f"cfg-{role}"
                created_bindings.append(
                    await client.post(
                        "/api/v1/model-bindings",
                        json={
                            "project_id": project_id,
                            "name": role,
                            "role": role,
                            "provider": "local",
                            "endpoint_kind": "https",
                            "endpoint": f"https://{role}.example",
                            "model": model,
                            "key_ref": {"project_id": project_id, "ref_id": ref["ref_id"], "revision": ref["revision"]},
                            "prompt_hash": prompt,
                            "tariff_id": "t1",
                            "compatibility_status": "unchecked",
                        },
                        headers=headers,
                    )
                )
            headers["Idempotency-Key"] = "cfg-read-secret"
            reread = await client.get(f"/api/v1/projects/{project_id}/secret-refs/{ref['ref_id']}", headers=headers)
            headers["Idempotency-Key"] = "cfg-settings"
            saved = await client.patch(
                f"/api/v1/projects/{project_id}/settings",
                json={"expected_lock": 0, "failure_policy": "stop_on_non_pass", "retention": "default", "timeout_seconds": 600, "healing_scope": "navigation"},
                headers=headers,
            )
            headers["Idempotency-Key"] = "cfg-stale"
            stale = await client.patch(
                f"/api/v1/projects/{project_id}/settings",
                json={"expected_lock": 0, "failure_policy": "continue", "healing_scope": "navigation"},
                headers=headers,
            )
            headers["Idempotency-Key"] = "cfg-expand"
            expanded = await client.patch(
                f"/api/v1/projects/{project_id}/settings",
                json={"expected_lock": 1, "expand_approved_case_id": seeded["case_id"], "healing_scope": "navigation,replay"},
                headers=headers,
            )
            page = await client.get(f"/ui/projects/{project_id}/settings", headers=headers)
            listed = await client.get(f"/api/v1/projects/{project_id}/settings", headers=headers)
            return {
                "secret": secret,
                "reread": reread,
                "bindings": created_bindings,
                "saved": saved,
                "stale": stale,
                "expanded": expanded,
                "page": page,
                "listed": listed,
            }

    result = asyncio.run(configure())
    with sqlite3.connect(database) as connection:
        current = connection.execute(
            "SELECT settings_json FROM case_versions WHERE version_id = ?",
            (seeded["version_id"],),
        ).fetchone()
    assert approved is not None and current is not None
    bindings = [item.json() for item in result["bindings"]]
    texts = result["secret"].text + result["reread"].text + result["listed"].text + "".join(item.text for item in result["bindings"])
    page = result["page"].text
    observed = {
        "role_bindings_separate": result["bindings"][0].status_code == 201
        and result["bindings"][1].status_code == 201
        and bindings[0]["binding_id"] != bindings[1]["binding_id"]
        and bindings[0]["role"] != bindings[1]["role"]
        and bindings[0]["model"] != bindings[1]["model"],
        "read_secret_plaintext": secret_value in texts,
        "browser_saved_key": "localStorage" in page or secret_value in page,
        "old_approval_expanded": current[0] != approved[0] or result["expanded"].status_code == 200,
    }
    assert result["secret"].status_code == 201, result["secret"].text
    assert result["saved"].status_code == 200, result["saved"].text
    assert result["stale"].status_code == 409
    assert result["expanded"].status_code == 422
    assert "authoring" in page and "verification" in page and "healing" in page and "maintenance" in page
    assert "키는 한 번 입력한 뒤 비웁니다." in page
    assert observed == {
        "role_bindings_separate": True,
        "read_secret_plaintext": False,
        "browser_saved_key": False,
        "old_approval_expanded": False,
    }


def _version_body(
    definition: dict[str, object],
    expected_head: str | None = None,
    settings: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "definition": definition,
        "settings": {"target_kind": "web"} if settings is None else settings,
        "recorded_steps": [],
        "parent_version_id": None,
        "base_version_id": None,
        "reason": "draft",
        "expected_head": expected_head,
        "branch": False,
    }


async def _read(app: object, query: str) -> dict[str, object]:
    import httpx

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        listed = await client.get(f"/ui/shell?{query}")
        detail = await client.get(f"/ui/shell/items/item-1?{query}")
        again = await client.get(f"/ui/shell?{query}")
        invalid = await client.get("/ui/shell?notice=invalid")
        forbidden = await client.get("/ui/shell?notice=forbidden")
        conflict = await client.get("/ui/shell?notice=conflict")
        stale = await client.get("/ui/shell?notice=stale")
        script = await client.get("/static/navigation.js")
        style = await client.get("/static/app.css")
        home = await client.get("/")
    return {
        "list": listed,
        "detail": detail,
        "reload": again,
        "invalid": invalid,
        "forbidden": forbidden,
        "conflict": conflict,
        "stale": stale,
        "script": script,
        "style": style,
        "home": home,
    }


async def _ui_session(client,project_id,key):
    origin='http://127.0.0.1'
    nonce=await client.post('/api/v1/session/nonces',json={'origin':origin,'project_id':project_id},headers={'Origin':origin,'Idempotency-Key':key+'-nonce'})
    boot=await client.post('/api/v1/session/bootstrap',json={'nonce':nonce.json()['nonce']},headers={'Origin':origin,'Idempotency-Key':key+'-bootstrap'})
    assert boot.status_code==201,boot.text
    return {'cookie':boot.cookies['aiqa_session'],'headers':{'Origin':origin,'X-CSRF-Token':boot.json()['csrf_token']}}
