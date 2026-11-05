"""RX-52: recording→trial→review→approve; reject healed/missing/wrong version; offline OK."""

from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import subprocess
from pathlib import Path
from uuid import UUID, uuid4

import httpx

from aiqa.api.app import create_app
from aiqa.config import load_settings
from aiqa.domain.projects import bind_store, create_project
from aiqa.recording.review_manifest import review_offline_gate
from aiqa.store.database import migrate_store
from aiqa.store.models import Actor, ProjectCreate
from ux_support import session

_BROWSERS = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
)


def test_rx_52_trial_review_approve_offline_and_rejects(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    app = create_app(
        load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)})
    )
    owner = Actor(uuid4(), None, True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("시범승인", "rx52", "검토", "android"))
    store.close()
    project_id = str(project.project_id)
    database = root / "db" / "aiqa.sqlite"
    graph = _graph(database, project_id, str(owner.actor_id))

    with sqlite3.connect(database) as connection:
        offline = review_offline_gate(connection, project.project_id, UUID(graph["case"]))
        assert offline.allowed is True
        assert offline.worker_online is False

    observed = asyncio.run(_flow(app, project_id, graph))

    with sqlite3.connect(database) as connection:
        before = connection.execute(
            "SELECT current_approval_id FROM automation_cases WHERE case_id = ?",
            (graph["case"],),
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO case_versions (
                project_id, case_id, version_id, revision, creation_kind, parent_version_id, base_version_id,
                is_branch, definition_json, settings_json, recorded_steps_json, content_hash, verification_digest,
                source_manifest_id, replay_package_id, readiness_json, actor_id, reason, created_at
            ) VALUES (?, ?, ?, 3, 'rerecorded', ?, ?, 0, '{}', '{}', '[]', 'new-hash', 'digest',
                NULL, NULL, '{}', ?, 'rerecord', '2026-11-05T01:00:00+00:00')
            """,
            (
                project_id,
                graph["case"],
                graph["rerecord_version"],
                graph["version"],
                graph["version"],
                graph["actor"],
            ),
        )
        preserved = connection.execute(
            "SELECT current_approval_id FROM automation_cases WHERE case_id = ?",
            (graph["case"],),
        ).fetchone()[0]
        version_count = connection.execute(
            "SELECT COUNT(*) FROM case_versions WHERE case_id = ?",
            (graph["case"],),
        ).fetchone()[0]
        connection.commit()

    browser_ok = _browser_shot(tmp_path, observed["review_html"])
    assert observed["healed_status"] >= 400
    assert observed["wrong_version_status"] >= 400
    assert observed["missing_status"] >= 400
    assert observed["review_status"] == 201
    assert observed["approve_status"] == 201
    assert observed["page_has_offline_gate"] is True
    assert observed["recording_has_review_link"] is True
    assert before == observed["approval_id"]
    assert preserved == observed["approval_id"]
    assert version_count == 3
    assert browser_ok is True


async def _flow(app: object, project_id: str, graph: dict[str, str]) -> dict[str, object]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        headers = await session(client, project_id)
        good_entries = [
            _entry("REC", graph["recording"], graph["rec_attempt"], "A001", graph["rec_artifact"], "hash-rec"),
            _entry("ITEM", graph["trial"], graph["item_attempt"], "A001", graph["item_artifact"], "hash-item"),
        ]
        healed = await client.post(
            f"/api/v1/case-versions/{graph['version']}/review-requests",
            json={"trial_case_run_id": graph["healed"], "entries": good_entries},
            headers={**headers, "Idempotency-Key": "rx52-healed"},
        )
        wrong = await client.post(
            f"/api/v1/case-versions/{graph['other_version']}/review-requests",
            json={"trial_case_run_id": graph["trial"], "entries": good_entries},
            headers={**headers, "Idempotency-Key": "rx52-wrong"},
        )
        missing = await client.post(
            f"/api/v1/case-versions/{graph['version']}/review-requests",
            json={"trial_case_run_id": graph["trial"], "entries": []},
            headers={**headers, "Idempotency-Key": "rx52-missing"},
        )
        created = await client.post(
            f"/api/v1/case-versions/{graph['version']}/review-requests",
            json={"trial_case_run_id": graph["trial"], "entries": good_entries},
            headers={**headers, "Idempotency-Key": "rx52-review"},
        )
        assert created.status_code == 201, created.text
        body = created.json()
        review_id = body["id"]
        evidence_hash = body["evidence_set_hash"]
        page = await client.get(
            f"/ui/projects/{project_id}/cases/{graph['case']}/review",
            headers=headers,
        )
        entry_ids = tuple(dict.fromkeys(re.findall(r'data-entry="([0-9a-f-]{36})"', page.text)))
        assert entry_ids, page.text[:800]
        for entry_id in entry_ids:
            opinion = await client.post(
                f"/api/v1/case-versions/{graph['version']}/action-reviews",
                json={
                    "review_id": review_id,
                    "entry_key": entry_id,
                    "evidence_digest": evidence_hash,
                    "state": "reviewed",
                    "comment": "확인",
                },
                headers={**headers, "Idempotency-Key": f"rx52-op-{entry_id[:8]}"},
            )
            assert opinion.status_code in {200, 201}, opinion.text
        approved = await client.post(
            f"/api/v1/case-versions/{graph['version']}/approvals",
            json={
                "review_id": review_id,
                "version_hash": "version-hash",
                "evidence_set_hash": evidence_hash,
                "expected_current_approval_id": None,
                "reason": "이 버전을 기본 실행본으로 사용합니다.",
            },
            headers={**headers, "Idempotency-Key": "rx52-approve"},
        )
        assert approved.status_code == 201, approved.text
        recording = await client.get(
            f"/ui/projects/{project_id}/recordings/{graph['recording']}",
            headers=headers,
        )
        review_page = await client.get(
            f"/ui/projects/{project_id}/cases/{graph['case']}/review",
            headers=headers,
        )
        return {
            "healed_status": healed.status_code,
            "wrong_version_status": wrong.status_code,
            "missing_status": missing.status_code,
            "review_status": created.status_code,
            "approve_status": approved.status_code,
            "approval_id": approved.json()["approval_id"],
            "page_has_offline_gate": 'id="offline-review-gate"' in review_page.text
            and 'data-allowed="true"' in review_page.text
            and 'data-worker-online="false"' in review_page.text,
            "recording_has_review_link": 'id="recording-review-link"' in recording.text,
            "review_html": review_page.text,
        }


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


def _browser_shot(tmp_path: Path, html: str) -> bool:
    browser = next((path for path in _BROWSERS if path.exists()), None)
    if browser is None:
        return False
    page = tmp_path / "rx52.html"
    shot = tmp_path / "rx52.png"
    page.write_text(html, encoding="utf-8")
    completed = subprocess.run(
        [
            str(browser),
            "--headless=new",
            "--disable-gpu",
            f"--screenshot={shot}",
            page.resolve().as_uri(),
        ],
        check=False,
        capture_output=True,
        timeout=60,
    )
    return completed.returncode == 0 and shot.exists() and shot.stat().st_size > 1024


def _graph(database: Path, project_id: str, actor_id: str) -> dict[str, str]:
    ids = {
        "actor": actor_id,
        "case": str(uuid4()),
        "version": str(uuid4()),
        "other_version": str(uuid4()),
        "rerecord_version": str(uuid4()),
        "manifest": str(uuid4()),
        "other_manifest": str(uuid4()),
        "package": str(uuid4()),
        "other_package": str(uuid4()),
        "recording": str(uuid4()),
        "execution": str(uuid4()),
        "trial": str(uuid4()),
        "healed_execution": str(uuid4()),
        "healed": str(uuid4()),
        "rec_job": str(uuid4()),
        "item_job": str(uuid4()),
        "healed_job": str(uuid4()),
        "rec_attempt": str(uuid4()),
        "item_attempt": str(uuid4()),
        "healed_attempt": str(uuid4()),
        "rec_artifact": str(uuid4()),
        "item_artifact": str(uuid4()),
        "source_artifact": str(uuid4()),
    }
    stamp = "2026-11-05T00:00:00+00:00"
    package_hash = "sha256:" + ("ab" * 32)
    other_hash = "sha256:" + ("cd" * 32)
    limits = json.dumps(
        {
            "self_healing_enabled": False,
            "actor": 0,
            "replay_package_id": ids["package"],
            "replay_package_hash": package_hash,
        }
    )
    healed_limits = json.dumps(
        {
            "self_healing_enabled": True,
            "actor": 0,
            "replay_package_id": ids["package"],
            "replay_package_hash": package_hash,
        }
    )
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
        for version_id, revision, manifest_id, package_id, content_hash in (
            (ids["other_version"], 1, ids["manifest"], ids["other_package"], "other-hash"),
            (ids["version"], 2, ids["manifest"], ids["package"], "version-hash"),
        ):
            connection.execute(
                """
                INSERT INTO case_versions (
                    project_id, case_id, version_id, revision, creation_kind, parent_version_id, base_version_id,
                    is_branch, definition_json, settings_json, recorded_steps_json, content_hash, verification_digest,
                    source_manifest_id, replay_package_id, readiness_json, actor_id, reason, created_at
                ) VALUES (?, ?, ?, ?, 'recorded', NULL, NULL, 0, '{}', ?, '[]', ?, 'digest',
                    ?, ?, '{}', ?, 'recorded', ?)
                """,
                (
                    project_id,
                    ids["case"],
                    version_id,
                    revision,
                    json.dumps({"self_healing_enabled": False}),
                    content_hash,
                    manifest_id,
                    package_id,
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
            (project_id, ids["case"], ids["recording"], ids["version"]),
        )
        connection.execute(
            """
            INSERT INTO recording_manifests (
                project_id, case_id, recording_id, manifest_id, revision, kind, prior_manifest_id,
                input_version_hash, source_artifact_hashes, action_mapping, evidence_completeness,
                request_key, body_hash
            ) VALUES (?, ?, ?, ?, 1, 'original', NULL, 'version-hash', '[]', '{}', 'complete', 'rx52-manifest', 'manifest-hash')
            """,
            (project_id, ids["case"], ids["recording"], ids["manifest"]),
        )
        for package_id, version_id, manifest_id, body in (
            (ids["package"], ids["version"], ids["manifest"], package_hash),
            (ids["other_package"], ids["other_version"], ids["manifest"], other_hash),
        ):
            connection.execute(
                """
                INSERT INTO replay_packages (
                    project_id, package_id, case_id, case_version_id, ready, schema_version, source_manifest_id,
                    source_manifest_hash, raw_source_hash, approved_code_hash, runtime_ref, compiler_ref, lock_hash,
                    step_mapping_hash, body_hash
                ) VALUES (?, ?, ?, ?, 1, 'replay-package-v1', ?, 'manifest-hash', 'raw', 'plan', 'android', 'android-plan-v1',
                    'lock', 'mapping', ?)
                """,
                (project_id, package_id, ids["case"], version_id, manifest_id, body),
            )
            connection.execute(
                "INSERT INTO package_version_links (project_id, case_id, version_id, package_id) VALUES (?, ?, ?, ?)",
                (project_id, ids["case"], version_id, package_id),
            )
        for execution, run in ((ids["execution"], ids["trial"]), (ids["healed_execution"], ids["healed"])):
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
                INSERT INTO item_finalizations (
                    project_id, case_run_id, created_seq, finalized_seq, release_label, content_hash, core_result, denominator
                ) VALUES (?, ?, 1, 1, '', 'version-hash', 'PASS', 1)
                """,
                (project_id, run),
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
            (ids["healed_attempt"], ids["healed_job"]),
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
            (ids["healed_attempt"], "A001"),
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
            (ids["source_artifact"], ids["rec_attempt"], "A001"),
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
        for artifact, owner, kind, attempt, action, job, digest, role in (
            (ids["rec_artifact"], ids["recording"], "REC", ids["rec_attempt"], "A001", ids["rec_job"], "hash-rec", "before"),
            (ids["item_artifact"], ids["trial"], "ITEM", ids["item_attempt"], "A001", ids["item_job"], "hash-item", "before"),
            (ids["source_artifact"], ids["recording"], "REC", ids["rec_attempt"], "A001", ids["rec_job"], "hash-source", "source"),
        ):
            connection.execute(
                """
                INSERT INTO artifact_objects (
                    project_id, artifact_id, object_key, content_hash, byte_length, media_type, owner_id, status, acked,
                    owner_kind, attempt_id, action_id, check_id, role, job_id, generation
                ) VALUES (?, ?, ?, ?, 4, 'image/png', ?, 'ready', 1, ?, ?, ?, NULL, ?, ?, 1)
                """,
                (project_id, artifact, artifact, digest, owner, kind, attempt, action, role, job),
            )
        connection.execute(
            """
            INSERT INTO materialization_receipts (
                project_id, receipt_id, manifest_id, produced_version_id, body_hash
            ) VALUES (?, ?, ?, ?, 'mat-hash')
            """,
            (project_id, str(uuid4()), ids["manifest"], ids["version"]),
        )
        connection.commit()
    return ids
