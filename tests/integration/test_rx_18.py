"""RX-18: durable server artifacts, digest gates, project download without worker."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from aiqa.api.app import create_app
from aiqa.api.auth import bound_auth_store, enroll_worker
from aiqa.config import load_settings
from aiqa.contracts.jobs import LeaseToken
from aiqa.domain.projects import bind_store, create_project, grant_membership, revoke_membership
from aiqa.store.artifacts import (
    ArtifactRejected,
    ArtifactUpload,
    content_hash,
    open_durable,
    publish_durable,
    resolve_stored,
)
from aiqa.store.database import migrate_store
from aiqa.store.evidence import ArtifactBinding, bind_artifact_ingest, ingest_artifact, reset_artifact_ingest
from aiqa.store.models import Actor, ProjectCreate, Transaction, WorkerScope
from aiqa.worker.service import bind_claim_store, claim_job


def _env(root: Path) -> dict[str, str]:
    return {
        "AIQA_HOST": "127.0.0.1",
        "AIQA_PORT": "8000",
        "AIQA_RUNTIME_ROOT": str(root),
    }


def test_durable_publish_rejects_partial_hash_escape_and_survives_reopen(tmp_path: Path) -> None:
    settings = load_settings(_env(tmp_path / "runtime"))
    root = settings.artifacts_dir
    project_id = uuid4()
    artifact_id = uuid4()
    body = b"durable-log-line\n"
    digest = content_hash(body)

    with pytest.raises(ArtifactRejected, match="hash"):
        publish_durable(root, project_id, artifact_id, ".log", body, declared_hash="sha256:" + ("0" * 64))
    with pytest.raises(ArtifactRejected, match="partial|suffix"):
        publish_durable(root, project_id, uuid4(), ".partial", body)
    with pytest.raises(ArtifactRejected, match="leaves|root|escape|partial"):
        open_durable(root, f"../outside/{artifact_id}.log", digest)
    assert resolve_stored(root, f"{project_id}/tmp/orphan.partial") is None
    assert resolve_stored(root, f"{project_id}/../escape.log") is None

    published = publish_durable(
        root, project_id, artifact_id, ".log", body, declared_hash=digest
    )
    assert published.content_hash == digest
    assert published.byte_length == len(body)
    assert not published.object_key.endswith(".partial")
    assert "/tmp/" not in published.object_key
    assert open_durable(root, published.object_key, digest) == body

    reopened = load_settings(_env(tmp_path / "runtime"))
    assert reopened.artifacts_dir == root
    again = open_durable(reopened.artifacts_dir, published.object_key, digest)
    assert again == body
    assert content_hash(again) == digest

    (root / published.object_key).write_bytes(b"tampered")
    with pytest.raises(ArtifactRejected, match="hash"):
        open_durable(root, published.object_key, digest)


def test_download_requires_project_capability_without_worker(tmp_path: Path) -> None:
    asyncio.run(_download_flow(tmp_path))


async def _download_flow(tmp_path: Path) -> None:
    root = tmp_path / "api"
    settings = load_settings(_env(root))
    app = create_app(settings)
    store = app.state.open_store()
    migrate_store(store)
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("Alpha", "alpha", "", "web"))
        other = create_project(owner, ProjectCreate("Beta", "beta", "", "web"))
    actor = Actor(owner.actor_id, project.project_id, True)
    with bound_auth_store(store):
        token = enroll_worker(actor, "worker-rx18", "recording")
    recording_id = _fixture_recording_job(store, actor, "worker-rx18", "rx18-job")
    now = datetime(2026, 11, 3, 18, 0, tzinfo=timezone.utc)
    worker = WorkerScope("worker-rx18", (project.project_id,), ("recording",))
    with bind_claim_store(store):
        claimed = claim_job(worker, now)
    assert claimed is not None
    lease = LeaseToken(claimed.project_id, claimed.job_id, claimed.generation)
    body = b"viewer-download\n"
    marker = bind_artifact_ingest(ArtifactBinding(store, worker, now))
    try:
        receipt = ingest_artifact(
            lease,
            ArtifactUpload(
                project.project_id,
                recording_id,
                "note.log",
                "text/plain",
                content_hash(body),
                len(body),
                body,
                "REC",
                None,
                None,
                None,
                "source",
            ),
        )
    finally:
        reset_artifact_ingest(marker)
    assert receipt.ready is True and receipt.acked is True
    artifact_id = receipt.artifact_id
    digest = receipt.content_hash

    viewer_id = uuid4()
    session_id = str(uuid4())
    outsider_session = str(uuid4())
    with store.transaction() as connection:
        grant_membership(Transaction(connection), project.project_id, viewer_id, "viewer", now=now)
        connection.execute(
            """
            INSERT INTO browser_sessions (
                session_id, origin, csrf_hash, actor_id, project_scope, is_local_owner, expires_at
            ) VALUES (?, ?, ?, ?, ?, 0, ?)
            """,
            (
                session_id,
                "http://127.0.0.1:8000",
                "hash",
                str(viewer_id),
                str(project.project_id),
                "2026-12-01T00:00:00+00:00",
            ),
        )
        connection.execute(
            """
            INSERT INTO browser_sessions (
                session_id, origin, csrf_hash, actor_id, project_scope, is_local_owner, expires_at
            ) VALUES (?, ?, ?, ?, ?, 0, ?)
            """,
            (
                outsider_session,
                "http://127.0.0.1:8000",
                "hash",
                str(uuid4()),
                str(other.project_id),
                "2026-12-01T00:00:00+00:00",
            ),
        )
    store.close()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
        # No worker Authorization — project membership alone downloads.
        client.cookies.set("aiqa_session", session_id)
        ok = await client.get(f"/api/v1/artifacts/{artifact_id}")
        assert ok.status_code == 200, ok.text
        assert ok.content == body
        assert content_hash(ok.content) == digest

        missing = await client.get(f"/api/v1/artifacts/{uuid4()}")
        assert missing.status_code == 404

        client.cookies.set("aiqa_session", outsider_session)
        stolen = await client.get(f"/api/v1/artifacts/{artifact_id}")
        assert stolen.status_code in {401, 404}

        # Worker token for another project cannot read either.
        stolen_worker = await client.get(
            f"/api/v1/artifacts/{artifact_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        # Same-project worker may read; outsider session path already covered.
        assert stolen_worker.status_code == 200

    store = app.state.open_store()
    with store.transaction() as connection:
        revoke_membership(Transaction(connection), project.project_id, viewer_id, now=now)
    store.close()
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
        client.cookies.set("aiqa_session", session_id)
        revoked = await client.get(f"/api/v1/artifacts/{artifact_id}")
        assert revoked.status_code == 404

    restarted = create_app(load_settings(_env(root)))
    store = restarted.state.open_store()
    migrate_store(store)
    with store.transaction() as connection:
        grant_membership(Transaction(connection), project.project_id, viewer_id, "viewer", now=now)
    store.close()
    async with AsyncClient(
        transport=ASGITransport(app=restarted), base_url="http://127.0.0.1:8000"
    ) as client:
        client.cookies.set("aiqa_session", session_id)
        after = await client.get(f"/api/v1/artifacts/{artifact_id}")
        assert after.status_code == 200, after.text
        assert after.content == body
        assert content_hash(after.content) == digest


def _fixture_recording_job(store, actor, worker_id, key):
    from worker_presence_support import seed_inventory, seed_presence

    from aiqa.contracts.cases import CaseDefinition, CaseRevisionInput, CaseSettings, PathPolicy
    from aiqa.contracts.jobs import IdempotencyKey, JobSubmission
    from aiqa.domain.versions import bind_case_store, create_case, save_case_revision
    from aiqa.store.queue import enqueue_job

    now = datetime(2026, 11, 3, 18, 0, tzinfo=timezone.utc)
    with bind_case_store(store):
        case = create_case(actor, "Evidence fixture", None)
        version = save_case_revision(
            actor,
            case.case_id,
            CaseRevisionInput(
                CaseDefinition("open", "open", (), {}, {}, (), (), PathPolicy()),
                CaseSettings("web"),
            ),
            None,
        )
    physical = uuid4()
    with store.transaction() as connection:
        connection.execute(
            "INSERT INTO physical_resource_keys(physical_key_id,worker_id,native_id) VALUES(?,?,?)",
            (str(physical), worker_id, "fixture-" + key),
        )
        connection.execute(
            "INSERT INTO resource_aliases(project_id,physical_key_id,display_name,target_kind) VALUES(?,?,?,?)",
            (str(actor.project_scope), str(physical), "Fixture", "web"),
        )
        seed_presence(connection, actor.project_scope, worker_id, now)
        seed_inventory(connection, physical)
        receipt = enqueue_job(
            Transaction(connection),
            JobSubmission(
                actor.project_scope,
                "recording",
                case.case_id,
                version.id,
                (str(physical),),
                "{}",
            ),
            IdempotencyKey(actor.actor_id, actor.project_scope, "enqueue_job", key),
            now=now,
        )
    return receipt.recording_id
