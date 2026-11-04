"""RX-07: worker attempt finishes, evidence/dispatch gates, and no worker approval."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from aiqa.api.app import create_app
from aiqa.api.auth import bound_auth_store, enroll_worker
from aiqa.config import WorkerClientSettings, load_settings
from aiqa.contracts.worker_attempt import WorkerAttemptFinishInput, WorkerAttemptFinishReceipt
from aiqa.domain.projects import bind_store, create_project
from aiqa.store.database import migrate_store
from aiqa.store.models import Actor, ProjectCreate
from aiqa.worker.http_client import SyncASGITransport, WorkerHttpClient, WorkerHttpError


def _empty_ack_hash() -> str:
    return "sha256:" + hashlib.sha256(b"").hexdigest()


def test_finish_dto_never_approves() -> None:
    receipt = WorkerAttemptFinishReceipt(
        uuid4(), uuid4(), uuid4(), "completed", "completed", False, False, None, "resource_probe"
    )
    assert receipt.approved is False
    finish = WorkerAttemptFinishInput(
        uuid4(),
        uuid4(),
        uuid4(),
        1,
        "completed",
        0,
        0,
        _empty_ack_hash(),
        "sha256:abc",
        True,
        False,
    )
    assert finish.evidence_complete is True
    assert finish.ambiguous_dispatch is False


def test_attempt_finish_gates_idempotency_and_no_approval(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "runtime"
    settings = load_settings(
        {"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}
    )
    app = create_app(settings)
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("종료", "rx07", "rx", "android"))
    actor = Actor(owner.actor_id, project.project_id, True)
    worker_id = str(uuid4())
    other_worker = str(uuid4())
    with bound_auth_store(store):
        token = enroll_worker(actor, worker_id, "resource_probe")
        other_token = enroll_worker(actor, other_worker, "resource_probe")
    resource = str(uuid4())
    now = datetime(2026, 11, 3, 18, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("aiqa.api.worker._server_now", lambda: now)
    with store.transaction() as connection:
        connection.execute(
            "INSERT INTO physical_resource_keys (physical_key_id, worker_id, native_id) VALUES (?, ?, ?)",
            (resource, worker_id, "emulator-5580"),
        )
        connection.execute(
            "INSERT INTO resource_aliases (project_id, physical_key_id, display_name, target_kind) VALUES (?, ?, ?, ?)",
            (str(project.project_id), resource, "종료기기", "android"),
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

    observed = _exercise(app, project.project_id, resource, token, other_token, now)
    assert observed == {
        "success": True,
        "worker_cannot_approve": True,
        "replayed": True,
        "missing_evidence": True,
        "ambiguous": True,
        "foreign_worker": True,
        "migration": True,
        "status_completed": True,
    }


def _exercise(app, project_id, resource: str, token: str, other_token: str, now: datetime) -> dict[str, object]:
    transport = SyncASGITransport(app)
    settings = WorkerClientSettings(
        base_url="https://127.0.0.1", token=token, timeout_seconds=10, verify_tls=False
    )
    with WorkerHttpClient(settings, transport=transport) as client:
        client.heartbeat("boot-rx07")
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
        claimed = client.claim(boot_id="boot-rx07", now=now.isoformat(), idempotency_key="rx07-claim")
        assert claimed is not None
        client.acknowledge(
            project_id=claimed["project_id"],
            job_id=claimed["job_id"],
            generation=claimed["generation"],
            runner_nonce=str(uuid4()),
            now=now.isoformat(),
            idempotency_key="rx07-ack",
        )
        digest = claimed["snapshot"]["digest"]
        base = {
            "project_id": claimed["project_id"],
            "job_id": claimed["job_id"],
            "attempt_id": claimed["attempt_id"],
            "generation": claimed["generation"],
            "final_seq": 0,
            "last_ack_seq": 0,
            "last_ack_hash": _empty_ack_hash(),
            "manifest_digest": digest,
            "physical_key_id": resource,
            "now": now.isoformat(),
            "source_artifact_hashes": [],
            "action_mapping": "{}",
        }

        missing = False
        try:
            client.finish_attempt(
                payload={**base, "outcome": "completed", "evidence_complete": False, "ambiguous_dispatch": False},
                idempotency_key="rx07-missing",
            )
        except WorkerHttpError as exc:
            missing = exc.status_code == 422

        ambiguous = False
        try:
            client.finish_attempt(
                payload={**base, "outcome": "completed", "evidence_complete": True, "ambiguous_dispatch": True},
                idempotency_key="rx07-ambiguous",
            )
        except WorkerHttpError as exc:
            ambiguous = exc.status_code == 422

        foreign = False
        other_settings = WorkerClientSettings(
            base_url="https://127.0.0.1", token=other_token, timeout_seconds=10, verify_tls=False
        )
        with WorkerHttpClient(other_settings, transport=transport) as other:
            other.heartbeat("boot-other")
            try:
                other.finish_attempt(
                    payload={
                        **base,
                        "outcome": "completed",
                        "evidence_complete": True,
                        "ambiguous_dispatch": False,
                    },
                    idempotency_key="rx07-foreign",
                )
            except WorkerHttpError as exc:
                foreign = exc.status_code in {403, 409, 422}

        first = client.finish_attempt(
            payload={**base, "outcome": "completed", "evidence_complete": True, "ambiguous_dispatch": False},
            idempotency_key="rx07-finish",
        )
        second = client.finish_attempt(
            payload={**base, "outcome": "completed", "evidence_complete": True, "ambiguous_dispatch": False},
            idempotency_key="rx07-finish",
        )

        store = app.state.open_store()
        try:
            with store.transaction() as connection:
                status = connection.execute(
                    "SELECT status FROM jobs WHERE job_id = ?",
                    (claimed["job_id"],),
                ).fetchone()[0]
                finishes = connection.execute(
                    "SELECT COUNT(*) FROM attempt_finish_requests WHERE attempt_id = ?",
                    (claimed["attempt_id"],),
                ).fetchone()[0]
                migration = (
                    connection.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='attempt_finish_requests'"
                    ).fetchone()
                    is not None
                )
                approvals = connection.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='approvals'"
                ).fetchone()[0]
        finally:
            store.close()

        return {
            "success": first["status"] == "completed" and first["outcome"] == "completed",
            "worker_cannot_approve": first["approved"] is False and second["approved"] is False,
            "replayed": second["replayed"] is True and finishes == 1,
            "missing_evidence": missing,
            "ambiguous": ambiguous,
            "foreign_worker": foreign,
            "migration": migration,
            "status_completed": status == "completed" and approvals >= 0,
        }
