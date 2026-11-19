"""Stored source is reviewed and approved, then the same package replays with no actor AI."""
import json
from uuid import UUID, uuid4
from aiqa.domain.approvals import ApprovalInput, approve_case, bind_approval_store
from aiqa.recording.check_bindings import save_check_bindings
from aiqa.recording.review_manifest import request_review, review_action
from test_rx87_check_bindings import recorded, ux_app
from test_rx_34 import _geometry, _observation, _replay
from unit.test_recording_check_bindings import PAYLOAD


def _artifact(c, project, owner_kind, owner, attempt, action, role, job):
    artifact = str(uuid4())
    digest = "sha256:" + "ab" * 32
    c.execute(
        """INSERT INTO artifact_refs(project_id,artifact_id,attempt_id,action_id) VALUES(?,?,?,?)""",
        (str(project), artifact, attempt, action),
    )
    c.execute(
        """INSERT INTO artifact_objects(project_id,artifact_id,object_key,content_hash,byte_length,media_type,owner_id,status,acked,custody,stored_at,owner_kind,attempt_id,action_id,role,job_id,generation)
           VALUES(?,?,?,?,4,'image/png',?,'ready',1,'stored','2026-11-19T00:00:00+00:00',?,?,?,?,?,1)""",
        (str(project), artifact, artifact, digest, owner, owner_kind, attempt, action, role, job),
    )
    return artifact, digest


def _action(c, project, attempt, case, version, seq):
    action = str(uuid4())
    c.execute(
        """INSERT INTO actions(project_id,attempt_id,action_seq,step_id,action_id,proposal_hash,dispatch_state,case_id,case_version_id,outcome_known)
           VALUES(?,?,?,?,?,'hash','observed',?,?,1)""",
        (str(project), attempt, seq, "s"+str(seq), action, case, version),
    )
    return action


def test_saved_source_is_approved_then_the_same_package_replays_without_actor_ai(recorded, tmp_path):
    r = recorded
    with r["store"].transaction() as c:
        saved = save_check_bindings(c, r["actor"], r["project"], r["recording"], expected_manifest_id=r["manifest"], expected_manifest_hash=r["hash"], bindings=PAYLOAD, request_key="ma05b2")
        version = saved["case_version_id"]
        package_id = saved["replay_package_id"]
        package_hash = c.execute("SELECT body_hash FROM replay_packages WHERE package_id=?", (package_id,)).fetchone()[0]
        content_hash = c.execute("SELECT content_hash FROM case_versions WHERE version_id=?", (version,)).fetchone()[0]
        recording_job, recording_attempt = c.execute("SELECT job_id, attempt_id FROM attempts WHERE job_id=(SELECT job_id FROM jobs WHERE recording_id=? AND purpose='recording')", (str(r["recording"]),)).fetchone()
        execution, run, job, attempt = (str(uuid4()) for _ in range(4))
        c.execute("INSERT INTO executions(project_id,execution_id,name,purpose,source,scope_requested_at) VALUES(?,?,'review','trial','single','2026-11-19T00:00:00+00:00')", (str(r["project"]), execution))
        c.execute("INSERT INTO case_runs(project_id,execution_id,case_run_id,case_id,case_version_id,purpose,requested_at) VALUES(?,?,?,?,?,'trial','2026-11-19T00:00:00+00:00')", (str(r["project"]), execution, run, r["case"], version))
        limits = json.dumps({"self_healing_enabled": False, "actor": 0, "replay_package_id": package_id, "replay_package_hash": package_hash})
        c.execute("INSERT INTO jobs(project_id,job_id,purpose,case_run_id,payload_hash,source_refs,limits,status) VALUES(?,?,'trial',?,'hash','[]',?,'completed')", (str(r["project"]), job, run, limits))
        c.execute("INSERT INTO attempts(project_id,attempt_id,job_id,generation) VALUES(?,?,?,1)", (str(r["project"]), attempt, job))
        source_action = _action(c, r["project"], recording_attempt, r["case"], r["input_version"], 1)
        trial_action = _action(c, r["project"], attempt, r["case"], version, 1)
        source_artifact, source_digest = _artifact(c, r["project"], "REC", str(r["recording"]), recording_attempt, source_action, "after", recording_job)
        trial_artifact, trial_digest = _artifact(c, r["project"], "ITEM", run, attempt, trial_action, "after", job)
        snapshot = request_review(c, r["project"], UUID(version), {"trial_case_run_id": run, "entries": [
            {"owner_kind": "REC", "owner_id": str(r["recording"]), "attempt_id": recording_attempt, "action_id": source_action, "artifact_id": source_artifact, "role": "after", "expected_hash": source_digest},
            {"owner_kind": "ITEM", "owner_id": run, "attempt_id": attempt, "action_id": trial_action, "artifact_id": trial_artifact, "role": "after", "expected_hash": trial_digest},
        ]})
        for entry_id, in c.execute("SELECT entry_id FROM review_evidence_entries WHERE review_id=?", (str(snapshot.review_id),)):
            review_action(c, r["project"], UUID(version), r["actor"].actor_id, {"review_id": str(snapshot.review_id), "entry_key": entry_id, "evidence_digest": snapshot.evidence_set_hash, "state": "reviewed", "comment": "확인"})
        before = c.execute("SELECT body_hash FROM replay_packages WHERE package_id=?", (package_id,)).fetchone()[0]
    with bind_approval_store(r["store"]):
        receipt = approve_case(r["actor"], ApprovalInput(snapshot.review_id, UUID(version), content_hash, snapshot.evidence_set_hash, None, "저장본을 승인합니다."))
    with r["store"].transaction() as c:
        pointer = c.execute("SELECT current_approval_id FROM automation_cases WHERE case_id=?", (r["case"],)).fetchone()[0]
        after = c.execute("SELECT body_hash FROM replay_packages WHERE package_id=?", (package_id,)).fetchone()[0]
        event = c.execute("SELECT event_kind, case_version_id FROM approval_events WHERE approval_id=?", (str(receipt.approval_id),)).fetchone()
    assert pointer == str(receipt.approval_id) and event == ("approved", version) and after == before == package_hash
    from aiqa.replay.packages import resolve_claim_package_pin
    with r["store"].transaction() as c:
        pin = resolve_claim_package_pin(c, str(r["project"]), package_id=package_id, package_hash=package_hash, purpose="trial")
    handler, calls = _replay(tmp_path, digest=package_hash)
    frame = _observation(geometry=_geometry(physical=(1000, 2000), model=(500, 1000)))
    handler.context.step_observations = tuple((frame, frame) for _ in range(5))
    handler.context.healing_enabled = False
    job = {"project_id": str(r["project"]), "job_id": str(uuid4()), "attempt_id": str(uuid4()), "generation": 1, "snapshot": {"purpose": "trial", "serial": handler.context.expected_serial, "approved_plan": pin.approved_plan, "replay_package_id": package_id, "replay_package_hash": package_hash, "self_healing_enabled": False, "native_source": pin.native_source}}
    result = handler.handle(job)
    assert result.actions == len(calls) == 5 and handler.stopped_reason == ""
    assert handler.authoring_calls_seen == handler.healer_calls == handler.verifier_calls == 0
    assert handler.package_digest_after == package_hash
