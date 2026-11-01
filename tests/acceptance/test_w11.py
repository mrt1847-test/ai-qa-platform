"""W11-01: resource list and redacted preview. No device is opened."""

from __future__ import annotations

from pathlib import Path


def test_w11_08(tmp_path: Path) -> None:
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
        home = create_project(owner, ProjectCreate("이력", "w1108a", "조회", "web"))
        other = create_project(owner, ProjectCreate("다른", "w1108b", "조회", "web"))
    store.close()
    with sqlite3.connect(root / "db" / "aiqa.sqlite") as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        for project_id, audit_id, action in (
            (home.project_id, "audit-1", "case"),
            (home.project_id, "audit-2", "environment"),
            (other.project_id, "audit-foreign", "case"),
        ):
            connection.execute(
                """
                INSERT INTO project_audits (project_id, audit_id, commit_seq, actor_id, action, created_at)
                VALUES (?, ?, 1, ?, ?, '2026-11-01T00:00:00+00:00')
                """,
                (str(project_id), audit_id, str(owner.actor_id), action),
            )
            connection.execute(
                """
                INSERT INTO project_audit_links (project_id, audit_id, note, commit_seq)
                VALUES (?, ?, '변경', 1)
                """,
                (str(project_id), audit_id),
            )
    page, listed, stored, claim = asyncio.run(_activity(app, home.project_id))
    foreign = [item for item in listed if item["project_id"] != str(home.project_id)]
    observed = {
        "foreign_audit_rows": len(foreign),
        "revoked_worker_can_claim": claim == 200,
        "protected_space_visible": "보호 공간" in page.text and "protected_bytes" in stored,
    }
    assert page.status_code == 200
    assert "빈 공간" in page.text and "한도 안" in page.text
    assert "<button" not in page.text and "PASS" not in page.text
    assert observed == {
        "foreign_audit_rows": 0,
        "revoked_worker_can_claim": False,
        "protected_space_visible": True,
    }


def test_w11_07(tmp_path: Path) -> None:
    import asyncio
    from uuid import uuid4

    from aiqa.api.app import create_app
    from aiqa.api.auth import bound_auth_store, enroll_worker
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
        project = create_project(owner, ProjectCreate("진단", "w1107", "환경", "web"))
    worker = str(uuid4())
    with bound_auth_store(store):
        token = enroll_worker(Actor(owner.actor_id, project.project_id, True), worker, "resource_probe")
    store.close()
    page, probe, recovery = asyncio.run(_diagnose(app, project.project_id, token))
    text = page.text
    observed = {
        "vm_missing_web_ready": probe.json()["ready"],
        "recovery_requires_proof": recovery.status_code == 422,
        "unsupported_buttons": text.count("cloud") + text.count("manualcontrol") + text.count("pause"),
        "diagnostic_qa": probe.json()["qa"],
    }
    assert page.status_code == 200
    assert "진단 작업" in text and "proof 없음" in text
    assert "키와 외부 전송은 막혀 있습니다." in text
    assert "<button" not in text and "PASS" not in text
    assert observed == {
        "vm_missing_web_ready": False,
        "recovery_requires_proof": True,
        "unsupported_buttons": 0,
        "diagnostic_qa": None,
    }


def test_w11_05(tmp_path: Path) -> None:
    import asyncio
    import base64
    import io
    import zipfile
    from uuid import uuid4

    from aiqa.api.app import create_app
    from aiqa.config import load_settings
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.environments.app_builds import ApkRejected, code_executions, inspect_apk, register_app_build
    from aiqa.environments.app_builds import ApkInspectionSpec
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
        project = create_project(owner, ProjectCreate("앱", "w1105", "등록", "android"))
    store.close()
    body = _zip({"AndroidManifest.xml": b"manifest"})
    spec = ApkInspectionSpec(project.project_id, "app.apk", body, len(body))
    missing = inspect_apk(spec, tool_path=None)
    split_rejected = False
    traversal_rejected = False
    try:
        inspect_apk(ApkInspectionSpec(project.project_id, "bundle.apks", body, len(body)), tool_path=None)
    except ApkRejected:
        split_rejected = True
    try:
        inspect_apk(ApkInspectionSpec(project.project_id, "app.apk", _zip({"../evil.xml": b"x"}), 16), tool_path=None)
    except ApkRejected:
        traversal_rejected = True
    first, _ = register_app_build(spec, tool_path=None)
    second, _ = register_app_build(spec, tool_path=None)
    page = asyncio.run(_apk_page(app, project.project_id, body))
    observed = {
        "split_rejected": split_rejected,
        "traversal_rejected": traversal_rejected,
        "tool_missing_ready": missing.ready,
        "uploaded_code_executed": code_executions != 0,
    }
    assert second.replayed is True and second.job_id == first.job_id
    assert page.status_code == 200
    assert "분석 도구가 없어 등록할 수 없습니다." in page.text
    assert "앱 코드는 실행하지 않습니다." in page.text
    assert "<button" not in page.text and "PASS" not in page.text
    assert observed == {
        "split_rejected": True,
        "traversal_rejected": True,
        "tool_missing_ready": False,
        "uploaded_code_executed": False,
    }


async def _activity(app: object, project_id: object):
    import httpx
    from uuid import UUID, uuid4

    assert isinstance(project_id, UUID)
    transport = httpx.ASGITransport(app=app)
    origin = "http://127.0.0.1"
    async with httpx.AsyncClient(transport=transport, base_url=origin) as client:
        issued = await client.post(
            "/api/v1/session/nonces",
            json={"origin": origin, "project_id": str(project_id)},
            headers={"Idempotency-Key": "w1108-nonce", "Origin": origin},
        )
        booted = await client.post(
            "/api/v1/session/bootstrap",
            json={"nonce": issued.json()["nonce"]},
            headers={"Idempotency-Key": "w1108-boot", "Origin": origin},
        )
        client.cookies.set("aiqa_session", booted.cookies["aiqa_session"])
        headers = {"Origin": origin, "X-CSRF-Token": booted.json()["csrf_token"]}
        denied = await client.get(f"/api/v1/projects/{project_id}/audit")
        assert denied.status_code == 403
        first = await client.get(f"/api/v1/projects/{project_id}/audit", params={"limit": 1}, headers=headers)
        assert first.status_code == 200, first.text
        assert first.json()["next_cursor"]
        second = await client.get(
            f"/api/v1/projects/{project_id}/audit",
            params={"limit": 1, "cursor": first.json()["next_cursor"]},
            headers=headers,
        )
        listed = first.json()["items"] + second.json()["items"]
        headers["Idempotency-Key"] = "w1108-enroll"
        enrolled = await client.post(
            f"/api/v1/projects/{project_id}/worker-enrollments",
            json={"worker_id": str(uuid4()), "purpose": "resource_probe"},
            headers=headers,
        )
        assert enrolled.status_code == 201, enrolled.text
        credential = enrolled.json()["credential"]
        claimed = await client.post(
            "/api/v1/worker/inventory",
            headers={"Authorization": f"Bearer {credential}", "Idempotency-Key": "w1108-claim"},
            json={
                "project_id": str(project_id),
                "native_id": "web-w1108",
                "target_kind": "web",
                "state": "offline",
                "os_build": "build-1",
                "geometry": "100x100",
                "permissions": "[]",
                "ime": "none",
                "observed_at": "2026-11-01T00:00:00+00:00",
                "display_name": "조회 웹",
                "raw_handle": None,
            },
        )
        assert claimed.status_code == 200, claimed.text
        headers["Idempotency-Key"] = "w1108-revoke"
        revoked = await client.post(
            f"/api/v1/workers/{enrolled.json()['worker_id']}/revoke",
            json={"project_id": str(project_id)},
            headers=headers,
        )
        assert revoked.status_code == 200, revoked.text
        again = await client.post(
            "/api/v1/worker/inventory",
            headers={"Authorization": f"Bearer {credential}", "Idempotency-Key": "w1108-claim-2"},
            json={
                "project_id": str(project_id),
                "native_id": "web-w1108",
                "target_kind": "web",
                "state": "ready",
                "os_build": "build-1",
                "geometry": "100x100",
                "permissions": "[]",
                "ime": "none",
                "observed_at": "2026-11-01T00:00:00+00:00",
                "display_name": "조회 웹",
                "raw_handle": None,
            },
        )
        stored = await client.get(f"/api/v1/projects/{project_id}/storage", headers=headers)
        page = await client.get(f"/ui/projects/{project_id}/settings")
    return page, listed, stored.text, again.status_code


async def _diagnose(app: object, project_id: object, token: str):
    import httpx
    from uuid import UUID

    assert isinstance(project_id, UUID)
    transport = httpx.ASGITransport(app=app)
    origin = "http://127.0.0.1"
    async with httpx.AsyncClient(transport=transport, base_url=origin) as client:
        reported = await client.post(
            "/api/v1/worker/inventory",
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "w1107-web"},
            json={
                "project_id": str(project_id),
                "native_id": "web-w1107",
                "target_kind": "web",
                "state": "offline",
                "os_build": "build-1",
                "geometry": "1280x720",
                "permissions": "[]",
                "ime": "none",
                "observed_at": "2026-11-01T00:00:00+00:00",
                "display_name": "진단 웹",
                "raw_handle": None,
            },
        )
        assert reported.status_code == 200, reported.text
        resource_id = reported.json()["physical_key_id"]
        issued = await client.post(
            "/api/v1/session/nonces",
            json={"origin": origin, "project_id": str(project_id)},
            headers={"Idempotency-Key": "w1107-nonce", "Origin": origin},
        )
        booted = await client.post(
            "/api/v1/session/bootstrap",
            json={"nonce": issued.json()["nonce"]},
            headers={"Idempotency-Key": "w1107-boot", "Origin": origin},
        )
        client.cookies.set("aiqa_session", booted.cookies["aiqa_session"])
        headers = {"Origin": origin, "X-CSRF-Token": booted.json()["csrf_token"], "Idempotency-Key": "w1107-probe"}
        probe = await client.post(
            f"/api/v1/resources/{resource_id}/probes",
            params={"project_id": str(project_id)},
            json={"provider": "fixture", "proof": None},
            headers=headers,
        )
        assert probe.status_code == 201, probe.text
        headers["Idempotency-Key"] = "w1107-recovery"
        recovery = await client.post(
            f"/api/v1/resources/{resource_id}/recoveries",
            params={"project_id": str(project_id)},
            json={"provider": "fixture", "proof": None},
            headers=headers,
        )
        headers["Idempotency-Key"] = "w1107-production"
        blocked = await client.post(
            f"/api/v1/resources/{resource_id}/probes",
            params={"project_id": str(project_id)},
            json={"provider": "production", "proof": None},
            headers=headers,
        )
        assert blocked.status_code == 422, blocked.text
        page = await client.get(f"/ui/projects/{project_id}/environments")
    return page, probe, recovery


def _zip(entries: dict[str, bytes]) -> bytes:
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


async def _apk_page(app: object, project_id: object, body: bytes):
    import base64
    import httpx
    from uuid import UUID

    assert isinstance(project_id, UUID)
    transport = httpx.ASGITransport(app=app)
    origin = "http://127.0.0.1"
    async with httpx.AsyncClient(transport=transport, base_url=origin) as client:
        issued = await client.post(
            "/api/v1/session/nonces",
            json={"origin": origin, "project_id": str(project_id)},
            headers={"Idempotency-Key": "w1105-nonce", "Origin": origin},
        )
        booted = await client.post(
            "/api/v1/session/bootstrap",
            json={"nonce": issued.json()["nonce"]},
            headers={"Idempotency-Key": "w1105-boot", "Origin": origin},
        )
        client.cookies.set("aiqa_session", booted.cookies["aiqa_session"])
        headers = {"Origin": origin, "X-CSRF-Token": booted.json()["csrf_token"], "Idempotency-Key": "w1105-apk"}
        posted = await client.post(
            f"/api/v1/projects/{project_id}/app-builds",
            json={"filename": "app.apk", "body_base64": base64.b64encode(body).decode("ascii"), "declared_length": len(body)},
            headers=headers,
        )
        assert posted.status_code == 201, posted.text
        assert posted.json()["ready"] is False
        return await client.get(f"/ui/projects/{project_id}/app-builds")


def test_w11_03(tmp_path: Path) -> None:
    import asyncio
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
        project = create_project(owner, ProjectCreate("데이터", "w1103", "행", "web"))
    store.close()
    page, invalid, duplicate, stored, listed = asyncio.run(_rows(app, project.project_id))
    secret = "hidden-dataset-plain"
    combined = page.text + invalid.text + duplicate.text + stored.text + listed.text
    observed = {
        "invalid_row_status": invalid.status_code,
        "duplicate_row_id_rejected": duplicate.status_code == 422,
        "old_run_values_unchanged": stored.json()["rows"][0]["values"]["amount"] == "1000",
        "secret_plaintext_returned": secret in combined,
    }
    assert page.status_code == 200
    assert "row-1 값이 바뀌었습니다." in page.text
    assert "연결 케이스" in page.text
    assert "<button" not in page.text and "PASS" not in page.text
    assert observed == {
        "invalid_row_status": 422,
        "duplicate_row_id_rejected": True,
        "old_run_values_unchanged": True,
        "secret_plaintext_returned": False,
    }


def test_w11_02(tmp_path: Path) -> None:
    import asyncio
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
        project = create_project(owner, ProjectCreate("환경", "w1102", "편집", "web"))
    store.close()
    page, outside, bad_package, old_hash, reread = asyncio.run(_edit(app, project.project_id))
    text = page.text
    observed = {
        "out_of_scope_blocked": outside.status_code == 422 and bad_package.status_code == 422,
        "unsupported_selectable": any(name in text for name in ("multitab", "rotation", 'name="file"')),
        "old_snapshot_unchanged": old_hash == reread,
    }
    assert page.status_code == 200
    assert 'value="1280"' in text and 'value="720"' in text
    assert 'value="ko-KR"' in text and 'value="Asia/Seoul"' in text
    assert 'value="portrait"' in text
    assert "<button" not in text and "PASS" not in text
    assert observed == {
        "out_of_scope_blocked": True,
        "unsupported_selectable": False,
        "old_snapshot_unchanged": True,
    }


def test_w11_01(tmp_path: Path) -> None:
    import asyncio
    from uuid import uuid4

    import httpx

    from aiqa.api.app import create_app
    from aiqa.api.auth import bound_auth_store, enroll_worker
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
        project = create_project(owner, ProjectCreate("자원", "w1101", "목록", "web"))
    worker = str(uuid4())
    with bound_auth_store(store):
        token = enroll_worker(Actor(owner.actor_id, project.project_id, True), worker, "resource_probe")
    store.close()
    page, preview_denied, preview = asyncio.run(_read(app, project.project_id, token))
    text = page.text
    observed = {
        "management_tab_is_test_browser": "테스트 브라우저" in text or 'data-tab="resources"' not in text,
        "stale_timestamp_visible": "2020-01-01T00:00:00+00:00" in text,
        "unauthorized_preview_denied": preview_denied.status_code == 403,
        "preview_raw_control": bool(preview.json()["raw_control"]),
    }
    assert page.status_code == 200
    assert "Web" in text and "Android" in text
    assert "사용 중" in text and "점유 실행" in text
    assert "권한이 없습니다." in text
    assert "보관 기한이 지났습니다." in text
    assert "아직 관찰이 없습니다." in text
    assert "사용할 수 없음" in text
    assert "<button" not in text and "PASS" not in text
    assert preview.status_code == 200
    assert preview.json()["reason"] == "expired"
    assert observed == {
        "management_tab_is_test_browser": False,
        "stale_timestamp_visible": True,
        "unauthorized_preview_denied": True,
        "preview_raw_control": False,
    }


async def _read(app: object, project_id: object, token: str) -> tuple[object, object, object]:
    from uuid import UUID

    assert isinstance(project_id, UUID)
    import httpx
    transport = httpx.ASGITransport(app=app)
    origin = "http://127.0.0.1"
    async with httpx.AsyncClient(transport=transport, base_url=origin) as client:
        for native_id, kind, state, observed_at, name in (
            ("web-w1101", "web", "ready", "2020-01-01T00:00:00+00:00", "오래된 웹"),
            ("and-busy-w1101", "android", "busy", "2026-11-01T00:00:00+00:00", "사용 중인 폰"),
            ("and-auth-w1101", "android", "unauthorized", "2026-11-01T00:00:00+00:00", "권한 없는 폰"),
        ):
            reported = await client.post(
                "/api/v1/worker/inventory",
                headers={"Authorization": f"Bearer {token}", "Idempotency-Key": native_id},
                json={
                    "project_id": str(project_id),
                    "native_id": native_id,
                    "target_kind": kind,
                    "state": state,
                    "os_build": "build-1",
                    "geometry": "100x200",
                    "permissions": "[]",
                    "ime": "none",
                    "observed_at": observed_at,
                    "display_name": name,
                    "raw_handle": None,
                },
            )
            assert reported.status_code == 200, reported.text
        issued = await client.post(
            "/api/v1/session/nonces",
            json={"origin": origin, "project_id": str(project_id)},
            headers={"Idempotency-Key": "w1101-nonce", "Origin": origin},
        )
        booted = await client.post(
            "/api/v1/session/bootstrap",
            json={"nonce": issued.json()["nonce"]},
            headers={"Idempotency-Key": "w1101-boot", "Origin": origin},
        )
        client.cookies.set("aiqa_session", booted.cookies["aiqa_session"])
        headers = {"Origin": origin, "X-CSRF-Token": booted.json()["csrf_token"]}
        page = await client.get(f"/ui/projects/{project_id}/environments")
        listed = await client.get(f"/api/v1/projects/{project_id}/resources", headers=headers)
        rows = {item["display_name"]: item["resource_id"] for item in listed.json()["resources"]}
        denied = await client.get(
            f"/api/v1/resources/{rows['권한 없는 폰']}/preview",
            params={"project_id": str(project_id)},
            headers=headers,
        )
        opened = await client.get(
            f"/api/v1/resources/{rows['오래된 웹']}/preview",
            params={"project_id": str(project_id)},
            headers=headers,
        )
    return page, denied, opened


async def _edit(app: object, project_id: object) -> tuple[object, object, object, str, str]:
    import httpx
    from uuid import UUID

    assert isinstance(project_id, UUID)
    transport = httpx.ASGITransport(app=app)
    origin = "http://127.0.0.1"
    async with httpx.AsyncClient(transport=transport, base_url=origin) as client:
        issued = await client.post(
            "/api/v1/session/nonces",
            json={"origin": origin, "project_id": str(project_id)},
            headers={"Idempotency-Key": "w1102-nonce", "Origin": origin},
        )
        booted = await client.post(
            "/api/v1/session/bootstrap",
            json={"nonce": issued.json()["nonce"]},
            headers={"Idempotency-Key": "w1102-boot", "Origin": origin},
        )
        client.cookies.set("aiqa_session", booted.cookies["aiqa_session"])
        headers = {"Origin": origin, "X-CSRF-Token": booted.json()["csrf_token"], "Idempotency-Key": "w1102-web"}
        page = await client.get(f"/ui/projects/{project_id}/environments/editor")
        created = await client.post(
            f"/api/v1/projects/{project_id}/environments",
            json=_web("https://shop.example"),
            headers=headers,
        )
        assert created.status_code == 201, created.text
        environment_id = created.json()["environment_id"]
        headers["Idempotency-Key"] = "w1102-outside"
        outside = await client.post(
            f"/api/v1/environments/{environment_id}/versions",
            json={**_web("https://evil.example"), "project_id": str(project_id)},
            headers=headers,
        )
        headers["Idempotency-Key"] = "w1102-package"
        bad_package = await client.post(
            f"/api/v1/projects/{project_id}/environments",
            json=_android("not a package"),
            headers=headers,
        )
        headers["Idempotency-Key"] = "w1102-next"
        revised = await client.post(
            f"/api/v1/environments/{environment_id}/versions",
            json={**_web("https://shop.example/cart"), "project_id": str(project_id), "locale": "ko-KR"},
            headers=headers,
        )
        assert revised.status_code == 201, revised.text
        stored = await client.get(
            f"/api/v1/projects/{project_id}/environments/{environment_id}/revisions/{created.json()['id']}",
            headers=headers,
        )
    return page, outside, bad_package, created.json()["content_hash"], stored.json()["content_hash"]


def _web(start_url: str) -> dict[str, object]:
    return {
        "name": "웹",
        "target_kind": "web",
        "allowlist": ["https://shop.example"],
        "viewport": {"width": 1280, "height": 720},
        "locale": "ko-KR",
        "reset_policy": "clear",
        "limits": {"timeout_seconds": 600, "max_actions": 50, "budget": "2.00", "currency": "USD"},
        "start_url": start_url,
        "dpr": 1,
        "timezone": "Asia/Seoul",
    }


async def _rows(app: object, project_id: object) -> tuple[object, object, object, object, object]:
    import httpx
    from uuid import UUID

    assert isinstance(project_id, UUID)
    transport = httpx.ASGITransport(app=app)
    origin = "http://127.0.0.1"
    schema = {"columns": [{"name": "amount", "type": "string", "required": True}]}
    async with httpx.AsyncClient(transport=transport, base_url=origin) as client:
        issued = await client.post(
            "/api/v1/session/nonces",
            json={"origin": origin, "project_id": str(project_id)},
            headers={"Idempotency-Key": "w1103-nonce", "Origin": origin},
        )
        booted = await client.post(
            "/api/v1/session/bootstrap",
            json={"nonce": issued.json()["nonce"]},
            headers={"Idempotency-Key": "w1103-boot", "Origin": origin},
        )
        client.cookies.set("aiqa_session", booted.cookies["aiqa_session"])
        headers = {"Origin": origin, "X-CSRF-Token": booted.json()["csrf_token"], "Idempotency-Key": "w1103-case"}
        case = await client.post(
            f"/api/v1/projects/{project_id}/cases",
            json={"name": "금액", "tc_reference": None},
            headers=headers,
        )
        assert case.status_code == 201, case.text
        headers["Idempotency-Key"] = "w1103-ref"
        ref = await client.post(
            f"/api/v1/projects/{project_id}/secret-refs",
            json={"name": "account", "value": "hidden-dataset-plain"},
            headers=headers,
        )
        assert ref.status_code == 201, ref.text
        secret_ref = {
            "project_id": str(project_id),
            "ref_id": ref.json()["ref_id"],
            "revision": ref.json()["revision"],
        }
        headers["Idempotency-Key"] = "w1103-data"
        created = await client.post(
            f"/api/v1/projects/{project_id}/datasets",
            json={
                "name": "금액표",
                "row_schema": schema,
                "rows": [{"id": "row-1", "values": {"amount": "1000"}}],
                "secret_ref": secret_ref,
                "case_id": case.json()["case_id"],
            },
            headers=headers,
        )
        assert created.status_code == 201, created.text
        dataset_id = created.json()["dataset_id"]
        headers["Idempotency-Key"] = "w1103-missing"
        invalid = await client.post(
            f"/api/v1/datasets/{dataset_id}/versions",
            json={
                "project_id": str(project_id),
                "name": "금액표",
                "row_schema": schema,
                "rows": [{"id": "row-1", "values": {}}],
                "case_id": case.json()["case_id"],
            },
            headers=headers,
        )
        headers["Idempotency-Key"] = "w1103-duplicate"
        duplicate = await client.post(
            f"/api/v1/datasets/{dataset_id}/versions",
            json={
                "project_id": str(project_id),
                "name": "금액표",
                "row_schema": schema,
                "rows": [
                    {"id": "row-1", "values": {"amount": "1000"}},
                    {"id": "row-1", "values": {"amount": "1000"}},
                ],
                "case_id": case.json()["case_id"],
            },
            headers=headers,
        )
        headers["Idempotency-Key"] = "w1103-next"
        revised = await client.post(
            f"/api/v1/datasets/{dataset_id}/versions",
            json={
                "project_id": str(project_id),
                "name": "금액표",
                "row_schema": schema,
                "rows": [{"id": "row-1", "values": {"amount": "1001"}}],
                "secret_ref": secret_ref,
                "case_id": case.json()["case_id"],
            },
            headers=headers,
        )
        assert revised.status_code == 201, revised.text
        stored = await client.get(
            f"/api/v1/projects/{project_id}/datasets/{dataset_id}/versions/{created.json()['id']}",
            headers=headers,
        )
        listed = await client.get(f"/api/v1/projects/{project_id}/datasets", headers=headers)
        page = await client.get(f"/ui/projects/{project_id}/datasets")
    return page, invalid, duplicate, stored, listed


def _android(package: str) -> dict[str, object]:
    return {
        "name": "폰",
        "target_kind": "android",
        "allowlist": [package],
        "viewport": {"width": 1080, "height": 1920},
        "locale": "ko-KR",
        "reset_policy": "clear",
        "limits": {"timeout_seconds": 600, "max_actions": 50, "budget": "2.00", "currency": "USD"},
        "package": package,
        "orientation": "portrait",
        "setup": "prepare",
        "reset": "reset",
        "cleanup": "cleanup",
        "account_ref": "account-1",
    }
