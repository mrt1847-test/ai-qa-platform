"""Adversarial regressions for the November contract review; temporary stores only."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from uuid import uuid4

import pytest

from aiqa.api.app import create_app
from aiqa.config import load_settings
from aiqa.contracts.cases import CaseDefinition, CaseRevisionInput, CaseSettings, PathPolicy, StepSpec
from aiqa.domain.projects import bind_store, create_project
from aiqa.domain.proposals import accept_case_proposal, bind_proposal_store, create_case_proposal
from aiqa.domain.versions import StaleHead, StepEditCommand, apply_step_edit, bind_case_store, create_case, save_case_revision
from aiqa.store.database import migrate_store
from aiqa.store.models import Actor, CaseProposalInput, ProjectCreate


@pytest.fixture
def context(tmp_path):
    app = create_app(load_settings({"AIQA_RUNTIME_ROOT": str(tmp_path / "runtime")}))
    store = app.state.open_store()
    migrate_store(store)
    owner = Actor(uuid4(), None, True)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("Review", "review", "", "web"))
    actor = replace(owner, project_scope=project.project_id)
    with bind_case_store(store):
        case = create_case(actor, "Review", None)
        revision = CaseRevisionInput(
            CaseDefinition("open", "open", (), {}, {}, (StepSpec("s1", "open", ()),), (), PathPolicy((), ())),
            CaseSettings(target_kind="android", document={"android_package": "com.example", "limits": {"timeout_seconds": 31}, "healing_policy": {"allowed": False}}),
            recorded_steps=({"action": "tap", "step_id": "s1"},),
        )
        version = save_case_revision(actor, case.case_id, revision, None)
        yield store, actor, case, revision, version
    store.close()


def test_snapshot_hash_covers_settings_and_recorded_steps(context):
    store, actor, case, revision, version = context
    settings = save_case_revision(actor, case.case_id, replace(revision, settings=CaseSettings(target_kind="web")), version.id)
    steps = save_case_revision(actor, case.case_id, replace(revision, recorded_steps=({"action": "type", "text": "public"},)), settings.id)
    assert len({version.content_hash, settings.content_hash, steps.content_hash}) == 3
    assert version.verification_digest == settings.verification_digest == steps.verification_digest
    identical = save_case_revision(actor, case.case_id, replace(revision, reason="new reason"), steps.id)
    assert identical.content_hash == version.content_hash
    projection_hash = store._connection.execute("SELECT content_hash FROM definition_documents WHERE version_id=?", (str(version.id),)).fetchone()[0]
    assert projection_hash != version.content_hash


def test_step_edit_preserves_full_unedited_snapshot(context):
    store, actor, case, revision, version = context
    edited, _ = apply_step_edit(actor, case.case_id, StepEditCommand("add", instruction="continue", expected_head=version.id))
    rows = store._connection.execute("SELECT settings_json, recorded_steps_json FROM case_versions WHERE version_id IN (?,?) ORDER BY revision", (str(version.id), str(edited.id))).fetchall()
    assert rows[0] == rows[1]
    assert edited.replay_package_id is None


def _proposal(context):
    store, actor, case, revision, version = context
    job = str(uuid4())
    with store.transaction() as connection:
        connection.execute("INSERT INTO jobs(project_id,job_id,purpose,recording_id,case_run_id,payload_hash,source_refs,limits,status) VALUES (?,?, 'structure',NULL,NULL,'hash',?,'{}','queued')", (str(actor.project_scope), job, json.dumps([str(case.case_id)])))
    from uuid import UUID
    with bind_proposal_store(store):
        return create_case_proposal(actor, CaseProposalInput(case.case_id, version.id, version.content_hash, "structure", json.loads(store._connection.execute("SELECT definition_json FROM case_versions WHERE version_id=?", (str(version.id),)).fetchone()[0]), source_job_id=UUID(job), tc_version_id=None))


def test_proposal_rejects_stale_base_even_with_current_head(context):
    store, actor, case, revision, version = context
    proposal = _proposal(context)
    current = save_case_revision(actor, case.case_id, replace(revision, definition=replace(revision.definition, objective="newer")), version.id)
    with bind_proposal_store(store), pytest.raises(StaleHead):
        accept_case_proposal(actor, proposal.proposal_id, current.id)
    assert store._connection.execute("SELECT COUNT(*) FROM case_proposal_decisions").fetchone()[0] == 0


def test_proposal_uses_same_full_snapshot_hash_and_preserves_steps(context):
    store, actor, case, revision, version = context
    proposal = _proposal(context)
    with bind_proposal_store(store):
        accepted = accept_case_proposal(actor, proposal.proposal_id, version.id)
        repeated = accept_case_proposal(actor, proposal.proposal_id, version.id)
    assert accepted == repeated
    assert accepted.content_hash == version.content_hash
    assert json.loads(store._connection.execute("SELECT recorded_steps_json FROM case_versions WHERE version_id=?", (str(accepted.id),)).fetchone()[0]) == list(revision.recorded_steps)


def _manifest(context, body_hash='manifest-hash'):
    store, actor, case, revision, version = context
    connection = store._connection
    recording, manifest = str(uuid4()), str(uuid4())
    connection.execute("INSERT INTO recordings VALUES (?,?,?,'recorded',?,NULL,NULL,NULL,'stored','stopped','completed','complete')", (str(actor.project_scope), str(case.case_id), recording, str(version.id)))
    connection.execute("INSERT INTO recording_manifests VALUES (?,?,?,?,1,'original',NULL,?,'[]','[]','complete','finish',?)", (str(actor.project_scope), str(case.case_id), recording, manifest, version.content_hash, body_hash))
    return manifest


def _produced(context, manifest, package=None, case_id=None, version_id=None):
    store, actor, case, revision, version = context
    connection = store._connection
    row = dict(zip([r[1] for r in connection.execute("PRAGMA table_info(case_versions)")], connection.execute("SELECT * FROM case_versions WHERE version_id=?", (str(version.id),)).fetchone()))
    row.update(version_id=str(version_id or uuid4()), revision=100, source_manifest_id=manifest, replay_package_id=package, creation_kind="recorded", case_id=str(case_id or case.case_id))
    from aiqa.domain.hashing import execution_snapshot_hash
    source_hash = connection.execute("SELECT body_hash FROM recording_manifests WHERE manifest_id=?", (manifest,)).fetchone()[0]
    row["content_hash"] = execution_snapshot_hash(
        json.loads(row["definition_json"]), json.loads(row["settings_json"]), json.loads(row["recorded_steps_json"]),
        source_manifest_hash=source_hash, replay_package_hash=None if package is None else "package-hash",
    )
    connection.execute(f"INSERT INTO case_versions ({','.join(row)}) VALUES ({','.join('?' for _ in row)})", tuple(row.values()))
    return row["version_id"]


def _package(context, manifest, version, package, ready=1):
    store, actor, case, _, _ = context
    store._connection.execute("INSERT INTO replay_packages VALUES (?,?,?,?,?,'1',?,'manifest-hash','raw','approved','runtime','compiler','lock','mapping','package-hash')", (str(actor.project_scope), package, str(case.case_id), version, ready, manifest))


def _link(context, version, package):
    store, actor, case, _, _ = context
    store._connection.execute("INSERT INTO package_version_links(project_id,case_id,version_id,package_id) VALUES (?,?,?,?)", (str(actor.project_scope), str(case.case_id), version, package))


@pytest.mark.parametrize("order", ["version_first", "package_first", "link_first"])
def test_exact_package_pair_allows_atomic_construction(context, order):
    manifest = _manifest(context)
    store, actor, case, revision, version = context
    package = str(uuid4())
    connection = store._connection
    connection.execute("BEGIN")
    if order != "version_first":
        connection.execute("PRAGMA defer_foreign_keys=ON")
    if order == "version_first":
        produced = _produced(context, manifest, package)
        _package(context, manifest, produced, package)
        _link(context, produced, package)
    else:
        # Create the version last to prove constraints are truly deferred.
        produced = str(uuid4())
        if order == "link_first":
            _link(context, produced, package)
        _package(context, manifest, produced, package)
        if order == "package_first":
            _link(context, produced, package)
        # Explicit ID injection only in the row fixture.
        row = dict(zip([r[1] for r in connection.execute("PRAGMA table_info(case_versions)")], connection.execute("SELECT * FROM case_versions WHERE version_id=?", (str(version.id),)).fetchone()))
        row.update(version_id=produced, revision=100, source_manifest_id=manifest, replay_package_id=package, creation_kind="recorded")
        connection.execute(f"INSERT INTO case_versions ({','.join(row)}) VALUES ({','.join('?' for _ in row)})", tuple(row.values()))
    connection.execute("COMMIT")
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.mark.parametrize("violation", ["wrong_link", "null_pointer", "not_ready", "missing_package", "missing_link"])
def test_invalid_package_pair_rejected_at_transaction_end(context, violation):
    manifest = _manifest(context)
    store, actor, case, revision, version = context
    connection = store._connection
    package = str(uuid4())
    connection.execute("BEGIN")
    with pytest.raises(sqlite3.IntegrityError):
        produced = _produced(context, manifest, None if violation == "null_pointer" else package)
        if violation != "missing_package":
            _package(context, manifest, produced, package, 0 if violation == "not_ready" else 1)
        if violation != "missing_link":
            _link(context, str(version.id) if violation == "wrong_link" else produced, package)
        connection.execute("COMMIT")
    if connection.in_transaction:
        connection.execute("ROLLBACK")


@pytest.mark.parametrize("violation", ["missing_version", "foreign_case", "wrong_source"])
def test_receipt_requires_same_case_and_exact_version_source(context, violation):
    manifest = _manifest(context)
    store, actor, case, revision, version = context
    connection = store._connection
    connection.execute("BEGIN")
    produced = str(uuid4())
    if violation == "foreign_case":
        connection.execute("INSERT INTO automation_cases(project_id,case_id,name,next_revision,lock_version) VALUES (?,?, 'Other',1,0)", (str(actor.project_scope), "other"))
        produced = _produced(context, manifest, case_id="other")
    if violation == "wrong_source":
        produced = str(version.id)
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute("INSERT INTO materialization_receipts(project_id,receipt_id,manifest_id,produced_version_id,body_hash) VALUES (?,?,?,?,?)", (str(actor.project_scope), str(uuid4()), manifest, produced, "manifest-hash"))
        connection.execute("COMMIT")
    if connection.in_transaction:
        connection.execute("ROLLBACK")


def test_receipt_can_precede_produced_version_in_atomic_transaction(context):
    manifest = _manifest(context)
    store, actor, case, revision, version = context
    connection = store._connection
    connection.execute("BEGIN")
    produced = str(uuid4())
    connection.execute("INSERT INTO materialization_receipts(project_id,receipt_id,manifest_id,produced_version_id,body_hash) VALUES (?,?,?,?,?)", (str(actor.project_scope), str(uuid4()), manifest, produced, "manifest-hash"))
    _produced(context, manifest, version_id=produced)
    connection.execute("COMMIT")
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.mark.parametrize("table", ["item_finalizations", "item_lifecycle_events", "item_usage_facts", "usage_adjustments", "analysis_records", "fingerprint_observations"])
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE"])
def test_permanent_facts_reject_update_and_delete(context, table, operation):
    store, actor, case, revision, version = context
    connection = store._connection
    project = str(actor.project_scope)
    connection.execute("INSERT INTO executions VALUES (?, 'execution','Trial','trial','single',NULL,'now')", (project,))
    connection.execute("INSERT INTO case_runs VALUES (?, 'execution','run',?,?,'trial','now')", (project, str(case.case_id), str(version.id)))
    rows = {
        "item_finalizations": (project,"run",1,2,"release","hash","PASS",1),
        "item_lifecycle_events": (project,"event","run",1,"created"),
        "item_usage_facts": (project,"usage","run",1,"authoring","unknown",None,None),
        "usage_adjustments": (project,"adjustment","run",2,"authoring","measured","1.00","USD"),
        "analysis_records": (project,"analysis","run",3,"{}"),
        "fingerprint_observations": (project,"observation","run",str(case.case_id),4,"digest","web","env","data","oracle","1"),
    }
    values = rows[table]
    connection.execute(f"INSERT INTO {table} VALUES ({','.join('?' for _ in values)})", values)
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(f"DELETE FROM {table}" if operation == "DELETE" else f"UPDATE {table} SET project_id=project_id")
    assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 1


def test_execution_hash_includes_source_package_and_excludes_metadata_and_secret_values():
    from aiqa.domain.hashing import execution_snapshot_hash

    definition = {"objective": "open", "variables": {"amount": "1.10"}}
    settings = {"target_kind": "android", "secret_refs": {"login": {"ref_id": "ref", "revision": 1}}}
    digest = execution_snapshot_hash(definition, settings, [])
    decorated = {**definition, "name": "renamed", "tags": ["tag"], "tc_reference": "TC", "secret_plaintext": "first"}
    assert execution_snapshot_hash(decorated, settings, []) == digest
    decorated["secret_plaintext"] = "second"
    assert execution_snapshot_hash(decorated, settings, []) == digest
    assert execution_snapshot_hash(definition, settings, [], source_manifest_hash="source") != digest
    assert execution_snapshot_hash(definition, settings, [], replay_package_hash="package") != digest
    assert execution_snapshot_hash(definition, {**settings, "secret_refs": {"login": {"ref_id": "ref", "revision": 2}}}, []) != digest


def test_clone_recomputes_snapshot_hash_after_removing_source_and_package(context):
    from aiqa.domain.catalog import bind_catalog_store, clone_case
    from aiqa.domain.hashing import execution_snapshot_hash
    from aiqa.store.models import CloneCaseInput

    store, actor, case, revision, version = context
    manifest = _manifest(context)
    package = str(uuid4())
    with store.transaction() as connection:
        produced = _produced(context, manifest, package)
        _package(context, manifest, produced, package)
        _link(context, produced, package)
        connection.execute("UPDATE automation_cases SET latest_draft_version_id=? WHERE case_id=?", (produced, str(case.case_id)))
    with bind_catalog_store(store):
        clone = clone_case(CloneCaseInput(actor.project_scope, actor.actor_id, case.case_id, "Clone"))
    row = store._connection.execute("SELECT definition_json,settings_json,recorded_steps_json,content_hash,source_manifest_id,replay_package_id FROM case_versions WHERE version_id=?", (str(clone.latest_draft_version_id),)).fetchone()
    assert row[3] == execution_snapshot_hash(*(json.loads(value) for value in row[:3]))
    source_hash = store._connection.execute("SELECT content_hash FROM case_versions WHERE version_id=?", (produced,)).fetchone()[0]
    assert row[3] != source_hash
    assert row[4:] == (None, None)
    assert clone.current_approval_id is None
    assert json.loads(row[2]) == list(revision.recorded_steps)


def test_usage_correction_appends_without_rewriting_original(context):
    store, actor, case, revision, version = context
    connection = store._connection
    project = str(actor.project_scope)
    connection.execute("INSERT INTO executions VALUES (?, 'execution','Trial','trial','single',NULL,'now')", (project,))
    connection.execute("INSERT INTO case_runs VALUES (?, 'execution','run',?,?,'trial','now')", (project, str(case.case_id), str(version.id)))
    connection.execute("INSERT INTO item_usage_facts VALUES (?,'original','run',1,'authoring','measured','2.00','USD')", (project,))
    connection.execute("INSERT INTO usage_adjustments VALUES (?,'correction','run',2,'authoring','measured','-0.50','USD')", (project,))
    assert connection.execute("SELECT amount FROM item_usage_facts").fetchone()[0] == "2.00"
    assert connection.execute("SELECT amount FROM usage_adjustments").fetchone()[0] == "-0.50"


def test_execution_keys_named_like_metadata_remain_in_snapshot_hash():
    from aiqa.domain.hashing import execution_snapshot_hash
    for key in ('name', 'tags', 'secret', 'availability'):
        a = execution_snapshot_hash({'variables': {key: 'Alice'}}, {}, [])
        b = execution_snapshot_hash({'variables': {key: 'Bob'}}, {}, [])
        assert a != b
    assert execution_snapshot_hash({'secret_refs': {'name': {'ref_id': 'a', 'revision': 1}}}, {}, []) != execution_snapshot_hash({'secret_refs': {'name': {'ref_id': 'b', 'revision': 2}}}, {}, [])
    assert execution_snapshot_hash({}, {}, [{'target': {'name': 'Save'}}]) != execution_snapshot_hash({}, {}, [{'target': {'name': 'Delete'}}])


def test_insert_or_replace_cannot_rewrite_permanent_usage(context):
    store, actor, case, _, version = context
    c = store._connection
    project = str(actor.project_scope)
    c.execute("INSERT INTO executions VALUES (?, 'execution','Trial','trial','single',NULL,'now')", (project,))
    c.execute("INSERT INTO case_runs VALUES (?, 'execution','run',?,?,'trial','now')", (project, str(case.case_id), str(version.id)))
    c.execute("INSERT INTO item_usage_facts VALUES (?,'original','run',1,'authoring','measured','2.00','USD')", (project,))
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("INSERT OR REPLACE INTO item_usage_facts VALUES (?,'original','run',1,'authoring','measured','999.00','USD')", (project,))
    assert c.execute('SELECT amount FROM item_usage_facts').fetchone()[0] == '2.00'


@pytest.mark.parametrize('mismatch', ['source_id', 'source_hash'])
def test_package_source_must_match_produced_version_and_manifest_hash(context, mismatch):
    c = context[0]._connection
    first = _manifest(context)
    other = _manifest(context, 'other-manifest-hash')
    package = str(uuid4())
    c.execute('BEGIN')
    produced = _produced(context, first, package)
    _package(context, other if mismatch == 'source_id' else first, produced, package)
    if mismatch == 'source_hash':
        # The package body is a newly constructed unapproved fixture, not a
        # mutation of a previously committed immutable package.
        c.execute("UPDATE replay_packages SET source_manifest_hash='wrong-source-hash' WHERE package_id=?", (package,))
    _link(context, produced, package)
    with pytest.raises(sqlite3.IntegrityError):
        c.execute('COMMIT')
    c.execute('ROLLBACK')


def test_clone_has_readable_editable_definition_projection(context):
    from aiqa.domain.catalog import bind_catalog_store, clone_case
    from aiqa.domain.versions import latest_draft
    from aiqa.store.models import CloneCaseInput
    store, actor, case, _, version = context
    with bind_catalog_store(store):
        clone = clone_case(CloneCaseInput(actor.project_scope, actor.actor_id, case.case_id, 'Copy'))
    assert store._connection.execute('SELECT COUNT(*) FROM definition_documents WHERE version_id=?', (str(clone.latest_draft_version_id),)).fetchone()[0] == 1
    assert latest_draft(actor, clone.case_id) is not None
    view, _ = apply_step_edit(actor, clone.case_id, StepEditCommand('add', instruction='next', expected_head=clone.latest_draft_version_id))
    assert view.parent_version_id == clone.latest_draft_version_id


def test_accepted_proposal_preserves_secret_refs_and_step_coordinates(context):
    from aiqa.store.models import SecretRef
    store, actor, case, revision, first = context
    definition = replace(revision.definition, secret_refs={'login': SecretRef(actor.project_scope, uuid4(), 1)}, steps=(StepSpec('s1', 'open', (), (12, 34)),))
    current_revision = replace(revision, definition=definition)
    current = save_case_revision(actor, case.case_id, current_revision, first.id)
    proposal = _proposal((store, actor, case, current_revision, current))
    with bind_proposal_store(store):
        accepted = accept_case_proposal(actor, proposal.proposal_id, current.id)
    saved = json.loads(store._connection.execute('SELECT definition_json FROM case_versions WHERE version_id=?', (str(accepted.id),)).fetchone()[0])
    assert saved['secret_refs']['login']['ref_id'] == str(definition.secret_refs['login'].ref_id)
    assert saved['steps'][0]['point'] == [12, 34]


def test_recorded_steps_reject_explicit_plaintext_secrets_before_persistence(context):
    store, actor, case, revision, version = context
    before = store._connection.execute('SELECT COUNT(*) FROM case_versions').fetchone()[0]
    with pytest.raises(ValueError):
        save_case_revision(actor, case.case_id, replace(revision, recorded_steps=({'action': 'type', 'secret_plaintext': 'synthetic-secret'},)), version.id)
    assert store._connection.execute('SELECT COUNT(*) FROM case_versions').fetchone()[0] == before


def test_recorded_artifact_availability_is_not_execution_identity():
    from aiqa.domain.hashing import execution_snapshot_hash
    ready = [{'action': 'tap', 'artifact': {'id': 'artifact', 'availability': 'ready'}}]
    expired = [{'action': 'tap', 'artifact': {'id': 'artifact', 'availability': 'expired'}}]
    assert execution_snapshot_hash({}, {}, ready) == execution_snapshot_hash({}, {}, expired)
    assert execution_snapshot_hash({}, {}, [{'selector': {'availability': 'visible'}}]) != execution_snapshot_hash({}, {}, [{'selector': {'availability': 'hidden'}}])
