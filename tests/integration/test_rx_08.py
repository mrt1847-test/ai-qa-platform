"""RX-08: independent worker consume loop without server DB access."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from aiqa.api.app import create_app
from aiqa.api.auth import bound_auth_store, enroll_worker
from aiqa.config import WorkerClientSettings, load_settings
from aiqa.domain.projects import bind_store, create_project
from aiqa.launcher import main as launcher_main
from aiqa.store.database import migrate_store
from aiqa.store.models import Actor, ProjectCreate
from aiqa.worker.http_client import SyncASGITransport, WorkerHttpClient
from aiqa.worker.runner import verify_job_snapshot
from aiqa.worker.runtime import InertHandler, WorkerRuntime, WorkerRuntimeConfig


def test_snapshot_gate_and_no_automatic_resume() -> None:
    ok = verify_job_snapshot(
        {"purpose": "resource_probe", "digest": "sha256:abc"},
        frozenset({"resource_probe"}),
    )
    assert ok.supported is True
    bad = verify_job_snapshot(
        {"purpose": "android", "digest": "sha256:abc"},
        frozenset({"resource_probe"}),
    )
    assert bad.supported is False and bad.reason == "unsupported_target"
    with pytest.raises(ValueError):
        WorkerRuntimeConfig(boot_id="b", prepared_adapters=frozenset({"resource_probe"}), automatic_resume=True)
    assert launcher_main(["aiqa.launcher"]) == 2


def test_offline_unregistered_stop_unsupported_and_inert(tmp_path: Path, monkeypatch) -> None:
    settings = WorkerClientSettings(base_url="https://manage.example", token="tok", verify_tls=True)
    handler_calls = {"n": 0}

    class CountingHandler(InertHandler):
        def handle(self, claim):
            handler_calls["n"] += 1
            return super().handle(claim)

    def offline_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    with WorkerHttpClient(settings, transport=httpx.MockTransport(offline_handler)) as client:
        runtime = WorkerRuntime(
            client,
            WorkerRuntimeConfig(boot_id="boot-off", prepared_adapters=frozenset({"resource_probe"})),
            CountingHandler(),
        )
        offline = runtime.run_once()
    assert offline.state == "offline" and offline.actions == 0 and handler_calls["n"] == 0

    def auth_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"})

    with WorkerHttpClient(settings, transport=httpx.MockTransport(auth_handler)) as client:
        runtime = WorkerRuntime(
            client,
            WorkerRuntimeConfig(boot_id="boot-auth", prepared_adapters=frozenset({"resource_probe"})),
            CountingHandler(),
        )
        unregistered = runtime.run_once()
    assert unregistered.state == "unregistered" and unregistered.actions == 0

    claims_seen = 0

    def stop_handler(request: httpx.Request) -> httpx.Response:
        nonlocal claims_seen
        if request.url.path.endswith("/heartbeats"):
            return httpx.Response(200, json={"state": "online"})
        if request.url.path.endswith("/claims"):
            claims_seen += 1
            return httpx.Response(204)
        return httpx.Response(500, json={})

    with WorkerHttpClient(settings, transport=httpx.MockTransport(stop_handler)) as client:
        runtime = WorkerRuntime(
            client,
            WorkerRuntimeConfig(boot_id="boot-stop", prepared_adapters=frozenset({"resource_probe"})),
            CountingHandler(),
        )
        runtime.request_stop()
        stopped = runtime.run_once()
    assert stopped.claimed is False and claims_seen == 0
    assert stopped.reason in {"stopped", "claim_blocked"}

    attempt = str(uuid4())
    job = str(uuid4())
    project = str(uuid4())
    ack_calls = 0
    finish_calls = 0

    def unsupported_handler(request: httpx.Request) -> httpx.Response:
        nonlocal ack_calls, finish_calls
        path = request.url.path
        if path.endswith("/heartbeats"):
            return httpx.Response(200, json={"state": "online"})
        if path.endswith("/claims"):
            return httpx.Response(
                200,
                json={
                    "project_id": project,
                    "job_id": job,
                    "attempt_id": attempt,
                    "generation": 1,
                    "physical_key_id": None,
                    "snapshot": {
                        "job_id": job,
                        "attempt_id": attempt,
                        "purpose": "resource_probe",
                        "target_ref": None,
                        "revision_ref": None,
                        "policy_ref": None,
                        "digest": "sha256:deadbeef",
                    },
                    "replayed": False,
                },
            )
        if path.endswith("/attempt-acks"):
            ack_calls += 1
            return httpx.Response(200, json={"attempt_id": attempt})
        if path.endswith("/attempt-finishes"):
            finish_calls += 1
            return httpx.Response(
                200,
                json={
                    "project_id": project,
                    "job_id": job,
                    "attempt_id": attempt,
                    "status": "error",
                    "outcome": "error",
                    "replayed": False,
                    "approved": False,
                    "verdict": None,
                    "purpose": "resource_probe",
                },
            )
        return httpx.Response(404, json={})

    with WorkerHttpClient(settings, transport=httpx.MockTransport(unsupported_handler)) as client:
        runtime = WorkerRuntime(
            client,
            WorkerRuntimeConfig(boot_id="boot-unsup", prepared_adapters=frozenset({"android"})),
            CountingHandler(),
        )
        unsupported = runtime.run_once()
    assert unsupported.reason == "unsupported_target" and unsupported.actions == 0
    assert handler_calls["n"] == 0
    assert ack_calls == 1 and finish_calls == 1

    root = tmp_path / "runtime"
    app = create_app(
        load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)})
    )
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        created = create_project(owner, ProjectCreate("소비", "rx08", "rx", "android"))
    actor = Actor(owner.actor_id, created.project_id, True)
    worker_id = str(uuid4())
    with bound_auth_store(store):
        token = enroll_worker(actor, worker_id, "resource_probe")
    resource = str(uuid4())
    now = datetime(2026, 11, 3, 19, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("aiqa.api.worker._server_now", lambda: now)
    with store.transaction() as connection:
        connection.execute(
            "INSERT INTO physical_resource_keys (physical_key_id, worker_id, native_id) VALUES (?, ?, ?)",
            (resource, worker_id, "emulator-5580"),
        )
        connection.execute(
            "INSERT INTO resource_aliases (project_id, physical_key_id, display_name, target_kind) VALUES (?, ?, ?, ?)",
            (str(created.project_id), resource, "소비기기", "android"),
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

    transport = SyncASGITransport(app)
    client_settings = WorkerClientSettings(
        base_url="https://127.0.0.1", token=token, timeout_seconds=10, verify_tls=False
    )
    with WorkerHttpClient(client_settings, transport=transport) as client:
        client.heartbeat("boot-rx08")
        store = app.state.open_store()
        try:
            with store.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO jobs (project_id, job_id, purpose, payload_hash, source_refs, limits, status)
                    VALUES (?, ?, 'resource_probe', 'hash', ?, '{}', 'queued')
                    """,
                    (str(created.project_id), str(uuid4()), json.dumps([resource])),
                )
        finally:
            store.close()
        runtime = WorkerRuntime(
            client,
            WorkerRuntimeConfig(
                boot_id="boot-rx08",
                prepared_adapters=frozenset({"resource_probe"}),
                poll_seconds=0.01,
            ),
            CountingHandler(),
            now=lambda: now,
            mono=lambda: 1.0,
            sleep=lambda _s: None,
        )
        finished = runtime.run_once()
        runtime.note_restart()
        assert runtime.resumed_past_jobs == 0
        assert runtime._active_attempt is None

    assert finished.claimed is True and finished.finished is True and finished.actions == 0
    assert handler_calls["n"] == 1
