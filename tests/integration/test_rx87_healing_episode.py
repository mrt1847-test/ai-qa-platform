"""A later unsent locator failure can reserve one server-owned healing episode."""
import json
import sqlite3
from datetime import datetime, timezone
from uuid import UUID, uuid4

from aiqa.healing.claim_reservation import reserve_claimed_healing, reserve_claimed_healing_http
from aiqa.store.healing import HealingRejected
from aiqa.store.models import WorkerScope
from aiqa.store.queue import claim_with_receipt
from test_rx86_healing_execution import healing_execution, healing_metadata, ux_app
from test_rx94_healing_claim import admitted_healing


def _claimed(f):
    from aiqa.store.database import migrate_store
    store = f["app"].state.open_store()
    try:
        migrate_store(store)
    finally:
        store.close()
    with sqlite3.connect(f["database"]) as db:
        db.execute("PRAGMA foreign_keys=ON")
        token = db.execute("SELECT token_id FROM worker_tokens LIMIT 1").fetchone()[0]
        worker = WorkerScope("worker-w2002", (UUID(f["project"]),), ("regression",), token)
        lease = claim_with_receipt(db, worker, datetime.now(timezone.utc), request_key="episode-claim", project_id=f["project"])
        assert lease is not None
        run, case, version = db.execute(
            "SELECT case_run_id, case_id, case_version_id FROM case_runs WHERE case_run_id=(SELECT case_run_id FROM jobs WHERE job_id=?)",
            (str(lease.job_id),),
        ).fetchone()
        limits = json.loads(db.execute("SELECT limits FROM jobs WHERE job_id=?", (str(lease.job_id),)).fetchone()[0])
        approval = db.execute("SELECT current_approval_id FROM automation_cases WHERE project_id=?", (f["project"],)).fetchall()
        package = db.execute("SELECT body_hash FROM replay_packages WHERE package_id=?", (limits["replay_package_id"],)).fetchone()[0]
    return worker, lease, run, case, version, limits, approval, package


def _action(db, f, lease, case, version, seq, state, journal):
    action = str(uuid4())
    db.execute(
        """INSERT INTO actions(project_id,attempt_id,action_seq,step_id,action_id,proposal_hash,dispatch_state,case_id,case_version_id,outcome_known)
           VALUES(?,?,?,?,?,'hash',?,?,?,?)""",
        (f["project"], str(lease.attempt_id), seq, "s"+str(seq), action, state, case, version, 1 if state == "observed" else 0),
    )
    for index, name in enumerate(journal, 1):
        db.execute(
            """INSERT INTO dispatch_journal(project_id,attempt_id,action_seq,entry_seq,dispatch_state,recorded_at)
               VALUES(?,?,?,?,?,?)""",
            (f["project"], str(lease.attempt_id), seq, index, name, "2026-11-19T00:00:00+00:00"),
        )
    return action


def test_prior_dispatch_still_allows_one_unsent_episode(admitted_healing):
    f = admitted_healing
    worker, lease, run, case, version, limits, approval, package = _claimed(f)
    forged = str(uuid4())
    with sqlite3.connect(f["database"]) as db:
        db.execute("PRAGMA foreign_keys=ON")
        _action(db, f, lease, case, version, 1, "observed", ("planned", "dispatch_started", "acknowledged", "observed"))
        failed = _action(db, f, lease, case, version, 2, "lookup_failed", ("planned", "lookup_failed"))
        first = reserve_claimed_healing(db, worker, project_id=lease.project_id, job_id=lease.job_id, attempt_id=lease.attempt_id, action_id=UUID(failed), reason="target_not_found", request_key="locator", now=datetime.now(timezone.utc))
        again = reserve_claimed_healing(db, worker, project_id=lease.project_id, job_id=lease.job_id, attempt_id=lease.attempt_id, action_id=UUID(failed), reason="target_not_found", request_key="locator", now=datetime.now(timezone.utc))
        other = reserve_claimed_healing(db, worker, project_id=lease.project_id, job_id=lease.job_id, attempt_id=lease.attempt_id, action_id=UUID(failed), reason="layout_shift", request_key="other", now=datetime.now(timezone.utc))
        stored = db.execute("SELECT action_id, reserved_calls, reserved_seconds FROM healing_reservations").fetchone()
        episodes = db.execute("SELECT COUNT(*) FROM healing_episodes").fetchone()[0]
        assert db.execute("SELECT current_approval_id FROM automation_cases WHERE project_id=?", (f["project"],)).fetchall() == approval
        assert db.execute("SELECT body_hash FROM replay_packages WHERE package_id=?", (limits["replay_package_id"],)).fetchone()[0] == package
    store = f["app"].state.open_store()
    try:
        status, body = reserve_claimed_healing_http(store, worker, {"project_id": f["project"], "job_id": str(lease.job_id), "attempt_id": str(lease.attempt_id), "action_id": failed, "reason": "target_not_found", "request_key": "locator", "episode_id": forged, "allowed": True})
    finally:
        store.close()
    assert first.eligible is True and first.replayed is False
    assert 1 <= first.reserved_calls <= 2 and 1 <= first.reserved_seconds <= 30
    assert again.replayed is True and again.episode_id == first.episode_id
    assert other.episode_id == first.episode_id and episodes == 1
    assert stored == (failed, first.reserved_calls, first.reserved_seconds)
    assert status == 200 and body["episode_id"] == str(first.episode_id) and body["episode_id"] != forged and body["replayed"] is True


def test_sent_or_unknown_action_does_not_receive_an_episode(admitted_healing):
    f = admitted_healing
    worker, lease, run, case, version, limits, approval, package = _claimed(f)
    with sqlite3.connect(f["database"]) as db:
        db.execute("PRAGMA foreign_keys=ON")
        sent = _action(db, f, lease, case, version, 1, "dispatch_started", ("planned", "dispatch_started"))
        receipt = reserve_claimed_healing(db, worker, project_id=lease.project_id, job_id=lease.job_id, attempt_id=lease.attempt_id, action_id=UUID(sent), reason="target_not_found", request_key="sent", now=datetime.now(timezone.utc))
        assert receipt.eligible is False and receipt.episode_id is None
        assert db.execute("SELECT COUNT(*) FROM healing_episodes").fetchone()[0] == 0


def test_authoring_role_and_cancellation_do_not_grant_an_episode(admitted_healing):
    f = admitted_healing
    worker, lease, run, case, version, limits, approval, package = _claimed(f)
    with sqlite3.connect(f["database"]) as db:
        db.execute("PRAGMA foreign_keys=ON")
        failed = _action(db, f, lease, case, version, 1, "lookup_failed", ("lookup_failed",))
        limits["healing_binding"]["role"] = "authoring"
        db.execute("UPDATE jobs SET limits=? WHERE job_id=?", (json.dumps(limits), str(lease.job_id)))
        try:
            reserve_claimed_healing(db, worker, project_id=lease.project_id, job_id=lease.job_id, attempt_id=lease.attempt_id, action_id=UUID(failed), reason="target_not_found", request_key="author", now=datetime.now(timezone.utc))
            raised = False
        except HealingRejected:
            raised = True
        assert raised is True and db.execute("SELECT COUNT(*) FROM healing_episodes").fetchone()[0] == 0
        limits["healing_binding"]["role"] = "healing"
        db.execute("UPDATE jobs SET limits=? WHERE job_id=?", (json.dumps(limits), str(lease.job_id)))
        db.execute(
            """INSERT INTO job_cancellations(project_id,actor_id,request_key,job_id,expected_state,body_hash,status_after,requested_at,runner_stopped,cleanup_completed)
               VALUES(?,?,?,?, 'preparing','hash','cancelled','2026-11-19T00:00:00+00:00',0,0)""",
            (f["project"], str(uuid4()), "cancel", str(lease.job_id)),
        )
        try:
            reserve_claimed_healing(db, worker, project_id=lease.project_id, job_id=lease.job_id, attempt_id=lease.attempt_id, action_id=UUID(failed), reason="target_not_found", request_key="cancelled", now=datetime.now(timezone.utc))
            cancelled = False
        except HealingRejected:
            cancelled = True
        assert cancelled is True and db.execute("SELECT COUNT(*) FROM healing_episodes").fetchone()[0] == 0


def test_existing_violation_stays_failed_and_blocks_the_episode(admitted_healing):
    f = admitted_healing
    worker, lease, run, case, version, limits, approval, package = _claimed(f)
    with sqlite3.connect(f["database"]) as db:
        db.execute("PRAGMA foreign_keys=ON")
        failed = _action(db, f, lease, case, version, 1, "lookup_failed", ("lookup_failed",))
        db.execute(
            """INSERT INTO check_results(project_id,attempt_id,action_id,check_id,status,method,expected_snapshot,sanitized_observed,reason,artifact_refs,observed_at)
               VALUES(?,?,?,'c1','violated','deterministic','mouse','','text_mismatch','[]','2026-11-19T00:00:00+00:00')""",
            (f["project"], str(lease.attempt_id), failed),
        )
        try:
            reserve_claimed_healing(db, worker, project_id=lease.project_id, job_id=lease.job_id, attempt_id=lease.attempt_id, action_id=UUID(failed), reason="ambiguous", request_key="fail", now=datetime.now(timezone.utc))
            raised = False
        except HealingRejected:
            raised = True
        assert raised is True
        assert db.execute("SELECT status, expected_snapshot FROM check_results").fetchone() == ("violated", "mouse")
        assert db.execute("SELECT COUNT(*) FROM healing_episodes").fetchone()[0] == 0
        assert db.execute("SELECT current_approval_id FROM automation_cases WHERE project_id=?", (f["project"],)).fetchall() == approval
