"""W14 spool journal tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from aiqa.contracts.evidence import EvidenceEnvelope, IngestReceipt
from aiqa.worker.service import (
    acknowledge_spool,
    append_evidence,
    bind_evidence_spool,
    mark_evidence_sent,
    note_evidence_pressure,
    purge_evidence,
)
from aiqa.worker.spool import EvidenceSpool, SpoolError
import pytest


def test_w14_01(tmp_path: Path) -> None:
    root = tmp_path / "spool"
    spool = EvidenceSpool(root)
    attempt = uuid4()
    now = datetime(2026, 11, 1, tzinfo=timezone.utc)
    old = (now - timedelta(days=8)).isoformat()
    with bind_evidence_spool(spool):
        first = append_evidence(EvidenceEnvelope(attempt, 1, b"png-1", "log-1", old))
        again = append_evidence(EvidenceEnvelope(attempt, 1, b"png-1", "log-1", old))
        with pytest.raises(SpoolError):
            append_evidence(EvidenceEnvelope(attempt, 1, b"png-other", "log-other", old))
        third = append_evidence(EvidenceEnvelope(attempt, 3, b"png-3", "log-3", old))
        reopened = EvidenceSpool(root)
        assert reopened.has_file(attempt, 1) and reopened.has_file(attempt, 3)
        mark_evidence_sent(attempt, 3)
        sent = EvidenceSpool(root)
        assert sent.has_file(attempt, 3)
        bad = acknowledge_spool(IngestReceipt(attempt, 1, "sha256:" + ("0" * 64), 0))
        good = acknowledge_spool(IngestReceipt(attempt, 1, spool.prefix_hash(attempt, 1), 0))
        blocked = acknowledge_spool(IngestReceipt(attempt, 3, spool.prefix_hash(attempt, 1), 0))
        purge_evidence(now)
        note_evidence_pressure()
        pressured = append_evidence(EvidenceEnvelope(attempt, 4, b"png-4", "log-4", now.isoformat()))
    observed = {
        "unacked_deleted": spool.unacked_deleted,
        "ack_hash_required": bad.accepted is False and good.accepted is True,
        "duplicate_actions_from_upload": spool.duplicate_actions_from_upload,
        "pressure_stops_actions": spool.pressure_stops_actions,
    }
    assert first.durable is True and again.payload_hash == first.payload_hash
    assert third.durable is True
    assert not (root / str(attempt) / "1.png").exists()
    assert (root / str(attempt) / "3.png").read_bytes() == b"png-3"
    assert blocked.accepted is False
    assert pressured.durable is False
    assert not (root / str(attempt) / "4.png").exists()
    assert observed == {
        "unacked_deleted": 0,
        "ack_hash_required": True,
        "duplicate_actions_from_upload": 0,
        "pressure_stops_actions": True,
    }


def test_w14_02(tmp_path: Path) -> None:
    from datetime import datetime, timezone
    from uuid import uuid4

    from aiqa.api.app import create_app
    from aiqa.api.auth import bound_auth_store, enroll_worker
    from aiqa.config import load_settings
    from aiqa.contracts.jobs import IdempotencyKey, JobSubmission, LeaseToken
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.store.artifacts import ArtifactUpload, content_hash
    from aiqa.store.database import migrate_store
    from aiqa.store.evidence import ArtifactBinding, bind_artifact_ingest, ingest_artifact, reset_artifact_ingest
    from aiqa.store.models import Actor, ProjectCreate, Transaction, WorkerScope
    from aiqa.store.queue import LeaseDenied, enqueue_job
    from aiqa.worker.service import bind_claim_store, claim_job

    root = tmp_path / "runtime"
    app = create_app(
        load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)})
    )
    assert any(getattr(route, "path", None) == "/api/v1/worker/artifacts" for route in app.routes)
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("Alpha", "w1402", "a", "web"))
    actor = Actor(owner.actor_id, project.project_id, True)
    with bound_auth_store(store):
        enroll_worker(actor, "worker-14", "recording")
    recording_id = _fixture_recording_job(store, actor, "worker-14", "w1402-job")
    now = datetime(2026, 11, 1, 1, 0, tzinfo=timezone.utc)
    worker = WorkerScope("worker-14", (project.project_id,), ("recording",))
    with bind_claim_store(store):
        claimed = claim_job(worker, now)
    assert claimed is not None
    lease = LeaseToken(claimed.project_id, claimed.job_id, claimed.generation)
    body = b"png-ready"
    upload = ArtifactUpload(
        project.project_id,
        recording_id,
        "shot.png",
        "image/png",
        content_hash(body),
        len(body),
        body,
    )
    marker = bind_artifact_ingest(ArtifactBinding(store, worker, now))
    try:
        first = ingest_artifact(lease, upload)
        second = ingest_artifact(lease, upload)
        mismatched = ingest_artifact(
            lease,
            ArtifactUpload(
                project.project_id,
                upload.owner_id,
                "shot.png",
                "image/png",
                "sha256:" + ("0" * 64),
                len(b"png-bad"),
                b"png-bad",
            ),
        )
        escaped = ingest_artifact(
            lease,
            ArtifactUpload(
                project.project_id,
                upload.owner_id,
                "../outside.png",
                "image/png",
                content_hash(b"png-escape"),
                len(b"png-escape"),
                b"png-escape",
            ),
        )
        other = uuid4()
        denied = False
        try:
            ingest_artifact(
                lease,
                ArtifactUpload(
                    other,
                    upload.owner_id,
                    "shot.png",
                    "image/png",
                    content_hash(b"png-other"),
                    len(b"png-other"),
                    b"png-other",
                ),
            )
        except LeaseDenied:
            denied = True
        staged = ingest_artifact(
            lease,
            ArtifactUpload(
                project.project_id,
                upload.owner_id,
                "later.png",
                "image/png",
                content_hash(b"png-staged"),
                len(b"png-staged"),
                b"png-staged",
            ),
            fail_ready=True,
        )
        staged_row = store._connection.execute(
            "SELECT acked FROM artifact_objects WHERE artifact_id = ?",
            (str(staged.artifact_id),),
        ).fetchone()
        ready_rows = store._connection.execute(
            "SELECT object_key, content_hash FROM artifact_objects WHERE status = 'ready'"
        ).fetchall()
    finally:
        reset_artifact_ingest(marker)
        store.close()
    ready_mismatch = False
    for object_key, digest in ready_rows:
        file_path = root / "artifacts" / str(object_key)
        ready_mismatch = ready_mismatch or content_hash(file_path.read_bytes()) != str(digest)
    observed = {
        "ack_before_ready": staged.acked or staged_row is not None,
        "hash_mismatch_ready": mismatched.ready or mismatched.acked or ready_mismatch,
        "path_escape": (tmp_path / "outside.png").exists() or ".." in escaped.object_key or not denied,
        "duplicate_receipt_same": first.artifact_id == second.artifact_id and first.acked and second.acked,
    }
    assert first.ready is True and first.status == "ready"
    assert escaped.status == "quarantine"
    assert (root / "artifacts" / first.object_key).read_bytes() == body
    assert not (root / "artifacts" / staged.object_key).name.endswith(".partial")
    assert (root / "artifacts" / staged.object_key).exists()
    assert observed == {
        "ack_before_ready": False,
        "hash_mismatch_ready": False,
        "path_escape": False,
        "duplicate_receipt_same": True,
    }


def test_w14_03(tmp_path: Path) -> None:
    import asyncio
    from datetime import datetime, timedelta, timezone
    from uuid import uuid4

    import httpx

    from aiqa.api.app import create_app
    from aiqa.api.auth import bound_auth_store, enroll_worker
    from aiqa.config import load_settings
    from aiqa.contracts.jobs import IdempotencyKey, JobSubmission, LeaseToken
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.store.artifacts import ArtifactUpload, content_hash
    from aiqa.store.database import migrate_store
    from aiqa.store.evidence import (
        ArtifactBinding,
        bind_artifact_ingest,
        ingest_artifact,
        reconcile_artifacts,
        reset_artifact_ingest,
    )
    from aiqa.store.models import Actor, ProjectCreate, Transaction, WorkerScope
    from aiqa.store.queue import enqueue_job
    from aiqa.worker.service import bind_claim_store, claim_job

    root = tmp_path / "runtime"
    app = create_app(
        load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)})
    )
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("Alpha", "w1403", "a", "web"))
    actor = Actor(owner.actor_id, project.project_id, True)
    with bound_auth_store(store):
        token = enroll_worker(actor, "worker-1403", "recording")
    recording_id = _fixture_recording_job(store, actor, "worker-1403", "w1403-job")
    now = datetime(2026, 11, 1, 1, 0, tzinfo=timezone.utc)
    worker = WorkerScope("worker-1403", (project.project_id,), ("recording",))
    with bind_claim_store(store):
        claimed = claim_job(worker, now)
    assert claimed is not None
    lease = LeaseToken(claimed.project_id, claimed.job_id, claimed.generation)
    kept_body = b"png-kept"
    missing_body = b"png-missing"
    log_body = b"log-line"
    old_body = b"png-old"
    marker = bind_artifact_ingest(ArtifactBinding(store, worker, now))
    try:
        kept = ingest_artifact(lease, _upload(project.project_id, recording_id, "kept.png", "image/png", kept_body))
        missing = ingest_artifact(lease, _upload(project.project_id, recording_id, "gone.png", "image/png", missing_body))
        logged = ingest_artifact(lease, _upload(project.project_id, recording_id, "note.log", "text/plain", log_body))
        aged = ingest_artifact(lease, _upload(project.project_id, recording_id, "aged.png", "image/png", old_body))
        before = {
            str(row[0]): str(row[1])
            for row in store._connection.execute(
                "SELECT artifact_id, content_hash FROM artifact_objects"
            ).fetchall()
        }
        ready_count = store._connection.execute(
            "SELECT COUNT(*) FROM artifact_objects WHERE status = 'ready'"
        ).fetchone()
        (root / "artifacts" / missing.object_key).unlink()
        (root / "artifacts" / logged.object_key).write_bytes(b"log-changed")
        store._connection.execute(
            "UPDATE artifact_objects SET stored_at = ? WHERE artifact_id = ?",
            ((now - timedelta(days=31)).isoformat(), str(aged.artifact_id)),
        )
        partial = root / "artifacts" / str(project.project_id) / "tmp" / "orphan.partial"
        partial.parent.mkdir(parents=True, exist_ok=True)
        partial.write_bytes(b"partial")
        (root / "artifacts" / str(project.project_id) / "crash.png").write_bytes(b"crash")
        report = reconcile_artifacts()
        after = {
            str(row[0]): str(row[1])
            for row in store._connection.execute(
                "SELECT artifact_id, content_hash FROM artifact_objects"
            ).fetchall()
        }
        ready_after = store._connection.execute(
            "SELECT COUNT(*) FROM artifact_objects WHERE status = 'ready'"
        ).fetchone()
        session_id = str(uuid4())
        store._connection.execute(
            """
            INSERT INTO browser_sessions (
                session_id, origin, csrf_hash, actor_id, project_scope, is_local_owner, expires_at
            ) VALUES (?, ?, ?, ?, ?, 1, ?)
            """,
            (
                session_id,
                "http://127.0.0.1:8000",
                "hash",
                str(owner.actor_id),
                str(project.project_id),
                "2026-12-01T00:00:00+00:00",
            ),
        )
    finally:
        reset_artifact_ingest(marker)
        store.close()

    async def read() -> tuple[int, int, int, str, str, str]:
        origin = "http://127.0.0.1:8000"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
            kept_response = await client.get(
                f"/api/v1/artifacts/{kept.artifact_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            missing_response = await client.get(
                f"/api/v1/artifacts/{missing.artifact_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            changed_response = await client.get(
                f"/api/v1/artifacts/{logged.artifact_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            client.cookies.set("aiqa_session", session_id)
            missing_page = await client.get(f"/ui/projects/{project.project_id}/artifacts/{missing.artifact_id}")
            expired_page = await client.get(f"/ui/projects/{project.project_id}/artifacts/{aged.artifact_id}")
            changed_page = await client.get(f"/ui/projects/{project.project_id}/artifacts/{logged.artifact_id}")
        return (
            kept_response.status_code,
            missing_response.status_code,
            changed_response.status_code,
            missing_page.text,
            expired_page.text,
            changed_page.text,
        )

    kept_status, missing_status, changed_status, missing_page, expired_page, changed_page = asyncio.run(read())
    assert kept_status == 200
    assert ready_count is not None and ready_after is not None
    assert int(ready_count[0]) == int(ready_after[0])
    assert report.corruption >= 1 and report.spooling >= 2
    assert 'data-state="missing">' in missing_page and "파일이 없습니다." in missing_page
    assert 'data-state="expired">' in expired_page and "보관 기한이 지났습니다." in expired_page
    assert 'data-state="corruption">' in changed_page and "파일 내용이 보관 hash와 다릅니다." in changed_page
    observed = {
        "missing_file_returned_success": missing_status == 200,
        "corruption_detected": changed_status != 200 and report.corruption >= 1,
        "original_result_hash_changed": before != after,
    }
    assert observed == {
        "missing_file_returned_success": False,
        "corruption_detected": True,
        "original_result_hash_changed": False,
    }


def test_w14_04(tmp_path: Path) -> None:
    import asyncio
    import hashlib
    from uuid import uuid4

    import httpx

    from aiqa.api.app import create_app
    from aiqa.config import load_settings
    from aiqa.contracts.cases import CaseDefinition, CaseRevisionInput, CaseSettings, CheckSpec, PathPolicy, StepSpec
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.domain.versions import bind_case_store, create_case, save_case_revision
    from aiqa.recording.recovery import EvidenceRecoverySpec, RecoveryCapture, RecoveryConflict, bind_recovery, reset_recovery
    from aiqa.store.artifacts import content_hash
    from aiqa.store.database import migrate_store
    from aiqa.store.models import Actor, ProjectCreate
    from aiqa.worker.service import recover_evidence

    root = tmp_path / "runtime"
    app = create_app(
        load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)})
    )
    assert any(
        getattr(route, "path", None) == "/api/v1/recordings/{recording_id}/evidence-recoveries" for route in app.routes
    )
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("Alpha", "w1404", "a", "web"))
    actor = Actor(owner.actor_id, project.project_id, True)
    with bind_case_store(store):
        case = create_case(actor, "Pay", None)
        version = save_case_revision(
            actor,
            case.case_id,
            CaseRevisionInput(
                CaseDefinition(
                    "pay",
                    "pay",
                    ("ready",),
                    {},
                    {},
                    (StepSpec("step-1", "pay", (CheckSpec("check-1", "text", "ok"),)),),
                    (),
                    PathPolicy(("pay",), ()),
                ),
                CaseSettings("web"),
                (),
                None,
                None,
                "draft",
                False,
            ),
            None,
        )
    recording_id = uuid4()
    store._connection.execute(
        """
        INSERT INTO recordings (
            project_id, case_id, recording_id, creation_kind, input_case_version_id,
            base_case_version_id, parent_recording_id, source_recording_id,
            storage_status, stop_status, completion_status, evidence_status
        ) VALUES (?, ?, ?, 'recorded', ?, NULL, NULL, NULL, 'spooling', 'stopped', 'interrupted', 'incomplete')
        """,
        (str(project.project_id), str(case.case_id), str(recording_id), str(version.id)),
    )
    before_hash = store._connection.execute(
        "SELECT content_hash FROM case_versions WHERE version_id = ?",
        (str(version.id),),
    ).fetchone()
    before_approvals = store._connection.execute("SELECT COUNT(*) FROM approval_events").fetchone()
    before_material = store._connection.execute("SELECT COUNT(*) FROM materialization_receipts").fetchone()
    immediate = b"unsent-after"
    delayed = b"later-photo"
    spec = EvidenceRecoverySpec(
        project.project_id,
        recording_id,
        "recover-1",
        (
            RecoveryCapture("act-1", "immediate", immediate),
            RecoveryCapture("act-2", "delayed", delayed),
        ),
    )
    marker = bind_recovery(store)
    try:
        first = recover_evidence(spec)
        second = recover_evidence(spec)
        conflict = False
        try:
            recover_evidence(
                EvidenceRecoverySpec(
                    project.project_id,
                    recording_id,
                    "recover-1",
                    (RecoveryCapture("act-1", "immediate", b"other-after"),),
                )
            )
        except RecoveryConflict:
            conflict = True
    finally:
        reset_recovery(marker)
    manifest = store._connection.execute(
        "SELECT source_artifact_hashes, input_version_hash, kind FROM recording_manifests WHERE manifest_id = ?",
        (str(first.manifest_id),),
    ).fetchone()
    after_hash = store._connection.execute(
        "SELECT content_hash FROM case_versions WHERE version_id = ?",
        (str(version.id),),
    ).fetchone()
    after_approvals = store._connection.execute("SELECT COUNT(*) FROM approval_events").fetchone()
    after_material = store._connection.execute("SELECT COUNT(*) FROM materialization_receipts").fetchone()
    attempts = store._connection.execute("SELECT COUNT(*) FROM attempts").fetchone()
    session_id = str(uuid4())
    store._connection.execute(
        """
        INSERT INTO browser_sessions (
            session_id, origin, csrf_hash, actor_id, project_scope, is_local_owner, expires_at
        ) VALUES (?, ?, ?, ?, ?, 1, ?)
        """,
        (
            session_id,
            "http://127.0.0.1:8000",
            hashlib.sha256(b"csrf-w14").hexdigest(),
            str(owner.actor_id),
            str(project.project_id),
            "2026-12-01T00:00:00+00:00",
        ),
    )
    store.close()

    async def post(body: bytes, key: str) -> httpx.Response:
        origin = "http://127.0.0.1:8000"
        payload = {
            "project_id": str(project.project_id),
            "captures": [
                {"action_id": "act-1", "timing": "immediate", "png_b64": _b64(immediate)},
                {"action_id": "act-2", "timing": "delayed", "png_b64": _b64(body)},
            ],
        }
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
            client.cookies.set("aiqa_session", session_id)
            return await client.post(
                f"/api/v1/recordings/{recording_id}/evidence-recoveries",
                json=payload,
                headers={
                    "Origin": origin,
                    "X-CSRF-Token": "csrf-w14",
                    "Idempotency-Key": key,
                },
            )

    same = asyncio.run(post(delayed, "recover-http"))
    again = asyncio.run(post(delayed, "recover-http"))
    changed = asyncio.run(post(b"changed-photo", "recover-http"))
    assert manifest is not None and before_hash is not None and after_hash is not None
    assert before_approvals is not None and after_approvals is not None
    assert before_material is not None and after_material is not None and attempts is not None
    delayed_hash = content_hash(delayed)
    observed = {
        "recovery_new_manifest": first.replayed is False
        and second.manifest_id == first.manifest_id
        and manifest[2] == "recovery"
        and conflict,
        "old_result_unchanged": str(before_hash[0]) == str(after_hash[0])
        and str(manifest[1]) == str(before_hash[0])
        and int(before_approvals[0]) == int(after_approvals[0])
        and int(before_material[0]) == int(after_material[0]),
        "delayed_satisfies_immediate": delayed_hash in str(manifest[0]),
        "recovery_dispatches": int(attempts[0]),
    }
    assert same.status_code == 200 and same.json()["purpose"] == "evidence_sync"
    assert same.json()["recording_id"] is None and again.json()["job_id"] == same.json()["job_id"]
    assert changed.status_code == 409
    assert (root / "artifacts" / "recovery" / str(recording_id) / str(first.manifest_id) / "delayed" / "act-2.png").read_bytes() == delayed
    assert observed == {
        "recovery_new_manifest": True,
        "old_result_unchanged": True,
        "delayed_satisfies_immediate": False,
        "recovery_dispatches": 0,
    }


def _b64(body: bytes) -> str:
    import base64

    return base64.b64encode(body).decode("ascii")


def _upload(project_id: object, owner_id: object, filename: str, media_type: str, body: bytes) -> object:
    from uuid import uuid4

    from aiqa.store.artifacts import ArtifactUpload, content_hash

    return ArtifactUpload(project_id, owner_id, filename, media_type, content_hash(body), len(body), body)


def _fixture_recording_job(store, actor, worker_id, key):
    """A real typed recording owner; the external device is a fixture only."""
    from aiqa.contracts.cases import CaseDefinition, CaseRevisionInput, CaseSettings, PathPolicy
    from aiqa.contracts.jobs import IdempotencyKey, JobSubmission
    from aiqa.domain.versions import bind_case_store, create_case, save_case_revision
    from aiqa.store.models import Transaction
    from aiqa.store.queue import enqueue_job
    with bind_case_store(store):
        case = create_case(actor, 'Evidence fixture', None)
        version = save_case_revision(actor, case.case_id, CaseRevisionInput(CaseDefinition('open','open',(),{},{},(),(),PathPolicy()),CaseSettings('web')),None)
    physical=uuid4()
    with store.transaction() as connection:
        connection.execute('INSERT INTO physical_resource_keys(physical_key_id,worker_id,native_id) VALUES(?,?,?)',(str(physical),worker_id,'fixture-'+key))
        connection.execute('INSERT INTO resource_aliases(project_id,physical_key_id,display_name,target_kind) VALUES(?,?,?,?)',(str(actor.project_scope),str(physical),'Fixture','web'))
        receipt=enqueue_job(Transaction(connection),JobSubmission(actor.project_scope,'recording',case.case_id,version.id,(str(physical),),'{}'),IdempotencyKey(actor.actor_id,actor.project_scope,'enqueue_job',key))
    return receipt.recording_id
