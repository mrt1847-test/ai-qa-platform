"""RX-78: W11 registration buttons vs unsupported controls, and a launcher worker that connects.

Main gates stay tests/acceptance/test_w11.py and test_w12.py. This file documents the
regression pack: environments.html may keep RX-28 PC registration buttons but no
cloud/manualcontrol/pause controls, and start_local_services must give the worker a loopback
HTTPS origin + token + CA instead of a worker that dies on missing settings.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from aiqa.launcher import LauncherConfig, start_local_services, stop_local_services

_REGISTRATION_ACTIONS = {"issue", "copy", "cancel", "revoke"}


def _assert_only_registration_controls(text: str) -> None:
    for tag in re.findall(r"<button\b[^>]*>", text):
        action = re.search(r'data-pc-action="([^"]+)"', tag)
        assert action is not None and action.group(1) in _REGISTRATION_ACTIONS, tag
    for hook in ("cloud", "manualcontrol", "pause"):
        assert hook not in text.lower(), hook


async def _get(port: int, path: str) -> httpx.Response:
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
        return await client.get(path)


async def _environments_page(app: object, project_id: object) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    origin = "http://127.0.0.1"
    async with httpx.AsyncClient(transport=transport, base_url=origin) as client:
        issued = await client.post(
            "/api/v1/session/nonces",
            json={"origin": origin, "project_id": str(project_id)},
            headers={"Idempotency-Key": "rx78-nonce", "Origin": origin},
        )
        booted = await client.post(
            "/api/v1/session/bootstrap",
            json={"nonce": issued.json()["nonce"]},
            headers={"Idempotency-Key": "rx78-boot", "Origin": origin},
        )
        client.cookies.set("aiqa_session", booted.cookies["aiqa_session"])
        return await client.get(f"/ui/projects/{project_id}/environments")


def test_rx_78_environments_allow_registration_not_unsupported_controls(tmp_path: Path) -> None:
    from aiqa.api.app import create_app
    from aiqa.config import load_settings
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.store.database import migrate_store
    from aiqa.store.models import Actor, ProjectCreate

    app = create_app(
        load_settings(
            {"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(tmp_path / "runtime")}
        )
    )
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("등록", "rx78", "환경", "web"))
    store.close()
    page = asyncio.run(_environments_page(app, project.project_id))
    assert page.status_code == 200
    assert "data-pc-registration" in page.text
    for action in _REGISTRATION_ACTIONS:
        assert f'data-pc-action="{action}"' in page.text
    _assert_only_registration_controls(page.text)
    assert "PASS" not in page.text
    # The blanket ban would have failed here; a stray unsupported control must still fail.
    with pytest.raises(AssertionError):
        _assert_only_registration_controls(page.text + '<button type="button">pause</button>')


def test_rx_78_launcher_worker_connects_with_enrolled_token(tmp_path: Path, monkeypatch) -> None:
    from aiqa.api.auth import bound_auth_store, enroll_worker
    from aiqa.config import load_settings
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.store.database import StorageConfig, migrate_store, open_store
    from aiqa.store.models import Actor, ProjectCreate
    from aiqa.worker.presence import get_presence

    monkeypatch.delenv("AIQA_WORKER_TOKEN", raising=False)
    monkeypatch.delenv("AIQA_LOCAL_TLS_CERT", raising=False)
    monkeypatch.delenv("AIQA_LOCAL_TLS_KEY", raising=False)
    config = LauncherConfig("127.0.0.1", 8878, str(tmp_path / "enrolled"))
    settings = load_settings(
        {"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": config.runtime_root}
    )
    storage = StorageConfig.from_settings(settings)
    store = open_store(storage)
    worker_id = str(uuid4())
    try:
        migrate_store(store)
        owner = Actor(uuid4(), None, True)
        with bind_store(store):
            project = create_project(owner, ProjectCreate("런처", "rx78-launch", "worker", "web"))
        with bound_auth_store(store):
            token = enroll_worker(Actor(owner.actor_id, project.project_id, True), worker_id, "resource_probe")
    finally:
        store.close()
    token_path = Path(config.runtime_root) / "worker" / "token"
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(token, encoding="utf-8")

    try:
        status = start_local_services(config)
        assert status.state == "running", status.explanation
        assert status.api_instances == 1 and status.worker_instances == 1
        assert "VM 미준비" in status.explanation
        record = json.loads((Path(config.runtime_root) / "launcher.json").read_text(encoding="utf-8"))
        assert record["management_origin"].startswith("https://127.0.0.1:")
        assert record["worker_registered"] is True and record["vm_ready"] is False
        assert token not in json.dumps(record)

        def online() -> bool:
            import sqlite3

            with closing(sqlite3.connect(storage.database_path.as_uri() + "?mode=ro", uri=True)) as connection:
                presence = get_presence(
                    connection, worker_id, datetime.now(timezone.utc), project_id=project.project_id
                )
            return presence.state == "online"

        deadline = time.monotonic() + 30
        while not online():
            assert time.monotonic() < deadline, "worker never reached the management API over TLS"
            time.sleep(0.5)
        page = asyncio.run(_get(config.port, "/ui/local"))
        assert page.status_code == 200
        assert "VM 미준비" in page.text and "PASS" not in page.text
    finally:
        stop_local_services(config)


def test_rx_78_launcher_without_enrollment_reports_unregistered(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("AIQA_WORKER_TOKEN", raising=False)
    monkeypatch.delenv("AIQA_LOCAL_TLS_CERT", raising=False)
    monkeypatch.delenv("AIQA_LOCAL_TLS_KEY", raising=False)
    config = LauncherConfig("127.0.0.1", 8879, str(tmp_path / "unenrolled"))
    try:
        status = start_local_services(config)
        assert status.state == "running", status.explanation
        assert "VM 미준비" in status.explanation and "미등록" in status.explanation
        page = asyncio.run(_get(config.port, "/ui/local"))
        assert page.status_code == 200 and "미등록" in page.text and "PASS" not in page.text
        record = json.loads((Path(config.runtime_root) / "launcher.json").read_text(encoding="utf-8"))
        assert record["worker_registered"] is False and record["vm_ready"] is False
    finally:
        stop_local_services(config)


def test_rx_78_missing_worker_config_is_explained_on_page(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("AIQA_WORKER_TOKEN", raising=False)
    monkeypatch.setenv("AIQA_LOCAL_TLS_CERT", str(tmp_path / "missing-cert.pem"))
    monkeypatch.setenv("AIQA_LOCAL_TLS_KEY", str(tmp_path / "missing-key.pem"))
    config = LauncherConfig("127.0.0.1", 8880, str(tmp_path / "noconfig"))
    try:
        status = start_local_services(config)
        assert status.state == "worker_missing"
        assert status.worker_instances == 0 and status.api_instances == 1
        assert "worker 연결 설정이 없습니다" in status.explanation
        page = asyncio.run(_get(config.port, "/ui/local"))
        assert page.status_code == 200
        assert "worker 연결 설정이 없습니다" in page.text
        assert "VM 미준비" not in page.text and "실행 중입니다" not in page.text
        record = json.loads((Path(config.runtime_root) / "launcher.json").read_text(encoding="utf-8"))
        assert record["state"] == "worker_missing" and record["vm_ready"] is False
    finally:
        stop_local_services(config)
