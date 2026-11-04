"""RX-38: finish success gates + lost finish confirm; no duplicate dispatch."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
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
from aiqa.worker.runtime import HandlerResult, WorkerRuntime, WorkerRuntimeConfig


def _empty_ack_hash() -> str:
    return "sha256:" + hashlib.sha256(b"").hexdigest()


def _setup(tmp_path: Path, monkeypatch, *, now: datetime):
    root = tmp_path / "runtime"
    settings = load_settings(
        {"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}
    )
    app = create_app(settings)
    monkeypatch.setattr("aiqa.api.worker._server_now", lambda: now)
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("종료재연결", "rx38", "rx", "android"))
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
            (resource, now.isoformat()),
        )
    store.close()
    return app, project.project_id, resource, token


def _claim(client, app, project_id, resource, now, *, boot="boot-rx38", key="rx38-claim"):
    # Presence must exist before the job insert trigger pins job_worker_sessions.
    client.heartbeat(boot)
    store = app.state.open_store()
    try:
        with store.transaction() as connection:
            connection.execute(
                """
                INSERT INTO jobs (project_id, job_id, purpose, payload_hash, source_refs, limits, status)
                VALUES (?, ?, 'resource_probe', 'hash', ?, '{}', 'queued')
                """,
                (str(project_id), str(uuid4()), json.dumps([resource])),
            )
    finally:
        store.close()
    return client.claim(boot_id=boot, now=now.isoformat(), idempotency_key=key)


def test_rx_38_success_requires_ack_lease_boot_and_rejects_cancel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime(2026, 11, 4, 18, 0, tzinfo=timezone.utc)
    app, project_id, resource, token = _setup(tmp_path, monkeypatch, now=now)
    transport = SyncASGITransport(app)
    settings = WorkerClientSettings(
        base_url="https://127.0.0.1", token=token, timeout_seconds=10, verify_tls=False
    )
    with WorkerHttpClient(settings, transport=transport) as client:
        claimed = _claim(client, app, project_id, resource, now)
        assert claimed is not None
        base = {
            "project_id": claimed["project_id"],
            "job_id": claimed["job_id"],
            "attempt_id": claimed["attempt_id"],
            "generation": claimed["generation"],
            "final_seq": 0,
            "last_ack_seq": 0,
            "last_ack_hash": _empty_ack_hash(),
            "manifest_digest": claimed["snapshot"]["digest"],
            "physical_key_id": resource,
            "now": now.isoformat(),
            "source_artifact_hashes": [],
            "action_mapping": "{}",
            "outcome": "completed",
            "evidence_complete": True,
            "ambiguous_dispatch": False,
        }

        # No start ACK → success refused; job status unchanged.
        missing_ack = False
        try:
            client.finish_attempt(payload=base, idempotency_key="rx38-no-ack")
        except WorkerHttpError as exc:
            missing_ack = exc.status_code == 422
        store = app.state.open_store()
        with store.transaction() as connection:
            status_before = connection.execute(
                "SELECT status FROM jobs WHERE job_id = ?", (claimed["job_id"],)
            ).fetchone()[0]
        store.close()
        assert missing_ack and status_before in {"preparing", "running"}

        client.acknowledge(
            project_id=claimed["project_id"],
            job_id=claimed["job_id"],
            generation=claimed["generation"],
            runner_nonce=str(uuid4()),
            now=now.isoformat(),
            idempotency_key="rx38-ack",
        )

        # Expired lease → success refused.
        store = app.state.open_store()
        with store.transaction() as connection:
            connection.execute(
                "UPDATE leases SET expires_at = ? WHERE job_id = ?",
                ((now - timedelta(seconds=1)).isoformat(), claimed["job_id"]),
            )
            status_mid = connection.execute(
                "SELECT status FROM jobs WHERE job_id = ?", (claimed["job_id"],)
            ).fetchone()[0]
        store.close()
        expired = False
        try:
            client.finish_attempt(payload=base, idempotency_key="rx38-expired")
        except WorkerHttpError as exc:
            expired = exc.status_code == 422
        assert expired and status_mid in {"preparing", "running"}

        # Restore lease, then cancel blocks success.
        store = app.state.open_store()
        with store.transaction() as connection:
            connection.execute(
                "UPDATE leases SET expires_at = ? WHERE job_id = ?",
                ((now + timedelta(seconds=60)).isoformat(), claimed["job_id"]),
            )
            connection.execute(
                "UPDATE jobs SET status = 'cancel_requested' WHERE job_id = ?",
                (claimed["job_id"],),
            )
        store.close()
        cancelled = False
        try:
            client.finish_attempt(payload=base, idempotency_key="rx38-cancel")
        except WorkerHttpError as exc:
            cancelled = exc.status_code == 422
        assert cancelled

        # New boot mismatch → success refused; prior result still not completed.
        store = app.state.open_store()
        with store.transaction() as connection:
            connection.execute(
                "UPDATE jobs SET status = 'running' WHERE job_id = ?",
                (claimed["job_id"],),
            )
        store.close()
        client.heartbeat("boot-new")
        boot_mismatch = False
        try:
            client.finish_attempt(payload=base, idempotency_key="rx38-boot")
        except WorkerHttpError as exc:
            boot_mismatch = exc.status_code == 422
        store = app.state.open_store()
        with store.transaction() as connection:
            final_status = connection.execute(
                "SELECT status FROM jobs WHERE job_id = ?", (claimed["job_id"],)
            ).fetchone()[0]
            finishes = connection.execute(
                "SELECT COUNT(*) FROM attempt_finish_requests WHERE attempt_id = ? AND body_hash IS NOT NULL",
                (claimed["attempt_id"],),
            ).fetchone()[0]
        store.close()
        assert boot_mismatch and final_status in {"preparing", "running"}
        assert finishes == 0


def test_rx_38_lost_finish_confirm_and_ack_loss_no_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime(2026, 11, 4, 18, 30, tzinfo=timezone.utc)
    app, project_id, resource, token = _setup(tmp_path / "rt", monkeypatch, now=now)
    calls = {"n": 0}

    class CountingHandler:
        def handle(self, claim):
            calls["n"] += 1
            return HandlerResult(
                actions=1,
                outcome="completed",
                evidence_complete=True,
                ambiguous_dispatch=False,
                final_seq=0,
                last_ack_seq=0,
                last_ack_hash=_empty_ack_hash(),
            )

    # ACK loss → handler never runs.
    def ack_fail(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/heartbeats"):
            return httpx.Response(200, json={"state": "online"})
        if path.endswith("/claims"):
            return httpx.Response(
                200,
                json={
                    "project_id": str(uuid4()),
                    "job_id": str(uuid4()),
                    "attempt_id": str(uuid4()),
                    "generation": 1,
                    "physical_key_id": resource,
                    "snapshot": {
                        "purpose": "resource_probe",
                        "digest": "sha256:abc",
                        "target_ref": "android:emulator-5580",
                    },
                },
            )
        if path.endswith("/attempt-acks"):
            return httpx.Response(503, json={"error": "unavailable"})
        return httpx.Response(204)

    settings = WorkerClientSettings(
        base_url="https://manage.example", token=token, verify_tls=False
    )
    with WorkerHttpClient(settings, transport=httpx.MockTransport(ack_fail)) as client:
        runtime = WorkerRuntime(
            client,
            WorkerRuntimeConfig(boot_id="boot-ack", prepared_adapters=frozenset({"resource_probe"})),
            CountingHandler(),
        )
        report = runtime.run_once()
    assert report.finished is False
    assert calls["n"] == 0
    assert runtime.finished == 0

    # Lost finish response → not complete until confirm with same key/body.
    finish_hits = {"n": 0}

    def finish_flaky(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/heartbeats"):
            return httpx.Response(200, json={"state": "online"})
        if path.endswith("/claims"):
            return httpx.Response(
                200,
                json={
                    "project_id": str(project_id),
                    "job_id": str(uuid4()),
                    "attempt_id": str(uuid4()),
                    "generation": 1,
                    "physical_key_id": resource,
                    "snapshot": {
                        "purpose": "resource_probe",
                        "digest": "sha256:xyz",
                        "target_ref": "android:emulator-5580",
                    },
                },
            )
        if path.endswith("/attempt-acks"):
            return httpx.Response(200, json={"attempt_id": "ok", "runner_nonce": str(uuid4()), "replayed": False})
        if path.endswith("/attempt-finishes"):
            finish_hits["n"] += 1
            if finish_hits["n"] == 1:
                return httpx.Response(503, json={"error": "lost"})
            return httpx.Response(
                201,
                json={
                    "project_id": str(project_id),
                    "job_id": str(uuid4()),
                    "attempt_id": str(uuid4()),
                    "status": "completed",
                    "outcome": "completed",
                    "replayed": finish_hits["n"] > 2,
                    "approved": False,
                    "verdict": None,
                    "purpose": "resource_probe",
                },
            )
        return httpx.Response(204)

    with WorkerHttpClient(settings, transport=httpx.MockTransport(finish_flaky)) as client:
        runtime = WorkerRuntime(
            client,
            WorkerRuntimeConfig(boot_id="boot-fin", prepared_adapters=frozenset({"resource_probe"})),
            CountingHandler(),
        )
        lost = runtime.run_once()
        assert lost.finished is False
        assert runtime.pending_finish is not None
        assert calls["n"] == 1
        confirmed = runtime.confirm_pending_finish()
        assert confirmed is not None
        assert runtime.finished == 1
        assert runtime.pending_finish is None
        # Confirm again does nothing new; handler not re-invoked.
        assert runtime.confirm_pending_finish() is None
        assert calls["n"] == 1
        assert finish_hits["n"] == 2
