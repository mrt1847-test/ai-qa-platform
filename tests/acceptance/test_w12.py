"""Acceptance coverage for the local launcher."""

from __future__ import annotations

import socket
from pathlib import Path

from aiqa.launcher import (
    LauncherConfig,
    acknowledge_tab_closed,
    start_local_services,
    stop_local_services,
)


def test_w12_03(tmp_path: Path) -> None:
    import asyncio
    import sqlite3
    from uuid import uuid4

    from aiqa.config import load_settings
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.launcher import LauncherConfig, ServiceStopRequest, start_local_services, stop_local_services
    from aiqa.store.database import StorageConfig, migrate_store, open_store
    from aiqa.store.models import Actor, ProjectCreate
    from aiqa.worker.service import bind_claim_store, reconcile_after_resume

    config = LauncherConfig("127.0.0.1", 8875, str(tmp_path / "resume"))
    started = False
    try:
        start_local_services(config)
        started = True
        owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
        settings = load_settings(
            {"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": config.runtime_root}
        )
        store = open_store(StorageConfig.from_settings(settings))
        migrate_store(store)
        with bind_store(store):
            project = create_project(owner, ProjectCreate("복귀", "w1203", "종료", "web"))
        project_id = str(project.project_id)
        job_id = str(uuid4())
        with store.transaction() as connection:
            connection.execute(
                """
                INSERT INTO jobs (
                    project_id, job_id, purpose, recording_id, case_run_id,
                    payload_hash, source_refs, limits, status
                ) VALUES (?, ?, 'resource_probe', NULL, NULL, 'hash', '["ref"]', '{}', 'running')
                """,
                (project_id, job_id),
            )
            connection.execute(
                """
                INSERT INTO worker_enrollments (enrollment_id, worker_id, project_id, created_at)
                VALUES ('enroll-w1203', 'worker-w1203', ?, '2026-11-01T00:00:00+00:00')
                """,
                (project_id,),
            )
            connection.execute(
                """
                INSERT INTO physical_resource_keys (physical_key_id, worker_id, native_id)
                VALUES ('key-w1203', 'worker-w1203', 'native-w1203')
                """
            )
            connection.execute(
                """
                INSERT INTO leases (
                    project_id, job_id, generation, worker_id, physical_key_id, expires_at
                ) VALUES (?, ?, 1, 'worker-w1203', 'key-w1203', '2020-01-01T00:00:00+00:00')
                """,
                (project_id, job_id),
            )
        store.close()
        stopped = stop_local_services(ServiceStopRequest(config, "stop", True))
        assert stopped.state == "stopped"
        start_local_services(config)
        store = open_store(StorageConfig.from_settings(settings))
        with bind_claim_store(store):
            reconcile_after_resume()
            with store.transaction() as connection:
                status = connection.execute("SELECT status FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
                running = connection.execute("SELECT COUNT(*) FROM jobs WHERE status = 'running'").fetchone()
                completed = connection.execute("SELECT COUNT(*) FROM jobs WHERE status = 'completed'").fetchone()
                quarantine = connection.execute("SELECT COUNT(*) FROM resource_quarantine").fetchone()
        store.close()
        page = asyncio.run(_local_page(config.port))
        observed = {
            "automatic_resume": int(running[0]),
            "unknown_marked_success": str(status[0]) == "completed" or int(completed[0]) > 0,
            "last_received_visible": "마지막 수신" in page.text,
            "cleanup_or_quarantine": int(quarantine[0]) > 0 and "정리" in page.text,
        }
        assert str(status[0]) == "lost"
        assert "자동 재개 0" in page.text
        assert "<button" not in page.text and "PASS" not in page.text
        assert observed == {
            "automatic_resume": 0,
            "unknown_marked_success": False,
            "last_received_visible": True,
            "cleanup_or_quarantine": True,
        }
    finally:
        if started:
            stop_local_services(config)


def test_w12_02(tmp_path: Path) -> None:
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
        project = create_project(owner, ProjectCreate("재접속", "w1202", "조회", "web"))
    store.close()
    project_id = str(project.project_id)
    attempt_id = str(uuid4())
    job_id = str(uuid4())
    with sqlite3.connect(root / "db" / "aiqa.sqlite") as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO jobs (
                project_id, job_id, purpose, recording_id, case_run_id,
                payload_hash, source_refs, limits, status
            ) VALUES (?, ?, 'resource_probe', NULL, NULL, 'hash', '["ref"]', '{}', 'queued')
            """,
            (project_id, job_id),
        )
        connection.execute(
            """
            INSERT INTO attempts (project_id, attempt_id, job_id, generation, physical_key_id)
            VALUES (?, ?, ?, 1, NULL)
            """,
            (project_id, attempt_id, job_id),
        )
        for seq, audit_id in ((1, "audit-1"), (5, "audit-5")):
            connection.execute(
                """
                INSERT INTO project_audits (project_id, audit_id, commit_seq, actor_id, action, created_at)
                VALUES (?, ?, ?, ?, 'case', '2026-11-01T00:00:00+00:00')
                """,
                (project_id, audit_id, seq, str(owner.actor_id)),
            )
        for seq, event_id in ((1, "event-1"), (5, "event-5")):
            connection.execute(
                """
                INSERT INTO attempt_events (
                    project_id, event_id, attempt_id, local_seq, captured_at, event_type,
                    minimum_facts, payload_hash, body_hash, detail_payload, sealed
                ) VALUES (?, ?, ?, ?, '2026-11-01T00:00:00+00:00', 'action', '{}', ?, ?, NULL, 0)
                """,
                (project_id, event_id, attempt_id, seq, f"p{seq}", f"b{seq}"),
            )
    page, project_page, attempt_page, script, again = asyncio.run(_poll(app, project_id, attempt_id))
    project_ids = {item["id"] for item in project_page["items"]}
    attempt_ids = {item["id"] for item in attempt_page["items"]}
    with sqlite3.connect(root / "db" / "aiqa.sqlite") as connection:
        stored = connection.execute("SELECT COUNT(*) FROM attempt_events").fetchone()[0]
    observed = {
        "poll_seconds": 2 if 'data-poll-seconds="2"' in page.text and "2000" in script else 0,
        "reconnect_mutations": project_page["mutations"] + attempt_page["mutations"] + again,
        "selected_action_restored": "tap-1" in page.text,
        "cursors_interchanged": bool(project_ids & attempt_ids),
    }
    assert project_ids == {"audit-5"} and attempt_ids == {"event-5"}
    assert project_page["stale"] is True and attempt_page["cursor_kind"] == "local"
    assert stored == 2
    assert "<button" not in page.text and "PASS" not in page.text
    assert observed == {
        "poll_seconds": 2,
        "reconnect_mutations": 0,
        "selected_action_restored": True,
        "cursors_interchanged": False,
    }


def test_w12_01(tmp_path: Path) -> None:
    import asyncio

    from aiqa.api.app import create_app
    from aiqa.config import load_settings

    primary = LauncherConfig("127.0.0.1", 8871, str(tmp_path / "primary"))
    missing = LauncherConfig("127.0.0.1", 8873, str(tmp_path / "missing"), start_worker=False)
    occupied = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    occupied.bind(("127.0.0.1", 8872))
    try:
        first = start_local_services(primary)
        second = start_local_services(primary)
        conflict = start_local_services(LauncherConfig("127.0.0.1", 8872, str(tmp_path / "conflict")))
        failed = start_local_services(missing)
        closed = acknowledge_tab_closed(primary)
        app = create_app(
            load_settings(
                {"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": primary.runtime_root}
            )
        )
        page, body = asyncio.run(_read(app))
        observed = {
            "api_instances": second.api_instances,
            "worker_instances": second.worker_instances,
            "tab_close_cancels": closed.tab_close_cancels,
            "port_conflict_explained": "다른 프로세스가 이 포트를 사용 중입니다." in conflict.explanation,
        }
        assert first.api_pid == second.api_pid and first.worker_pid == second.worker_pid
        assert failed.state == "worker_missing" and failed.worker_instances == 0
        assert "VM 미준비" in first.explanation and "VM 미준비" in page.text
        assert body["tab_close_cancels"] is False
        assert "탭을 닫아도 프로세스는 유지됩니다" in page.text
        assert "<button" not in page.text and "PASS" not in page.text
        assert observed == {
            "api_instances": 1,
            "worker_instances": 1,
            "tab_close_cancels": False,
            "port_conflict_explained": True,
        }
    finally:
        occupied.close()
        stop_local_services(primary)
        stop_local_services(missing)


async def _local_page(port: int):
    import httpx

    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
        return await client.get("/ui/local")


async def _poll(app: object, project_id: str, attempt_id: str):
    import httpx

    transport = httpx.ASGITransport(app=app)
    origin = "http://127.0.0.1"
    async with httpx.AsyncClient(transport=transport, base_url=origin) as client:
        issued = await client.post(
            "/api/v1/session/nonces",
            json={"origin": origin, "project_id": project_id},
            headers={"Idempotency-Key": "w1202-nonce", "Origin": origin},
        )
        booted = await client.post(
            "/api/v1/session/bootstrap",
            json={"nonce": issued.json()["nonce"]},
            headers={"Idempotency-Key": "w1202-boot", "Origin": origin},
        )
        client.cookies.set("aiqa_session", booted.cookies["aiqa_session"])
        headers = {"Origin": origin, "X-CSRF-Token": booted.json()["csrf_token"]}
        project_page = await client.get(
            f"/api/v1/projects/{project_id}/events",
            params={"after_commit_seq": 1, "after_local_seq": 5},
            headers=headers,
        )
        attempt_page = await client.get(
            f"/api/v1/attempts/{attempt_id}/events",
            params={"after_local_seq": 1, "after_commit_seq": 5},
            headers=headers,
        )
        again = await client.get(
            f"/api/v1/projects/{project_id}/events",
            params={"after_commit_seq": 1},
            headers=headers,
        )
        page = await client.get(
            "/ui/local",
            params={"project": project_id, "attempt": attempt_id, "rec": "rec-1", "item": "item-1", "action": "tap-1"},
        )
        script = await client.get("/static/polling.js")
    assert project_page.status_code == 200, project_page.text
    assert attempt_page.status_code == 200, attempt_page.text
    assert again.status_code == 200
    return page, project_page.json(), attempt_page.json(), script.text, 0 if again.json()["items"] == project_page.json()["items"] else 1


async def _read(app: object):
    import httpx

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        page = await client.get("/ui/local")
        status = await client.get("/api/v1/local-status")
    return page, status.json()
