"""RX-20: backup generation, restore gates, no worker auto-replay, secret refs only."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from aiqa.api.app import create_app
from aiqa.config import load_settings
from aiqa.domain.projects import bind_store, create_project
from aiqa.security.secrets import (
    MemorySecretBackend,
    bind_secret_store,
    build_server_secret_resolver,
)
from aiqa.store.backup import (
    BackupSpec,
    RestoreActivation,
    RestoreRejected,
    RestoreSpec,
    activate_restore,
    create_backup,
    ensure_store_identity,
    validate_restore,
)
from aiqa.store.database import migrate_store
from aiqa.store.models import Actor, ProjectCreate, SecretInput


def _env(root: Path) -> dict[str, str]:
    return {
        "AIQA_HOST": "127.0.0.1",
        "AIQA_PORT": "8000",
        "AIQA_RUNTIME_ROOT": str(root),
    }


def _register_snapshot(
    store: object,
    project_id,
    receipt_id,
    *,
    content_hash_value: str,
    byte_length: int,
    state: str,
    missing_count: int,
    now: datetime,
) -> None:
    job_id = uuid4()
    with store.transaction() as connection:
        connection.execute(
            """
            INSERT INTO jobs (
                project_id, job_id, purpose, recording_id, case_run_id, payload_hash, source_refs, limits, status
            ) VALUES (?, ?, 'backup', NULL, NULL, ?, '["pc-store"]', '{}', 'completed')
            """,
            (str(project_id), str(job_id), content_hash_value),
        )
        connection.execute(
            "INSERT INTO backup_receipts (project_id, receipt_id, created_at) VALUES (?, ?, ?)",
            (str(project_id), str(receipt_id), now.isoformat()),
        )
        connection.execute(
            """
            INSERT INTO backup_snapshots (
                project_id, receipt_id, job_id, byte_length, content_hash, state, missing_count, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(project_id),
                str(receipt_id),
                str(job_id),
                byte_length,
                content_hash_value,
                state,
                missing_count,
                now.isoformat(),
            ),
        )


def test_generation_rejects_missing_broken_interrupted_and_foreign_store(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    settings = load_settings(_env(root))
    assert settings.backups_dir == root / "backups"
    app = create_app(settings)
    store = app.state.open_store()
    migrate_store(store)
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("Backup", "rx20", "", "web"))
    actor = Actor(owner.actor_id, project.project_id, True)
    backend = MemorySecretBackend()
    resolver = build_server_secret_resolver(settings, backend=backend)
    with bind_secret_store(store):
        resolver.put(actor, SecretInput(value="rx20-plain-SECRET", name="model"))

    now = datetime(2026, 11, 4, 6, 0, tzinfo=timezone.utc)
    receipt = create_backup(store, BackupSpec(project.project_id, actor), now)
    assert receipt.state == "complete"
    assert receipt.generation_id is not None
    assert receipt.store_id == ensure_store_identity(root)
    folder = root / "backups" / str(receipt.receipt_id)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["generation_id"] == str(receipt.generation_id)
    assert manifest["store_id"] == receipt.store_id
    assert manifest["db_hash"] == receipt.content_hash
    assert manifest["missing_count"] == 0
    assert isinstance(manifest["artifacts"], list)
    assert len(manifest["secret_refs"]) >= 1
    assert all("value" not in item and "secret" not in item for item in manifest["secret_refs"])
    copied = b"".join(path.read_bytes() for path in folder.rglob("*") if path.is_file())
    assert b"rx20-plain-SECRET" not in copied

    good = validate_restore(store, RestoreSpec(project.project_id, receipt.receipt_id, actor), now)
    assert good.accepted is True
    assert Path(good.separate_path).resolve() != store.config.database_path.resolve()

    missing_id = uuid4()
    missing_folder = root / "backups" / str(missing_id)
    shutil.copytree(folder, missing_folder)
    missing_manifest = json.loads((missing_folder / "manifest.json").read_text(encoding="utf-8"))
    missing_manifest["artifacts"] = [
        {"object_key": "gone/missing.log", "content_hash": "sha256:" + ("a" * 64)}
    ]
    (missing_folder / "manifest.json").write_text(
        json.dumps(missing_manifest, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )
    _register_snapshot(
        store,
        project.project_id,
        missing_id,
        content_hash_value=receipt.content_hash,
        byte_length=receipt.byte_length,
        state="complete",
        missing_count=0,
        now=now,
    )
    missing = validate_restore(store, RestoreSpec(project.project_id, missing_id, actor), now)
    assert missing.accepted is False

    broken_id = uuid4()
    broken_dir = root / "backups" / str(broken_id)
    shutil.copytree(folder, broken_dir)
    (broken_dir / "snapshot.sqlite").write_bytes(b"not-a-sqlite")
    _register_snapshot(
        store,
        project.project_id,
        broken_id,
        content_hash_value=receipt.content_hash,
        byte_length=12,
        state="complete",
        missing_count=0,
        now=now,
    )
    broken = validate_restore(store, RestoreSpec(project.project_id, broken_id, actor), now)
    assert broken.accepted is False
    assert broken.integrity_ok is False

    interrupted_id = uuid4()
    interrupted_dir = root / "backups" / str(interrupted_id)
    shutil.copytree(folder, interrupted_dir)
    (interrupted_dir / "snapshot.sqlite").unlink()
    _register_snapshot(
        store,
        project.project_id,
        interrupted_id,
        content_hash_value="sha256:" + ("0" * 64),
        byte_length=0,
        state="incomplete",
        missing_count=1,
        now=now,
    )
    with pytest.raises(RestoreRejected, match="interrupted"):
        validate_restore(store, RestoreSpec(project.project_id, interrupted_id, actor), now)

    incomplete = create_backup(store, BackupSpec(project.project_id, actor), now)
    with store.transaction() as connection:
        connection.execute(
            "UPDATE backup_snapshots SET state = 'incomplete', missing_count = 1 WHERE receipt_id = ?",
            (str(incomplete.receipt_id),),
        )
    with pytest.raises(RestoreRejected, match="incomplete"):
        validate_restore(store, RestoreSpec(project.project_id, incomplete.receipt_id, actor), now)

    foreign_id = uuid4()
    foreign_dir = root / "backups" / str(foreign_id)
    shutil.copytree(folder, foreign_dir)
    foreign_manifest = json.loads((foreign_dir / "manifest.json").read_text(encoding="utf-8"))
    foreign_manifest["store_id"] = str(uuid4())
    (foreign_dir / "manifest.json").write_text(
        json.dumps(foreign_manifest, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )
    _register_snapshot(
        store,
        project.project_id,
        foreign_id,
        content_hash_value=receipt.content_hash,
        byte_length=receipt.byte_length,
        state="complete",
        missing_count=0,
        now=now,
    )
    with pytest.raises(RestoreRejected, match="foreign store"):
        validate_restore(store, RestoreSpec(project.project_id, foreign_id, actor), now)

    store.close()


def test_activate_clears_workers_and_keeps_approval_zero_auto_replay(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    settings = load_settings(_env(root))
    app = create_app(settings)
    store = app.state.open_store()
    migrate_store(store)
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("Restore", "rx20b", "", "web"))
    actor = Actor(owner.actor_id, project.project_id, True)
    now = datetime(2026, 11, 4, 7, 0, tzinfo=timezone.utc)
    worker_id = f"worker-{uuid4()}"
    job_id = uuid4()
    case_id = uuid4()
    version_id = uuid4()
    enroll_id = str(uuid4())
    token_id = str(uuid4())
    stamp = now.isoformat()
    with store.transaction() as connection:
        connection.execute(
            """
            INSERT INTO automation_cases (
                project_id, case_id, name, folder_id, tc_reference, next_revision,
                latest_draft_version_id, current_approval_id, lock_version, archived_at
            ) VALUES (?, ?, 'kept', NULL, NULL, 2, NULL, NULL, 0, NULL)
            """,
            (str(project.project_id), str(case_id)),
        )
        connection.execute(
            """
            INSERT INTO case_versions (
                project_id, case_id, version_id, revision, creation_kind, parent_version_id, base_version_id,
                is_branch, definition_json, settings_json, recorded_steps_json, content_hash, verification_digest,
                source_manifest_id, replay_package_id, readiness_json, actor_id, reason, created_at
            ) VALUES (?, ?, ?, 1, 'recorded', NULL, NULL, 0, '{}', '{}', '[]', 'sha256:rx20', 'digest-rx20',
                NULL, NULL, '{}', ?, 'recorded', ?)
            """,
            (str(project.project_id), str(case_id), str(version_id), str(actor.actor_id), stamp),
        )
        connection.execute(
            "INSERT INTO worker_enrollments (enrollment_id, worker_id, project_id, created_at) VALUES (?, ?, ?, ?)",
            (enroll_id, worker_id, str(project.project_id), stamp),
        )
        connection.execute(
            """
            INSERT INTO worker_tokens (token_id, enrollment_id, token_hash, purpose, created_at)
            VALUES (?, ?, ?, 'recording', ?)
            """,
            (token_id, enroll_id, "hash-rx20", stamp),
        )
        connection.execute(
            """
            INSERT INTO worker_presence (
                project_id, worker_id, token_id, boot_id, last_seen, session_id
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (str(project.project_id), worker_id, token_id, "boot-1", stamp, "sess-1"),
        )
        connection.execute(
            """
            INSERT INTO jobs (
                project_id, job_id, purpose, recording_id, case_run_id, payload_hash, source_refs, limits, status
            ) VALUES (?, ?, 'resource_probe', NULL, NULL, 'payload', '["probe"]', '{}', 'running')
            """,
            (str(project.project_id), str(job_id)),
        )
        connection.execute(
            """
            INSERT INTO leases (project_id, job_id, generation, worker_id, physical_key_id, expires_at)
            VALUES (?, ?, 1, ?, NULL, ?)
            """,
            (str(project.project_id), str(job_id), worker_id, stamp),
        )

    receipt = create_backup(store, BackupSpec(project.project_id, actor), now)
    assert receipt.state == "complete"
    validation = validate_restore(store, RestoreSpec(project.project_id, receipt.receipt_id, actor), now)
    assert validation.accepted is True
    activated = activate_restore(
        store,
        RestoreActivation(project.project_id, validation.validation_id, actor, True),
        now,
    )
    assert activated.auto_replayed_jobs == 0
    assert activated.old_leases_reused is False
    assert activated.secret_reset_required is True

    with store.transaction() as connection:
        tokens = connection.execute("SELECT COUNT(*) FROM worker_tokens").fetchone()[0]
        leases = connection.execute("SELECT COUNT(*) FROM leases").fetchone()[0]
        presence = connection.execute("SELECT COUNT(*) FROM worker_presence").fetchone()[0]
        job_status = connection.execute(
            "SELECT status FROM jobs WHERE job_id = ?", (str(job_id),)
        ).fetchone()[0]
        kept = connection.execute(
            "SELECT content_hash FROM case_versions WHERE version_id = ?",
            (str(version_id),),
        ).fetchone()
    assert tokens == 0
    assert leases == 0
    assert presence == 0
    assert job_status == "cancelled"
    assert kept is not None and kept[0] == "sha256:rx20"
    store.close()
