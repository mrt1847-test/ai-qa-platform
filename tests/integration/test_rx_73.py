"""RX-73: WorkerRuntime confirms cleanup itself so consecutive jobs reuse one resource."""

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
from aiqa.store.database import migrate_store
from aiqa.store.models import Actor, ProjectCreate
from aiqa.worker.http_client import SyncASGITransport, WorkerHttpClient, WorkerHttpError
from aiqa.worker.runtime import InertHandler, WorkerRuntime, WorkerRuntimeConfig

_NOW = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)
_BOOT = "boot-rx73"
_CLEANUP_PATH = "/api/v1/worker/cleanup-confirmations"


class _SpyTransport(httpx.BaseTransport):
    """Forward to the ASGI app, count cleanup posts, optionally lose the first cleanup response."""

    def __init__(self, inner: httpx.BaseTransport, *, lose_first_cleanup: bool = False) -> None:
        self._inner = inner
        self._lose = lose_first_cleanup
        self.cleanup_requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = self._inner.handle_request(request)
        if request.url.path == _CLEANUP_PATH:
            self.cleanup_requests.append(request)
            if self._lose:
                self._lose = False
                # Server applied the cleanup; the worker only sees a failed response.
                return httpx.Response(503, json={"error": "lost"}, request=request)
        return response


def _setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "runtime"
    settings = load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)})
    app = create_app(settings)
    monkeypatch.setattr("aiqa.api.worker._server_now", lambda: _NOW)
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("정리연결", "rx73", "rx", "android"))
    actor = Actor(owner.actor_id, project.project_id, True)
    worker_id = str(uuid4())
    with bound_auth_store(store):
        token = enroll_worker(actor, worker_id, "resource_probe")
    resource = str(uuid4())
    with store.transaction() as connection:
        connection.execute(
            "INSERT INTO physical_resource_keys (physical_key_id, worker_id, native_id) VALUES (?, ?, ?)",
            (resource, worker_id, "emulator-5580"),
        )
        connection.execute(
            "INSERT INTO resource_aliases (project_id, physical_key_id, display_name, target_kind) VALUES (?, ?, ?, ?)",
            (str(project.project_id), resource, "기기", "android"),
        )
        connection.execute(
            """
            INSERT INTO resource_inventory (
                physical_key_id, state, os_build, geometry, permissions, ime, observed_at
            ) VALUES (?, 'ready', '', '', '[]', '', ?)
            """,
            (resource, _NOW.isoformat()),
        )
    store.close()
    return app, project.project_id, resource, token


def _enqueue(app, project_id, resource: str) -> str:
    job_id = str(uuid4())
    store = app.state.open_store()
    try:
        with store.transaction() as connection:
            connection.execute(
                """
                INSERT INTO jobs (project_id, job_id, purpose, payload_hash, source_refs, limits, status)
                VALUES (?, ?, 'resource_probe', 'hash', ?, '{}', 'queued')
                """,
                (str(project_id), job_id, json.dumps([resource])),
            )
    finally:
        store.close()
    return job_id


def _scalar(app, sql: str, params: tuple = ()) -> int:
    store = app.state.open_store()
    try:
        with store.transaction() as connection:
            row = connection.execute(sql, params).fetchone()
    finally:
        store.close()
    return int(row[0])


def _runtime(client: WorkerHttpClient) -> WorkerRuntime:
    return WorkerRuntime(
        client,
        WorkerRuntimeConfig(
            boot_id=_BOOT,
            prepared_adapters=frozenset({"resource_probe", "recording", "trial", "regression"}),
            max_cycles=1,
        ),
        InertHandler(),
        now=lambda: _NOW,
    )


def test_rx_73_runtime_cleanup_frees_lease_for_next_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, project_id, resource, token = _setup(tmp_path, monkeypatch)
    spy = _SpyTransport(SyncASGITransport(app))
    settings = WorkerClientSettings(base_url="https://127.0.0.1", token=token, timeout_seconds=10, verify_tls=False)
    with WorkerHttpClient(settings, transport=spy) as client:
        runtime = _runtime(client)
        # Presence must exist before job rows pin the worker session.
        client.heartbeat(_BOOT)
        job_1 = _enqueue(app, project_id, resource)
        job_2 = _enqueue(app, project_id, resource)

        # The test never posts cleanup-confirmations itself on the happy path.
        first = runtime.run_once()
        assert first.claimed and first.finished and first.state == "running"
        assert runtime.pending_cleanup is None
        assert len(spy.cleanup_requests) == 1
        assert _scalar(app, "SELECT COUNT(*) FROM leases WHERE physical_key_id = ?", (resource,)) == 0
        assert _scalar(
            app, "SELECT COUNT(*) FROM cleanup_confirmations WHERE released = 1 AND quarantined = 0"
        ) == 1
        assert _scalar(app, "SELECT COUNT(*) FROM resource_quarantine WHERE physical_key_id = ?", (resource,)) == 0

        # The same physical resource is claimable again only because the runtime released it.
        second = runtime.run_once()
        assert second.claimed and second.finished and second.state == "running"
        assert len(spy.cleanup_requests) == 2
        assert _scalar(app, "SELECT COUNT(*) FROM leases WHERE physical_key_id = ?", (resource,)) == 0
        assert _scalar(
            app, "SELECT COUNT(*) FROM cleanup_confirmations WHERE released = 1 AND quarantined = 0"
        ) == 2
        for job in (job_1, job_2):
            assert _scalar(app, "SELECT COUNT(*) FROM cleanup_confirmations WHERE job_id = ?", (job,)) == 1
        proof = _scalar(
            app, "SELECT COUNT(*) FROM cleanup_confirmations WHERE proof_refs = ?", (json.dumps(["runtime:inert"]),)
        )
        assert proof == 2
        assert runtime.finished == 2
        assert len(spy.cleanup_requests) == 2

        drained = runtime.run_once()
        assert drained.claimed is False and drained.reason == "empty"

        # Explicit client checks happen after the happy-path assertions.
        row = _scalar(app, "SELECT generation FROM cleanup_confirmations WHERE job_id = ?", (job_1,))
        attempt_id = str(
            _text(app, "SELECT attempt_id FROM cleanup_confirmations WHERE job_id = ?", (job_1,))
        )
        replay = client.confirm_cleanup(
            project_id=str(project_id),
            job_id=job_1,
            attempt_id=attempt_id,
            generation=row,
            physical_key_id=resource,
            proof_refs=["runtime:inert"],
            now=_NOW.isoformat(),
            idempotency_key="rx73-replay",
        )
        assert replay["replayed"] is True and replay["released"] is True
        with pytest.raises(WorkerHttpError) as stale:
            client.confirm_cleanup(
                project_id=str(project_id),
                job_id=job_1,
                attempt_id=str(uuid4()),
                generation=row + 5,
                physical_key_id=resource,
                proof_refs=["runtime:inert"],
                now=_NOW.isoformat(),
                idempotency_key="rx73-stale",
            )
        assert stale.value.status_code == 409
        with pytest.raises(WorkerHttpError):
            client.confirm_cleanup(
                project_id=str(project_id),
                job_id=job_1,
                attempt_id=attempt_id,
                generation=row,
                physical_key_id=None,
                proof_refs=[],
                now=_NOW.isoformat(),
                idempotency_key="  ",
            )


def test_rx_73_lost_cleanup_response_confirms_with_same_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, project_id, resource, token = _setup(tmp_path, monkeypatch)
    spy = _SpyTransport(SyncASGITransport(app), lose_first_cleanup=True)
    settings = WorkerClientSettings(base_url="https://127.0.0.1", token=token, timeout_seconds=10, verify_tls=False)
    with WorkerHttpClient(settings, transport=spy) as client:
        runtime = _runtime(client)
        client.heartbeat(_BOOT)
        _enqueue(app, project_id, resource)

        report = runtime.run_once()
        # Attempt is sealed; only the release response was lost.
        assert report.finished is True and report.state == "cleanup_pending"
        assert runtime.finished == 1
        assert runtime.pending_cleanup is not None
        key = runtime.pending_cleanup["idempotency_key"]
        assert key == f"cleanup-{runtime.pending_cleanup['payload']['attempt_id']}"

        receipt = runtime.confirm_pending_cleanup()
        assert receipt is not None and receipt["replayed"] is True and receipt["released"] is True
        assert runtime.pending_cleanup is None
        assert runtime.confirm_pending_cleanup() is None
        assert [r.headers["Idempotency-Key"] for r in spy.cleanup_requests] == [key, key]
        assert _scalar(app, "SELECT COUNT(*) FROM leases WHERE physical_key_id = ?", (resource,)) == 0
        assert _scalar(app, "SELECT COUNT(*) FROM cleanup_confirmations") == 1

        # note_restart drops the in-memory cleanup state.
        runtime.note_restart()
        assert runtime.pending_cleanup is None


def _text(app, sql: str, params: tuple = ()) -> str:
    store = app.state.open_store()
    try:
        with store.transaction() as connection:
            row = connection.execute(sql, params).fetchone()
    finally:
        store.close()
    return str(row[0])
