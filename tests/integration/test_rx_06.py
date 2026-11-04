"""RX-06: sanitized evidence commit ACK, idempotency, and late isolation."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from aiqa.api.app import create_app
from aiqa.api.auth import bound_auth_store, enroll_worker
from aiqa.config import load_settings
from aiqa.contracts.evidence import EvidenceCommitAck, EvidenceEnvelope, IngestReceipt
from aiqa.domain.projects import bind_store, create_project
from aiqa.store.database import migrate_store
from aiqa.store.models import Actor, ProjectCreate
from aiqa.config import WorkerClientSettings
from aiqa.worker.http_client import SanitizationRequired, SyncASGITransport, WorkerHttpClient
from aiqa.worker.spool import EvidenceSpool


def _sha(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def test_client_blocks_unsanitized_and_spool_requires_matching_ack(tmp_path: Path) -> None:
    settings = WorkerClientSettings(
        base_url="https://mgmt.example.test",
        token="tok",
        timeout_seconds=5,
        verify_tls=True,
        ca_bundle=None,
    )
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json={"attempt_id": str(uuid4()), "contiguous_seq": 1, "prefix_hash": "sha256:x"})

    with WorkerHttpClient(settings, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SanitizationRequired):
            client.commit_evidence(
                sanitized=False,
                project_id=str(uuid4()),
                job_id=str(uuid4()),
                generation=1,
                now="2026-11-03T12:00:00+00:00",
                events=[],
                artifacts=[],
                idempotency_key="no-send",
            )
    assert calls == []

    spool = EvidenceSpool(tmp_path / "spool")
    attempt = uuid4()
    old = datetime(2026, 10, 20, tzinfo=timezone.utc).isoformat()
    spool.append(EvidenceEnvelope(attempt, 1, b"png", "log", old))
    bad = spool.acknowledge(IngestReceipt(attempt, 1, "sha256:" + ("0" * 64), 0))
    good_hash = spool.prefix_hash(attempt, 1)
    good = spool.acknowledge(
        IngestReceipt(attempt, 1, good_hash, 0)
    )
    wire = EvidenceCommitAck(attempt, 1, good_hash, 0, False, 0)
    applied = spool.apply_commit_ack(wire)
    spool.purge(datetime(2026, 11, 3, tzinfo=timezone.utc))
    assert bad.accepted is False
    assert good.accepted is True
    assert applied.accepted is True
    assert not (tmp_path / "spool" / str(attempt) / "1.png").exists()


def test_evidence_commit_idempotent_hash_auth_and_late(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "runtime"
    settings = load_settings(
        {"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}
    )
    app = create_app(settings)
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("증거", "rx06", "rx", "android"))
    actor = Actor(owner.actor_id, project.project_id, True)
    worker_id = str(uuid4())
    with bound_auth_store(store):
        token = enroll_worker(actor, worker_id, "resource_probe")
    resource = str(uuid4())
    now = datetime(2026, 11, 3, 17, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("aiqa.api.worker._server_now", lambda: now)
    with store.transaction() as connection:
        connection.execute(
            "INSERT INTO physical_resource_keys (physical_key_id, worker_id, native_id) VALUES (?, ?, ?)",
            (resource, worker_id, "emulator-5580"),
        )
        connection.execute(
            "INSERT INTO resource_aliases (project_id, physical_key_id, display_name, target_kind) VALUES (?, ?, ?, ?)",
            (str(project.project_id), resource, "별칭", "android"),
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

    observed = _exercise(app, project.project_id, resource, token, now, root)
    assert observed == {
        "commit_ok": True,
        "wire_fields": True,
        "replay_dupes": 0,
        "bad_hash": True,
        "forbidden": True,
        "late_ok": True,
        "verdict_unchanged": True,
        "evidence_status_unchanged": True,
        "late_inbox": True,
        "migration": True,
    }


def _exercise(app, project_id, resource: str, token: str, now: datetime, root: Path) -> dict[str, object]:
    transport = SyncASGITransport(app)
    client_settings = WorkerClientSettings(
        base_url="https://127.0.0.1",
        token=token,
        timeout_seconds=10,
        verify_tls=False,
        ca_bundle=None,
    )
    with WorkerHttpClient(client_settings, transport=transport) as client:
        client.heartbeat("boot-rx06")
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
        claimed = client.claim(boot_id="boot-rx06", now=now.isoformat(), idempotency_key="rx06-claim")
        assert claimed is not None, "claim should return a receipt"
        client.acknowledge(
            project_id=claimed["project_id"],
            job_id=claimed["job_id"],
            generation=claimed["generation"],
            runner_nonce=str(uuid4()),
            now=now.isoformat(),
            idempotency_key="rx06-ack",
        )
        attempt_id = claimed["attempt_id"]
        event_body = json.dumps({"step": 1}, separators=(",", ":"))
        payload_hash = _sha(b"1\n" + event_body.encode())
        body_hash = _sha(event_body.encode())
        event = {
            "event_id": str(uuid4()),
            "attempt_id": attempt_id,
            "local_seq": 1,
            "captured_at": now.isoformat(),
            "event_type": "action.observed",
            "minimum_facts": "{}",
            "payload_hash": payload_hash,
            "body_hash": body_hash,
            "detail_payload": event_body,
        }
        png = b"\x89PNG\r\n\x1a\n" + b"rx06"
        first = client.commit_evidence(
            sanitized=True,
            project_id=claimed["project_id"],
            job_id=claimed["job_id"],
            generation=claimed["generation"],
            now=now.isoformat(),
            events=[event],
            artifacts=[],
            idempotency_key="rx06-commit",
        )
        wire_fields = (
            "contiguous_seq" in first
            and "prefix_hash" in first
            and first["attempt_id"] == attempt_id
            and first["contiguous_seq"] == 1
            and first["prefix_hash"].startswith("sha256:")
            and first["late"] is False
        )
        second = client.commit_evidence(
            sanitized=True,
            project_id=claimed["project_id"],
            job_id=claimed["job_id"],
            generation=claimed["generation"],
            now=now.isoformat(),
            events=[event],
            artifacts=[],
            idempotency_key="rx06-commit",
        )
        assert second["contiguous_seq"] == first["contiguous_seq"]
        assert second["prefix_hash"] == first["prefix_hash"]

        store = app.state.open_store()
        try:
            with store.transaction() as connection:
                events_after_replay = connection.execute(
                    "SELECT COUNT(*) FROM attempt_events WHERE attempt_id = ?",
                    (attempt_id,),
                ).fetchone()[0]
        finally:
            store.close()
        replay_dupes = events_after_replay - 1

        bad_event = dict(event)
        bad_event["event_id"] = str(uuid4())
        bad_event["payload_hash"] = _sha(b"tampered")
        bad_hash = False
        try:
            client.commit_evidence(
                sanitized=True,
                project_id=claimed["project_id"],
                job_id=claimed["job_id"],
                generation=claimed["generation"],
                now=now.isoformat(),
                events=[bad_event],
                artifacts=[],
                idempotency_key="rx06-bad-hash",
            )
        except Exception as exc:
            bad_hash = getattr(exc, "status_code", None) in {409, 422}

        foreign = WorkerClientSettings(
            base_url="https://127.0.0.1",
            token="not-a-token",
            timeout_seconds=10,
            verify_tls=False,
            ca_bundle=None,
        )
        forbidden = False
        with WorkerHttpClient(foreign, transport=transport) as other:
            try:
                other.commit_evidence(
                    sanitized=True,
                    project_id=claimed["project_id"],
                    job_id=claimed["job_id"],
                    generation=claimed["generation"],
                    now=now.isoformat(),
                    events=[event],
                    artifacts=[],
                    idempotency_key="rx06-forbidden",
                )
            except Exception as exc:
                forbidden = getattr(exc, "status_code", None) in {401, 403}

        store = app.state.open_store()
        try:
            with store.transaction() as connection:
                connection.execute(
                    "UPDATE jobs SET status = 'completed' WHERE job_id = ?",
                    (claimed["job_id"],),
                )
                connection.execute(
                    """
                    INSERT INTO job_finish_facts (
                        project_id, job_id, verdict, finish_reason, cleanup_failed, resource_state, created_at
                    ) VALUES (?, ?, 'FAIL', 'cancelled', 0, 'unchanged', ?)
                    """,
                    (claimed["project_id"], claimed["job_id"], now.isoformat()),
                )
                before_verdict = connection.execute(
                    "SELECT verdict FROM job_finish_facts WHERE job_id = ?",
                    (claimed["job_id"],),
                ).fetchone()[0]
        finally:
            store.close()

        late_event = {
            "event_id": str(uuid4()),
            "attempt_id": attempt_id,
            "local_seq": 2,
            "captured_at": (now + timedelta(seconds=1)).isoformat(),
            "event_type": "action.observed",
            "minimum_facts": "{}",
            "payload_hash": _sha(b"2\nlate"),
            "body_hash": _sha(b"late"),
            "detail_payload": "late",
        }
        late = client.commit_evidence(
            sanitized=True,
            project_id=claimed["project_id"],
            job_id=claimed["job_id"],
            generation=claimed["generation"],
            now=(now + timedelta(seconds=2)).isoformat(),
            events=[late_event],
            artifacts=[
                {
                    "filename": "late.png",
                    "media_type": "image/png",
                    "declared_hash": _sha(png),
                    "declared_length": len(png),
                    "body_b64": base64.b64encode(png).decode("ascii"),
                    "owner_kind": "REC",
                    "owner_id": str(uuid4()),
                    "attempt_id": attempt_id,
                    "role": "source",
                }
            ],
            idempotency_key="rx06-late",
        )

        store = app.state.open_store()
        try:
            with store.transaction() as connection:
                after_verdict = connection.execute(
                    "SELECT verdict FROM job_finish_facts WHERE job_id = ?",
                    (claimed["job_id"],),
                ).fetchone()[0]
                event_count_after = connection.execute(
                    "SELECT COUNT(*) FROM attempt_events WHERE attempt_id = ?",
                    (attempt_id,),
                ).fetchone()[0]
                stale = connection.execute(
                    "SELECT COUNT(*) FROM stale_event_inbox WHERE attempt_id = ?",
                    (attempt_id,),
                ).fetchone()[0]
                late_arts = connection.execute(
                    "SELECT COUNT(*) FROM late_evidence_inbox WHERE attempt_id = ?",
                    (attempt_id,),
                ).fetchone()[0]
                job_status = connection.execute(
                    "SELECT status FROM jobs WHERE job_id = ?",
                    (claimed["job_id"],),
                ).fetchone()[0]
                evidence_status_unchanged = (
                    job_status == "completed"
                    and after_verdict == before_verdict
                    and event_count_after == 1
                )
                migration = (
                    connection.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='evidence_commit_requests'"
                    ).fetchone()
                    is not None
                )
        finally:
            store.close()

        return {
            "commit_ok": first["contiguous_seq"] == 1,
            "wire_fields": wire_fields,
            "replay_dupes": replay_dupes,
            "bad_hash": bad_hash,
            "forbidden": forbidden,
            "late_ok": late.get("late") is True and late["contiguous_seq"] == 1,
            "verdict_unchanged": after_verdict == "FAIL",
            "evidence_status_unchanged": evidence_status_unchanged,
            "late_inbox": stale >= 1 and late_arts >= 1,
            "migration": migration,
        }
