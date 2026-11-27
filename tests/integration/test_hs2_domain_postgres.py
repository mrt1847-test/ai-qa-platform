"""Recorded evidence, deferred package pairing, and review on real PostgreSQL.

The shared fixture creates and removes only a unique aiqa_test_* schema on an
explicit loopback server. Existing W18 graph SQL is reused against the actual
PostgreSQL adapter; SQLite is never opened by this module.
"""

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from tests.integration.test_hs2_postgres import pg_store


@pytest.fixture
def recorded_graph(pg_store, monkeypatch):
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.store.models import Actor, ProjectCreate
    from tests.acceptance import test_w18

    owner = Actor(uuid4(), None, True)
    with bind_store(pg_store):
        project = create_project(owner, ProjectCreate("Postgres evidence", "pg-domain", "fixture", "web"))

    class GraphConnection:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, sql, params=()):
            if sql.strip().upper() == "PRAGMA FOREIGN_KEYS=ON":
                return None  # PostgreSQL always enforces the actual constraints.
            return self.connection.execute(sql, params)

        def commit(self):
            # W18 calls commit explicitly; the enclosing real Store owns it.
            pass

    @contextmanager
    def connect(_):
        with pg_store.transaction() as connection:
            yield GraphConnection(connection)

    # Replace only this acceptance module's binding, never sqlite3.connect.
    with monkeypatch.context() as local:
        local.setattr(test_w18, "sqlite3", SimpleNamespace(connect=connect))
        graph = test_w18._graph(Path("unused-synthetic-fixture"), str(project.project_id), str(owner.actor_id))
    return pg_store, project.project_id, Actor(owner.actor_id, project.project_id, True), graph


def _payload(graph):
    return {
        "trial_case_run_id": graph["trial"],
        "entries": [
            dict(owner_kind="REC", owner_id=graph["recording"], attempt_id=graph["rec_attempt"],
                 action_id="A001", artifact_id=graph["rec_artifact"], role="before", expected_hash="hash-rec"),
            dict(owner_kind="ITEM", owner_id=graph["trial"], attempt_id=graph["item_attempt"],
                 action_id="A001", artifact_id=graph["item_artifact"], role="before", expected_hash="hash-item"),
        ],
    }


def test_recorded_version_package_and_source_claims_commit_together(recorded_graph):
    store, project_id, _, graph = recorded_graph
    connection = store._connection
    # W18 inserts the version before its referenced source/package/link exist.
    # All source and pair claims must nevertheless resolve at real PG COMMIT.
    for table in ("review_package_pair_claims", "review_package_source_claims", "review_version_source_claims"):
        assert connection.execute(f"SELECT COUNT(*) FROM {table} WHERE project_id=?", (str(project_id),)).fetchone()[0] == 1
    row = connection.execute(
        "SELECT v.version_id,p.package_id,m.manifest_id FROM case_versions v "
        "JOIN replay_packages p ON p.project_id=v.project_id AND p.package_id=v.replay_package_id "
        "JOIN recording_manifests m ON m.project_id=v.project_id AND m.manifest_id=v.source_manifest_id "
        "WHERE v.project_id=?", (str(project_id),),
    ).fetchone()
    assert tuple(row) == (graph["version"], graph["package"], graph["manifest"])


def test_missing_package_link_fails_at_commit_and_restores_pair(recorded_graph):
    store, project_id, _, _ = recorded_graph
    reached_commit = False
    with pytest.raises(sqlite3.IntegrityError):
        with store.transaction() as connection:
            connection.execute("DELETE FROM package_version_links WHERE project_id=?", (str(project_id),))
            assert connection.execute("SELECT COUNT(*) FROM package_version_links").fetchone()[0] == 0
            reached_commit = True
    assert reached_commit, "the foreign key must remain deferred until COMMIT"
    assert not store.in_transaction()
    assert store._connection.execute("SELECT COUNT(*) FROM package_version_links").fetchone()[0] == 1
    assert store._connection.execute("SELECT COUNT(*) FROM review_package_pair_claims").fetchone()[0] == 1


def test_version_with_missing_package_fails_deferred_commit(recorded_graph):
    store, project_id, _, graph = recorded_graph
    missing_version, missing_package = str(uuid4()), str(uuid4())
    reached_commit = False
    with pytest.raises(sqlite3.IntegrityError):
        with store.transaction() as connection:
            connection.execute(
                """INSERT INTO case_versions (
                project_id,case_id,version_id,revision,creation_kind,parent_version_id,base_version_id,
                is_branch,definition_json,settings_json,recorded_steps_json,content_hash,verification_digest,
                source_manifest_id,replay_package_id,readiness_json,actor_id,reason,created_at)
                SELECT project_id,case_id,?,2,creation_kind,parent_version_id,base_version_id,
                is_branch,definition_json,settings_json,recorded_steps_json,content_hash,verification_digest,
                source_manifest_id,?,readiness_json,actor_id,reason,created_at
                FROM case_versions WHERE project_id=? AND version_id=?""",
                (missing_version, missing_package, str(project_id), graph["version"]),
            )
            assert connection.execute("SELECT COUNT(*) FROM review_package_pair_claims").fetchone()[0] == 2
            reached_commit = True
    assert reached_commit
    assert store._connection.execute("SELECT COUNT(*) FROM case_versions").fetchone()[0] == 1
    assert store._connection.execute("SELECT COUNT(*) FROM review_package_pair_claims").fetchone()[0] == 1


def test_source_evidence_and_permanent_facts_reject_mutation(recorded_graph):
    store, project_id, _, graph = recorded_graph
    with store.transaction() as connection:
        connection.execute(
            "INSERT INTO item_finalizations(project_id,case_run_id,created_seq,finalized_seq,release_label,content_hash,core_result,denominator) "
            "VALUES(?,?,1,2,'fixture','result-hash','INCONCLUSIVE',1)", (str(project_id), graph["trial"]),
        )
        forbidden = [
            ("UPDATE case_versions SET content_hash='changed'", ()),
            ("DELETE FROM case_versions", ()),
            ("UPDATE recording_manifests SET body_hash='changed'", ()),
            ("DELETE FROM recording_manifests", ()),
            ("UPDATE artifact_objects SET content_hash='changed'", ()),
            ("DELETE FROM artifact_objects", ()),
            ("UPDATE artifact_refs SET action_id=action_id", ()),
            ("DELETE FROM artifact_refs", ()),
            ("UPDATE recordings SET case_id=case_id", ()),  # UPDATE OF guards equal assignments too.
            ("UPDATE item_finalizations SET core_result='PASS'", ()),
            ("DELETE FROM item_finalizations", ()),
            ("UPDATE automation_cases SET current_approval_id=?", (str(uuid4()),)),
        ]
        for sql, params in forbidden:
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(sql, params)
            assert connection.execute("SELECT COUNT(*) FROM case_versions").fetchone()[0] == 1
        # The translated boolean-sum CHECK must still enforce exactly one owner.
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO artifact_refs(project_id,artifact_id,attempt_id,action_id,recording_id) VALUES(?,?,?,?,?)",
                (str(project_id), str(uuid4()), graph["rec_attempt"], "A001", graph["recording"]),
            )
    assert store._connection.execute("SELECT core_result FROM item_finalizations").fetchone()[0] == "INCONCLUSIVE"


def test_evidence_review_opinions_approval_and_pointer_are_atomic(recorded_graph):
    from aiqa.domain.approvals import ApprovalConflict, ApprovalInput, approve_case, bind_approval_store
    from aiqa.recording.review_manifest import ReviewRejected, request_review, review_action, review_board

    store, project_id, actor, graph = recorded_graph
    payload = _payload(graph)
    rejected = [
        {**payload, "trial_case_run_id": graph["healed"]},
        {**payload, "entries": [dict(payload["entries"][0], attempt_id=graph["item_attempt"], artifact_id=graph["item_artifact"], expected_hash="hash-item")]},
        {**payload, "entries": [dict(payload["entries"][1], owner_id=graph["foreign"], attempt_id=graph["foreign_attempt"], artifact_id=graph["foreign_artifact"], action_id="A002", expected_hash="hash-foreign")]},
    ]
    for invalid in rejected:
        with pytest.raises(ReviewRejected):
            with store.transaction() as connection:
                request_review(connection, project_id, UUID(graph["version"]), invalid)
    assert store._connection.execute("SELECT COUNT(*) FROM reviews").fetchone()[0] == 0

    with store.transaction() as connection:
        snapshot = request_review(connection, project_id, UUID(graph["version"]), payload)
        entries = connection.execute("SELECT entry_id,owner_kind FROM review_evidence_entries ORDER BY owner_kind").fetchall()
        for entry_id, owner_kind in entries:
            if owner_kind == "REC":
                review_action(connection, project_id, UUID(graph["version"]), actor.actor_id,
                              dict(review_id=str(snapshot.review_id), entry_key=entry_id, evidence_digest=snapshot.evidence_set_hash,
                                   state="needs_change", comment="Inspect the recording"))
            reviewed = review_action(connection, project_id, UUID(graph["version"]), actor.actor_id,
                                     dict(review_id=str(snapshot.review_id), entry_key=entry_id, evidence_digest=snapshot.evidence_set_hash,
                                          state="reviewed", comment="Exact evidence reviewed"))
            assert reviewed.latest_state == "reviewed"
            assert reviewed.history_count == (2 if owner_kind == "REC" else 1)
        board = review_board(connection, project_id, UUID(graph["case"]), UUID(graph["version"]))
        assert (board.source_reviewed, board.source_total, board.trial_reviewed, board.trial_total) == (1, 1, 1, 1)
        source_artifact = str(uuid4())
        connection.execute("INSERT INTO artifact_refs(project_id,artifact_id,recording_id) VALUES(?,?,?)",
                           (str(project_id), source_artifact, graph["recording"]))
        connection.execute(
            """INSERT INTO artifact_objects(project_id,artifact_id,object_key,content_hash,byte_length,media_type,
            owner_id,status,acked,owner_kind,attempt_id,action_id,check_id,role,job_id,generation)
            VALUES(?,?,?,'source-hash',4,'application/json',?,'ready',1,'REC',?,NULL,NULL,'source',?,1)""",
            (str(project_id), source_artifact, source_artifact, graph["recording"], graph["rec_attempt"], graph["rec_job"]),
        )
    approval = ApprovalInput(snapshot.review_id, UUID(graph["version"]), snapshot.version_hash,
                             snapshot.evidence_set_hash, None, "Reviewed exact source and trial")
    with bind_approval_store(store):
        receipt = approve_case(actor, approval)
        with pytest.raises(ApprovalConflict):
            approve_case(actor, approval)
    assert len(receipt.protection_ids) == 3
    connection = store._connection
    assert connection.execute("SELECT current_approval_id FROM automation_cases WHERE case_id=?", (graph["case"],)).fetchone()[0] == str(receipt.approval_id)
    assert connection.execute("SELECT COUNT(*) FROM approval_events").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM artifact_protections WHERE kind='review'").fetchone()[0] == 2
    assert connection.execute("SELECT COUNT(*) FROM artifact_protections WHERE kind='approval'").fetchone()[0] == 3
    assert connection.execute("SELECT COUNT(*) FROM project_audits WHERE action='approve'").fetchone()[0] == 1
    with store.transaction() as connection:
        for sql in ("UPDATE action_reviews SET comment='changed'", "DELETE FROM action_reviews"):
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(sql)
        other_case = str(uuid4())
        connection.execute(
            "INSERT INTO automation_cases(project_id,case_id,name,next_revision,lock_version) VALUES(?,?,'Other case',1,0)",
            (str(project_id), other_case),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE automation_cases SET current_approval_id=? WHERE case_id=?", (str(receipt.approval_id), other_case))
        assert connection.execute("SELECT COUNT(*) FROM action_reviews").fetchone()[0] == 3
