"""Approval commits the event, pins, pointer, and audit together."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from uuid import uuid4

from aiqa.store.models import Actor


def test_w19_01(tmp_path: Path) -> None:
    import asyncio

    from aiqa.api.app import create_app
    from aiqa.config import load_settings
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.store.database import migrate_store
    from aiqa.store.models import ProjectCreate

    root = tmp_path / "runtime"
    app = create_app(load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}))
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("승인", "w1901", "approval", "web"))
    store.close()
    database = root / "db" / "aiqa.sqlite"
    project_id = str(project.project_id)
    actor_id = str(owner.actor_id)
    case_id = str(uuid4())
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO automation_cases (
                project_id, case_id, name, folder_id, tc_reference, next_revision,
                latest_draft_version_id, current_approval_id, lock_version, archived_at
            ) VALUES (?, ?, '승인', NULL, NULL, 4, NULL, NULL, 0, NULL)
            """,
            (project_id, case_id),
        )
        first = _bundle(connection, project_id, actor_id, case_id, 1, "first")
        second = _bundle(connection, project_id, actor_id, case_id, 2, "second")
        expired = _bundle(connection, project_id, actor_id, case_id, 3, "expired", expired=True)
        bare = _bundle(connection, project_id, actor_id, case_id, 4, "bare", script=False)
        connection.commit()
    winner, loser, replay, mismatch, denied, moved = asyncio.run(
        _calls(app, project_id, first, second, expired, bare)
    )
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        pointer = connection.execute(
            "SELECT current_approval_id FROM automation_cases WHERE case_id = ?",
            (case_id,),
        ).fetchone()
        revoked = connection.execute(
            "SELECT COUNT(*) FROM approval_events WHERE event_kind = 'revoked'"
        ).fetchone()[0]
        first_kind = connection.execute(
            "SELECT event_kind, prior_approval_id FROM approval_events WHERE approval_id = ?",
            (winner["approval_id"],),
        ).fetchone()
        approvals = connection.execute(
            "SELECT approval_id, review_id FROM approval_events WHERE event_kind = 'approved'"
        ).fetchall()
        partial = 0
        covered = {first["review"]: False, second["review"]: False}
        for approval_id, review_id in approvals:
            graph = first if review_id == first["review"] else second if review_id == second["review"] else None
            audit = connection.execute(
                "SELECT 1 FROM project_audit_links WHERE note = ?",
                (approval_id,),
            ).fetchone()
            if graph is None or audit is None or _pins(connection, graph) != 3:
                partial += 1
            elif review_id in covered:
                covered[review_id] = True
    observed = {
        "partial_approval_rows": partial,
        "concurrent_loser_status": loser,
        "old_approval_auto_revoked": revoked != 0 or first_kind is None or first_kind[0] != "approved" or first_kind[1] is not None,
        "default_and_pins_atomic": pointer is not None
        and pointer[0] == moved["approval_id"]
        and covered[first["review"]]
        and covered[second["review"]]
        and replay["approval_id"] == winner["approval_id"]
        and mismatch >= 400
        and denied >= 400,
    }
    assert observed == {
        "partial_approval_rows": 0,
        "concurrent_loser_status": 409,
        "old_approval_auto_revoked": False,
        "default_and_pins_atomic": True,
    }


def _pins(connection: sqlite3.Connection, graph: dict[str, str]) -> int:
    row = connection.execute(
        """
        SELECT COUNT(DISTINCT artifact_id) FROM artifact_protections
        WHERE kind = 'approval' AND artifact_id IN (?, ?, ?)
        """,
        (graph["source"], graph["trial_artifact"], graph["script"]),
    ).fetchone()
    return 0 if row is None else int(row[0])


def _bundle(
    connection: sqlite3.Connection,
    project_id: str,
    actor_id: str,
    case_id: str,
    revision: int,
    name: str,
    *,
    expired: bool = False,
    script: bool = True,
) -> dict[str, str]:
    ids = {
        "version": str(uuid4()),
        "manifest": str(uuid4()),
        "package": str(uuid4()),
        "recording": str(uuid4()),
        "execution": str(uuid4()),
        "trial": str(uuid4()),
        "rec_job": str(uuid4()),
        "item_job": str(uuid4()),
        "rec_attempt": str(uuid4()),
        "item_attempt": str(uuid4()),
        "source": str(uuid4()),
        "trial_artifact": str(uuid4()),
        "script": str(uuid4()),
        "review": str(uuid4()),
        "source_entry": str(uuid4()),
        "trial_entry": str(uuid4()),
        "version_hash": name + "-version",
        "evidence_hash": name + "-evidence",
    }
    stamp = "2026-11-01T00:00:00+00:00"
    stored = "2020-01-01T00:00:00+00:00" if expired else stamp
    custody = "expired" if expired else "stored"
    limits = json.dumps({"self_healing_enabled": False, "actor": 0})
    definition = json.dumps({"checks": [{"id": "check-1"}]})
    settings = json.dumps({"self_healing_enabled": False})
    connection.execute(
        """
        INSERT INTO case_versions (
            project_id, case_id, version_id, revision, creation_kind, parent_version_id, base_version_id,
            is_branch, definition_json, settings_json, recorded_steps_json, content_hash, verification_digest,
            source_manifest_id, replay_package_id, readiness_json, actor_id, reason, created_at
        ) VALUES (?, ?, ?, ?, 'recorded', NULL, NULL, 0, ?, ?, '[]', ?, 'digest', ?, ?, '{}', ?, 'recorded', ?)
        """,
        (
            project_id,
            case_id,
            ids["version"],
            revision,
            definition,
            settings,
            ids["version_hash"],
            ids["manifest"],
            ids["package"],
            actor_id,
            stamp,
        ),
    )
    connection.execute(
        """
        INSERT INTO recordings (
            project_id, case_id, recording_id, creation_kind, input_case_version_id, base_case_version_id,
            parent_recording_id, source_recording_id, storage_status, stop_status, completion_status, evidence_status
        ) VALUES (?, ?, ?, 'recorded', ?, NULL, NULL, NULL, 'stored', 'stopped', 'completed', 'complete')
        """,
        (project_id, case_id, ids["recording"], ids["version"]),
    )
    connection.execute(
        """
        INSERT INTO recording_manifests (
            project_id, case_id, recording_id, manifest_id, revision, kind, prior_manifest_id,
            input_version_hash, source_artifact_hashes, action_mapping, evidence_completeness,
            request_key, body_hash
        ) VALUES (?, ?, ?, ?, 1, 'original', NULL, ?, '[]', '{}', 'complete', ?, ?)
        """,
        (project_id, case_id, ids["recording"], ids["manifest"], ids["version_hash"], name + "-manifest", name + "-manifest-hash"),
    )
    connection.execute(
        """
        INSERT INTO replay_packages (
            project_id, package_id, case_id, case_version_id, ready, schema_version, source_manifest_id,
            source_manifest_hash, raw_source_hash, approved_code_hash, runtime_ref, compiler_ref, lock_hash,
            step_mapping_hash, body_hash
        ) VALUES (?, ?, ?, ?, 1, 'replay-package-v1', ?, ?, 'raw', 'plan', 'web', 'web-ipc-subset',
            'lock', 'mapping', ?)
        """,
        (project_id, ids["package"], case_id, ids["version"], ids["manifest"], name + "-manifest-hash", name + "-package"),
    )
    connection.execute(
        "INSERT INTO package_version_links (project_id, case_id, version_id, package_id) VALUES (?, ?, ?, ?)",
        (project_id, case_id, ids["version"], ids["package"]),
    )
    connection.execute(
        """
        INSERT INTO executions (
            project_id, execution_id, name, purpose, source, suite_version_id, scope_requested_at
        ) VALUES (?, ?, '시범', 'trial', 'single', NULL, ?)
        """,
        (project_id, ids["execution"], stamp),
    )
    connection.execute(
        """
        INSERT INTO case_runs (
            project_id, execution_id, case_run_id, case_id, case_version_id, purpose, requested_at
        ) VALUES (?, ?, ?, ?, ?, 'trial', ?)
        """,
        (project_id, ids["execution"], ids["trial"], case_id, ids["version"], stamp),
    )
    connection.execute(
        """
        INSERT INTO jobs (
            project_id, job_id, purpose, recording_id, case_run_id, payload_hash, source_refs, limits, status
        ) VALUES (?, ?, 'recording', ?, NULL, 'payload', '[]', ?, 'completed')
        """,
        (project_id, ids["rec_job"], ids["recording"], limits),
    )
    connection.execute(
        """
        INSERT INTO jobs (
            project_id, job_id, purpose, recording_id, case_run_id, payload_hash, source_refs, limits, status
        ) VALUES (?, ?, 'trial', NULL, ?, 'payload', '[]', ?, 'completed')
        """,
        (project_id, ids["item_job"], ids["trial"], limits),
    )
    connection.execute(
        "INSERT INTO attempts (project_id, attempt_id, job_id, generation, physical_key_id) VALUES (?, ?, ?, 1, NULL)",
        (project_id, ids["rec_attempt"], ids["rec_job"]),
    )
    connection.execute(
        "INSERT INTO attempts (project_id, attempt_id, job_id, generation, physical_key_id) VALUES (?, ?, ?, 1, NULL)",
        (project_id, ids["item_attempt"], ids["item_job"]),
    )
    for attempt, action in ((ids["rec_attempt"], "A001"), (ids["item_attempt"], "A001")):
        connection.execute(
            """
            INSERT INTO actions (
                project_id, attempt_id, action_seq, step_id, action_id, package_step_id, proposal_hash,
                dispatch_state, case_id, case_version_id, outcome_known
            ) VALUES (?, ?, 1, 'step-1', ?, NULL, 'proposal', 'observed', ?, ?, 1)
            """,
            (project_id, attempt, action, case_id, ids["version"]),
        )
    connection.execute(
        """
        INSERT INTO check_results (
            project_id, attempt_id, action_id, check_id, status, method, expected_snapshot,
            sanitized_observed, reason, artifact_refs, observed_at
        ) VALUES (?, ?, 'A001', 'check-1', 'satisfied', 'deterministic', '{}', '{}', '같음', '[]', ?)
        """,
        (project_id, ids["item_attempt"], stamp),
    )
    connection.execute(
        """
        INSERT INTO artifact_refs (
            project_id, artifact_id, attempt_id, action_id, check_id, recording_id, review_id, build_id,
            export_id, package_id, healing_id, proposal_id, resource_observation_id
        ) VALUES (?, ?, ?, 'A001', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL)
        """,
        (project_id, ids["source"], ids["rec_attempt"]),
    )
    connection.execute(
        """
        INSERT INTO artifact_refs (
            project_id, artifact_id, attempt_id, action_id, check_id, recording_id, review_id, build_id,
            export_id, package_id, healing_id, proposal_id, resource_observation_id
        ) VALUES (?, ?, ?, 'A001', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL)
        """,
        (project_id, ids["trial_artifact"], ids["item_attempt"]),
    )
    connection.execute(
        """
        INSERT INTO artifact_objects (
            project_id, artifact_id, object_key, content_hash, byte_length, media_type, owner_id, status, acked,
            custody, stored_at, owner_kind, attempt_id, action_id, role, job_id, generation
        ) VALUES (?, ?, ?, ?, 4, 'image/png', ?, 'ready', 1, ?, ?, 'REC', ?, 'A001', 'before', ?, 1)
        """,
        (project_id, ids["source"], ids["source"], name + "-source", ids["recording"], custody, stored, ids["rec_attempt"], ids["rec_job"]),
    )
    connection.execute(
        """
        INSERT INTO artifact_objects (
            project_id, artifact_id, object_key, content_hash, byte_length, media_type, owner_id, status, acked,
            custody, stored_at, owner_kind, attempt_id, action_id, role, job_id, generation
        ) VALUES (?, ?, ?, ?, 4, 'image/png', ?, 'ready', 1, 'stored', ?, 'ITEM', ?, 'A001', 'before', ?, 1)
        """,
        (project_id, ids["trial_artifact"], ids["trial_artifact"], name + "-trial", ids["trial"], stamp, ids["item_attempt"], ids["item_job"]),
    )
    if script:
        connection.execute(
            """
            INSERT INTO artifact_refs (
                project_id, artifact_id, attempt_id, action_id, check_id, recording_id, review_id, build_id,
                export_id, package_id, healing_id, proposal_id, resource_observation_id
            ) VALUES (?, ?, NULL, NULL, NULL, ?, NULL, NULL, NULL, NULL, NULL, NULL, NULL)
            """,
            (project_id, ids["script"], ids["recording"]),
        )
        connection.execute(
            """
            INSERT INTO artifact_objects (
                project_id, artifact_id, object_key, content_hash, byte_length, media_type, owner_id, status, acked,
                custody, stored_at, owner_kind, attempt_id, action_id, role, job_id, generation
            ) VALUES (?, ?, ?, ?, 4, 'text/plain', ?, 'ready', 1, 'stored', ?, 'REC', ?, NULL, 'source', ?, 1)
            """,
            (project_id, ids["script"], ids["script"], name + "-script", ids["recording"], stamp, ids["rec_attempt"], ids["rec_job"]),
        )
    connection.execute(
        """
        INSERT INTO reviews (
            project_id, review_id, case_id, case_version_id, version_hash, source_manifest_id,
            trial_case_run_id, evidence_set_hash, expected_current_approval_id, created_commit_seq
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
        """,
        (
            project_id,
            ids["review"],
            case_id,
            ids["version"],
            ids["version_hash"],
            ids["manifest"],
            ids["trial"],
            ids["evidence_hash"],
            revision,
        ),
    )
    for entry, kind, owner, attempt, artifact, digest in (
        (ids["source_entry"], "REC", ids["recording"], ids["rec_attempt"], ids["source"], name + "-source"),
        (ids["trial_entry"], "ITEM", ids["trial"], ids["item_attempt"], ids["trial_artifact"], name + "-trial"),
    ):
        connection.execute(
            """
            INSERT INTO review_evidence_entries (
                project_id, review_id, entry_id, owner_kind, owner_id, attempt_id, action_id,
                artifact_ref_id, role, expected_hash, evidence_digest
            ) VALUES (?, ?, ?, ?, ?, ?, 'A001', ?, 'before', ?, ?)
            """,
            (project_id, ids["review"], entry, kind, owner, attempt, artifact, digest, digest),
        )
        connection.execute(
            """
            INSERT INTO action_reviews (
                project_id, opinion_id, review_id, entry_id, owner_kind, owner_id, attempt_id, action_id,
                evidence_digest, state, actor_id, created_at, comment
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'A001', ?, 'reviewed', ?, ?, '확인')
            """,
            (project_id, str(uuid4()), ids["review"], entry, kind, owner, attempt, digest, actor_id, stamp),
        )
    return ids


async def _calls(
    app: object,
    project_id: str,
    first: dict[str, str],
    second: dict[str, str],
    expired: dict[str, str],
    bare: dict[str, str],
) -> tuple[dict[str, object], int, dict[str, object], int, int, dict[str, object]]:
    import asyncio

    import httpx

    origin = "http://127.0.0.1"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        headers = await _session(client, origin, project_id, "w1901")
        raced = await asyncio.gather(
            _approve(client, first, None, headers, "w1901-a"),
            _approve(client, first, None, headers, "w1901-b"),
        )
        winner = next(item for item in raced if item[0] == 201)
        loser = next(item[0] for item in raced if item[0] != 201)
        replay_status, replay = await _approve(client, first, None, headers, "w1901-a")
        held = str(winner[1]["approval_id"])
        mismatch, _body = await _approve(client, first, held, headers, "w1901-mismatch", version_hash="other-hash")
        denied_expired, _expired_body = await _approve(client, expired, held, headers, "w1901-expired")
        denied_bare, _bare_body = await _approve(client, bare, held, headers, "w1901-bare")
        moved_status, moved = await _approve(client, second, held, headers, "w1901-next")
    assert replay_status == 200 and moved_status == 201
    return winner[1], loser, replay, mismatch, max(denied_expired, denied_bare), moved


async def _approve(
    client: object,
    graph: dict[str, str],
    expected: str | None,
    headers: dict[str, str],
    key: str,
    version_hash: str | None = None,
) -> tuple[int, dict[str, object]]:
    sent = dict(headers)
    sent["Idempotency-Key"] = key
    response = await client.post(  # type: ignore[attr-defined]
        f"/api/v1/case-versions/{graph['version']}/approvals",
        json={
            "review_id": graph["review"],
            "version_hash": graph["version_hash"] if version_hash is None else version_hash,
            "evidence_set_hash": graph["evidence_hash"],
            "expected_current_approval_id": expected,
            "reason": "검토가 맞습니다.",
        },
        headers=sent,
    )
    body = response.json()
    assert type(body) is dict
    return response.status_code, body


async def _session(client: object, origin: str, project_id: str, key: str) -> dict[str, str]:
    issued = await client.post(  # type: ignore[attr-defined]
        "/api/v1/session/nonces",
        json={"origin": origin, "project_id": project_id},
        headers={"Idempotency-Key": key + "-nonce", "Origin": origin},
    )
    booted = await client.post(  # type: ignore[attr-defined]
        "/api/v1/session/bootstrap",
        json={"nonce": issued.json()["nonce"]},
        headers={"Idempotency-Key": key + "-boot", "Origin": origin},
    )
    client.cookies.set("aiqa_session", booted.cookies["aiqa_session"])  # type: ignore[attr-defined]
    return {"Origin": origin, "X-CSRF-Token": booted.json()["csrf_token"]}
