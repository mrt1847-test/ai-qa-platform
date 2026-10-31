"""W06 schema tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4

from aiqa.contracts.cases import CaseDefinition, CaseRevisionInput, CaseSettings, CheckSpec, PathPolicy, StepSpec
from aiqa.store.models import Actor, ProjectCreate


def test_w06_01(tmp_path: Path) -> None:
    from aiqa.api.app import create_app
    from aiqa.config import load_settings
    from aiqa.contracts.recordings import MaterializationReceipt, RecordingManifest, RecordingSession
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.domain.versions import bind_case_store, create_case, save_case_revision
    from aiqa.store.database import migrate_store

    root = tmp_path / "runtime"
    app = create_app(
        load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)})
    )
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("A", "rec", "a", "web"))
    actor = Actor(actor_id=owner.actor_id, project_scope=project.project_id, is_local_owner=True)
    with bind_case_store(store):
        case_a = create_case(actor, "Alpha", None)
        case_b = create_case(actor, "Beta", None)
        version_a = save_case_revision(actor, case_a.case_id, _revision(), None)
        version_b = save_case_revision(actor, case_b.case_id, _revision(), None)
    store.close()

    recording_a = uuid4()
    recording_b = uuid4()
    manifest_id = uuid4()
    session = RecordingSession(
        project_id=project.project_id,
        case_id=case_a.case_id,
        recording_id=recording_a,
        creation_kind="recorded",
        input_case_version_id=version_a.id,
        base_case_version_id=None,
        parent_recording_id=None,
        source_recording_id=None,
        storage_status="local",
        stop_status="running",
        completion_status="open",
        evidence_status="incomplete",
    )
    manifest = RecordingManifest(
        project_id=project.project_id,
        case_id=case_a.case_id,
        recording_id=recording_a,
        manifest_id=manifest_id,
        revision=1,
        kind="package_rebuild",
        prior_manifest_id=None,
        input_version_hash=version_a.content_hash,
        source_artifact_hashes="sha256:" + ("ab" * 32),
        action_mapping="[]",
        evidence_completeness="incomplete",
        request_key="finish-1",
        body_hash="sha256:" + ("cd" * 32),
    )
    receipt = MaterializationReceipt(
        project_id=project.project_id,
        receipt_id=uuid4(),
        manifest_id=manifest_id,
        produced_version_id=uuid4(),
        body_hash=manifest.body_hash,
    )
    with sqlite3.connect(root / "db" / "aiqa.sqlite") as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        _insert_recording(connection, session)
        cross_input = _denied(
            connection,
            """
            INSERT INTO recordings (
                project_id, case_id, recording_id, creation_kind, input_case_version_id,
                base_case_version_id, parent_recording_id, source_recording_id,
                storage_status, stop_status, completion_status, evidence_status
            ) VALUES (?, ?, ?, 'recorded', ?, NULL, NULL, NULL, 'local', 'running', 'open', 'incomplete')
            """,
            (str(project.project_id), str(case_a.case_id), str(uuid4()), str(version_b.id)),
        )
        cross_base = _denied(
            connection,
            """
            INSERT INTO recordings (
                project_id, case_id, recording_id, creation_kind, input_case_version_id,
                base_case_version_id, parent_recording_id, source_recording_id,
                storage_status, stop_status, completion_status, evidence_status
            ) VALUES (?, ?, ?, 'recorded', ?, ?, NULL, NULL, 'local', 'running', 'open', 'incomplete')
            """,
            (str(project.project_id), str(case_a.case_id), str(uuid4()), str(version_a.id), str(version_b.id)),
        )
        _insert_recording(
            connection,
            RecordingSession(
                project.project_id,
                case_b.case_id,
                recording_b,
                "recorded",
                version_b.id,
                None,
                None,
                None,
                "local",
                "running",
                "open",
                "incomplete",
            ),
        )
        cross_source = _denied(
            connection,
            """
            INSERT INTO recordings (
                project_id, case_id, recording_id, creation_kind, input_case_version_id,
                base_case_version_id, parent_recording_id, source_recording_id,
                storage_status, stop_status, completion_status, evidence_status
            ) VALUES (?, ?, ?, 'recorded', ?, NULL, NULL, ?, 'local', 'running', 'open', 'incomplete')
            """,
            (str(project.project_id), str(case_a.case_id), str(uuid4()), str(version_a.id), str(recording_b)),
        )
        wrong_kind = _denied(
            connection,
            """
            INSERT INTO recordings (
                project_id, case_id, recording_id, creation_kind, input_case_version_id,
                base_case_version_id, parent_recording_id, source_recording_id,
                storage_status, stop_status, completion_status, evidence_status
            ) VALUES (?, ?, ?, 'package_rebuild', ?, NULL, NULL, NULL, 'local', 'running', 'open', 'incomplete')
            """,
            (str(project.project_id), str(case_a.case_id), str(uuid4()), str(version_a.id)),
        )
        _insert_manifest(connection, manifest)
        _insert_produced_fixture(connection, version_a.id, receipt.produced_version_id, manifest_id)
        _insert_receipt(connection, receipt)
        duplicate = _denied(
            connection,
            """
            INSERT INTO materialization_receipts (
                project_id, receipt_id, manifest_id, produced_version_id, body_hash
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (str(project.project_id), str(uuid4()), str(manifest_id), str(uuid4()), "sha256:" + ("ef" * 32)),
        )
        same_key = _denied(
            connection,
            """
            INSERT INTO recording_manifests (
                project_id, case_id, recording_id, manifest_id, revision, kind, prior_manifest_id,
                input_version_hash, source_artifact_hashes, action_mapping, evidence_completeness,
                request_key, body_hash
            ) VALUES (?, ?, ?, ?, 2, 'original', NULL, ?, ?, '[]', 'incomplete', ?, ?)
            """,
            (
                str(project.project_id),
                str(case_a.case_id),
                str(recording_a),
                str(uuid4()),
                version_a.content_hash,
                "sha256:" + ("11" * 32),
                manifest.request_key,
                "sha256:" + ("22" * 32),
            ),
        )
        connection.execute(
            "UPDATE recordings SET storage_status = 'stored' WHERE recording_id = ?",
            (str(recording_a),),
        )
        axes = connection.execute(
            """
            SELECT storage_status, stop_status, completion_status, evidence_status, creation_kind
            FROM recordings WHERE recording_id = ?
            """,
            (str(recording_a),),
        ).fetchone()
        before_hash = connection.execute(
            "SELECT body_hash FROM recording_manifests WHERE manifest_id = ?",
            (str(manifest_id),),
        ).fetchone()
        connection.execute(
            """
            INSERT INTO recording_notes (
                project_id, recording_id, note_id, actor_id, created_at, commit_seq, body, request_key
            ) VALUES (?, ?, ?, ?, '2026-11-01T00:00:00+00:00', 1, 'first', 'note-1')
            """,
            (str(project.project_id), str(recording_a), str(uuid4()), str(actor.actor_id)),
        )
        connection.execute(
            """
            INSERT INTO recording_notes (
                project_id, recording_id, note_id, actor_id, created_at, commit_seq, body, request_key
            ) VALUES (?, ?, ?, ?, '2026-11-01T00:00:01+00:00', 2, 'second', 'note-2')
            """,
            (str(project.project_id), str(recording_a), str(uuid4()), str(actor.actor_id)),
        )
        note_update = _denied(
            connection,
            "UPDATE recording_notes SET body = 'changed' WHERE recording_id = ?",
            (str(recording_a),),
        )
        after_hash = connection.execute(
            "SELECT body_hash FROM recording_manifests WHERE manifest_id = ?",
            (str(manifest_id),),
        ).fetchone()
        sequences = [
            int(row[0])
            for row in connection.execute(
                "SELECT commit_seq FROM recording_notes WHERE recording_id = ? ORDER BY commit_seq",
                (str(recording_a),),
            )
        ]
        columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(recording_notes)")}
        manifest_columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(recording_manifests)")}
    assert axes is not None and before_hash is not None and after_hash is not None
    assert wrong_kind is True
    assert same_key is True
    assert axes[4] == "recorded"
    assert manifest.kind == "package_rebuild"
    assert "produced_version_id" not in manifest_columns
    assert before_hash[0] == after_hash[0]
    observed = {
        "cross_case_denied": cross_input and cross_base and cross_source,
        "duplicate_materialization_denied": duplicate,
        "independent_status_axes": axes[0] == "stored" and axes[1] == "running" and axes[2] == "open" and axes[3] == "incomplete",
        "notes_have_independent_sequence": sequences == [1, 2] and "local_seq" not in columns and note_update,
    }
    assert observed == {
        "cross_case_denied": True,
        "duplicate_materialization_denied": True,
        "independent_status_axes": True,
        "notes_have_independent_sequence": True,
    }


def test_w06_10(tmp_path: Path) -> None:
    from aiqa.api.app import create_app
    from aiqa.api.auth import bound_auth_store, enroll_worker
    from aiqa.config import load_settings
    from aiqa.contracts.resources import PhysicalResourceKey, ResourceAlias
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.store.database import migrate_store
    from aiqa.store.models import Actor, ProjectCreate

    root = tmp_path / "runtime"
    app = create_app(
        load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)})
    )
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project_a = create_project(owner, ProjectCreate("Alpha", "w0610a", "a", "web"))
        project_b = create_project(owner, ProjectCreate("Beta", "w0610b", "b", "web"))
        project_c = create_project(owner, ProjectCreate("Gamma", "w0610c", "c", "web"))
    worker = uuid4()
    other = uuid4()
    serial = "SERIAL-W06-10"
    with bound_auth_store(store):
        enroll_worker(Actor(owner.actor_id, project_a.project_id, True), str(worker), "recording")
        enroll_worker(Actor(owner.actor_id, project_b.project_id, True), str(worker), "recording")
        enroll_worker(Actor(owner.actor_id, project_a.project_id, True), str(other), "recording")
    store.close()

    key_id = uuid4()
    key = PhysicalResourceKey(worker_id=worker, native_id=serial)
    alias_a = ResourceAlias(project_a.project_id, key_id, "browser-a", "web")
    alias_b = ResourceAlias(project_b.project_id, key_id, "browser-b", "web")
    with sqlite3.connect(root / "db" / "aiqa.sqlite") as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        _insert_physical_key(connection, key_id, key)
        duplicate = _denied(
            connection,
            """
            INSERT INTO physical_resource_keys (physical_key_id, worker_id, native_id)
            VALUES (?, ?, ?)
            """,
            (str(uuid4()), str(worker), serial),
        )
        unknown = _denied(
            connection,
            """
            INSERT INTO physical_resource_keys (physical_key_id, worker_id, native_id)
            VALUES (?, ?, ?)
            """,
            (str(uuid4()), str(uuid4()), "UNKNOWN-SERIAL"),
        )
        _insert_physical_key(
            connection,
            uuid4(),
            PhysicalResourceKey(worker_id=other, native_id="OTHER-NATIVE"),
        )
        _insert_physical_key(
            connection,
            uuid4(),
            PhysicalResourceKey(worker_id=worker, native_id="OTHER-NATIVE"),
        )
        _insert_alias(connection, alias_a)
        _insert_alias(connection, alias_b)
        foreign_alias = _denied(
            connection,
            """
            INSERT INTO resource_aliases (project_id, physical_key_id, display_name, target_kind)
            VALUES (?, ?, ?, ?)
            """,
            (str(project_c.project_id), str(key_id), "browser-c", "web"),
        )
        cross = _denied(
            connection,
            "UPDATE resource_aliases SET project_id = ? WHERE project_id = ? AND physical_key_id = ?",
            (str(project_b.project_id), str(project_a.project_id), str(key_id)),
        )
        connection.execute(
            "UPDATE resource_aliases SET display_name = ? WHERE project_id = ? AND physical_key_id = ?",
            ("browser-a-renamed", str(project_a.project_id), str(key_id)),
        )
        other_name = connection.execute(
            "SELECT display_name FROM resource_aliases WHERE project_id = ? AND physical_key_id = ?",
            (str(project_b.project_id), str(key_id)),
        ).fetchone()
        same_serial = connection.execute(
            "SELECT COUNT(*) FROM physical_resource_keys WHERE worker_id = ? AND native_id = ?",
            (str(worker), serial),
        ).fetchone()
        alias_count = connection.execute(
            "SELECT COUNT(*) FROM resource_aliases WHERE physical_key_id = ?",
            (str(key_id),),
        ).fetchone()
    assert other_name is not None and same_serial is not None and alias_count is not None
    assert duplicate is True
    assert foreign_alias is True
    assert other_name[0] == "browser-b"
    observed = {
        "physical_keys_for_same_worker_serial": int(same_serial[0]),
        "project_aliases": int(alias_count[0]),
        "unknown_worker_rejected": unknown,
        "cross_project_alias_mutation_denied": cross,
    }
    assert observed == {
        "physical_keys_for_same_worker_serial": 1,
        "project_aliases": 2,
        "unknown_worker_rejected": True,
        "cross_project_alias_mutation_denied": True,
    }


def test_w06_02(tmp_path: Path) -> None:
    from aiqa.api.app import create_app
    from aiqa.api.auth import bound_auth_store, enroll_worker
    from aiqa.config import load_settings
    from aiqa.contracts.jobs import AttemptSnapshot, CaseRunSnapshot, ExecutionSnapshot, JobSpec
    from aiqa.contracts.recordings import RecordingSession
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.domain.versions import bind_case_store, create_case, save_case_revision
    from aiqa.store.database import migrate_store
    from aiqa.store.models import Actor, ProjectCreate

    root = tmp_path / "runtime"
    app = create_app(
        load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)})
    )
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("Alpha", "w0602", "a", "web"))
    actor = Actor(actor_id=owner.actor_id, project_scope=project.project_id, is_local_owner=True)
    with bind_case_store(store):
        case = create_case(actor, "Alpha", None)
        version = save_case_revision(actor, case.case_id, _revision(), None)
    worker = uuid4()
    with bound_auth_store(store):
        enroll_worker(actor, str(worker), "recording")
    store.close()

    requested = "2026-11-01T00:00:00+00:00"
    recording_id = uuid4()
    key_id = uuid4()
    execution_id = uuid4()
    case_run_id = uuid4()
    suite_version_id = uuid4()
    payload = "sha256:" + ("ab" * 32)
    session = RecordingSession(
        project_id=project.project_id,
        case_id=case.case_id,
        recording_id=recording_id,
        creation_kind="recorded",
        input_case_version_id=version.id,
        base_case_version_id=None,
        parent_recording_id=None,
        source_recording_id=None,
        storage_status="stored",
        stop_status="stopped",
        completion_status="completed",
        evidence_status="incomplete",
    )
    trial = ExecutionSnapshot(
        project.project_id, execution_id, "Trial", "trial", "single", None, requested
    )
    item = CaseRunSnapshot(
        project.project_id, execution_id, case_run_id, case.case_id, version.id, "trial", requested
    )
    recording_job = JobSpec(
        project.project_id, uuid4(), "recording", recording_id, None, payload, "[]", "{}", "queued"
    )
    item_job = JobSpec(
        project.project_id, uuid4(), "trial", None, case_run_id, payload, "[]", "{}", "queued"
    )
    rebuild = JobSpec(
        project.project_id,
        uuid4(),
        "package_rebuild",
        None,
        None,
        payload,
        '{"manifest_id":"m1"}',
        "{}",
        "queued",
    )
    with sqlite3.connect(root / "db" / "aiqa.sqlite") as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        _insert_physical_key(connection, key_id, _resource_key(worker))
        _insert_recording(connection, session)
        connection.execute(
            "INSERT INTO suites (project_id, suite_id, name) VALUES (?, ?, 'nightly')",
            (str(project.project_id), str(uuid4())),
        )
        suite_id = connection.execute("SELECT suite_id FROM suites").fetchone()
        assert suite_id is not None
        connection.execute(
            """
            INSERT INTO suite_versions (project_id, suite_id, suite_version_id, content_hash)
            VALUES (?, ?, ?, ?)
            """,
            (str(project.project_id), suite_id[0], str(suite_version_id), payload),
        )
        connection.execute(
            """
            INSERT INTO suite_entries (project_id, suite_version_id, entry_id, position)
            VALUES (?, ?, ?, 1)
            """,
            (str(project.project_id), str(suite_version_id), str(uuid4())),
        )
        _insert_execution(connection, trial)
        suite_execution = _denied(
            connection,
            """
            INSERT INTO executions (
                project_id, execution_id, name, purpose, source, suite_version_id, scope_requested_at
            ) VALUES (?, ?, 'Suite', 'regression', 'single', ?, ?)
            """,
            (str(project.project_id), str(uuid4()), str(suite_version_id), requested),
        )
        connection.execute(
            """
            INSERT INTO executions (
                project_id, execution_id, name, purpose, source, suite_version_id, scope_requested_at
            ) VALUES (?, ?, 'Suite', 'regression', 'suite', ?, ?)
            """,
            (str(project.project_id), str(uuid4()), str(suite_version_id), requested),
        )
        _insert_case_run(connection, item)
        scope_mismatch = _denied(
            connection,
            """
            INSERT INTO case_runs (
                project_id, execution_id, case_run_id, case_id, case_version_id, purpose, requested_at
            ) VALUES (?, ?, ?, ?, ?, 'trial', '2026-11-01T01:00:00+00:00')
            """,
            (
                str(project.project_id),
                str(execution_id),
                str(uuid4()),
                str(case.case_id),
                str(version.id),
            ),
        )
        purpose_mismatch = _denied(
            connection,
            """
            INSERT INTO case_runs (
                project_id, execution_id, case_run_id, case_id, case_version_id, purpose, requested_at
            ) VALUES (?, ?, ?, ?, ?, 'regression', ?)
            """,
            (
                str(project.project_id),
                str(execution_id),
                str(uuid4()),
                str(case.case_id),
                str(version.id),
                requested,
            ),
        )
        _insert_job(connection, recording_job)
        _insert_job(connection, item_job)
        double_owner = _denied(
            connection,
            """
            INSERT INTO jobs (
                project_id, job_id, purpose, recording_id, case_run_id, payload_hash,
                source_refs, limits, status
            ) VALUES (?, ?, 'trial', ?, ?, ?, '[]', '{}', 'queued')
            """,
            (str(project.project_id), str(uuid4()), str(recording_id), str(case_run_id), payload),
        )
        second_recording = _denied(
            connection,
            """
            INSERT INTO jobs (
                project_id, job_id, purpose, recording_id, case_run_id, payload_hash,
                source_refs, limits, status
            ) VALUES (?, ?, 'recording', ?, NULL, ?, '[]', '{}', 'queued')
            """,
            (str(project.project_id), str(uuid4()), str(recording_id), payload),
        )
        second_item = _denied(
            connection,
            """
            INSERT INTO jobs (
                project_id, job_id, purpose, recording_id, case_run_id, payload_hash,
                source_refs, limits, status
            ) VALUES (?, ?, 'trial', NULL, ?, ?, '[]', '{}', 'queued')
            """,
            (str(project.project_id), str(uuid4()), str(case_run_id), payload),
        )
        reverification_id = uuid4()
        reverification_run = uuid4()
        _insert_execution(
            connection,
            ExecutionSnapshot(
                project.project_id,
                reverification_id,
                "Again",
                "reverification",
                "rerun",
                None,
                requested,
            ),
        )
        _insert_case_run(
            connection,
            CaseRunSnapshot(
                project.project_id,
                reverification_id,
                reverification_run,
                case.case_id,
                version.id,
                "reverification",
                requested,
            ),
        )
        mapped = JobSpec(
            project.project_id,
            uuid4(),
            "regression",
            None,
            reverification_run,
            payload,
            "[]",
            "{}",
            "queued",
        )
        _insert_job(connection, mapped)
        mapped_as_trial = _denied(
            connection,
            """
            INSERT INTO jobs (
                project_id, job_id, purpose, recording_id, case_run_id, payload_hash,
                source_refs, limits, status
            ) VALUES (?, ?, 'trial', NULL, ?, ?, '[]', '{}', 'queued')
            """,
            (str(project.project_id), str(uuid4()), str(reverification_run), payload),
        )
        _insert_job(connection, rebuild)
        owned_rebuild = _denied(
            connection,
            """
            INSERT INTO jobs (
                project_id, job_id, purpose, recording_id, case_run_id, payload_hash,
                source_refs, limits, status
            ) VALUES (?, ?, 'package_rebuild', ?, NULL, ?, '{"manifest_id":"m2"}', '{}', 'queued')
            """,
            (str(project.project_id), str(uuid4()), str(recording_id), payload),
        )
        owners = connection.execute(
            "SELECT recording_id, case_run_id FROM jobs WHERE job_id = ?",
            (str(rebuild.job_id),),
        ).fetchone()
        attempt = AttemptSnapshot(project.project_id, uuid4(), rebuild.job_id, key_id, 1)
        _insert_attempt(connection, attempt)
        connection.execute(
            """
            INSERT INTO leases (
                project_id, job_id, generation, worker_id, physical_key_id, expires_at
            ) VALUES (?, ?, 1, ?, ?, '2026-11-01T00:01:00+00:00')
            """,
            (str(project.project_id), str(rebuild.job_id), str(worker), str(key_id)),
        )
        missing_lease = _denied(
            connection,
            """
            INSERT INTO leases (
                project_id, job_id, generation, worker_id, physical_key_id, expires_at
            ) VALUES (?, ?, 2, ?, ?, '2026-11-01T00:01:00+00:00')
            """,
            (str(project.project_id), str(rebuild.job_id), str(worker), str(uuid4())),
        )
        missing_key = _denied(
            connection,
            """
            INSERT INTO attempts (project_id, attempt_id, job_id, generation, physical_key_id)
            VALUES (?, ?, ?, 2, ?)
            """,
            (str(project.project_id), str(uuid4()), str(rebuild.job_id), str(uuid4())),
        )
    assert suite_id is not None and owners is not None
    assert suite_execution is True
    assert connection.execute(
        "SELECT COUNT(*) FROM executions WHERE source = 'suite'"
    ).fetchone() == (1,)
    assert scope_mismatch is True
    assert purpose_mismatch is True
    assert mapped_as_trial is True
    assert missing_lease is True
    assert missing_key is True
    observed = {
        "double_owner_denied": double_owner,
        "owner_job_unique": second_recording and second_item,
        "package_rebuild_owners_null": owners[0] is None and owners[1] is None and owned_rebuild,
    }
    assert observed == {
        "double_owner_denied": True,
        "owner_job_unique": True,
        "package_rebuild_owners_null": True,
    }


def test_w06_03(tmp_path: Path) -> None:
    from aiqa.api.app import create_app
    from aiqa.config import load_settings
    from aiqa.contracts.evidence import ActionEnvelope, CheckResult, EventEnvelope, ModelCallFact
    from aiqa.contracts.jobs import AttemptSnapshot, JobSpec
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.domain.versions import bind_case_store, create_case, save_case_revision
    from aiqa.store.database import migrate_store
    from aiqa.store.models import Actor, ProjectCreate

    root = tmp_path / "runtime"
    app = create_app(
        load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)})
    )
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("Alpha", "w0603", "a", "web"))
    actor = Actor(actor_id=owner.actor_id, project_scope=project.project_id, is_local_owner=True)
    with bind_case_store(store):
        case = create_case(actor, "Alpha", None)
        version = save_case_revision(actor, case.case_id, _revision(), None)
    store.close()

    payload = "sha256:" + ("ab" * 32)
    body = "sha256:" + ("cd" * 32)
    other_body = "sha256:" + ("ef" * 32)
    job_id = uuid4()
    attempt_a = uuid4()
    attempt_b = uuid4()
    action_id = uuid4()
    event_id = uuid4()
    job = JobSpec(
        project.project_id, job_id, "package_rebuild", None, None, payload, '{"manifest_id":"m1"}', "{}", "queued"
    )
    action = ActionEnvelope(
        project.project_id,
        attempt_a,
        1,
        "step-1",
        action_id,
        None,
        payload,
        "planned",
        case.case_id,
        version.id,
        False,
    )
    event = EventEnvelope(
        project.project_id,
        event_id,
        attempt_a,
        1,
        "2026-11-01T00:00:00+00:00",
        "action",
        '{"seq":1}',
        payload,
        body,
        "detail",
    )
    with sqlite3.connect(root / "db" / "aiqa.sqlite") as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        _insert_job(connection, job)
        _insert_attempt(connection, AttemptSnapshot(project.project_id, attempt_a, job_id, None, 1))
        _insert_attempt(connection, AttemptSnapshot(project.project_id, attempt_b, job_id, None, 2))
        duplicate_seq = _denied(
            connection,
            """
            INSERT INTO attempts (project_id, attempt_id, job_id, generation, physical_key_id)
            VALUES (?, ?, ?, 1, NULL)
            """,
            (str(project.project_id), str(uuid4()), str(job_id)),
        )
        _insert_action(connection, action)
        foreign_version = _denied(
            connection,
            """
            INSERT INTO actions (
                project_id, attempt_id, action_seq, step_id, action_id, package_step_id,
                proposal_hash, dispatch_state, case_id, case_version_id, outcome_known
            ) VALUES (?, ?, 2, 'step-1', ?, NULL, ?, 'planned', ?, ?, 0)
            """,
            (str(project.project_id), str(attempt_a), str(uuid4()), payload, str(case.case_id), str(uuid4())),
        )
        _insert_check(
            connection,
            CheckResult(
                project.project_id,
                attempt_a,
                action_id,
                "check-1",
                "unknown",
                "deterministic",
                "ok",
                "",
                "unobserved",
                "[]",
                "2026-11-01T00:00:01+00:00",
            ),
        )
        cross_attempt = _denied(
            connection,
            """
            INSERT INTO check_results (
                project_id, attempt_id, action_id, check_id, status, method, expected_snapshot,
                sanitized_observed, reason, artifact_refs, observed_at
            ) VALUES (?, ?, ?, 'check-2', 'unknown', 'deterministic', 'ok', '', 'cross', '[]', ?)
            """,
            (str(project.project_id), str(attempt_b), str(action_id), "2026-11-01T00:00:02+00:00"),
        )
        connection.execute(
            """
            INSERT INTO dispatch_journal (
                project_id, attempt_id, action_seq, entry_seq, dispatch_state, recorded_at
            ) VALUES (?, ?, 1, 1, 'planned', '2026-11-01T00:00:00+00:00')
            """,
            (str(project.project_id), str(attempt_a)),
        )
        connection.execute(
            """
            INSERT INTO dispatch_journal (
                project_id, attempt_id, action_seq, entry_seq, dispatch_state, recorded_at
            ) VALUES (?, ?, 1, 2, 'dispatch_started', '2026-11-01T00:00:01+00:00')
            """,
            (str(project.project_id), str(attempt_a)),
        )
        lookup_after_dispatch = _denied(
            connection,
            """
            INSERT INTO dispatch_journal (
                project_id, attempt_id, action_seq, entry_seq, dispatch_state, recorded_at
            ) VALUES (?, ?, 1, 3, 'lookup_failed', '2026-11-01T00:00:02+00:00')
            """,
            (str(project.project_id), str(attempt_a)),
        )
        _insert_event(connection, event)
        same_replay = _denied(
            connection,
            """
            INSERT INTO attempt_events (
                project_id, event_id, attempt_id, local_seq, captured_at, event_type,
                minimum_facts, payload_hash, body_hash, detail_payload
            ) VALUES (?, ?, ?, 1, '2026-11-01T00:00:00+00:00', 'action', '{"seq":1}', ?, ?, 'detail')
            """,
            (str(project.project_id), str(uuid4()), str(attempt_a), payload, body),
        )
        stored = connection.execute(
            "SELECT event_id, body_hash FROM attempt_events WHERE attempt_id = ? AND local_seq = 1",
            (str(attempt_a),),
        ).fetchone()
        different_hash = _denied(
            connection,
            """
            INSERT INTO attempt_events (
                project_id, event_id, attempt_id, local_seq, captured_at, event_type,
                minimum_facts, payload_hash, body_hash, detail_payload
            ) VALUES (?, ?, ?, 1, '2026-11-01T00:00:00+00:00', 'action', '{"seq":1}', ?, ?, 'other')
            """,
            (str(project.project_id), str(uuid4()), str(attempt_a), payload, other_body),
        )
        after_conflict = connection.execute(
            "SELECT body_hash FROM attempt_events WHERE attempt_id = ? AND local_seq = 1",
            (str(attempt_a),),
        ).fetchone()
        connection.execute(
            "UPDATE attempt_events SET detail_payload = 'expanded' WHERE event_id = ?",
            (str(event_id),),
        )
        hash_after_detail = connection.execute(
            "SELECT body_hash FROM attempt_events WHERE event_id = ?",
            (str(event_id),),
        ).fetchone()
        connection.execute("UPDATE attempt_events SET sealed = 1 WHERE event_id = ?", (str(event_id),))
        sealed_change = _denied(
            connection,
            "UPDATE attempt_events SET detail_payload = 'changed' WHERE event_id = ?",
            (str(event_id),),
        )
        _insert_model_call(
            connection,
            ModelCallFact(
                project.project_id,
                uuid4(),
                attempt_a,
                "verification",
                action_id,
                None,
                "unknown",
                None,
                None,
                None,
                None,
            ),
        )
        usage = connection.execute(
            """
            SELECT input_tokens FROM model_call_facts
            WHERE attempt_id = ? AND measurement_status = 'unknown'
            """,
            (str(attempt_a),),
        ).fetchone()
        numbered_unknown = _denied(
            connection,
            """
            INSERT INTO model_call_facts (
                project_id, call_id, attempt_id, role, action_id, check_id, measurement_status,
                input_tokens, output_tokens, cache_tokens, image_tokens
            ) VALUES (?, ?, ?, 'verification', ?, NULL, 'unknown', 1, NULL, NULL, NULL)
            """,
            (str(project.project_id), str(uuid4()), str(attempt_a), str(action_id)),
        )
        both_owners = _denied(
            connection,
            """
            INSERT INTO model_call_facts (
                project_id, call_id, attempt_id, role, action_id, check_id, measurement_status,
                input_tokens, output_tokens, cache_tokens, image_tokens
            ) VALUES (?, ?, ?, 'verification', ?, 'check-1', 'unknown', NULL, NULL, NULL, NULL)
            """,
            (str(project.project_id), str(uuid4()), str(attempt_a), str(action_id)),
        )
    assert stored is not None and after_conflict is not None and hash_after_detail is not None and usage is not None
    assert duplicate_seq is True
    assert foreign_version is True
    assert lookup_after_dispatch is True
    assert sealed_change is True
    assert numbered_unknown is True
    assert both_owners is True
    assert hash_after_detail[0] == body
    observed = {
        "same_event_receipt": same_replay and stored[0] == str(event_id) and stored[1] == body,
        "different_hash_status": 409 if different_hash and after_conflict[0] == body else 0,
        "cross_attempt_denied": cross_attempt,
        "unknown_usage": usage[0],
    }
    assert observed == {
        "same_event_receipt": True,
        "different_hash_status": 409,
        "cross_attempt_denied": True,
        "unknown_usage": None,
    }


def test_w06_04(tmp_path: Path) -> None:
    from aiqa.api.app import create_app
    from aiqa.config import load_settings
    from aiqa.contracts.evidence import ActionEnvelope
    from aiqa.contracts.jobs import AttemptSnapshot, CaseRunSnapshot, ExecutionSnapshot, JobSpec
    from aiqa.contracts.reviews import (
        ApprovalEvent,
        ArtifactProtection,
        ArtifactRef,
        ReviewEvidenceEntry,
        ReviewSnapshot,
    )
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.domain.versions import bind_case_store, create_case, save_case_revision
    from aiqa.store.database import migrate_store
    from aiqa.store.models import Actor, ProjectCreate
    from uuid import UUID

    root = tmp_path / "runtime"
    app = create_app(
        load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)})
    )
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("Alpha", "w0604", "a", "web"))
    actor = Actor(actor_id=owner.actor_id, project_scope=project.project_id, is_local_owner=True)
    with bind_case_store(store):
        case_a = create_case(actor, "Alpha", None)
        case_b = create_case(actor, "Beta", None)
        version_a = save_case_revision(actor, case_a.case_id, _revision(), None)
        version_b = save_case_revision(actor, case_b.case_id, _revision(), None)
    store.close()

    requested = "2026-11-01T00:00:00+00:00"
    payload = "sha256:" + ("ab" * 32)
    execution_id = uuid4()
    run_a = uuid4()
    run_b = uuid4()
    attempt_a = uuid4()
    attempt_b = uuid4()
    action_a = uuid4()
    action_b = uuid4()
    review_a = uuid4()
    review_b = uuid4()
    artifact_id = uuid4()
    approval_a = uuid4()
    approval_b = uuid4()
    with sqlite3.connect(root / "db" / "aiqa.sqlite") as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        _insert_execution(
            connection,
            ExecutionSnapshot(project.project_id, execution_id, "Trial", "trial", "single", None, requested),
        )
        _insert_case_run(
            connection,
            CaseRunSnapshot(
                project.project_id, execution_id, run_a, case_a.case_id, version_a.id, "trial", requested
            ),
        )
        _insert_case_run(
            connection,
            CaseRunSnapshot(
                project.project_id, execution_id, run_b, case_b.case_id, version_b.id, "trial", requested
            ),
        )
        _insert_job(
            connection,
            JobSpec(project.project_id, uuid4(), "trial", None, run_a, payload, "[]", "{}", "queued"),
        )
        job_b = uuid4()
        _insert_job(
            connection,
            JobSpec(project.project_id, job_b, "trial", None, run_b, payload, "[]", "{}", "queued"),
        )
        job_a = connection.execute(
            "SELECT job_id FROM jobs WHERE case_run_id = ?",
            (str(run_a),),
        ).fetchone()
        assert job_a is not None
        _insert_attempt(connection, AttemptSnapshot(project.project_id, attempt_a, UUID(job_a[0]), None, 1))
        _insert_attempt(connection, AttemptSnapshot(project.project_id, attempt_b, job_b, None, 1))
        _insert_action(
            connection,
            ActionEnvelope(
                project.project_id, attempt_a, 1, "step-1", action_a, None, payload, "planned",
                case_a.case_id, version_a.id, False,
            ),
        )
        _insert_action(
            connection,
            ActionEnvelope(
                project.project_id, attempt_b, 1, "step-1", action_b, None, payload, "planned",
                case_b.case_id, version_b.id, False,
            ),
        )
        _insert_review(
            connection,
            ReviewSnapshot(
                project.project_id, review_a, case_a.case_id, version_a.id, payload, None, run_a, payload, None, 1
            ),
        )
        _insert_review(
            connection,
            ReviewSnapshot(
                project.project_id, review_b, case_b.case_id, version_b.id, payload, None, run_b, payload, None, 2
            ),
        )
        _insert_artifact(
            connection,
            ArtifactRef(
                project.project_id, artifact_id, attempt_a, action_a, None, None, None, None, None, None, None, None, None
            ),
        )
        zero_owner = _denied(
            connection,
            """
            INSERT INTO artifact_refs (
                project_id, artifact_id, attempt_id, action_id, check_id, recording_id, review_id,
                build_id, export_id, package_id, healing_id, proposal_id, resource_observation_id
            ) VALUES (?, ?, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL)
            """,
            (str(project.project_id), str(uuid4())),
        )
        two_owners = _denied(
            connection,
            """
            INSERT INTO artifact_refs (
                project_id, artifact_id, attempt_id, action_id, check_id, recording_id, review_id,
                build_id, export_id, package_id, healing_id, proposal_id, resource_observation_id
            ) VALUES (?, ?, ?, ?, NULL, NULL, ?, NULL, NULL, NULL, NULL, NULL, NULL)
            """,
            (str(project.project_id), str(uuid4()), str(attempt_a), str(action_a), str(review_a)),
        )
        _insert_evidence(
            connection,
            ReviewEvidenceEntry(
                project.project_id, review_a, uuid4(), "ITEM", run_a, attempt_a, action_a, artifact_id,
                "after", payload, payload,
            ),
        )
        cross_item = _denied(
            connection,
            """
            INSERT INTO review_evidence_entries (
                project_id, review_id, entry_id, owner_kind, owner_id, attempt_id, action_id,
                artifact_ref_id, role, expected_hash, evidence_digest
            ) VALUES (?, ?, ?, 'ITEM', ?, ?, ?, ?, 'after', ?, ?)
            """,
            (
                str(project.project_id), str(review_a), str(uuid4()), str(run_b), str(attempt_b),
                str(action_b), str(artifact_id), payload, payload,
            ),
        )
        connection.execute(
            """
            INSERT INTO review_decisions (
                project_id, review_id, decision_id, state, actor_id, created_at, reason, version_hash
            ) VALUES (?, ?, ?, 'approved', ?, '2026-11-01T00:00:00+00:00', 'ok', ?)
            """,
            (str(project.project_id), str(review_a), str(uuid4()), str(actor.actor_id), payload),
        )
        second_decision = _denied(
            connection,
            """
            INSERT INTO review_decisions (
                project_id, review_id, decision_id, state, actor_id, created_at, reason, version_hash
            ) VALUES (?, ?, ?, 'approved', ?, '2026-11-01T00:00:01+00:00', 'again', ?)
            """,
            (str(project.project_id), str(review_a), str(uuid4()), str(actor.actor_id), payload),
        )
        _insert_approval(
            connection,
            ApprovalEvent(
                project.project_id, approval_a, case_a.case_id, version_a.id, review_a, "approved",
                None, payload, payload, "ok",
            ),
        )
        _insert_approval(
            connection,
            ApprovalEvent(
                project.project_id, approval_b, case_b.case_id, version_b.id, review_b, "approved",
                None, payload, payload, "ok",
            ),
        )
        foreign_approval = _denied(
            connection,
            "UPDATE automation_cases SET current_approval_id = ? WHERE project_id = ? AND case_id = ?",
            (str(approval_b), str(project.project_id), str(case_a.case_id)),
        )
        connection.execute(
            "UPDATE automation_cases SET current_approval_id = ? WHERE project_id = ? AND case_id = ?",
            (str(approval_b), str(project.project_id), str(case_b.case_id)),
        )
        connection.execute(
            """
            INSERT INTO approval_events (
                project_id, approval_id, case_id, case_version_id, review_id, event_kind,
                prior_approval_id, version_hash, evidence_set_hash, reason
            ) VALUES (?, ?, ?, ?, ?, 'revoked', ?, ?, ?, 'withdraw')
            """,
            (
                str(project.project_id), str(uuid4()), str(case_a.case_id), str(version_a.id),
                str(review_a), str(approval_a), payload, payload,
            ),
        )
        second_revoke = _denied(
            connection,
            """
            INSERT INTO approval_events (
                project_id, approval_id, case_id, case_version_id, review_id, event_kind,
                prior_approval_id, version_hash, evidence_set_hash, reason
            ) VALUES (?, ?, ?, ?, ?, 'revoked', ?, ?, ?, 'again')
            """,
            (
                str(project.project_id), str(uuid4()), str(case_a.case_id), str(version_a.id),
                str(review_a), str(approval_a), payload, payload,
            ),
        )
        connection.execute(
            """
            INSERT INTO artifact_provenance (project_id, provenance_id, artifact_id, source_note)
            VALUES (?, ?, ?, 'lineage')
            """,
            (str(project.project_id), str(uuid4()), str(artifact_id)),
        )
        pins = connection.execute(
            "SELECT COUNT(*) FROM artifact_protections WHERE artifact_id = ?",
            (str(artifact_id),),
        ).fetchone()
        connection.execute(
            "INSERT INTO app_builds (project_id, build_id, content_hash) VALUES (?, ?, ?)",
            (str(project.project_id), str(uuid4()), payload),
        )
        connection.execute(
            "INSERT INTO backup_receipts (project_id, receipt_id, created_at) VALUES (?, ?, ?)",
            (str(project.project_id), str(uuid4()), requested),
        )
        manual_id = uuid4()
        connection.execute(
            """
            INSERT INTO manual_retention_requests (project_id, request_id, created_at)
            VALUES (?, ?, ?)
            """,
            (str(project.project_id), str(manual_id), requested),
        )
        protection_id = uuid4()
        _insert_protection(
            connection,
            ArtifactProtection(project.project_id, protection_id, artifact_id, "manual", None, None, manual_id),
        )
        connection.execute(
            """
            INSERT INTO protection_releases (project_id, release_id, protection_id, released_at)
            VALUES (?, ?, ?, ?)
            """,
            (str(project.project_id), str(uuid4()), str(protection_id), requested),
        )
    assert pins is not None
    assert cross_item is True
    observed = {
        "invalid_typed_owner_denied": zero_owner and two_owners,
        "foreign_approval_denied": foreign_approval,
        "duplicate_decision_denied": second_decision and second_revoke,
        "provenance_implies_pin": int(pins[0]) != 0,
    }
    assert observed == {
        "invalid_typed_owner_denied": True,
        "foreign_approval_denied": True,
        "duplicate_decision_denied": True,
        "provenance_implies_pin": False,
    }


def test_w06_05(tmp_path: Path) -> None:
    from aiqa.api.app import create_app
    from aiqa.config import load_settings
    from aiqa.contracts.jobs import AttemptSnapshot, CaseRunSnapshot, ExecutionSnapshot, JobSpec
    from aiqa.contracts.recordings import RecordingManifest, RecordingSession
    from aiqa.contracts.replay import HealingEpisode, PackageStep, RepairProposal, ReplayPackage, RuntimeOverride
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.domain.versions import bind_case_store, create_case, save_case_revision
    from aiqa.store.database import migrate_store
    from aiqa.store.models import Actor, ProjectCreate

    root = tmp_path / "runtime"
    app = create_app(
        load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)})
    )
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("Alpha", "w0605", "a", "web"))
    actor = Actor(actor_id=owner.actor_id, project_scope=project.project_id, is_local_owner=True)
    with bind_case_store(store):
        case_a = create_case(actor, "Alpha", None)
        case_b = create_case(actor, "Beta", None)
        version_a = save_case_revision(actor, case_a.case_id, _revision(), None)
        version_b = save_case_revision(actor, case_b.case_id, _revision(), None)
    store.close()

    requested = "2026-11-01T00:00:00+00:00"
    payload = "sha256:" + ("ab" * 32)
    body = "sha256:" + ("cd" * 32)
    recording_id = uuid4()
    manifest_id = uuid4()
    package_id = uuid4()
    execution_id = uuid4()
    run_id = uuid4()
    job_id = uuid4()
    attempt_id = uuid4()
    episode_id = uuid4()
    package = ReplayPackage(
        project.project_id, package_id, case_a.case_id, version_a.id, True, "1", manifest_id, payload,
        payload, payload, "runtime", "compiler", payload, payload, body,
    )
    connection = sqlite3.connect(root / "db" / "aiqa.sqlite")
    connection.isolation_level = None
    connection.execute("PRAGMA foreign_keys=ON")
    try:
        _insert_recording(
            connection,
            RecordingSession(
                project.project_id, case_a.case_id, recording_id, "recorded", version_a.id, None, None, None,
                "stored", "stopped", "completed", "incomplete",
            ),
        )
        _insert_manifest(
            connection,
            RecordingManifest(
                project.project_id, case_a.case_id, recording_id, manifest_id, 1, "original", None,
                version_a.content_hash, payload, "[]", "incomplete", "finish-1", body,
            ),
        )
        from dataclasses import replace

        package_version_id = uuid4()
        connection.execute("BEGIN")
        _insert_produced_fixture(connection, version_a.id, package_version_id, manifest_id, package_id)
        package = replace(package, case_version_id=package_version_id, source_manifest_hash=body)
        _insert_execution(
            connection,
            ExecutionSnapshot(project.project_id, execution_id, "Trial", "trial", "single", None, requested),
        )
        _insert_case_run(
            connection,
            CaseRunSnapshot(
                project.project_id, execution_id, run_id, case_a.case_id, package_version_id, "trial", requested
            ),
        )
        _insert_job(connection, JobSpec(project.project_id, job_id, "trial", None, run_id, payload, "[]", "{}", "queued"))
        _insert_attempt(connection, AttemptSnapshot(project.project_id, attempt_id, job_id, None, 1))
        connection.execute(
            """
            INSERT INTO package_version_links (project_id, case_id, version_id, package_id)
            VALUES (?, ?, ?, ?)
            """,
            (str(project.project_id), str(case_a.case_id), str(package_version_id), str(package_id)),
        )
        _insert_package(connection, package)
        _insert_step(connection, PackageStep(project.project_id, package_id, "step-1", 1, payload))
        connection.execute("COMMIT")
        draft = _denied(
            connection,
            """
            INSERT INTO replay_packages (
                project_id, package_id, case_id, case_version_id, ready, schema_version,
                source_manifest_id, source_manifest_hash, raw_source_hash, approved_code_hash,
                runtime_ref, compiler_ref, lock_hash, step_mapping_hash, body_hash
            ) VALUES (?, ?, ?, ?, 0, '1', ?, ?, ?, ?, 'runtime', 'compiler', ?, ?, ?)
            """,
            (
                str(project.project_id), str(uuid4()), str(case_a.case_id), str(package_version_id),
                str(manifest_id), payload, payload, payload, payload, payload, body,
            ),
        )
        cross_package = _denied(
            connection,
            """
            INSERT INTO replay_packages (
                project_id, package_id, case_id, case_version_id, ready, schema_version,
                source_manifest_id, source_manifest_hash, raw_source_hash, approved_code_hash,
                runtime_ref, compiler_ref, lock_hash, step_mapping_hash, body_hash
            ) VALUES (?, ?, ?, ?, 1, '1', ?, ?, ?, ?, 'runtime', 'compiler', ?, ?, ?)
            """,
            (
                str(project.project_id), str(uuid4()), str(case_a.case_id), str(version_b.id),
                str(manifest_id), payload, payload, payload, payload, payload, body,
            ),
        )
        foreign_pointer = _denied(
            connection,
            """
            INSERT INTO package_version_links (project_id, case_id, version_id, package_id)
            VALUES (?, ?, ?, ?)
            """,
            (str(project.project_id), str(case_b.case_id), str(version_b.id), str(package_id)),
        )
        episode = HealingEpisode(project.project_id, episode_id, run_id, attempt_id, package_id, "reserve-1")
        _insert_episode(connection, episode)
        second_episode = _denied(
            connection,
            """
            INSERT INTO healing_episodes (
                project_id, episode_id, case_run_id, attempt_id, package_id, request_key
            ) VALUES (?, ?, ?, ?, ?, 'reserve-2')
            """,
            (str(project.project_id), str(uuid4()), str(run_id), str(attempt_id), str(package_id)),
        )
        _insert_override(
            connection,
            RuntimeOverride(
                project.project_id, uuid4(), episode_id, run_id, attempt_id, package_id, "override-1", payload
            ),
        )
        second_override = _denied(
            connection,
            """
            INSERT INTO runtime_overrides (
                project_id, override_id, episode_id, case_run_id, attempt_id, package_id, request_key, body_hash
            ) VALUES (?, ?, ?, ?, ?, ?, 'override-2', ?)
            """,
            (
                str(project.project_id), str(uuid4()), str(episode_id), str(run_id),
                str(attempt_id), str(package_id), payload,
            ),
        )
        _insert_proposal(
            connection,
            RepairProposal(
                project.project_id, uuid4(), episode_id, run_id, attempt_id, package_id, "proposal-1", payload
            ),
        )
        columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(replay_packages)")}
        drafts = connection.execute(
            "SELECT COUNT(*) FROM replay_packages WHERE case_version_id = ? AND ready = 0",
            (str(package_version_id),),
        ).fetchone()
        ready = connection.execute(
            "SELECT COUNT(*) FROM replay_packages WHERE case_version_id = ? AND ready = 1",
            (str(package_version_id),),
        ).fetchone()
    finally:
        connection.close()
    assert drafts is not None and ready is not None
    assert draft is True
    assert foreign_pointer is True
    assert "produced_version_hash" not in columns
    assert "produced_version_id" not in columns
    observed = {
        "draft_package_count": int(drafts[0]),
        "ready_package_count": int(ready[0]),
        "cross_package_denied": cross_package,
        "episode_unique": second_episode and second_override,
    }
    assert observed == {
        "draft_package_count": 0,
        "ready_package_count": 1,
        "cross_package_denied": True,
        "episode_unique": True,
    }


async def _proposal_flow(
    app: object, root: Path, project_id: object, tc_version_id: object, body: dict[str, object]
) -> dict[str, object]:
    import json
    from uuid import UUID

    import httpx
    from fastapi import FastAPI

    from aiqa.api.app import create_app
    from aiqa.config import load_settings
    from aiqa.contracts.jobs import JobSpec

    assert isinstance(app, FastAPI)
    assert isinstance(project_id, UUID)
    assert isinstance(tc_version_id, UUID)
    origin = "http://127.0.0.1:8000"
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=origin) as client:
        session = await _proposal_session(client, origin, project_id, "w0609")
        created = await _proposal_send(
            client, session, "POST", f"/api/v1/projects/{project_id}/cases", {"name": "Alpha", "tc_reference": None}, "case"
        )
        other = await _proposal_send(
            client, session, "POST", f"/api/v1/projects/{project_id}/cases", {"name": "Other", "tc_reference": None}, "other-case"
        )
        assert created.status_code == 201, created.text
        assert other.status_code == 201, other.text
        case_id = created.json()["case_id"]
        other_id = other.json()["case_id"]
        version_body = {
            "definition": body,
            "settings": {"target_kind": "web"},
            "recorded_steps": [],
            "parent_version_id": None,
            "base_version_id": None,
            "reason": "draft",
            "expected_head": None,
            "branch": False,
        }
        first = await _proposal_send(
            client, session, "POST", f"/api/v1/projects/{project_id}/cases/{case_id}/versions", version_body, "version"
        )
        other_version = await _proposal_send(
            client, session, "POST", f"/api/v1/projects/{project_id}/cases/{other_id}/versions", version_body, "other-version"
        )
        assert first.status_code == 201, first.text
        assert other_version.status_code == 201, other_version.text
        head = first.json()["id"]
        base_hash = first.json()["content_hash"]
        structure_job = uuid4()
        foreign_job = uuid4()
        with sqlite3.connect(root / "db" / "aiqa.sqlite") as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            _insert_job(
                connection,
                JobSpec(project_id, structure_job, "structure", None, None, "hash", json.dumps([case_id]), "{}", "queued"),
            )
            _insert_job(
                connection,
                JobSpec(project_id, foreign_job, "structure", None, None, "hash", json.dumps([other_id]), "{}", "queued"),
            )
        common = {"base_version_id": head, "base_hash": base_hash, "body": body}
        rejected = await _proposal_send(
            client,
            session,
            "POST",
            f"/api/v1/projects/{project_id}/cases/{case_id}/tc-import-proposals",
            {**common, "source_job_id": None, "tc_version_id": str(tc_version_id)},
            "reject-proposal",
        )
        assert rejected.status_code == 201, rejected.text
        refusal = await _proposal_send(
            client,
            session,
            "POST",
            f"/api/v1/projects/{project_id}/cases/{case_id}/proposal-rejections",
            {"proposal_id": rejected.json()["proposal_id"]},
            "reject",
        )
        accepted = await _proposal_send(
            client,
            session,
            "POST",
            f"/api/v1/projects/{project_id}/cases/{case_id}/tc-import-proposals",
            {**common, "source_job_id": None, "tc_version_id": str(tc_version_id)},
            "accept-proposal",
        )
        assert accepted.status_code == 201, accepted.text
        first_accept = await _proposal_send(
            client,
            session,
            "POST",
            f"/api/v1/projects/{project_id}/cases/{case_id}/proposal-acceptances",
            {"proposal_id": accepted.json()["proposal_id"], "expected_head": head},
            "accept-1",
        )
        second_accept = await _proposal_send(
            client,
            session,
            "POST",
            f"/api/v1/projects/{project_id}/cases/{case_id}/proposal-acceptances",
            {"proposal_id": accepted.json()["proposal_id"], "expected_head": head},
            "accept-2",
        )
        assert first_accept.status_code == 201, first_accept.text
        assert second_accept.status_code == 201, second_accept.text
        assert first_accept.json()["id"] == second_accept.json()["id"]
        structure = await _proposal_send(
            client,
            session,
            "POST",
            f"/api/v1/projects/{project_id}/cases/{case_id}/proposals",
            {**common, "kind": "structure", "source_job_id": str(structure_job), "tc_version_id": None},
            "structure-proposal",
        )
        assert structure.status_code == 201, structure.text
        stale = await _proposal_send(
            client,
            session,
            "POST",
            f"/api/v1/projects/{project_id}/cases/{case_id}/proposal-acceptances",
            {"proposal_id": structure.json()["proposal_id"], "expected_head": head},
            "stale",
        )
        foreign = await _proposal_send(
            client,
            session,
            "POST",
            f"/api/v1/projects/{project_id}/cases/{case_id}/proposals",
            {**common, "kind": "structure", "source_job_id": str(foreign_job), "tc_version_id": None},
            "foreign",
        )
        assert foreign.status_code == 422, foreign.text
        stored_hash = structure.json()["body_hash"]
        proposal_id = structure.json()["proposal_id"]
    restarted = create_app(
        load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)})
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=restarted), base_url=origin) as client:
        session = await _proposal_session(client, origin, project_id, "w0609-again")
        loaded = await _proposal_send(
            client,
            session,
            "GET",
            f"/api/v1/projects/{project_id}/cases/{case_id}/proposals/{proposal_id}",
            None,
            "read",
        )
    with sqlite3.connect(root / "db" / "aiqa.sqlite") as connection:
        accepted_count = connection.execute(
            """
            SELECT COUNT(produced_version_id) FROM case_proposal_decisions
            WHERE proposal_id = ? AND decision = 'accepted'
            """,
            (accepted.json()["proposal_id"],),
        ).fetchone()
        rejected_count = connection.execute(
            "SELECT COUNT(produced_version_id) FROM case_proposal_decisions WHERE decision = 'rejected'"
        ).fetchone()
        approval = connection.execute(
            "SELECT current_approval_id FROM automation_cases WHERE case_id = ?",
            (case_id,),
        ).fetchone()
    assert accepted_count is not None and rejected_count is not None and approval is not None
    assert refusal.status_code == 200
    return {
        "accepted_versions_per_proposal": int(accepted_count[0]),
        "rejected_versions": int(rejected_count[0]),
        "stale_head_status": stale.status_code,
        "proposal_survives_restart": loaded.status_code == 200 and loaded.json()["body_hash"] == stored_hash,
        "approval_copied": approval[0] is not None,
    }


async def _proposal_session(client: object, origin: str, project_id: object, name: str) -> dict[str, str]:
    import httpx

    assert isinstance(client, httpx.AsyncClient)
    issued = await client.post(
        "/api/v1/session/nonces",
        json={"origin": origin, "project_id": str(project_id)},
        headers={"Idempotency-Key": f"{name}-nonce", "Origin": origin},
    )
    booted = await client.post(
        "/api/v1/session/bootstrap",
        json={"nonce": issued.json()["nonce"]},
        headers={"Idempotency-Key": f"{name}-boot", "Origin": origin},
    )
    return {"Origin": origin, "X-CSRF-Token": booted.json()["csrf_token"], "cookie": booted.cookies["aiqa_session"]}


async def _proposal_send(
    client: object,
    session: dict[str, str],
    method: str,
    path: str,
    payload: dict[str, object] | None,
    key: str,
) -> object:
    import httpx

    assert isinstance(client, httpx.AsyncClient)
    client.cookies.set("aiqa_session", session["cookie"])
    headers = {"Origin": session["Origin"], "X-CSRF-Token": session["X-CSRF-Token"], "Idempotency-Key": key}
    if method == "GET":
        return await client.get(path, headers=headers)
    return await client.post(path, json=payload, headers=headers)


def test_w06_09(tmp_path: Path) -> None:
    import asyncio

    import httpx

    from aiqa.api.app import create_app
    from aiqa.config import load_settings
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.domain.tcs import bind_tc_store, save_tc_revision
    from aiqa.store.database import StorageConfig, migrate_store, open_store
    from aiqa.store.models import Actor, ProjectCreate, TcRevisionInput
    from aiqa.store.schema import validate_schema

    root = tmp_path / "runtime"
    app = create_app(
        load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)})
    )
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("Alpha", "w0609", "a", "web"))
    actor = Actor(owner.actor_id, project.project_id, True)
    with bind_tc_store(store):
        tc = save_tc_revision(TcRevisionInput(project.project_id, actor.actor_id, "Checkout", {"title": "pay"}))
    store.close()

    body = {
        "raw_text": "pay",
        "objective": "pay the bill",
        "preconditions": ["logged in"],
        "variables": {"amount": "1.10"},
        "secret_refs": {},
        "steps": [
            {"id": "step-1", "instruction": "press pay", "expected": [{"id": "check-1", "kind": "text", "expected": "ok"}]}
        ],
        "final_expected": [],
        "path_policy": {"must_use": ["pay"], "forbidden": []},
    }
    observed = asyncio.run(_proposal_flow(app, root, project.project_id, tc.id, body))
    checked = open_store(
        StorageConfig.from_settings(
            load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)})
        )
    )
    try:
        report = validate_schema(checked)
    finally:
        checked.close()
    assert report.integrity == "ok"
    assert report.foreign_key_violations == 0
    assert report.all_fk_target_tables_exist is True
    assert observed == {
        "accepted_versions_per_proposal": 1,
        "rejected_versions": 0,
        "stale_head_status": 409,
        "proposal_survives_restart": True,
        "approval_copied": False,
    }


def test_w06_08(tmp_path: Path) -> None:
    from aiqa.api.app import create_app
    from aiqa.api.auth import bound_auth_store, enroll_worker
    from aiqa.config import load_settings
    from aiqa.contracts.jobs import AttemptSnapshot, JobSpec
    from aiqa.contracts.recordings import RecordingSession
    from aiqa.contracts.resources import PhysicalResourceKey, ResourceAlias, ResourceObservation
    from aiqa.contracts.reviews import ArtifactRef
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.domain.versions import bind_case_store, create_case, save_case_revision
    from aiqa.store.database import StorageConfig, migrate_store, open_store
    from aiqa.store.models import Actor, ProjectCreate
    from aiqa.store.schema import validate_schema

    root = tmp_path / "runtime"
    app = create_app(
        load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)})
    )
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project_a = create_project(owner, ProjectCreate("Alpha", "w0608a", "a", "web"))
        project_b = create_project(owner, ProjectCreate("Beta", "w0608b", "b", "web"))
    actor = Actor(owner.actor_id, project_a.project_id, True)
    with bind_case_store(store):
        case = create_case(actor, "Alpha", None)
        version = save_case_revision(actor, case.case_id, _revision(), None)
    worker = uuid4()
    with bound_auth_store(store):
        enroll_worker(Actor(owner.actor_id, project_a.project_id, True), str(worker), "recording")
    store.close()

    key_id = uuid4()
    probe_job = uuid4()
    other_job = uuid4()
    foreign_job = uuid4()
    attempt_id = uuid4()
    other_attempt = uuid4()
    artifact_id = uuid4()
    recording_id = uuid4()
    observation = ResourceObservation(
        project_a.project_id,
        key_id,
        probe_job,
        attempt_id,
        "2026-11-01T00:00:00+00:00",
        '{"width": 100, "height": 200}',
        artifact_id,
        "scope-w06-08",
    )
    with sqlite3.connect(root / "db" / "aiqa.sqlite") as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        _insert_physical_key(connection, key_id, PhysicalResourceKey(worker, "SERIAL-W06-08"))
        _insert_alias(connection, ResourceAlias(project_a.project_id, key_id, "browser", "web"))
        _insert_job(
            connection,
            JobSpec(project_a.project_id, probe_job, "resource_probe", None, None, "hash", '["preview"]', "{}", "queued"),
        )
        _insert_job(
            connection,
            JobSpec(project_a.project_id, other_job, "resource_probe", None, None, "hash", '["other"]', "{}", "queued"),
        )
        _insert_job(
            connection,
            JobSpec(project_b.project_id, foreign_job, "resource_probe", None, None, "hash", '["foreign"]', "{}", "queued"),
        )
        connection.execute(
            """
            INSERT INTO leases (project_id, job_id, generation, worker_id, physical_key_id, expires_at)
            VALUES (?, ?, 1, ?, ?, '2026-11-01T01:00:00+00:00')
            """,
            (str(project_a.project_id), str(probe_job), str(worker), str(key_id)),
        )
        connection.execute(
            """
            INSERT INTO leases (project_id, job_id, generation, worker_id, physical_key_id, expires_at)
            VALUES (?, ?, 1, ?, ?, '2026-11-01T01:00:00+00:00')
            """,
            (str(project_a.project_id), str(other_job), str(worker), str(key_id)),
        )
        _insert_attempt(connection, AttemptSnapshot(project_a.project_id, attempt_id, probe_job, key_id, 1))
        _insert_attempt(connection, AttemptSnapshot(project_a.project_id, other_attempt, other_job, key_id, 1))
        _insert_recording(
            connection,
            RecordingSession(
                project_a.project_id, case.case_id, recording_id, "recorded", version.id,
                None, None, None, "local", "stopped", "open", "incomplete",
            ),
        )
        _insert_observation(connection, observation)
        foreign_project = _denied(
            connection,
            """
            INSERT INTO resource_observations (
                project_id, resource_id, probe_job_id, attempt_id, captured_at, geometry, artifact_id, scope_hash
            ) VALUES (?, ?, ?, ?, '2026-11-01T00:00:01+00:00', '{}', ?, 'other-scope')
            """,
            (str(project_a.project_id), str(key_id), str(foreign_job), str(attempt_id), str(uuid4())),
        )
        foreign_attempt = _denied(
            connection,
            """
            INSERT INTO resource_observations (
                project_id, resource_id, probe_job_id, attempt_id, captured_at, geometry, artifact_id, scope_hash
            ) VALUES (?, ?, ?, ?, '2026-11-01T00:00:02+00:00', '{}', ?, 'other-attempt')
            """,
            (str(project_a.project_id), str(key_id), str(probe_job), str(other_attempt), str(uuid4())),
        )
        recording_after = _denied(
            connection,
            """
            INSERT INTO artifact_refs (
                project_id, artifact_id, attempt_id, action_id, check_id, recording_id, review_id,
                build_id, export_id, package_id, healing_id, proposal_id, resource_observation_id
            ) VALUES (?, ?, NULL, NULL, NULL, ?, NULL, NULL, NULL, NULL, NULL, NULL, NULL)
            """,
            (str(project_a.project_id), str(artifact_id), str(recording_id)),
        )
        two_owners = _denied(
            connection,
            """
            INSERT INTO artifact_refs (
                project_id, artifact_id, attempt_id, action_id, check_id, recording_id, review_id,
                build_id, export_id, package_id, healing_id, proposal_id, resource_observation_id
            ) VALUES (?, ?, NULL, NULL, NULL, ?, NULL, NULL, NULL, NULL, NULL, NULL, ?)
            """,
            (str(project_a.project_id), str(uuid4()), str(recording_id), str(artifact_id)),
        )
        _insert_artifact(
            connection,
            ArtifactRef(
                project_a.project_id, artifact_id, attempt_id, None, None, None, None,
                None, None, None, None, None, artifact_id,
            ),
        )
        recording_links = connection.execute(
            """
            SELECT COUNT(*) FROM artifact_refs
            WHERE artifact_id = ? AND recording_id IS NOT NULL
            """,
            (str(artifact_id),),
        ).fetchone()
    checked = open_store(StorageConfig.from_settings(
        load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)})
    ))
    try:
        report = validate_schema(checked)
    finally:
        checked.close()
    assert recording_links is not None
    assert report.integrity == "ok"
    assert report.foreign_key_violations == 0
    assert report.all_fk_target_tables_exist is True
    observed = {
        "foreign_observation_denied": foreign_project and foreign_attempt,
        "exactly_one_artifact_owner": two_owners,
        "probe_capture_as_recording_after": recording_after is False or int(recording_links[0]) > 0,
    }
    assert observed == {
        "foreign_observation_denied": True,
        "exactly_one_artifact_owner": True,
        "probe_capture_as_recording_after": False,
    }


def test_w06_07(tmp_path: Path) -> None:
    from test_schema_integrity import observed_reports

    observed = observed_reports(tmp_path)
    expected = {
        "integrity": "ok",
        "foreign_key_violations": 0,
        "required_indexes_present": True,
        "mutable_sealed_content": False,
        "all_fk_target_tables_exist": True,
        "nullable_fk_inserts_work": True,
    }
    assert observed[0] == expected
    assert observed[1] == expected


def test_w06_06(tmp_path: Path) -> None:
    from aiqa.api.app import create_app
    from aiqa.config import load_settings
    from aiqa.contracts.jobs import CaseRunSnapshot, ExecutionSnapshot
    from aiqa.contracts.reports import (
        FingerprintObservation,
        ItemFinalization,
        ItemLifecycleEvent,
        UsageAdjustment,
    )
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.domain.versions import bind_case_store, create_case, save_case_revision
    from aiqa.store.database import migrate_store
    from aiqa.store.models import Actor, ProjectCreate

    root = tmp_path / "runtime"
    app = create_app(
        load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)})
    )
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("Alpha", "w0606", "a", "web"))
    actor = Actor(actor_id=owner.actor_id, project_scope=project.project_id, is_local_owner=True)
    with bind_case_store(store):
        case = create_case(actor, "Alpha", None)
        version = save_case_revision(actor, case.case_id, _revision(), None)
    store.close()

    requested = "2026-11-01T00:00:00+00:00"
    content_hash = "sha256:" + ("ab" * 32)
    execution_id = uuid4()
    run_id = uuid4()
    with sqlite3.connect(root / "db" / "aiqa.sqlite") as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        _insert_execution(
            connection,
            ExecutionSnapshot(project.project_id, execution_id, "Trial", "trial", "single", None, requested),
        )
        _insert_case_run(
            connection,
            CaseRunSnapshot(
                project.project_id, execution_id, run_id, case.case_id, version.id, "trial", requested
            ),
        )
        _insert_finalization(
            connection,
            ItemFinalization(
                project.project_id, run_id, 10, 20, "2026-11", content_hash, "PASS", True
            ),
        )
        second_final = _denied(
            connection,
            """
            INSERT INTO item_finalizations (
                project_id, case_run_id, created_seq, finalized_seq, release_label,
                content_hash, core_result, denominator
            ) VALUES (?, ?, 10, 20, '2026-11', ?, 'FAIL', 1)
            """,
            (str(project.project_id), str(run_id), content_hash),
        )
        hash_update = _denied(
            connection,
            "UPDATE item_finalizations SET content_hash = ? WHERE case_run_id = ?",
            ("sha256:" + ("ef" * 32), str(run_id)),
        )
        result_update = _denied(
            connection,
            "UPDATE item_finalizations SET core_result = 'FAIL' WHERE case_run_id = ?",
            (str(run_id),),
        )
        _insert_lifecycle(
            connection,
            ItemLifecycleEvent(project.project_id, uuid4(), run_id, 10, "created"),
        )
        _insert_lifecycle(
            connection,
            ItemLifecycleEvent(project.project_id, uuid4(), run_id, 20, "finalized"),
        )
        connection.execute(
            """
            INSERT INTO item_usage_facts (
                project_id, usage_id, case_run_id, commit_seq, role, measurement_status, amount, currency
            ) VALUES (?, ?, ?, 10, 'verification', 'measured', '1.00', 'USD')
            """,
            (str(project.project_id), str(uuid4()), str(run_id)),
        )
        connection.execute(
            """
            INSERT INTO item_usage_facts (
                project_id, usage_id, case_run_id, commit_seq, role, measurement_status, amount, currency
            ) VALUES (?, ?, ?, 10, 'authoring', 'not_used', NULL, NULL)
            """,
            (str(project.project_id), str(uuid4()), str(run_id)),
        )
        connection.execute(
            """
            INSERT INTO item_usage_facts (
                project_id, usage_id, case_run_id, commit_seq, role, measurement_status, amount, currency
            ) VALUES (?, ?, ?, 10, 'maintenance', 'unknown', NULL, NULL)
            """,
            (str(project.project_id), str(uuid4()), str(run_id)),
        )
        _insert_adjustment(
            connection,
            UsageAdjustment(
                project.project_id, uuid4(), run_id, 30, "verification", "measured", "0.10", "USD"
            ),
        )
        usage_update = _denied(
            connection,
            "UPDATE item_usage_facts SET amount = '9.00' WHERE case_run_id = ? AND measurement_status = 'measured'",
            (str(run_id),),
        )
        original = connection.execute(
            """
            SELECT amount FROM item_usage_facts
            WHERE case_run_id = ? AND measurement_status = 'measured'
            """,
            (str(run_id),),
        ).fetchone()
        _insert_fingerprint(
            connection,
            FingerprintObservation(
                project.project_id, uuid4(), run_id, 20, case.case_id, version.verification_digest,
                "web", "env-1", "data-1", "oracle-1", "series-v1",
            ),
        )
        fingerprint = connection.execute(
            "SELECT commit_seq FROM fingerprint_observations WHERE case_run_id = ?",
            (str(run_id),),
        ).fetchone()
        connection.execute(
            """
            INSERT INTO analysis_records (project_id, record_id, case_run_id, commit_seq, body)
            VALUES (?, ?, ?, 20, 'note')
            """,
            (str(project.project_id), str(uuid4()), str(run_id)),
        )
        analysis_update = _denied(
            connection,
            "UPDATE analysis_records SET body = 'changed' WHERE case_run_id = ?",
            (str(run_id),),
        )
        visible = [
            int(row[0])
            for row in connection.execute(
                """
                SELECT commit_seq FROM item_lifecycle_events WHERE case_run_id = ? AND commit_seq <= ?
                UNION ALL
                SELECT commit_seq FROM usage_adjustments WHERE case_run_id = ? AND commit_seq <= ?
                ORDER BY commit_seq
                """,
                (str(run_id), 30, str(run_id), 30),
            )
        ]
        visible_10 = [
            int(row[0])
            for row in connection.execute(
                """
                SELECT commit_seq FROM item_lifecycle_events WHERE case_run_id = ? AND commit_seq <= 10
                UNION ALL
                SELECT commit_seq FROM usage_adjustments WHERE case_run_id = ? AND commit_seq <= 10
                """,
                (str(run_id), str(run_id)),
            )
        ]
        stored = connection.execute(
            "SELECT created_seq, finalized_seq, content_hash FROM item_finalizations WHERE case_run_id = ?",
            (str(run_id),),
        ).fetchone()
    assert original is not None and fingerprint is not None and stored is not None
    assert hash_update is True
    assert result_update is True
    assert usage_update is True
    assert analysis_update is True
    assert visible_10 == [10]
    assert visible == [10, 20, 30]
    assert stored[0] == 10 and stored[1] == 20 and stored[2] == content_hash
    observed = {
        "finalization_unique": second_final,
        "late_usage_updates_original": original[0] != "1.00",
        "actual_fingerprint_has_seq": fingerprint[0] is not None,
    }
    assert observed == {
        "finalization_unique": True,
        "late_usage_updates_original": False,
        "actual_fingerprint_has_seq": True,
    }


def _resource_key(worker_id: object):
    from uuid import UUID

    from aiqa.contracts.resources import PhysicalResourceKey

    assert isinstance(worker_id, UUID)
    return PhysicalResourceKey(worker_id, "SERIAL-W06-02")


def _revision() -> CaseRevisionInput:
    definition = CaseDefinition(
        raw_text="pay",
        objective="pay",
        preconditions=("logged in",),
        variables={"amount": "1.10"},
        secret_refs={},
        steps=(StepSpec("step-1", "press pay", (CheckSpec("check-1", "text", "ok"),)),),
        final_expected=(),
        path_policy=PathPolicy(("pay",), ()),
    )
    return CaseRevisionInput(definition, CaseSettings("web"), (), None, None, "draft", False)


def _insert_recording(connection: sqlite3.Connection, session: object) -> None:
    from aiqa.contracts.recordings import RecordingSession

    assert isinstance(session, RecordingSession)
    connection.execute(
        """
        INSERT INTO recordings (
            project_id, case_id, recording_id, creation_kind, input_case_version_id,
            base_case_version_id, parent_recording_id, source_recording_id,
            storage_status, stop_status, completion_status, evidence_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(session.project_id),
            str(session.case_id),
            str(session.recording_id),
            session.creation_kind,
            str(session.input_case_version_id),
            None if session.base_case_version_id is None else str(session.base_case_version_id),
            None if session.parent_recording_id is None else str(session.parent_recording_id),
            None if session.source_recording_id is None else str(session.source_recording_id),
            session.storage_status,
            session.stop_status,
            session.completion_status,
            session.evidence_status,
        ),
    )


def _insert_manifest(connection: sqlite3.Connection, manifest: object) -> None:
    from aiqa.contracts.recordings import RecordingManifest

    assert isinstance(manifest, RecordingManifest)
    connection.execute(
        """
        INSERT INTO recording_manifests (
            project_id, case_id, recording_id, manifest_id, revision, kind, prior_manifest_id,
            input_version_hash, source_artifact_hashes, action_mapping, evidence_completeness,
            request_key, body_hash
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(manifest.project_id),
            str(manifest.case_id),
            str(manifest.recording_id),
            str(manifest.manifest_id),
            manifest.revision,
            manifest.kind,
            None if manifest.prior_manifest_id is None else str(manifest.prior_manifest_id),
            manifest.input_version_hash,
            manifest.source_artifact_hashes,
            manifest.action_mapping,
            manifest.evidence_completeness,
            manifest.request_key,
            manifest.body_hash,
        ),
    )


def _insert_receipt(connection: sqlite3.Connection, receipt: object) -> None:
    from aiqa.contracts.recordings import MaterializationReceipt

    assert isinstance(receipt, MaterializationReceipt)
    connection.execute(
        """
        INSERT INTO materialization_receipts (
            project_id, receipt_id, manifest_id, produced_version_id, body_hash
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (
            str(receipt.project_id),
            str(receipt.receipt_id),
            str(receipt.manifest_id),
            str(receipt.produced_version_id),
            receipt.body_hash,
        ),
    )


def _insert_physical_key(connection: sqlite3.Connection, key_id: object, key: object) -> None:
    from uuid import UUID

    from aiqa.contracts.resources import PhysicalResourceKey

    assert isinstance(key_id, UUID)
    assert isinstance(key, PhysicalResourceKey)
    connection.execute(
        """
        INSERT INTO physical_resource_keys (physical_key_id, worker_id, native_id)
        VALUES (?, ?, ?)
        """,
        (str(key_id), str(key.worker_id), key.native_id),
    )


def _insert_execution(connection: sqlite3.Connection, execution: object) -> None:
    from aiqa.contracts.jobs import ExecutionSnapshot

    assert isinstance(execution, ExecutionSnapshot)
    connection.execute(
        """
        INSERT INTO executions (
            project_id, execution_id, name, purpose, source, suite_version_id, scope_requested_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(execution.project_id),
            str(execution.execution_id),
            execution.name,
            execution.purpose,
            execution.source,
            None if execution.suite_version_id is None else str(execution.suite_version_id),
            execution.scope_requested_at,
        ),
    )


def _insert_case_run(connection: sqlite3.Connection, item: object) -> None:
    from aiqa.contracts.jobs import CaseRunSnapshot

    assert isinstance(item, CaseRunSnapshot)
    connection.execute(
        """
        INSERT INTO case_runs (
            project_id, execution_id, case_run_id, case_id, case_version_id, purpose, requested_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(item.project_id),
            str(item.execution_id),
            str(item.case_run_id),
            str(item.case_id),
            str(item.case_version_id),
            item.purpose,
            item.requested_at,
        ),
    )


def _insert_job(connection: sqlite3.Connection, job: object) -> None:
    from aiqa.contracts.jobs import JobSpec

    assert isinstance(job, JobSpec)
    connection.execute(
        """
        INSERT INTO jobs (
            project_id, job_id, purpose, recording_id, case_run_id, payload_hash,
            source_refs, limits, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(job.project_id),
            str(job.job_id),
            job.purpose,
            None if job.recording_id is None else str(job.recording_id),
            None if job.case_run_id is None else str(job.case_run_id),
            job.payload_hash,
            job.source_refs,
            job.limits,
            job.status,
        ),
    )


def _insert_attempt(connection: sqlite3.Connection, attempt: object) -> None:
    from aiqa.contracts.jobs import AttemptSnapshot

    assert isinstance(attempt, AttemptSnapshot)
    connection.execute(
        """
        INSERT INTO attempts (project_id, attempt_id, job_id, generation, physical_key_id)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            str(attempt.project_id),
            str(attempt.attempt_id),
            str(attempt.job_id),
            attempt.generation,
            None if attempt.physical_key_id is None else str(attempt.physical_key_id),
        ),
    )


def _insert_action(connection: sqlite3.Connection, action: object) -> None:
    from aiqa.contracts.evidence import ActionEnvelope

    assert isinstance(action, ActionEnvelope)
    connection.execute(
        """
        INSERT INTO actions (
            project_id, attempt_id, action_seq, step_id, action_id, package_step_id,
            proposal_hash, dispatch_state, case_id, case_version_id, outcome_known
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(action.project_id),
            str(action.attempt_id),
            action.action_seq,
            action.step_id,
            str(action.action_id),
            None if action.package_step_id is None else str(action.package_step_id),
            action.proposal_hash,
            action.dispatch_state,
            str(action.case_id),
            str(action.case_version_id),
            1 if action.outcome_known else 0,
        ),
    )


def _insert_check(connection: sqlite3.Connection, result: object) -> None:
    from aiqa.contracts.evidence import CheckResult

    assert isinstance(result, CheckResult)
    connection.execute(
        """
        INSERT INTO check_results (
            project_id, attempt_id, action_id, check_id, status, method, expected_snapshot,
            sanitized_observed, reason, artifact_refs, observed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(result.project_id),
            str(result.attempt_id),
            str(result.action_id),
            result.check_id,
            result.status,
            result.method,
            result.expected_snapshot,
            result.sanitized_observed,
            result.reason,
            result.artifact_refs,
            result.observed_at,
        ),
    )


def _insert_event(connection: sqlite3.Connection, event: object) -> None:
    from aiqa.contracts.evidence import EventEnvelope

    assert isinstance(event, EventEnvelope)
    connection.execute(
        """
        INSERT INTO attempt_events (
            project_id, event_id, attempt_id, local_seq, captured_at, event_type,
            minimum_facts, payload_hash, body_hash, detail_payload
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(event.project_id),
            str(event.event_id),
            str(event.attempt_id),
            event.local_seq,
            event.captured_at,
            event.event_type,
            event.minimum_facts,
            event.payload_hash,
            event.body_hash,
            event.detail_payload,
        ),
    )


def _insert_model_call(connection: sqlite3.Connection, fact: object) -> None:
    from aiqa.contracts.evidence import ModelCallFact

    assert isinstance(fact, ModelCallFact)
    connection.execute(
        """
        INSERT INTO model_call_facts (
            project_id, call_id, attempt_id, role, action_id, check_id, measurement_status,
            input_tokens, output_tokens, cache_tokens, image_tokens
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(fact.project_id),
            str(fact.call_id),
            str(fact.attempt_id),
            fact.role,
            None if fact.action_id is None else str(fact.action_id),
            fact.check_id,
            fact.measurement_status,
            fact.input_tokens,
            fact.output_tokens,
            fact.cache_tokens,
            fact.image_tokens,
        ),
    )


def _insert_observation(connection: sqlite3.Connection, observation: object) -> None:
    from aiqa.contracts.resources import ResourceObservation

    assert isinstance(observation, ResourceObservation)
    connection.execute(
        """
        INSERT INTO resource_observations (
            project_id, resource_id, probe_job_id, attempt_id, captured_at, geometry, artifact_id, scope_hash
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(observation.project_id),
            str(observation.resource_id),
            str(observation.probe_job_id),
            str(observation.attempt_id),
            observation.captured_at,
            observation.geometry,
            str(observation.artifact_id),
            observation.scope_hash,
        ),
    )


def _insert_alias(connection: sqlite3.Connection, alias: object) -> None:
    from aiqa.contracts.resources import ResourceAlias

    assert isinstance(alias, ResourceAlias)
    connection.execute(
        """
        INSERT INTO resource_aliases (project_id, physical_key_id, display_name, target_kind)
        VALUES (?, ?, ?, ?)
        """,
        (str(alias.project_id), str(alias.physical_key_id), alias.display_name, alias.target_kind),
    )


def _insert_package(connection: sqlite3.Connection, package: object) -> None:
    from aiqa.contracts.replay import ReplayPackage

    assert isinstance(package, ReplayPackage)
    connection.execute(
        """
        INSERT INTO replay_packages (
            project_id, package_id, case_id, case_version_id, ready, schema_version,
            source_manifest_id, source_manifest_hash, raw_source_hash, approved_code_hash,
            runtime_ref, compiler_ref, lock_hash, step_mapping_hash, body_hash
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(package.project_id),
            str(package.package_id),
            str(package.case_id),
            str(package.case_version_id),
            1 if package.ready else 0,
            package.schema_version,
            str(package.source_manifest_id),
            package.source_manifest_hash,
            package.raw_source_hash,
            package.approved_code_hash,
            package.runtime_ref,
            package.compiler_ref,
            package.lock_hash,
            package.step_mapping_hash,
            package.body_hash,
        ),
    )


def _insert_step(connection: sqlite3.Connection, step: object) -> None:
    from aiqa.contracts.replay import PackageStep

    assert isinstance(step, PackageStep)
    connection.execute(
        """
        INSERT INTO package_steps (project_id, package_id, step_id, position, step_hash)
        VALUES (?, ?, ?, ?, ?)
        """,
        (str(step.project_id), str(step.package_id), step.step_id, step.position, step.step_hash),
    )


def _insert_episode(connection: sqlite3.Connection, episode: object) -> None:
    from aiqa.contracts.replay import HealingEpisode

    assert isinstance(episode, HealingEpisode)
    connection.execute(
        """
        INSERT INTO healing_episodes (
            project_id, episode_id, case_run_id, attempt_id, package_id, request_key
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            str(episode.project_id),
            str(episode.episode_id),
            str(episode.case_run_id),
            str(episode.attempt_id),
            str(episode.package_id),
            episode.request_key,
        ),
    )


def _insert_override(connection: sqlite3.Connection, override: object) -> None:
    from aiqa.contracts.replay import RuntimeOverride

    assert isinstance(override, RuntimeOverride)
    connection.execute(
        """
        INSERT INTO runtime_overrides (
            project_id, override_id, episode_id, case_run_id, attempt_id, package_id, request_key, body_hash
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(override.project_id),
            str(override.override_id),
            str(override.episode_id),
            str(override.case_run_id),
            str(override.attempt_id),
            str(override.package_id),
            override.request_key,
            override.body_hash,
        ),
    )


def _insert_proposal(connection: sqlite3.Connection, proposal: object) -> None:
    from aiqa.contracts.replay import RepairProposal

    assert isinstance(proposal, RepairProposal)
    connection.execute(
        """
        INSERT INTO repair_proposals (
            project_id, proposal_id, episode_id, case_run_id, attempt_id, package_id, request_key, diff_hash
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(proposal.project_id),
            str(proposal.proposal_id),
            str(proposal.episode_id),
            str(proposal.case_run_id),
            str(proposal.attempt_id),
            str(proposal.package_id),
            proposal.request_key,
            proposal.diff_hash,
        ),
    )


def _insert_finalization(connection: sqlite3.Connection, item: object) -> None:
    from aiqa.contracts.reports import ItemFinalization

    assert isinstance(item, ItemFinalization)
    connection.execute(
        """
        INSERT INTO item_finalizations (
            project_id, case_run_id, created_seq, finalized_seq, release_label,
            content_hash, core_result, denominator
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(item.project_id),
            str(item.case_run_id),
            item.created_seq,
            item.finalized_seq,
            item.release_label,
            item.content_hash,
            item.core_result,
            1 if item.denominator else 0,
        ),
    )


def _insert_lifecycle(connection: sqlite3.Connection, event: object) -> None:
    from aiqa.contracts.reports import ItemLifecycleEvent

    assert isinstance(event, ItemLifecycleEvent)
    connection.execute(
        """
        INSERT INTO item_lifecycle_events (project_id, event_id, case_run_id, commit_seq, kind)
        VALUES (?, ?, ?, ?, ?)
        """,
        (str(event.project_id), str(event.event_id), str(event.case_run_id), event.commit_seq, event.kind),
    )


def _insert_adjustment(connection: sqlite3.Connection, adjustment: object) -> None:
    from aiqa.contracts.reports import UsageAdjustment

    assert isinstance(adjustment, UsageAdjustment)
    connection.execute(
        """
        INSERT INTO usage_adjustments (
            project_id, adjustment_id, case_run_id, commit_seq, role, measurement_status, amount, currency
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(adjustment.project_id),
            str(adjustment.adjustment_id),
            str(adjustment.case_run_id),
            adjustment.commit_seq,
            adjustment.role,
            adjustment.measurement_status,
            adjustment.amount,
            adjustment.currency,
        ),
    )


def _insert_fingerprint(connection: sqlite3.Connection, observation: object) -> None:
    from aiqa.contracts.reports import FingerprintObservation

    assert isinstance(observation, FingerprintObservation)
    connection.execute(
        """
        INSERT INTO fingerprint_observations (
            project_id, observation_id, case_run_id, case_id, commit_seq, verification_digest,
            target_kind, env_profile_revision, data_fingerprint, oracle_policy, schema_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(observation.project_id),
            str(observation.observation_id),
            str(observation.case_run_id),
            str(observation.case_id),
            observation.commit_seq,
            observation.verification_digest,
            observation.target_kind,
            observation.env_profile_revision,
            observation.data_fingerprint,
            observation.oracle_policy,
            observation.schema_version,
        ),
    )


def _text(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _insert_review(connection: sqlite3.Connection, review: object) -> None:
    from aiqa.contracts.reviews import ReviewSnapshot

    assert isinstance(review, ReviewSnapshot)
    connection.execute(
        """
        INSERT INTO reviews (
            project_id, review_id, case_id, case_version_id, version_hash, source_manifest_id,
            trial_case_run_id, evidence_set_hash, expected_current_approval_id, created_commit_seq
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(review.project_id),
            str(review.review_id),
            str(review.case_id),
            str(review.case_version_id),
            review.version_hash,
            _text(review.source_manifest_id),
            _text(review.trial_case_run_id),
            review.evidence_set_hash,
            _text(review.expected_current_approval_id),
            review.created_commit_seq,
        ),
    )


def _insert_artifact(connection: sqlite3.Connection, artifact: object) -> None:
    from aiqa.contracts.reviews import ArtifactRef

    assert isinstance(artifact, ArtifactRef)
    connection.execute(
        """
        INSERT INTO artifact_refs (
            project_id, artifact_id, attempt_id, action_id, check_id, recording_id, review_id,
            build_id, export_id, package_id, healing_id, proposal_id, resource_observation_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(artifact.project_id),
            str(artifact.artifact_id),
            _text(artifact.attempt_id),
            _text(artifact.action_id),
            artifact.check_id,
            _text(artifact.recording_id),
            _text(artifact.review_id),
            _text(artifact.build_id),
            _text(artifact.export_id),
            _text(artifact.package_id),
            _text(artifact.healing_id),
            _text(artifact.proposal_id),
            _text(artifact.resource_observation_id),
        ),
    )


def _insert_evidence(connection: sqlite3.Connection, entry: object) -> None:
    from aiqa.contracts.reviews import ReviewEvidenceEntry

    assert isinstance(entry, ReviewEvidenceEntry)
    connection.execute(
        """
        INSERT INTO review_evidence_entries (
            project_id, review_id, entry_id, owner_kind, owner_id, attempt_id, action_id,
            artifact_ref_id, role, expected_hash, evidence_digest
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(entry.project_id),
            str(entry.review_id),
            str(entry.entry_id),
            entry.owner_kind,
            str(entry.owner_id),
            str(entry.attempt_id),
            str(entry.action_id),
            str(entry.artifact_ref_id),
            entry.role,
            entry.expected_hash,
            entry.evidence_digest,
        ),
    )


def _insert_approval(connection: sqlite3.Connection, event: object) -> None:
    from aiqa.contracts.reviews import ApprovalEvent

    assert isinstance(event, ApprovalEvent)
    connection.execute(
        """
        INSERT INTO approval_events (
            project_id, approval_id, case_id, case_version_id, review_id, event_kind,
            prior_approval_id, version_hash, evidence_set_hash, reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(event.project_id),
            str(event.approval_id),
            str(event.case_id),
            str(event.case_version_id),
            str(event.review_id),
            event.event_kind,
            _text(event.prior_approval_id),
            event.version_hash,
            event.evidence_set_hash,
            event.reason,
        ),
    )


def _insert_protection(connection: sqlite3.Connection, protection: object) -> None:
    from aiqa.contracts.reviews import ArtifactProtection

    assert isinstance(protection, ArtifactProtection)
    connection.execute(
        """
        INSERT INTO artifact_protections (
            project_id, protection_id, artifact_id, kind, backup_receipt_id, build_id, manual_request_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(protection.project_id),
            str(protection.protection_id),
            str(protection.artifact_id),
            protection.kind,
            _text(protection.backup_receipt_id),
            _text(protection.build_id),
            _text(protection.manual_request_id),
        ),
    )


def _denied(connection: sqlite3.Connection, sql: str, params: tuple[object, ...]) -> bool:
    try:
        connection.execute(sql, params)
    except sqlite3.IntegrityError:
        return True
    return False


def _insert_produced_fixture(connection, template_id, version_id, manifest_id, package_id=None):
    """Create a fresh immutable produced snapshot, never mutate an input version."""
    import json
    from aiqa.domain.hashing import execution_snapshot_hash

    columns = [row[1] for row in connection.execute("PRAGMA table_info(case_versions)")]
    row = dict(zip(columns, connection.execute("SELECT * FROM case_versions WHERE version_id=?", (str(template_id),)).fetchone()))
    row.update(version_id=str(version_id), revision=100, creation_kind="recorded", source_manifest_id=str(manifest_id), replay_package_id=None if package_id is None else str(package_id))
    source_hash = connection.execute("SELECT body_hash FROM recording_manifests WHERE manifest_id=?", (str(manifest_id),)).fetchone()[0]
    row["content_hash"] = execution_snapshot_hash(json.loads(row["definition_json"]),json.loads(row["settings_json"]),json.loads(row["recorded_steps_json"]),source_manifest_hash=source_hash,replay_package_hash=None if package_id is None else "sha256:" + ("cd" * 32))
    connection.execute(f"INSERT INTO case_versions ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})", tuple(row.values()))
