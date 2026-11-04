"""RX-04: outbound WorkerHttpClient TLS, redirect, auth, timeout, and claim idempotency."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx

from aiqa.api.app import create_app
from aiqa.api.auth import bound_auth_store, enroll_worker
from aiqa.config import SettingsError, WorkerClientSettings, load_settings, load_worker_client_settings
from aiqa.domain.projects import bind_store, create_project
from aiqa.store.database import migrate_store
from aiqa.store.models import Actor, ProjectCreate
from aiqa.worker.http_client import (
    RetryClass,
    SyncASGITransport,
    WorkerHttpClient,
    WorkerHttpError,
    classify_exception,
    classify_status,
)


def test_settings_and_retry_classification() -> None:
    settings = load_worker_client_settings(
        {
            "AIQA_MANAGEMENT_BASE_URL": "https://manage.example",
            "AIQA_WORKER_TOKEN": "secret-token",
            "AIQA_WORKER_TIMEOUT_SECONDS": "12.5",
            "AIQA_WORKER_VERIFY_TLS": "true",
        }
    )
    assert settings.base_url == "https://manage.example"
    assert settings.timeout_seconds == 12.5
    try:
        load_worker_client_settings({"AIQA_MANAGEMENT_BASE_URL": "http://manage.example", "AIQA_WORKER_TOKEN": "x"})
        http_ok = True
    except SettingsError:
        http_ok = False
    assert http_ok is False
    assert classify_status(503) is RetryClass.retryable
    assert classify_status(401) is RetryClass.auth
    assert classify_status(403) is RetryClass.auth
    assert classify_status(409) is RetryClass.conflict
    assert classify_exception(httpx.TimeoutException("slow")) is RetryClass.timeout


def test_client_rejects_tls_redirect_timeout_auth_and_hides_bearer() -> None:
    settings = WorkerClientSettings(base_url="https://manage.example", token="super-secret-token")

    def tls_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("CERTIFICATE_VERIFY_FAILED ssl handshake", request=request)

    with WorkerHttpClient(settings, transport=httpx.MockTransport(tls_handler)) as client:
        try:
            client.heartbeat("boot-1")
            tls_ok = True
        except WorkerHttpError as exc:
            tls_ok = False
            assert exc.retry_class is RetryClass.tls
            assert "super-secret-token" not in str(exc)
            assert "super-secret-token" not in repr(client)

    def redirect_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://evil.example/steal"}, request=request)

    with WorkerHttpClient(settings, transport=httpx.MockTransport(redirect_handler)) as client:
        try:
            client.heartbeat("boot-1")
            redirect_ok = True
        except WorkerHttpError as exc:
            redirect_ok = False
            assert exc.retry_class is RetryClass.redirect

    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    with WorkerHttpClient(settings, transport=httpx.MockTransport(timeout_handler)) as client:
        try:
            client.heartbeat("boot-1")
            timeout_ok = True
        except WorkerHttpError as exc:
            timeout_ok = False
            assert exc.retry_class is RetryClass.timeout

    def auth_handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer super-secret-token"
        return httpx.Response(403, json={"error": {"message": "revoked"}}, request=request)

    with WorkerHttpClient(settings, transport=httpx.MockTransport(auth_handler)) as client:
        try:
            client.claim(boot_id="boot-1", now="2026-11-03T15:00:00+00:00", idempotency_key="k1")
            auth_ok = True
        except WorkerHttpError as exc:
            auth_ok = False
            assert exc.retry_class is RetryClass.auth
            assert exc.status_code == 403
            assert "super-secret-token" not in str(exc)

    assert tls_ok is False
    assert redirect_ok is False
    assert timeout_ok is False
    assert auth_ok is False


def test_claim_replay_uses_same_idempotency_key_against_app(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "runtime"
    app = create_app(
        load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)})
    )
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("HTTP", "rx04", "http", "android"))
    actor = Actor(owner.actor_id, project.project_id, True)
    worker_id = str(uuid4())
    with bound_auth_store(store):
        token = enroll_worker(actor, worker_id, "resource_probe")
    resource = str(uuid4())
    now = datetime(2026, 11, 3, 15, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("aiqa.api.worker._server_now", lambda: now)
    with store.transaction() as connection:
        connection.execute(
            "INSERT INTO physical_resource_keys (physical_key_id, worker_id, native_id) VALUES (?, ?, ?)",
            (resource, worker_id, "emulator-5580"),
        )
        connection.execute(
            "INSERT INTO resource_aliases (project_id, physical_key_id, display_name, target_kind) VALUES (?, ?, ?, ?)",
            (str(project.project_id), resource, "AIQA", "android"),
        )
        connection.execute(
            """
            INSERT INTO resource_inventory (
                physical_key_id, state, os_build, geometry, permissions, ime, observed_at
            ) VALUES (?, 'ready', '', '', '[]', '', ?)
            """,
            (resource, now.isoformat()),
        )
    store.close()

    settings = WorkerClientSettings(base_url="https://127.0.0.1", token=token, verify_tls=False)
    with WorkerHttpClient(settings, transport=SyncASGITransport(app)) as client:
        beat = client.heartbeat("boot-rx04")
        assert beat["state"] == "online"
        store = app.state.open_store()
        try:
            with store.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO jobs (project_id, job_id, purpose, payload_hash, source_refs, limits, status)
                    VALUES (?, ?, 'resource_probe', 'hash', ?, '{}', 'queued')
                    """,
                    (str(project.project_id), str(uuid4()), json.dumps([resource])),
                )
        finally:
            store.close()
        first = client.claim(
            boot_id="boot-rx04",
            now=now.isoformat(),
            idempotency_key="rx04-claim",
        )
        assert first is not None
        assert first["replayed"] is False
        assert "token" not in first
        lost_then_retry = client.claim(
            boot_id="boot-rx04",
            now=now.isoformat(),
            idempotency_key="rx04-claim",
        )
        assert lost_then_retry is not None
        assert lost_then_retry["attempt_id"] == first["attempt_id"]
        assert lost_then_retry["replayed"] is True
        inventory = client.report_inventory(
            {
                "project_id": str(project.project_id),
                "native_id": "emulator-5580",
                "target_kind": "android",
                "state": "ready",
                "os_build": "Android 16",
                "geometry": "720x1600",
                "permissions": "[]",
                "ime": "none",
                "observed_at": now.isoformat(),
                "display_name": "AIQA",
                "raw_handle": None,
            },
            idempotency_key="rx04-inv",
        )
        assert inventory["state"] == "ready"
        acked = client.acknowledge(
            project_id=first["project_id"],
            job_id=first["job_id"],
            generation=first["generation"],
            runner_nonce=str(uuid4()),
            now=now.isoformat(),
            idempotency_key="rx04-ack",
        )
        assert acked["attempt_id"] == first["attempt_id"]
        renewed = client.renew(
            project_id=first["project_id"],
            job_id=first["job_id"],
            generation=first["generation"],
            now=now.isoformat(),
            idempotency_key="rx04-renew",
        )
        assert renewed["generation"] == first["generation"]
