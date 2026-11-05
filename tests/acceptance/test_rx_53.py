"""RX-53: suite revision pins approved snapshots; mid-edit preserves RUN; schedule mix."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import subprocess
from pathlib import Path
from uuid import UUID, uuid4

import httpx

from aiqa.api.app import create_app
from aiqa.config import load_settings
from aiqa.domain.execution_scheduler import CaseRunView, advance_execution
from aiqa.domain.projects import bind_store, create_project
from aiqa.store.database import migrate_store
from aiqa.store.models import Actor, ProjectCreate, Transaction
from ux_support import session
from worker_presence_support import seed_inventory, seed_presence

_BROWSERS = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
)


def test_rx_53_suite_regression_pins_and_schedule(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    app = create_app(
        load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)})
    )
    owner = Actor(uuid4(), None, True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("묶음회귀", "rx53", "회귀", "web"))
    store.close()
    project_id = str(project.project_id)
    database = root / "db" / "aiqa.sqlite"
    graph = _graph(database, project_id, str(owner.actor_id))

    observed = asyncio.run(_flow(app, project_id, graph, owner.actor_id, project.project_id, database, tmp_path))

    with sqlite3.connect(database) as connection:
        run = connection.execute(
            """
            SELECT suite_version_id, source, purpose FROM executions WHERE execution_id = ?
            """,
            (observed["execution_id"],),
        ).fetchone()
        pins = connection.execute(
            """
            SELECT case_runs.case_version_id, jobs.limits, item_finalizations.core_result
            FROM case_runs
            JOIN jobs
              ON jobs.project_id = case_runs.project_id AND jobs.case_run_id = case_runs.case_run_id
            LEFT JOIN item_finalizations
              ON item_finalizations.project_id = case_runs.project_id
             AND item_finalizations.case_run_id = case_runs.case_run_id
            WHERE case_runs.execution_id = ?
            ORDER BY case_runs.rowid
            """,
            (observed["execution_id"],),
        ).fetchall()
        edited = connection.execute(
            "SELECT COUNT(*) FROM suite_versions WHERE suite_id = ?",
            (graph["suite_id"],),
        ).fetchone()[0]

    assert run is not None
    assert run[0] == graph["suite_version_id"]
    assert run[1] == "suite" and run[2] == "regression"
    assert [row[0] for row in pins] == [
        graph["version_a"],
        graph["version_b"],
        graph["version_a"],
    ]
    assert [row[2] for row in pins] == ["PASS", "FAIL", "CANCELLED"]
    for row, approval in zip(pins, (graph["approval_a"], graph["approval_b"], graph["approval_a"]), strict=True):
        limits = json.loads(str(row[1]))
        assert limits["approval_id"] == approval
        assert limits["failure_policy"] == "continue"
        assert limits["execution_snapshot"]["case_version_id"] == row[0]
        assert limits["execution_snapshot"]["approval_id"] == approval
    assert edited == 2
    assert observed["preview_ready"] is True
    assert observed["enqueue_status"] == 201
    assert observed["page_has_suite"] is True
    assert observed["page_has_verdicts"] is True
    assert observed["rerun_status"] in {200, 201}
    assert observed["rerun_ready"] is True
    assert observed["browser_ok"] is True


async def _flow(
    app: object,
    project_id: str,
    graph: dict[str, str],
    actor_id: UUID,
    project_uuid: UUID,
    database: Path,
    tmp_path: Path,
) -> dict[str, object]:
    transport = httpx.ASGITransport(app=app)
    origin = "http://127.0.0.1"
    async with httpx.AsyncClient(transport=transport, base_url=origin) as client:
        headers = await session(client, project_id)
        headers["Idempotency-Key"] = "rx53-preview"
        preview = await client.post(
            f"/api/v1/projects/{project_id}/execution-previews",
            json=_preview_body(graph),
            headers=headers,
        )
        assert preview.status_code == 200, preview.text
        body = preview.json()
        headers["Idempotency-Key"] = "rx53-enqueue"
        enqueued = await client.post(
            f"/api/v1/projects/{project_id}/executions",
            json=_enqueue_body(graph, body),
            headers=headers,
        )
        assert enqueued.status_code == 201, enqueued.text
        receipt = enqueued.json()
        execution_id = str(receipt["execution_id"])
        item_ids = [str(item) for item in receipt["item_ids"]]

        _mid_edit_suite(database, graph)

        store = app.state.open_store()
        try:
            with store.transaction() as connection:
                tx = Transaction(connection)
                first = advance_execution(
                    tx, project_uuid, UUID(execution_id), CaseRunView(UUID(item_ids[0]), "PASS", "unchanged")
                )
                second = advance_execution(
                    tx, project_uuid, UUID(execution_id), CaseRunView(UUID(item_ids[1]), "FAIL", "unchanged")
                )
                third = advance_execution(
                    tx,
                    project_uuid,
                    UUID(execution_id),
                    CaseRunView(UUID(item_ids[2]), "CANCELLED", "unchanged", True),
                )
        finally:
            store.close()
        _ = actor_id

        page = await client.get(f"/ui/projects/{project_id}/executions/{execution_id}")
        assert page.status_code == 200, page.text
        html = page.text
        headers["Idempotency-Key"] = "rx53-rerun"
        rerun = await client.post(
            f"/api/v1/executions/{execution_id}/reruns",
            params={"project_id": project_id},
            json={"reason": "실패 항목 재확인", "scope": "failed"},
            headers=headers,
        )
        browser_ok = _browser_shot(tmp_path, html)
        return {
            "execution_id": execution_id,
            "preview_ready": body["ready"] is True and body["proposed_n"] == 3,
            "enqueue_status": enqueued.status_code,
            "page_has_suite": graph["suite_hash"] in html and "묶음" in html and "개정" in html,
            "page_has_verdicts": "PASS" in html and "FAIL" in html and "CANCELLED" in html,
            "page_has_pins": graph["version_a"] in html and graph["approval_a"] in html,
            "next_after_pass": None if first.next_case_run_id is None else str(first.next_case_run_id),
            "remaining_after_fail": list(second.remaining),
            "parent_terminal": third.parent_terminal is True,
            "rerun_status": rerun.status_code,
            "rerun_ready": rerun.status_code in {200, 201} and rerun.json().get("ready") is True,
            "browser_ok": browser_ok,
            "html": html,
        }


def _preview_body(graph: dict[str, str]) -> dict[str, object]:
    return {
        "name": "묶음 회귀",
        "purpose": "regression",
        "source": "suite",
        "failure_policy": "continue",
        "self_healing_enabled": False,
        "exclusions": [],
        "selection": {"suite_version_id": graph["suite_version_id"]},
    }


def _enqueue_body(graph: dict[str, str], preview: dict[str, object]) -> dict[str, object]:
    return {
        "name": "묶음 회귀",
        "purpose": "regression",
        "source": "suite",
        "suite_version_id": graph["suite_version_id"],
        "failure_policy": "continue",
        "self_healing_enabled": False,
        "preview_hash": preview["preview_hash"],
        "exclusions": [],
        "items": preview["resolved_items"],
    }


def _mid_edit_suite(database: Path, graph: dict[str, str]) -> None:
    new_version = str(uuid4())
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO suite_versions (project_id, suite_id, suite_version_id, content_hash)
            VALUES (?, ?, ?, 'suite-hash-edited')
            """,
            (graph["project_id"], graph["suite_id"], new_version),
        )
        connection.execute(
            """
            INSERT INTO suite_entries (
                project_id, suite_version_id, entry_id, position, case_id, case_version_id,
                approval_id, data_name, environment_revision_id, reset_policy, failure_policy,
                resource_id, target_kind
            ) VALUES (?, ?, 'edited-a', 1, ?, ?, ?, 'data-a', ?, 'none', 'continue', ?, 'web')
            """,
            (
                graph["project_id"],
                new_version,
                graph["case_a"],
                graph["version_b"],
                graph["approval_b"],
                graph["environment_id"],
                graph["resource_id"],
            ),
        )
        connection.commit()


def _browser_shot(tmp_path: Path, html: str) -> bool:
    browser = next((path for path in _BROWSERS if path.exists()), None)
    if browser is None:
        return False
    page = tmp_path / "rx53.html"
    shot = tmp_path / "rx53.png"
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
        "project_id": project_id,
        "case_a": str(uuid4()),
        "case_b": str(uuid4()),
        "version_a": str(uuid4()),
        "version_b": str(uuid4()),
        "approval_a": str(uuid4()),
        "approval_b": str(uuid4()),
        "package_a": str(uuid4()),
        "package_b": str(uuid4()),
        "manifest_a": str(uuid4()),
        "manifest_b": str(uuid4()),
        "recording_a": str(uuid4()),
        "recording_b": str(uuid4()),
        "environment_id": str(uuid4()),
        "resource_id": str(uuid4()),
        "suite_id": str(uuid4()),
        "suite_version_id": str(uuid4()),
        "suite_hash": "suite-hash-rx53",
        "worker": "worker-rx53",
    }
    stamp = "2026-11-05T00:00:00+00:00"
    definition = json.dumps(
        {"final_expected": [{"id": "exp-1", "kind": "text", "expected": "보임"}]},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    settings = json.dumps(
        {
            "target_kind": "web",
            "build_id": "build-rx53",
            "limits": {"timeout_seconds": 600, "budget": "2.00", "currency": "USD"},
            "self_healing_enabled": False,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "INSERT INTO app_builds (project_id, build_id, content_hash) VALUES (?, 'build-rx53', 'build-hash-rx53')",
            (project_id,),
        )
        connection.execute(
            """
            INSERT INTO worker_enrollments (enrollment_id, worker_id, project_id, created_at)
            VALUES ('enroll-rx53', ?, ?, ?)
            """,
            (ids["worker"], project_id, stamp),
        )
        seed_presence(connection, project_id, ids["worker"])
        connection.execute(
            "INSERT INTO physical_resource_keys (physical_key_id, worker_id, native_id) VALUES (?, ?, 'native-rx53')",
            (ids["resource_id"], ids["worker"]),
        )
        connection.execute(
            "INSERT INTO resource_aliases (project_id, physical_key_id, display_name, target_kind) VALUES (?, ?, '브라우저', 'web')",
            (project_id, ids["resource_id"]),
        )
        seed_inventory(connection, ids["resource_id"])
        connection.execute(
            """
            INSERT INTO environments (project_id, environment_id, name, next_revision, latest_revision_id)
            VALUES (?, 'env-rx53', '로컬', 2, ?)
            """,
            (project_id, ids["environment_id"]),
        )
        connection.execute(
            """
            INSERT INTO environment_revisions (
                project_id, environment_id, revision_id, revision, body_json, content_hash, actor_id, created_at
            ) VALUES (?, 'env-rx53', ?, 1, '{}', 'env-hash-rx53', ?, ?)
            """,
            (project_id, ids["environment_id"], actor_id, stamp),
        )
        for label, case_id, version_id, approval_id, package_id, manifest_id, recording_id, content_hash in (
            (
                "로그인A",
                ids["case_a"],
                ids["version_a"],
                ids["approval_a"],
                ids["package_a"],
                ids["manifest_a"],
                ids["recording_a"],
                "version-hash-a",
            ),
            (
                "로그인B",
                ids["case_b"],
                ids["version_b"],
                ids["approval_b"],
                ids["package_b"],
                ids["manifest_b"],
                ids["recording_b"],
                "version-hash-b",
            ),
        ):
            connection.execute(
                """
                INSERT INTO automation_cases (
                    project_id, case_id, name, folder_id, tc_reference, next_revision,
                    latest_draft_version_id, current_approval_id, lock_version, archived_at
                ) VALUES (?, ?, ?, NULL, NULL, 2, NULL, ?, 0, NULL)
                """,
                (project_id, case_id, label, approval_id),
            )
            connection.execute(
                """
                INSERT INTO case_versions (
                    project_id, case_id, version_id, revision, creation_kind, parent_version_id, base_version_id,
                    is_branch, definition_json, settings_json, recorded_steps_json, content_hash, verification_digest,
                    source_manifest_id, replay_package_id, readiness_json, actor_id, reason, created_at
                ) VALUES (?, ?, ?, 1, 'recorded', NULL, NULL, 0, ?, ?, '[]', ?, 'digest',
                    ?, ?, '{}', ?, 'recorded', ?)
                """,
                (
                    project_id,
                    case_id,
                    version_id,
                    definition,
                    settings,
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
                    project_id, case_id, recording_id, creation_kind, input_case_version_id,
                    storage_status, stop_status, completion_status, evidence_status
                ) VALUES (?, ?, ?, 'recorded', ?, 'stored', 'stopped', 'completed', 'complete')
                """,
                (project_id, case_id, recording_id, version_id),
            )
            connection.execute(
                """
                INSERT INTO recording_manifests (
                    project_id, case_id, recording_id, manifest_id, revision, kind,
                    input_version_hash, source_artifact_hashes, action_mapping, evidence_completeness,
                    request_key, body_hash
                ) VALUES (?, ?, ?, ?, 1, 'original', ?, '[]', '{}', 'complete', ?, 'manifest-hash')
                """,
                (project_id, case_id, recording_id, manifest_id, content_hash, manifest_id),
            )
            connection.execute(
                """
                INSERT INTO replay_packages (
                    project_id, package_id, case_id, case_version_id, ready, schema_version,
                    source_manifest_id, source_manifest_hash, raw_source_hash, approved_code_hash,
                    runtime_ref, compiler_ref, lock_hash, step_mapping_hash, body_hash
                ) VALUES (?, ?, ?, ?, 1, 'replay-package-v1', ?, 'manifest-hash', 'raw', 'code',
                    'web', 'web-ipc-subset', 'lock', 'map', ?)
                """,
                (project_id, package_id, case_id, version_id, manifest_id, f"pkg-{label}"),
            )
            connection.execute(
                "INSERT INTO package_version_links (project_id, case_id, version_id, package_id) VALUES (?, ?, ?, ?)",
                (project_id, case_id, version_id, package_id),
            )
            review_id = str(uuid4())
            connection.execute(
                """
                INSERT INTO reviews (
                    project_id, review_id, case_id, case_version_id, version_hash, evidence_set_hash, created_commit_seq
                ) VALUES (?, ?, ?, ?, ?, 'evidence', 1)
                """,
                (project_id, review_id, case_id, version_id, content_hash),
            )
            connection.execute(
                """
                INSERT INTO approval_events (
                    project_id, approval_id, case_id, case_version_id, review_id, event_kind,
                    prior_approval_id, version_hash, evidence_set_hash, reason
                ) VALUES (?, ?, ?, ?, ?, 'approved', NULL, ?, 'evidence', '승인')
                """,
                (project_id, approval_id, case_id, version_id, review_id, content_hash),
            )
        connection.execute(
            "INSERT INTO suites (project_id, suite_id, name) VALUES (?, ?, '회귀 묶음')",
            (project_id, ids["suite_id"]),
        )
        connection.execute(
            """
            INSERT INTO suite_versions (project_id, suite_id, suite_version_id, content_hash)
            VALUES (?, ?, ?, ?)
            """,
            (project_id, ids["suite_id"], ids["suite_version_id"], ids["suite_hash"]),
        )
        for position, entry_id, case_id, version_id, approval_id, data_name in (
            (1, "suite-a", ids["case_a"], ids["version_a"], ids["approval_a"], "data-a"),
            (2, "suite-b", ids["case_b"], ids["version_b"], ids["approval_b"], "data-b"),
            (3, "suite-a-again", ids["case_a"], ids["version_a"], ids["approval_a"], "data-a2"),
        ):
            connection.execute(
                """
                INSERT INTO suite_entries (
                    project_id, suite_version_id, entry_id, position, case_id, case_version_id,
                    approval_id, data_name, environment_revision_id, reset_policy, failure_policy,
                    resource_id, target_kind
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'none', 'continue', ?, 'web')
                """,
                (
                    project_id,
                    ids["suite_version_id"],
                    entry_id,
                    position,
                    case_id,
                    version_id,
                    approval_id,
                    data_name,
                    ids["environment_id"],
                    ids["resource_id"],
                ),
            )
        connection.commit()
    return ids
