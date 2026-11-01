"""Review snapshots pin exact evidence. A healed trial is not accepted."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from uuid import UUID, uuid4

from aiqa.store.models import Actor


def test_w18_01(tmp_path: Path) -> None:
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
        project = create_project(owner, ProjectCreate("검토", "w1801", "snapshot", "web"))
    store.close()
    graph = _graph(root / "db" / "aiqa.sqlite", str(project.project_id), str(owner.actor_id))
    foreign, mixed, healed, created, page = asyncio.run(_requests(app, str(project.project_id), graph))
    with sqlite3.connect(root / "db" / "aiqa.sqlite") as connection:
        reviews = connection.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
        pins = connection.execute("SELECT COUNT(*) FROM artifact_protections WHERE kind = 'review'").fetchone()[0]
    observed = {
        "foreign_item_evidence_rejected": foreign >= 400 and reviews == 1,
        "same_action_id_mixing_rejected": mixed >= 400 and reviews == 1,
        "healed_trial_accepted": healed < 400,
        "review_pins_created": created == 201 and pins == 2,
    }
    assert "검토 snapshot" in page and "30일 보호" in page and "PASS" not in page
    assert created == 201 and reviews == 1
    assert observed == {
        "foreign_item_evidence_rejected": True,
        "same_action_id_mixing_rejected": True,
        "healed_trial_accepted": False,
        "review_pins_created": True,
    }


def _graph(database: Path, project_id: str, actor_id: str) -> dict[str, str]:
    ids = {
        "case": str(uuid4()),
        "version": str(uuid4()),
        "manifest": str(uuid4()),
        "package": str(uuid4()),
        "recording": str(uuid4()),
        "execution": str(uuid4()),
        "trial": str(uuid4()),
        "healed_execution": str(uuid4()),
        "healed": str(uuid4()),
        "foreign_execution": str(uuid4()),
        "foreign": str(uuid4()),
        "rec_job": str(uuid4()),
        "item_job": str(uuid4()),
        "healed_job": str(uuid4()),
        "foreign_job": str(uuid4()),
        "rec_attempt": str(uuid4()),
        "item_attempt": str(uuid4()),
        "foreign_attempt": str(uuid4()),
        "rec_artifact": str(uuid4()),
        "item_artifact": str(uuid4()),
        "foreign_artifact": str(uuid4()),
    }
    stamp = "2026-11-01T00:00:00+00:00"
    limits = json.dumps({"self_healing_enabled": False, "actor": 0})
    healed_limits = json.dumps({"self_healing_enabled": True, "actor": 0})
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO automation_cases (
                project_id, case_id, name, folder_id, tc_reference, next_revision,
                latest_draft_version_id, current_approval_id, lock_version, archived_at
            ) VALUES (?, ?, '로그인', NULL, NULL, 2, NULL, NULL, 0, NULL)
            """,
            (project_id, ids["case"]),
        )
        connection.execute(
            """
            INSERT INTO case_versions (
                project_id, case_id, version_id, revision, creation_kind, parent_version_id, base_version_id,
                is_branch, definition_json, settings_json, recorded_steps_json, content_hash, verification_digest,
                source_manifest_id, replay_package_id, readiness_json, actor_id, reason, created_at
            ) VALUES (?, ?, ?, 1, 'recorded', NULL, NULL, 0, '{}', '{}', '[]', 'version-hash', 'digest',
                ?, ?, '{}', ?, 'recorded', ?)
            """,
            (project_id, ids["case"], ids["version"], ids["manifest"], ids["package"], actor_id, stamp),
        )
        connection.execute(
            """
            INSERT INTO recordings (
                project_id, case_id, recording_id, creation_kind, input_case_version_id, base_case_version_id,
                parent_recording_id, source_recording_id, storage_status, stop_status, completion_status, evidence_status
            ) VALUES (?, ?, ?, 'recorded', ?, NULL, NULL, NULL, 'stored', 'stopped', 'completed', 'complete')
            """,
            (project_id, ids["case"], ids["recording"], ids["version"]),
        )
        connection.execute(
            """
            INSERT INTO recording_manifests (
                project_id, case_id, recording_id, manifest_id, revision, kind, prior_manifest_id,
                input_version_hash, source_artifact_hashes, action_mapping, evidence_completeness,
                request_key, body_hash
            ) VALUES (?, ?, ?, ?, 1, 'original', NULL, 'version-hash', '[]', '{}', 'complete', 'w1801-manifest', 'manifest-hash')
            """,
            (project_id, ids["case"], ids["recording"], ids["manifest"]),
        )
        connection.execute(
            """
            INSERT INTO replay_packages (
                project_id, package_id, case_id, case_version_id, ready, schema_version, source_manifest_id,
                source_manifest_hash, raw_source_hash, approved_code_hash, runtime_ref, compiler_ref, lock_hash,
                step_mapping_hash, body_hash
            ) VALUES (?, ?, ?, ?, 1, 'replay-package-v1', ?, 'manifest-hash', 'raw', 'plan', 'web', 'web-ipc-subset',
                'lock', 'mapping', 'package-hash')
            """,
            (project_id, ids["package"], ids["case"], ids["version"], ids["manifest"]),
        )
        connection.execute(
            "INSERT INTO package_version_links (project_id, case_id, version_id, package_id) VALUES (?, ?, ?, ?)",
            (project_id, ids["case"], ids["version"], ids["package"]),
        )
        for execution, run in (
            (ids["execution"], ids["trial"]),
            (ids["healed_execution"], ids["healed"]),
            (ids["foreign_execution"], ids["foreign"]),
        ):
            connection.execute(
                """
                INSERT INTO executions (
                    project_id, execution_id, name, purpose, source, suite_version_id, scope_requested_at
                ) VALUES (?, ?, '시범', 'trial', 'single', NULL, ?)
                """,
                (project_id, execution, stamp),
            )
            connection.execute(
                """
                INSERT INTO case_runs (
                    project_id, execution_id, case_run_id, case_id, case_version_id, purpose, requested_at
                ) VALUES (?, ?, ?, ?, ?, 'trial', ?)
                """,
                (project_id, execution, run, ids["case"], ids["version"], stamp),
            )
        connection.execute(
            """
            INSERT INTO jobs (
                project_id, job_id, purpose, recording_id, case_run_id, payload_hash, source_refs, limits, status
            ) VALUES (?, ?, 'recording', ?, NULL, 'payload', '[]', ?, 'completed')
            """,
            (project_id, ids["rec_job"], ids["recording"], limits),
        )
        for job, run, body in (
            (ids["item_job"], ids["trial"], limits),
            (ids["healed_job"], ids["healed"], healed_limits),
            (ids["foreign_job"], ids["foreign"], limits),
        ):
            connection.execute(
                """
                INSERT INTO jobs (
                    project_id, job_id, purpose, recording_id, case_run_id, payload_hash, source_refs, limits, status
                ) VALUES (?, ?, 'trial', NULL, ?, 'payload', '[]', ?, 'completed')
                """,
                (project_id, job, run, body),
            )
        for attempt, job in (
            (ids["rec_attempt"], ids["rec_job"]),
            (ids["item_attempt"], ids["item_job"]),
            (ids["foreign_attempt"], ids["foreign_job"]),
        ):
            connection.execute(
                """
                INSERT INTO attempts (project_id, attempt_id, job_id, generation, physical_key_id)
                VALUES (?, ?, ?, 1, NULL)
                """,
                (project_id, attempt, job),
            )
        for attempt, action in (
            (ids["rec_attempt"], "A001"),
            (ids["item_attempt"], "A001"),
            (ids["foreign_attempt"], "A002"),
        ):
            connection.execute(
                """
                INSERT INTO actions (
                    project_id, attempt_id, action_seq, step_id, action_id, package_step_id, proposal_hash,
                    dispatch_state, case_id, case_version_id, outcome_known
                ) VALUES (?, ?, 1, 'step-1', ?, NULL, 'proposal', 'observed', ?, ?, 1)
                """,
                (project_id, attempt, action, ids["case"], ids["version"]),
            )
        for artifact, attempt, action in (
            (ids["rec_artifact"], ids["rec_attempt"], "A001"),
            (ids["item_artifact"], ids["item_attempt"], "A001"),
            (ids["foreign_artifact"], ids["foreign_attempt"], "A002"),
        ):
            connection.execute(
                """
                INSERT INTO artifact_refs (
                    project_id, artifact_id, attempt_id, action_id, check_id, recording_id, review_id, build_id,
                    export_id, package_id, healing_id, proposal_id, resource_observation_id
                ) VALUES (?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL)
                """,
                (project_id, artifact, attempt, action),
            )
        for artifact, owner, kind, attempt, action, job, digest in (
            (ids["rec_artifact"], ids["recording"], "REC", ids["rec_attempt"], "A001", ids["rec_job"], "hash-rec"),
            (ids["item_artifact"], ids["trial"], "ITEM", ids["item_attempt"], "A001", ids["item_job"], "hash-item"),
            (ids["foreign_artifact"], ids["foreign"], "ITEM", ids["foreign_attempt"], "A002", ids["foreign_job"], "hash-foreign"),
        ):
            connection.execute(
                """
                INSERT INTO artifact_objects (
                    project_id, artifact_id, object_key, content_hash, byte_length, media_type, owner_id, status, acked,
                    owner_kind, attempt_id, action_id, check_id, role, job_id, generation
                ) VALUES (?, ?, ?, ?, 4, 'image/png', ?, 'ready', 1, ?, ?, ?, NULL, 'before', ?, 1)
                """,
                (project_id, artifact, artifact, digest, owner, kind, attempt, action, job),
            )
        connection.commit()
    return ids


async def _requests(
    app: object, project_id: str, graph: dict[str, str]
) -> tuple[int, int, int, int, str]:
    import httpx

    origin = "http://127.0.0.1"
    good = {
        "trial_case_run_id": graph["trial"],
        "entries": [_entry("REC", graph["recording"], graph["rec_attempt"], "A001", graph["rec_artifact"], "hash-rec"), _entry("ITEM", graph["trial"], graph["item_attempt"], "A001", graph["item_artifact"], "hash-item")],
    }
    foreign = {
        "trial_case_run_id": graph["trial"],
        "entries": [_entry("ITEM", graph["foreign"], graph["foreign_attempt"], "A002", graph["foreign_artifact"], "hash-foreign")],
    }
    mixed = {
        "trial_case_run_id": graph["trial"],
        "entries": [_entry("REC", graph["recording"], graph["item_attempt"], "A001", graph["item_artifact"], "hash-item")],
    }
    healed = {
        "trial_case_run_id": graph["healed"],
        "entries": good["entries"],
    }
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        headers = await _session(client, origin, project_id, "w1801")
        foreign_status = await _post(client, graph["version"], foreign, headers, "w1801-foreign")
        mixed_status = await _post(client, graph["version"], mixed, headers, "w1801-mixed")
        healed_status = await _post(client, graph["version"], healed, headers, "w1801-healed")
        created = await _post(client, graph["version"], good, headers, "w1801-create")
        page = await client.get(f"/ui/projects/{project_id}/cases/{graph['case']}/review")
    assert page.status_code == 200
    return foreign_status, mixed_status, healed_status, created, page.text


async def _post(client: object, version_id: str, body: dict[str, object], headers: dict[str, str], key: str) -> int:
    sent = dict(headers)
    sent["Idempotency-Key"] = key
    response = await client.post(f"/api/v1/case-versions/{version_id}/review-requests", json=body, headers=sent)  # type: ignore[attr-defined]
    return response.status_code


def _entry(kind: str, owner: str, attempt: str, action: str, artifact: str, digest: str) -> dict[str, str]:
    return {
        "owner_kind": kind,
        "owner_id": owner,
        "attempt_id": attempt,
        "action_id": action,
        "artifact_id": artifact,
        "role": "before",
        "expected_hash": digest,
    }


def test_w18_02(tmp_path: Path) -> None:
    import asyncio

    from aiqa.api.app import create_app
    from aiqa.config import load_settings
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.store.artifacts import content_hash, place_ready
    from aiqa.store.database import migrate_store
    from aiqa.store.models import ProjectCreate

    root = tmp_path / "runtime"
    app = create_app(load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}))
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("증거", "w1802", "viewer", "web"))
    store.close()
    graph = _viewer_graph(root, str(project.project_id), str(owner.actor_id))
    page, again, retention, script = asyncio.run(_viewer(app, str(project.project_id), graph))
    observed = {
        "exact_selection_restored": graph["attempt"] in page and graph["attempt"] in again and 'data-action-id="A001"' in page and 'data-action-id="A001"' in again,
        "missing_image_substituted": graph["other_artifact"] in page,
        "keyboard_navigation": 'data-keynav="true"' in page and "ArrowRight" in script and "ArrowLeft" in script,
        "before_after_distinct": graph["before"] in page and graph["after"] in page and graph["before"] != graph["after"],
    }
    assert retention["substituted"] is False and retention["state"] == "expired"
    assert "파일이 없습니다." in page and "보관 기한이 지났습니다." in page and "긴 기록" in page
    assert "PASS" not in page and "1024" in page
    assert observed == {
        "exact_selection_restored": True,
        "missing_image_substituted": False,
        "keyboard_navigation": True,
        "before_after_distinct": True,
    }


def _viewer_graph(root: Path, project_id: str, actor_id: str) -> dict[str, str]:
    from aiqa.store.artifacts import content_hash, place_ready

    ids = {
        "case": str(uuid4()),
        "version": str(uuid4()),
        "recording": str(uuid4()),
        "job": str(uuid4()),
        "other_recording": str(uuid4()),
        "other_job": str(uuid4()),
        "attempt": str(uuid4()),
        "other_attempt": str(uuid4()),
        "before": str(uuid4()),
        "after": str(uuid4()),
        "log": str(uuid4()),
        "expired": str(uuid4()),
        "other_artifact": str(uuid4()),
    }
    before = b"\x89PNG\r\n\x1a\nbefore"
    after = b"\x89PNG\r\n\x1a\nafter"
    other = b"\x89PNG\r\n\x1a\nother"
    log = ("긴 기록 " * 300).encode("utf-8")
    artifacts = root / "artifacts"
    ids["before_key"] = place_ready(artifacts, UUID(project_id), UUID(ids["before"]), ".png", before)
    ids["after_key"] = place_ready(artifacts, UUID(project_id), UUID(ids["after"]), ".png", after)
    ids["log_key"] = place_ready(artifacts, UUID(project_id), UUID(ids["log"]), ".log", log)
    ids["other_key"] = place_ready(artifacts, UUID(project_id), UUID(ids["other_artifact"]), ".png", other)
    stamp = "2026-11-01T00:00:00+00:00"
    limits = json.dumps({"self_healing_enabled": False, "actor": 0})
    with sqlite3.connect(root / "db" / "aiqa.sqlite") as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO automation_cases (
                project_id, case_id, name, folder_id, tc_reference, next_revision,
                latest_draft_version_id, current_approval_id, lock_version, archived_at
            ) VALUES (?, ?, '증거', NULL, NULL, 1, NULL, NULL, 0, NULL)
            """,
            (project_id, ids["case"]),
        )
        connection.execute(
            """
            INSERT INTO case_versions (
                project_id, case_id, version_id, revision, creation_kind, parent_version_id, base_version_id,
                is_branch, definition_json, settings_json, recorded_steps_json, content_hash, verification_digest,
                source_manifest_id, replay_package_id, readiness_json, actor_id, reason, created_at
            ) VALUES (?, ?, ?, 1, 'recorded', NULL, NULL, 0, '{}', '{}', '[]', 'version-hash', 'digest',
                NULL, NULL, '{}', ?, 'recorded', ?)
            """,
            (project_id, ids["case"], ids["version"], actor_id, stamp),
        )
        for recording in (ids["recording"], ids["other_recording"]):
            connection.execute(
                """
                INSERT INTO recordings (
                    project_id, case_id, recording_id, creation_kind, input_case_version_id, base_case_version_id,
                    parent_recording_id, source_recording_id, storage_status, stop_status, completion_status, evidence_status
                ) VALUES (?, ?, ?, 'recorded', ?, NULL, NULL, NULL, 'stored', 'stopped', 'completed', 'complete')
                """,
                (project_id, ids["case"], recording, ids["version"]),
            )
        for job, recording in ((ids["job"], ids["recording"]), (ids["other_job"], ids["other_recording"])):
            connection.execute(
                """
                INSERT INTO jobs (
                    project_id, job_id, purpose, recording_id, case_run_id, payload_hash, source_refs, limits, status
                ) VALUES (?, ?, 'recording', ?, NULL, 'payload', '[]', ?, 'completed')
                """,
                (project_id, job, recording, limits),
            )
        for attempt, job in ((ids["attempt"], ids["job"]), (ids["other_attempt"], ids["other_job"])):
            connection.execute(
                "INSERT INTO attempts (project_id, attempt_id, job_id, generation, physical_key_id) VALUES (?, ?, ?, 1, NULL)",
                (project_id, attempt, job),
            )
        for attempt, action, seq in ((ids["attempt"], "A001", 1), (ids["attempt"], "A002", 2), (ids["other_attempt"], "A001", 1)):
            connection.execute(
                """
                INSERT INTO actions (
                    project_id, attempt_id, action_seq, step_id, action_id, package_step_id, proposal_hash,
                    dispatch_state, case_id, case_version_id, outcome_known
                ) VALUES (?, ?, ?, 'step-1', ?, NULL, 'proposal', 'observed', ?, ?, 1)
                """,
                (project_id, attempt, seq, action, ids["case"], ids["version"]),
            )
        rows = (
            (ids["before"], ids["attempt"], "A001", "before", ids["before_key"], content_hash(before), "ready", 1, "stored", stamp, "image/png"),
            (ids["after"], ids["attempt"], "A001", "after", ids["after_key"], content_hash(after), "ready", 1, "stored", stamp, "image/png"),
            (ids["log"], ids["attempt"], "A001", "log", ids["log_key"], content_hash(log), "ready", 1, "stored", stamp, "text/plain"),
            (ids["expired"], ids["attempt"], "A002", "after", ids["after_key"], content_hash(after), "ready", 1, "expired", "2020-01-01T00:00:00+00:00", "image/png"),
            (ids["other_artifact"], ids["other_attempt"], "A001", "before", ids["other_key"], content_hash(other), "ready", 1, "stored", stamp, "image/png"),
        )
        for artifact, attempt, action, role, key, digest, status, acked, custody, stored, media in rows:
            connection.execute(
                """
                INSERT INTO artifact_refs (
                    project_id, artifact_id, attempt_id, action_id, check_id, recording_id, review_id, build_id,
                    export_id, package_id, healing_id, proposal_id, resource_observation_id
                ) VALUES (?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL)
                """,
                (project_id, artifact, attempt, action),
            )
            connection.execute(
                """
                INSERT INTO artifact_objects (
                    project_id, artifact_id, object_key, content_hash, byte_length, media_type, owner_id, status, acked,
                    custody, stored_at, owner_kind, attempt_id, action_id, role, job_id, generation
                ) VALUES (?, ?, ?, ?, 4, ?, ?, ?, ?, ?, ?, 'REC', ?, ?, ?, ?, 1)
                """,
                (
                    project_id,
                    artifact,
                    key,
                    digest,
                    media,
                    ids["recording"] if attempt == ids["attempt"] else ids["other_recording"],
                    status,
                    acked,
                    custody,
                    stored,
                    attempt,
                    action,
                    role,
                    ids["job"] if attempt == ids["attempt"] else ids["other_job"],
                ),
            )
        connection.execute(
            """
            INSERT INTO check_results (
                project_id, attempt_id, action_id, check_id, status, method, expected_snapshot,
                sanitized_observed, reason, artifact_refs, observed_at
            ) VALUES (?, ?, 'A002', 'check-1', 'violated', 'deterministic', '보임', '없음', '값이 다릅니다', '', ?)
            """,
            (project_id, ids["attempt"], stamp),
        )
        connection.commit()
    return ids


async def _viewer(app: object, project_id: str, graph: dict[str, str]) -> tuple[str, str, dict[str, object], str]:
    import httpx

    origin = "http://127.0.0.1"
    query = (
        f"/ui/projects/{project_id}/evidence?owner_kind=REC&owner_id={graph['recording']}"
        f"&attempt_id={graph['attempt']}&action_id=A001"
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        await _session(client, origin, project_id, "w1802")
        first = await client.get(query)
        second = await client.get(query)
        kept = await client.get(f"/api/v1/artifacts/{graph['expired']}/retention")
        script = await client.get("/static/evidence_viewer.js")
    assert first.status_code == 200 and second.status_code == 200 and kept.status_code == 200 and script.status_code == 200
    body = kept.json()
    assert type(body) is dict
    return first.text, second.text, body, script.text


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
    return {"Origin": origin, "X-CSRF-Token": booted.json()["csrf_token"], "Idempotency-Key": key}


def test_w18_03(tmp_path: Path) -> None:
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
        project = create_project(owner, ProjectCreate("의견", "w1803", "opinions", "web"))
    store.close()
    database = root / "db" / "aiqa.sqlite"
    graph = _action_graph(database, str(project.project_id), str(owner.actor_id))
    reviewed, conflict, other, blocked, page = asyncio.run(_opinions(app, database, str(project.project_id), graph))
    with sqlite3.connect(database) as connection:
        rec_states = [
            row[0]
            for row in connection.execute(
                """
                SELECT state FROM action_reviews
                WHERE entry_id = ?
                ORDER BY created_at, rowid
                """,
                (graph["rec_entry"],),
            ).fetchall()
        ]
        other_count = connection.execute(
            "SELECT COUNT(*) FROM action_reviews WHERE entry_id = ?",
            (graph["other_entry"],),
        ).fetchone()[0]
        item_state = connection.execute(
            """
            SELECT state FROM action_reviews
            WHERE entry_id = ?
            ORDER BY created_at DESC, rowid DESC
            LIMIT 1
            """,
            (graph["item_entry"],),
        ).fetchone()
        qa = connection.execute("SELECT core_result, COUNT(*) FROM item_finalizations").fetchone()
    observed = {
        "reviews_append_only": rec_states == ["needs_change", "reviewed"] and other_count == 1,
        "qa_unchanged": qa is not None and qa[0] == "INCONCLUSIVE" and qa[1] == 1,
        "count_uses_full_owner_key": reviewed["source_reviewed"] == 1 and reviewed["trial_reviewed"] == 0 and reviewed["action_id"] == "A001" and item_state is None,
        "recording_review_allowed": blocked < 400,
    }
    assert conflict == 409 and other == 201 and blocked == 422
    assert reviewed["history_count"] == 2 and reviewed["latest_state"] == "reviewed"
    assert reviewed["source_total"] + reviewed["trial_total"] == 3
    assert "다음 미검토" in page and "출처 검토 1 / 1" in page and "시범 검토 0 / 2" in page
    assert "PASS" not in page and "QA 판정을 바꾸지 않습니다." in page
    assert observed == {
        "reviews_append_only": True,
        "qa_unchanged": True,
        "count_uses_full_owner_key": True,
        "recording_review_allowed": False,
    }


def _action_graph(database: Path, project_id: str, actor_id: str) -> dict[str, str]:
    ids = {
        "case": str(uuid4()),
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
        "rec_artifact": str(uuid4()),
        "item_artifact": str(uuid4()),
        "other_artifact": str(uuid4()),
    }
    stamp = "2026-11-01T00:00:00+00:00"
    limits = json.dumps({"self_healing_enabled": False, "actor": 0})
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO automation_cases (
                project_id, case_id, name, folder_id, tc_reference, next_revision,
                latest_draft_version_id, current_approval_id, lock_version, archived_at
            ) VALUES (?, ?, '로그인', NULL, NULL, 2, NULL, NULL, 0, NULL)
            """,
            (project_id, ids["case"]),
        )
        connection.execute(
            """
            INSERT INTO case_versions (
                project_id, case_id, version_id, revision, creation_kind, parent_version_id, base_version_id,
                is_branch, definition_json, settings_json, recorded_steps_json, content_hash, verification_digest,
                source_manifest_id, replay_package_id, readiness_json, actor_id, reason, created_at
            ) VALUES (?, ?, ?, 1, 'recorded', NULL, NULL, 0, '{}', '{}', '[]', 'version-hash', 'digest',
                ?, ?, '{}', ?, 'recorded', ?)
            """,
            (project_id, ids["case"], ids["version"], ids["manifest"], ids["package"], actor_id, stamp),
        )
        connection.execute(
            """
            INSERT INTO recordings (
                project_id, case_id, recording_id, creation_kind, input_case_version_id, base_case_version_id,
                parent_recording_id, source_recording_id, storage_status, stop_status, completion_status, evidence_status
            ) VALUES (?, ?, ?, 'recorded', ?, NULL, NULL, NULL, 'stored', 'stopped', 'completed', 'complete')
            """,
            (project_id, ids["case"], ids["recording"], ids["version"]),
        )
        connection.execute(
            """
            INSERT INTO recording_manifests (
                project_id, case_id, recording_id, manifest_id, revision, kind, prior_manifest_id,
                input_version_hash, source_artifact_hashes, action_mapping, evidence_completeness,
                request_key, body_hash
            ) VALUES (?, ?, ?, ?, 1, 'original', NULL, 'version-hash', '[]', '{}', 'complete', 'w1803-manifest', 'manifest-hash')
            """,
            (project_id, ids["case"], ids["recording"], ids["manifest"]),
        )
        connection.execute(
            """
            INSERT INTO replay_packages (
                project_id, package_id, case_id, case_version_id, ready, schema_version, source_manifest_id,
                source_manifest_hash, raw_source_hash, approved_code_hash, runtime_ref, compiler_ref, lock_hash,
                step_mapping_hash, body_hash
            ) VALUES (?, ?, ?, ?, 1, 'replay-package-v1', ?, 'manifest-hash', 'raw', 'plan', 'web', 'web-ipc-subset',
                'lock', 'mapping', 'package-hash')
            """,
            (project_id, ids["package"], ids["case"], ids["version"], ids["manifest"]),
        )
        connection.execute(
            "INSERT INTO package_version_links (project_id, case_id, version_id, package_id) VALUES (?, ?, ?, ?)",
            (project_id, ids["case"], ids["version"], ids["package"]),
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
            (project_id, ids["execution"], ids["trial"], ids["case"], ids["version"], stamp),
        )
        connection.execute(
            """
            INSERT INTO item_finalizations (
                project_id, case_run_id, created_seq, finalized_seq, release_label, content_hash, core_result, denominator
            ) VALUES (?, ?, 1, 1, 'local', 'qa-hash', 'INCONCLUSIVE', 1)
            """,
            (project_id, ids["trial"]),
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
        for attempt, job in ((ids["rec_attempt"], ids["rec_job"]), (ids["item_attempt"], ids["item_job"])):
            connection.execute(
                "INSERT INTO attempts (project_id, attempt_id, job_id, generation, physical_key_id) VALUES (?, ?, ?, 1, NULL)",
                (project_id, attempt, job),
            )
        for attempt, action, seq in (
            (ids["rec_attempt"], "A001", 1),
            (ids["item_attempt"], "A001", 1),
            (ids["item_attempt"], "A002", 2),
        ):
            connection.execute(
                """
                INSERT INTO actions (
                    project_id, attempt_id, action_seq, step_id, action_id, package_step_id, proposal_hash,
                    dispatch_state, case_id, case_version_id, outcome_known
                ) VALUES (?, ?, ?, 'step-1', ?, NULL, 'proposal', 'observed', ?, ?, 1)
                """,
                (project_id, attempt, seq, action, ids["case"], ids["version"]),
            )
        for artifact, attempt, action in (
            (ids["rec_artifact"], ids["rec_attempt"], "A001"),
            (ids["item_artifact"], ids["item_attempt"], "A001"),
            (ids["other_artifact"], ids["item_attempt"], "A002"),
        ):
            connection.execute(
                """
                INSERT INTO artifact_refs (
                    project_id, artifact_id, attempt_id, action_id, check_id, recording_id, review_id, build_id,
                    export_id, package_id, healing_id, proposal_id, resource_observation_id
                ) VALUES (?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL)
                """,
                (project_id, artifact, attempt, action),
            )
        for artifact, owner, kind, attempt, action, job, digest in (
            (ids["rec_artifact"], ids["recording"], "REC", ids["rec_attempt"], "A001", ids["rec_job"], "hash-rec"),
            (ids["item_artifact"], ids["trial"], "ITEM", ids["item_attempt"], "A001", ids["item_job"], "hash-item"),
            (ids["other_artifact"], ids["trial"], "ITEM", ids["item_attempt"], "A002", ids["item_job"], "hash-other"),
        ):
            connection.execute(
                """
                INSERT INTO artifact_objects (
                    project_id, artifact_id, object_key, content_hash, byte_length, media_type, owner_id, status, acked,
                    owner_kind, attempt_id, action_id, check_id, role, job_id, generation
                ) VALUES (?, ?, ?, ?, 4, 'image/png', ?, 'ready', 1, ?, ?, ?, NULL, 'before', ?, 1)
                """,
                (project_id, artifact, artifact, digest, owner, kind, attempt, action, job),
            )
        connection.commit()
    return ids


async def _opinions(
    app: object, database: Path, project_id: str, graph: dict[str, str]
) -> tuple[dict[str, object], int, int, int, str]:
    import httpx

    origin = "http://127.0.0.1"
    body = {
        "trial_case_run_id": graph["trial"],
        "entries": [
            _entry("REC", graph["recording"], graph["rec_attempt"], "A001", graph["rec_artifact"], "hash-rec"),
            _entry("ITEM", graph["trial"], graph["item_attempt"], "A001", graph["item_artifact"], "hash-item"),
            _entry("ITEM", graph["trial"], graph["item_attempt"], "A002", graph["other_artifact"], "hash-other"),
        ],
    }
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        headers = await _session(client, origin, project_id, "w1803")
        created = await _post(client, graph["version"], body, headers, "w1803-create")
        assert created == 201
        with sqlite3.connect(database) as connection:
            rows = connection.execute(
                "SELECT entry_id, owner_kind, action_id, evidence_digest, review_id FROM review_evidence_entries"
            ).fetchall()
        found = {(str(row[1]), str(row[2])): row for row in rows}
        graph["rec_entry"] = str(found[("REC", "A001")][0])
        graph["item_entry"] = str(found[("ITEM", "A001")][0])
        graph["other_entry"] = str(found[("ITEM", "A002")][0])
        digest = str(found[("REC", "A001")][3])
        review_id = str(found[("REC", "A001")][4])
        await _opinion(client, graph["version"], review_id, graph["rec_entry"], digest, "needs_change", "고쳐 주세요", headers, "w1803-change")
        reviewed = await _opinion(client, graph["version"], review_id, graph["rec_entry"], digest, "reviewed", "확인했습니다", headers, "w1803-reviewed")
        conflict = await _opinion(client, graph["version"], review_id, graph["rec_entry"], "other-digest", "reviewed", "다른 digest", headers, "w1803-digest")
        other = await _opinion(client, graph["version"], review_id, graph["other_entry"], digest, "needs_change", "다른 entry", headers, "w1803-other")
        with sqlite3.connect(database) as connection:
            connection.execute("UPDATE recordings SET stop_status = 'running' WHERE recording_id = ?", (graph["recording"],))
        blocked = await _opinion(client, graph["version"], review_id, graph["item_entry"], digest, "reviewed", "녹화 중", headers, "w1803-open")
        page = await client.get(f"/ui/projects/{project_id}/cases/{graph['case']}/review")
    assert reviewed.status_code == 201 and page.status_code == 200
    payload = reviewed.json()
    assert type(payload) is dict
    return payload, conflict.status_code, other.status_code, blocked.status_code, page.text


async def _opinion(
    client: object,
    version_id: str,
    review_id: str,
    entry_id: str,
    digest: str,
    state: str,
    comment: str,
    headers: dict[str, str],
    key: str,
) -> object:
    sent = dict(headers)
    sent["Idempotency-Key"] = key
    return await client.post(  # type: ignore[attr-defined]
        f"/api/v1/case-versions/{version_id}/action-reviews",
        json={
            "review_id": review_id,
            "entry_key": entry_id,
            "evidence_digest": digest,
            "state": state,
            "comment": comment,
        },
        headers=sent,
    )


def test_w18_04(tmp_path: Path) -> None:
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
        project = create_project(owner, ProjectCreate("차이", "w1804", "diff", "web"))
    store.close()
    database = root / "db" / "aiqa.sqlite"
    graph = _readiness_graph(database, str(project.project_id), str(owner.actor_id))
    body, page = asyncio.run(_readiness(app, str(project.project_id), graph))
    with sqlite3.connect(database) as connection:
        candidate_reviews = connection.execute(
            "SELECT COUNT(*) FROM reviews WHERE case_version_id = ?",
            (graph["candidate"],),
        ).fetchone()[0]
        base_reviews = connection.execute(
            "SELECT COUNT(*) FROM reviews WHERE case_version_id = ?",
            (graph["base"],),
        ).fetchone()[0]
    fields = {item["field"]: item for item in body["diffs"]}
    reasons = set(body["block_reasons"])
    observed = {
        "incomplete_candidate_approve": body["approve_allowed"],
        "block_reasons_explicit": reasons
        == {
            "recording is partial",
            "evidence is incomplete",
            "package is missing",
            "lock is missing",
            "mapping is missing",
            "trial hash is stale",
            "action review is missing",
        }
        and body["trial_off"] is True
        and all(body["block_labels"][reason] for reason in reasons),
        "old_review_copied": body["old_review_copied"] or candidate_reviews != 1 or base_reviews != 1,
        "source_trial_tabs_distinct": body["source_owner_id"] == graph["candidate_recording"]
        and body["trial_owner_id"] == graph["trial"]
        and body["source_owner_id"] != body["trial_owner_id"]
        and 'data-tab="source"' in page
        and 'data-tab="trial"' in page,
    }
    assert fields["expected"]["changed"] is True and fields["procedure"]["changed"] is True
    assert fields["path"]["changed"] is False and fields["settings"]["changed"] is False
    assert "이 후보를 승인할 수 없습니다." in page and "이전 검토를 복사하지 않았습니다." in page
    assert "새 초안" in page and "전체 재녹화" in page and 'aria-label="저장 근거의 단계"' in page
    assert "PASS" not in page
    assert observed == {
        "incomplete_candidate_approve": False,
        "block_reasons_explicit": True,
        "old_review_copied": False,
        "source_trial_tabs_distinct": True,
    }


def _readiness_graph(database: Path, project_id: str, actor_id: str) -> dict[str, str]:
    ids = {
        "case": str(uuid4()),
        "base": str(uuid4()),
        "candidate": str(uuid4()),
        "base_manifest": str(uuid4()),
        "candidate_manifest": str(uuid4()),
        "base_package": str(uuid4()),
        "candidate_package": str(uuid4()),
        "base_recording": str(uuid4()),
        "candidate_recording": str(uuid4()),
        "execution": str(uuid4()),
        "trial": str(uuid4()),
        "base_job": str(uuid4()),
        "candidate_job": str(uuid4()),
        "trial_job": str(uuid4()),
        "base_attempt": str(uuid4()),
        "candidate_attempt": str(uuid4()),
        "item_attempt": str(uuid4()),
        "base_review": str(uuid4()),
        "candidate_review": str(uuid4()),
        "open_entry": str(uuid4()),
        "done_entry": str(uuid4()),
        "rec_artifact": str(uuid4()),
        "item_artifact": str(uuid4()),
    }
    stamp = "2026-11-01T00:00:00+00:00"
    limits = json.dumps({"self_healing_enabled": False, "actor": 0})
    base_definition = json.dumps({"expected": "원문", "path": "login", "target": "web", "errors": ""}, ensure_ascii=False)
    candidate_definition = json.dumps({"expected": "바뀐 기대", "path": "login", "target": "web", "errors": ""}, ensure_ascii=False)
    settings = json.dumps({"mode": "off"}, ensure_ascii=False)
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO automation_cases (
                project_id, case_id, name, folder_id, tc_reference, next_revision,
                latest_draft_version_id, current_approval_id, lock_version, archived_at
            ) VALUES (?, ?, '로그인', NULL, NULL, 3, NULL, NULL, 0, NULL)
            """,
            (project_id, ids["case"]),
        )
        _version_row(
            connection, project_id, ids, actor_id, stamp, "base", 1, None, base_definition, settings, "[]", "base-hash", ids["base_manifest"], ids["base_package"]
        )
        _version_row(
            connection,
            project_id,
            ids,
            actor_id,
            stamp,
            "candidate",
            2,
            ids["base"],
            candidate_definition,
            settings,
            '[{"id":"step-1"}]',
            "candidate-hash",
            ids["candidate_manifest"],
            None,
        )
        _recording_row(connection, project_id, ids, "base", "stored", "complete", "completed")
        _recording_row(connection, project_id, ids, "candidate", "spooling", "incomplete", "open")
        _manifest_row(connection, project_id, ids, "base")
        _manifest_row(connection, project_id, ids, "candidate")
        _package_row(connection, project_id, ids, "base", 1, "lock-base", "mapping-base")
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
            (project_id, ids["execution"], ids["trial"], ids["case"], ids["base"], stamp),
        )
        for name, purpose, recording, run in (
            ("base", "recording", ids["base_recording"], None),
            ("candidate", "recording", ids["candidate_recording"], None),
            ("trial", "trial", None, ids["trial"]),
        ):
            connection.execute(
                """
                INSERT INTO jobs (
                    project_id, job_id, purpose, recording_id, case_run_id, payload_hash, source_refs, limits, status
                ) VALUES (?, ?, ?, ?, ?, 'payload', '[]', ?, 'completed')
                """,
                (project_id, ids[name + "_job"], purpose, recording, run, limits),
            )
        for name, job in (("base", ids["base_job"]), ("candidate", ids["candidate_job"]), ("item", ids["trial_job"])):
            connection.execute(
                "INSERT INTO attempts (project_id, attempt_id, job_id, generation, physical_key_id) VALUES (?, ?, ?, 1, NULL)",
                (project_id, ids[name + "_attempt"], job),
            )
        for attempt, action, seq, version in (
            (ids["candidate_attempt"], "A001", 1, ids["candidate"]),
            (ids["item_attempt"], "A001", 1, ids["base"]),
        ):
            connection.execute(
                """
                INSERT INTO actions (
                    project_id, attempt_id, action_seq, step_id, action_id, package_step_id, proposal_hash,
                    dispatch_state, case_id, case_version_id, outcome_known
                ) VALUES (?, ?, ?, 'step-1', ?, NULL, 'proposal', 'observed', ?, ?, 1)
                """,
                (project_id, attempt, seq, action, ids["case"], version),
            )
        for artifact, attempt in ((ids["rec_artifact"], ids["candidate_attempt"]), (ids["item_artifact"], ids["item_attempt"])):
            connection.execute(
                """
                INSERT INTO artifact_refs (
                    project_id, artifact_id, attempt_id, action_id, check_id, recording_id, review_id, build_id,
                    export_id, package_id, healing_id, proposal_id, resource_observation_id
                ) VALUES (?, ?, ?, 'A001', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL)
                """,
                (project_id, artifact, attempt),
            )
        connection.execute(
            """
            INSERT INTO reviews (
                project_id, review_id, case_id, case_version_id, version_hash, source_manifest_id,
                trial_case_run_id, evidence_set_hash, expected_current_approval_id, created_commit_seq
            ) VALUES (?, ?, ?, ?, 'base-hash', ?, NULL, 'base-set', NULL, 1)
            """,
            (project_id, ids["base_review"], ids["case"], ids["base"], ids["base_manifest"]),
        )
        connection.execute(
            """
            INSERT INTO reviews (
                project_id, review_id, case_id, case_version_id, version_hash, source_manifest_id,
                trial_case_run_id, evidence_set_hash, expected_current_approval_id, created_commit_seq
            ) VALUES (?, ?, ?, ?, 'candidate-hash', ?, ?, 'candidate-set', NULL, 2)
            """,
            (project_id, ids["candidate_review"], ids["case"], ids["candidate"], ids["candidate_manifest"], ids["trial"]),
        )
        for entry, kind, owner, attempt, artifact in (
            (ids["open_entry"], "REC", ids["candidate_recording"], ids["candidate_attempt"], ids["rec_artifact"]),
            (ids["done_entry"], "ITEM", ids["trial"], ids["item_attempt"], ids["item_artifact"]),
        ):
            connection.execute(
                """
                INSERT INTO review_evidence_entries (
                    project_id, review_id, entry_id, owner_kind, owner_id, attempt_id, action_id,
                    artifact_ref_id, role, expected_hash, evidence_digest
                ) VALUES (?, ?, ?, ?, ?, ?, 'A001', ?, 'before', 'hash', 'candidate-set')
                """,
                (project_id, ids["candidate_review"], entry, kind, owner, attempt, artifact),
            )
        connection.execute(
            """
            INSERT INTO action_reviews (
                project_id, opinion_id, review_id, entry_id, owner_kind, owner_id, attempt_id, action_id,
                evidence_digest, state, actor_id, created_at, comment
            ) VALUES (?, ?, ?, ?, 'ITEM', ?, ?, 'A001', 'candidate-set', 'reviewed', ?, ?, '확인')
            """,
            (project_id, str(uuid4()), ids["candidate_review"], ids["done_entry"], ids["trial"], ids["item_attempt"], actor_id, stamp),
        )
        connection.commit()
    return ids


def _version_row(
    connection: sqlite3.Connection,
    project_id: str,
    ids: dict[str, str],
    actor_id: str,
    stamp: str,
    name: str,
    revision: int,
    base: str | None,
    definition: str,
    settings: str,
    steps: str,
    content_hash: str,
    manifest: str,
    package: str,
) -> None:
    connection.execute(
        """
        INSERT INTO case_versions (
            project_id, case_id, version_id, revision, creation_kind, parent_version_id, base_version_id,
            is_branch, definition_json, settings_json, recorded_steps_json, content_hash, verification_digest,
            source_manifest_id, replay_package_id, readiness_json, actor_id, reason, created_at
        ) VALUES (?, ?, ?, ?, 'recorded', NULL, ?, 0, ?, ?, ?, ?, 'digest', ?, ?, '{}', ?, 'recorded', ?)
        """,
        (project_id, ids["case"], ids[name], revision, base, definition, settings, steps, content_hash, manifest, package, actor_id, stamp),
    )


def _recording_row(
    connection: sqlite3.Connection, project_id: str, ids: dict[str, str], name: str, storage: str, evidence: str, completion: str
) -> None:
    connection.execute(
        """
        INSERT INTO recordings (
            project_id, case_id, recording_id, creation_kind, input_case_version_id, base_case_version_id,
            parent_recording_id, source_recording_id, storage_status, stop_status, completion_status, evidence_status
        ) VALUES (?, ?, ?, 'recorded', ?, NULL, NULL, NULL, ?, 'stopped', ?, ?)
        """,
        (project_id, ids["case"], ids[name + "_recording"], ids[name], storage, completion, evidence),
    )


def _manifest_row(connection: sqlite3.Connection, project_id: str, ids: dict[str, str], name: str) -> None:
    connection.execute(
        """
        INSERT INTO recording_manifests (
            project_id, case_id, recording_id, manifest_id, revision, kind, prior_manifest_id,
            input_version_hash, source_artifact_hashes, action_mapping, evidence_completeness,
            request_key, body_hash
        ) VALUES (?, ?, ?, ?, 1, 'original', NULL, 'hash', '[]', '{}', 'complete', ?, 'manifest-hash')
        """,
        (project_id, ids["case"], ids[name + "_recording"], ids[name + "_manifest"], "w1804-" + name),
    )


def _package_row(
    connection: sqlite3.Connection, project_id: str, ids: dict[str, str], name: str, ready: int, lock: str, mapping: str
) -> None:
    connection.execute(
        """
        INSERT INTO replay_packages (
            project_id, package_id, case_id, case_version_id, ready, schema_version, source_manifest_id,
            source_manifest_hash, raw_source_hash, approved_code_hash, runtime_ref, compiler_ref, lock_hash,
            step_mapping_hash, body_hash
        ) VALUES (?, ?, ?, ?, ?, 'replay-package-v1', ?, 'manifest-hash', 'raw', 'plan', 'web', 'web-ipc-subset', ?, ?, ?)
        """,
        (
            project_id,
            ids[name + "_package"],
            ids["case"],
            ids[name],
            ready,
            ids[name + "_manifest"],
            lock,
            mapping,
            name + "-package",
        ),
    )
    connection.execute(
        "INSERT INTO package_version_links (project_id, case_id, version_id, package_id) VALUES (?, ?, ?, ?)",
        (project_id, ids["case"], ids[name], ids[name + "_package"]),
    )


async def _readiness(app: object, project_id: str, graph: dict[str, str]) -> tuple[dict[str, object], str]:
    import httpx

    origin = "http://127.0.0.1"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        headers = await _session(client, origin, project_id, "w1804")
        response = await client.get(f"/api/v1/case-versions/{graph['candidate']}/review-readiness", headers=headers)
        page = await client.get(f"/ui/projects/{project_id}/cases/{graph['case']}/review")
    assert response.status_code == 200 and page.status_code == 200
    body = response.json()
    assert type(body) is dict
    return body, page.text


def test_w18_05(tmp_path: Path) -> None:
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
        project = create_project(owner, ProjectCreate("보호", "w1805", "retention", "web"))
    store.close()
    database = root / "db" / "aiqa.sqlite"
    graph = _retention_graph(database, str(project.project_id), str(owner.actor_id))
    status, body, page = asyncio.run(_retention(app, str(project.project_id), graph))
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        kept = connection.execute(
            "SELECT expires_at FROM review_retention_events WHERE event_id = ?",
            (graph["first_event"],),
        ).fetchone()
        events = connection.execute(
            "SELECT COUNT(*) FROM review_retention_events WHERE review_id = ?",
            (graph["review"],),
        ).fetchone()[0]
        decision = connection.execute(
            "SELECT state FROM review_decisions WHERE review_id = ?",
            (graph["review"],),
        ).fetchone()
        pin = connection.execute(
            "SELECT kind FROM artifact_protections WHERE protection_id = ?",
            (graph["approval_pin"],),
        ).fetchone()
        try:
            connection.execute(
                "UPDATE review_retention_events SET expires_at = '2099-01-01T00:00:00+00:00' WHERE event_id = ?",
                (graph["first_event"],),
            )
            mutable = True
        except sqlite3.IntegrityError:
            connection.rollback()
            mutable = False
    observed = {
        "extension_appends": status == 201
        and body["event_count"] == 2
        and body["prior_expires_at"] == graph["first_expires"]
        and body["expires_at"] != graph["first_expires"]
        and kept is not None
        and kept[0] == graph["first_expires"]
        and events == 2
        and mutable is False
        and body["temporary"] is True,
        "expired_missing_approve": body["approve_allowed"],
        "rejected_record_retained": decision is not None
        and decision[0] == "rejected"
        and "반려 기록은 남아 있습니다." in page
        and "영구 pin" in page,
        "other_approval_pin_preserved": pin is not None and pin[0] == "approval",
    }
    assert "보호 기한" in page and "만료된 근거가 있어 승인할 수 없습니다." in page
    assert "새 녹화" in page and "새 시범" in page and "PASS" not in page
    assert observed == {
        "extension_appends": True,
        "expired_missing_approve": False,
        "rejected_record_retained": True,
        "other_approval_pin_preserved": True,
    }


def _retention_graph(database: Path, project_id: str, actor_id: str) -> dict[str, str]:
    ids = {
        "case": str(uuid4()),
        "version": str(uuid4()),
        "manifest": str(uuid4()),
        "package": str(uuid4()),
        "recording": str(uuid4()),
        "job": str(uuid4()),
        "attempt": str(uuid4()),
        "live": str(uuid4()),
        "expired": str(uuid4()),
        "pinned": str(uuid4()),
        "review": str(uuid4()),
        "live_entry": str(uuid4()),
        "expired_entry": str(uuid4()),
        "decision": str(uuid4()),
        "first_protection": str(uuid4()),
        "first_event": str(uuid4()),
        "approval_pin": str(uuid4()),
        "first_expires": "2026-10-01T00:00:00+00:00",
    }
    stamp = "2026-11-01T00:00:00+00:00"
    limits = json.dumps({"self_healing_enabled": False, "actor": 0})
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO automation_cases (
                project_id, case_id, name, folder_id, tc_reference, next_revision,
                latest_draft_version_id, current_approval_id, lock_version, archived_at
            ) VALUES (?, ?, '보호', NULL, NULL, 2, NULL, NULL, 0, NULL)
            """,
            (project_id, ids["case"]),
        )
        connection.execute(
            """
            INSERT INTO case_versions (
                project_id, case_id, version_id, revision, creation_kind, parent_version_id, base_version_id,
                is_branch, definition_json, settings_json, recorded_steps_json, content_hash, verification_digest,
                source_manifest_id, replay_package_id, readiness_json, actor_id, reason, created_at
            ) VALUES (?, ?, ?, 1, 'recorded', NULL, NULL, 0, '{}', '{}', '[]', 'version-hash', 'digest',
                ?, ?, '{}', ?, 'recorded', ?)
            """,
            (project_id, ids["case"], ids["version"], ids["manifest"], ids["package"], actor_id, stamp),
        )
        connection.execute(
            """
            INSERT INTO recordings (
                project_id, case_id, recording_id, creation_kind, input_case_version_id, base_case_version_id,
                parent_recording_id, source_recording_id, storage_status, stop_status, completion_status, evidence_status
            ) VALUES (?, ?, ?, 'recorded', ?, NULL, NULL, NULL, 'stored', 'stopped', 'completed', 'complete')
            """,
            (project_id, ids["case"], ids["recording"], ids["version"]),
        )
        connection.execute(
            """
            INSERT INTO recording_manifests (
                project_id, case_id, recording_id, manifest_id, revision, kind, prior_manifest_id,
                input_version_hash, source_artifact_hashes, action_mapping, evidence_completeness,
                request_key, body_hash
            ) VALUES (?, ?, ?, ?, 1, 'original', NULL, 'version-hash', '[]', '{}', 'complete', 'w1805-manifest', 'manifest-hash')
            """,
            (project_id, ids["case"], ids["recording"], ids["manifest"]),
        )
        connection.execute(
            """
            INSERT INTO replay_packages (
                project_id, package_id, case_id, case_version_id, ready, schema_version, source_manifest_id,
                source_manifest_hash, raw_source_hash, approved_code_hash, runtime_ref, compiler_ref, lock_hash,
                step_mapping_hash, body_hash
            ) VALUES (?, ?, ?, ?, 1, 'replay-package-v1', ?, 'manifest-hash', 'raw', 'plan', 'web', 'web-ipc-subset',
                'lock', 'mapping', 'package-hash')
            """,
            (project_id, ids["package"], ids["case"], ids["version"], ids["manifest"]),
        )
        connection.execute(
            "INSERT INTO package_version_links (project_id, case_id, version_id, package_id) VALUES (?, ?, ?, ?)",
            (project_id, ids["case"], ids["version"], ids["package"]),
        )
        connection.execute(
            """
            INSERT INTO jobs (
                project_id, job_id, purpose, recording_id, case_run_id, payload_hash, source_refs, limits, status
            ) VALUES (?, ?, 'recording', ?, NULL, 'payload', '[]', ?, 'completed')
            """,
            (project_id, ids["job"], ids["recording"], limits),
        )
        connection.execute(
            "INSERT INTO attempts (project_id, attempt_id, job_id, generation, physical_key_id) VALUES (?, ?, ?, 1, NULL)",
            (project_id, ids["attempt"], ids["job"]),
        )
        connection.execute(
            """
            INSERT INTO actions (
                project_id, attempt_id, action_seq, step_id, action_id, package_step_id, proposal_hash,
                dispatch_state, case_id, case_version_id, outcome_known
            ) VALUES (?, ?, 1, 'step-1', 'A001', NULL, 'proposal', 'observed', ?, ?, 1)
            """,
            (project_id, ids["attempt"], ids["case"], ids["version"]),
        )
        rows = (
            (ids["live"], "before", "hash-live", "stored", stamp),
            (ids["expired"], "after", "hash-expired", "expired", "2020-01-01T00:00:00+00:00"),
            (ids["pinned"], "log", "hash-pinned", "stored", stamp),
        )
        for artifact, role, digest, custody, stored in rows:
            connection.execute(
                """
                INSERT INTO artifact_refs (
                    project_id, artifact_id, attempt_id, action_id, check_id, recording_id, review_id, build_id,
                    export_id, package_id, healing_id, proposal_id, resource_observation_id
                ) VALUES (?, ?, ?, 'A001', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL)
                """,
                (project_id, artifact, ids["attempt"]),
            )
            connection.execute(
                """
                INSERT INTO artifact_objects (
                    project_id, artifact_id, object_key, content_hash, byte_length, media_type, owner_id, status, acked,
                    custody, stored_at, owner_kind, attempt_id, action_id, role, job_id, generation
                ) VALUES (?, ?, ?, ?, 4, 'image/png', ?, 'ready', 1, ?, ?, 'REC', ?, 'A001', ?, ?, 1)
                """,
                (project_id, artifact, artifact, digest, ids["recording"], custody, stored, ids["attempt"], role, ids["job"]),
            )
        connection.execute(
            """
            INSERT INTO reviews (
                project_id, review_id, case_id, case_version_id, version_hash, source_manifest_id,
                trial_case_run_id, evidence_set_hash, expected_current_approval_id, created_commit_seq
            ) VALUES (?, ?, ?, ?, 'version-hash', ?, NULL, 'evidence-set', NULL, 1)
            """,
            (project_id, ids["review"], ids["case"], ids["version"], ids["manifest"]),
        )
        for entry, artifact, role, digest in (
            (ids["live_entry"], ids["live"], "before", "hash-live"),
            (ids["expired_entry"], ids["expired"], "after", "hash-expired"),
        ):
            connection.execute(
                """
                INSERT INTO review_evidence_entries (
                    project_id, review_id, entry_id, owner_kind, owner_id, attempt_id, action_id,
                    artifact_ref_id, role, expected_hash, evidence_digest
                ) VALUES (?, ?, ?, 'REC', ?, ?, 'A001', ?, ?, ?, ?)
                """,
                (project_id, ids["review"], entry, ids["recording"], ids["attempt"], artifact, role, digest, digest),
            )
        connection.execute(
            """
            INSERT INTO review_decisions (
                project_id, review_id, decision_id, state, actor_id, created_at, reason, version_hash
            ) VALUES (?, ?, ?, 'rejected', ?, ?, '근거가 만료되었습니다.', 'version-hash')
            """,
            (project_id, ids["review"], ids["decision"], actor_id, stamp),
        )
        connection.execute(
            """
            INSERT INTO artifact_protections (
                project_id, protection_id, artifact_id, kind, backup_receipt_id, build_id, manual_request_id
            ) VALUES (?, ?, ?, 'review', NULL, NULL, NULL)
            """,
            (project_id, ids["first_protection"], ids["live"]),
        )
        connection.execute(
            """
            INSERT INTO review_retention_events (
                project_id, event_id, review_id, protection_id, artifact_id, reason, expires_at, created_at
            ) VALUES (?, ?, ?, ?, ?, '첫 임시 보호', ?, '2026-09-01T00:00:00+00:00')
            """,
            (project_id, ids["first_event"], ids["review"], ids["first_protection"], ids["live"], ids["first_expires"]),
        )
        connection.execute(
            """
            INSERT INTO artifact_protections (
                project_id, protection_id, artifact_id, kind, backup_receipt_id, build_id, manual_request_id
            ) VALUES (?, ?, ?, 'approval', NULL, NULL, NULL)
            """,
            (project_id, ids["approval_pin"], ids["pinned"]),
        )
        connection.commit()
    return ids


async def _retention(app: object, project_id: str, graph: dict[str, str]) -> tuple[int, dict[str, object], str]:
    import httpx

    origin = "http://127.0.0.1"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        headers = await _session(client, origin, project_id, "w1805")
        sent = dict(headers)
        sent["Idempotency-Key"] = "w1805-extend"
        response = await client.post(
            f"/api/v1/review-requests/{graph['review']}/retention-extensions",
            json={"artifact_id": graph["live"], "reason": "임시 보호를 30일 연장합니다."},
            headers=sent,
        )
        page = await client.get(f"/ui/projects/{project_id}/cases/{graph['case']}/review")
    assert page.status_code == 200
    body = response.json()
    assert type(body) is dict
    return response.status_code, body, page.text
