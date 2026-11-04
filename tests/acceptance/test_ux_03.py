"""UX-03: suite entry editor UI — add/remove/order, save CAS, upgrade decide."""

from __future__ import annotations

import asyncio
import sqlite3
from html.parser import HTMLParser
from pathlib import Path
from uuid import uuid4

import httpx
from ux_support import session


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.has_script = False
        self.has_form = False
        self.has_add = False
        self.has_save = False
        self.entry_rows = 0
        self.approved = 0
        self.upgrade = False
        self.names: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and "suite_editor.js" in attrs.get("src", ""):
            self.has_script = True
        if tag == "form" and attrs.get("id") == "suite-entries":
            self.has_form = True
        if tag == "button" and "data-add-case" in attrs:
            self.has_add = True
            self.approved += 1
        if tag == "input" and "data-save-button" in attrs:
            self.has_save = True
        if tag == "li" and "data-entry-row" in attrs:
            self.entry_rows += 1
        if tag == "section" and "data-upgrade-panel" in attrs:
            self.upgrade = True
        if tag in {"input", "select", "textarea"} and attrs.get("name"):
            self.names.append(attrs["name"])


def test_suite_entry_editor_ui_flows(tmp_path: Path) -> None:
    from aiqa.api.app import create_app
    from aiqa.config import load_settings
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
        project = create_project(owner, ProjectCreate("UX03", "ux03", "", "web"))
    store.close()
    project_id = str(project.project_id)
    database = root / "db" / "aiqa.sqlite"
    asyncio.run(_exercise(app, project_id, database, str(owner.actor_id)))


async def _exercise(app, project_id: str, database: Path, actor_id: str) -> None:
    origin = "http://127.0.0.1"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        headers = await session(client, project_id)
        created = await client.post(
            f"/api/v1/projects/{project_id}/suites",
            json={
                "name": "편집 묶음",
                "description": "entry",
                "target_kind": "web",
                "owner_name": "담당",
                "classification": "회귀",
            },
            headers={**headers, "Idempotency-Key": "ux03-create"},
        )
        assert created.status_code == 201, created.text
        suite_id = created.json()["suite_id"]
        head = created.json()["version_id"]
        seed = _seed(database, project_id, actor_id)

        empty_page = await client.get(f"/ui/projects/{project_id}/suites/{suite_id}")
        assert empty_page.status_code == 200
        parsed = _Page()
        parsed.feed(empty_page.text)
        assert parsed.has_script and parsed.has_form and parsed.has_save
        assert parsed.has_add and parsed.approved >= 1
        assert "순서를 바꿀 수 있습니다" in empty_page.text
        assert "이전 구성은 그대로입니다" in empty_page.text
        assert "승인된 검증 로그인 검증" in empty_page.text
        assert "expected_version_id" in parsed.names
        assert "구성이 비어 있습니다" in empty_page.text

        entries = [
            {
                "entry_id": "entry-a",
                "case_id": seed["case_id"],
                "case_version_id": seed["version_v2"],
                "approval_id": seed["approval_v2"],
                "data_name": "행-가",
                "environment_revision_id": seed["environment"],
                "reset_policy": "keep",
                "failure_policy": "continue",
                "resource_id": "key-web-ux03",
                "target_kind": "web",
            },
            {
                "entry_id": "entry-b",
                "case_id": seed["case_id"],
                "case_version_id": seed["version_v2"],
                "approval_id": seed["approval_v2"],
                "data_name": "행-나",
                "environment_revision_id": seed["environment"],
                "reset_policy": "reset",
                "failure_policy": "stop",
                "resource_id": "key-web-ux03",
                "target_kind": "web",
            },
        ]
        saved = await client.post(
            f"/api/v1/suites/{suite_id}/versions",
            json={"project_id": project_id, "expected_version_id": head, "entries": entries},
            headers={**headers, "Idempotency-Key": "ux03-save"},
        )
        assert saved.status_code == 201, saved.text
        first_version = saved.json()["suite_version_id"]
        assert first_version != head
        assert {item["entry_id"] for item in saved.json()["entries"]} == {"entry-a", "entry-b"}

        # Stale expected_version → 409, previous revision rows unchanged
        before = _entry_rows(database, first_version)
        stale = await client.post(
            f"/api/v1/suites/{suite_id}/versions",
            json={
                "project_id": project_id,
                "expected_version_id": head,
                "entries": [{**entries[0], "data_name": "행-바뀜"}],
            },
            headers={**headers, "Idempotency-Key": "ux03-stale"},
        )
        assert stale.status_code == 409
        assert _entry_rows(database, first_version) == before

        reordered = [entries[1], entries[0]]
        second = await client.post(
            f"/api/v1/suites/{suite_id}/versions",
            json={
                "project_id": project_id,
                "expected_version_id": first_version,
                "entries": reordered,
            },
            headers={**headers, "Idempotency-Key": "ux03-reorder"},
        )
        assert second.status_code == 201, second.text
        assert second.json()["entries"][0]["entry_id"] == "entry-b"
        assert _entry_rows(database, first_version) == before

        # Promote newer approval so upgrade panel appears
        _promote_approval(database, project_id, seed)
        page = await client.get(f"/ui/projects/{project_id}/suites/{suite_id}")
        assert page.status_code == 200
        filled = _Page()
        filled.feed(page.text)
        assert filled.entry_rows == 2
        assert filled.upgrade is True
        assert "영향 항목" in page.text
        for field in (
            "entry_id",
            "data_name",
            "environment_revision_id",
            "reset_policy",
            "failure_policy",
            "resource_id",
            "target_kind",
        ):
            assert field in filled.names

        current_head = second.json()["suite_version_id"]
        rejected = await client.post(
            f"/api/v1/suites/{suite_id}/versions",
            json={
                "project_id": project_id,
                "decision": "reject",
                "expected_version_id": current_head,
                "entry_ids": [],
            },
            headers={**headers, "Idempotency-Key": "ux03-reject"},
        )
        assert rejected.status_code == 200, rejected.text
        assert rejected.json()["suite_version_id"] == current_head

        accepted = await client.post(
            f"/api/v1/suites/{suite_id}/versions",
            json={
                "project_id": project_id,
                "decision": "accept",
                "expected_version_id": current_head,
                "entry_ids": ["entry-a"],
            },
            headers={**headers, "Idempotency-Key": "ux03-accept"},
        )
        assert accepted.status_code == 201, accepted.text
        moved = [item for item in accepted.json()["entries"] if item["entry_id"] == "entry-a"]
        kept = [item for item in accepted.json()["entries"] if item["entry_id"] == "entry-b"]
        assert moved and moved[0]["case_version_id"] == seed["version_v4"]
        assert kept and kept[0]["case_version_id"] == seed["version_v2"]
        assert accepted.json()["suite_version_id"] != current_head
        assert _entry_rows(database, current_head)[0] is not None


def _entry_rows(database: Path, version_id: str) -> tuple[object, ...]:
    with sqlite3.connect(database) as connection:
        version = connection.execute(
            "SELECT content_hash FROM suite_versions WHERE suite_version_id = ?",
            (version_id,),
        ).fetchone()
        entries = connection.execute(
            """
            SELECT entry_id, position, case_version_id, data_name
            FROM suite_entries WHERE suite_version_id = ?
            ORDER BY position, entry_id
            """,
            (version_id,),
        ).fetchall()
    return (version, tuple(entries))


def _seed(database: Path, project_id: str, actor_id: str) -> dict[str, str]:
    case_id = str(uuid4())
    version_v2 = str(uuid4())
    version_v4 = str(uuid4())
    approval_v2 = str(uuid4())
    approval_v4 = str(uuid4())
    review_v2 = str(uuid4())
    review_v4 = str(uuid4())
    environment_id = str(uuid4())
    environment = str(uuid4())
    stamp = "2026-11-03T12:00:00+00:00"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO automation_cases (
                project_id, case_id, name, folder_id, tc_reference, next_revision,
                latest_draft_version_id, current_approval_id, lock_version, archived_at
            ) VALUES (?, ?, '로그인 검증', NULL, NULL, 5, NULL, NULL, 0, NULL)
            """,
            (project_id, case_id),
        )
        for version_id, revision, definition in (
            (version_v2, 2, '{"goal":"login-v2"}'),
            (version_v4, 4, '{"goal":"login-v4"}'),
        ):
            connection.execute(
                """
                INSERT INTO case_versions (
                    project_id, case_id, version_id, revision, creation_kind, parent_version_id, base_version_id,
                    is_branch, definition_json, settings_json, recorded_steps_json, content_hash, verification_digest,
                    source_manifest_id, replay_package_id, readiness_json, actor_id, reason, created_at
                ) VALUES (?, ?, ?, ?, 'recorded', NULL, NULL, 0, ?, '{"target":"web"}', '[]', 'hash', 'digest',
                    NULL, NULL, '{}', ?, 'recorded', ?)
                """,
                (project_id, case_id, version_id, revision, definition, actor_id, stamp),
            )
        for review_id, version_id, approval_id in (
            (review_v2, version_v2, approval_v2),
            (review_v4, version_v4, approval_v4),
        ):
            connection.execute(
                """
                INSERT INTO reviews (
                    project_id, review_id, case_id, case_version_id, version_hash,
                    source_manifest_id, trial_case_run_id, evidence_set_hash,
                    expected_current_approval_id, created_commit_seq
                ) VALUES (?, ?, ?, ?, 'version-hash', NULL, NULL, 'evidence-hash', NULL, 1)
                """,
                (project_id, review_id, case_id, version_id),
            )
            connection.execute(
                """
                INSERT INTO approval_events (
                    project_id, approval_id, case_id, case_version_id, review_id, event_kind,
                    prior_approval_id, version_hash, evidence_set_hash, reason
                ) VALUES (?, ?, ?, ?, ?, 'approved', NULL, 'version-hash', 'evidence-hash', '승인')
                """,
                (project_id, approval_id, case_id, version_id, review_id),
            )
        connection.execute(
            "UPDATE automation_cases SET current_approval_id = ? WHERE project_id = ? AND case_id = ?",
            (approval_v2, project_id, case_id),
        )
        connection.execute(
            """
            INSERT INTO environments (project_id, environment_id, name, next_revision, latest_revision_id)
            VALUES (?, ?, '기본 환경', 2, ?)
            """,
            (project_id, environment_id, environment),
        )
        connection.execute(
            """
            INSERT INTO environment_revisions (
                project_id, environment_id, revision_id, revision, body_json, content_hash, actor_id, created_at
            ) VALUES (?, ?, ?, 1, '{}', 'env-hash', ?, ?)
            """,
            (project_id, environment_id, environment, actor_id, stamp),
        )
        connection.execute(
            "INSERT INTO worker_enrollments (enrollment_id, worker_id, project_id, created_at) VALUES ('enroll-ux03', 'worker-ux03', ?, ?)",
            (project_id, stamp),
        )
        connection.execute(
            "INSERT INTO physical_resource_keys (physical_key_id, worker_id, native_id) VALUES ('key-web-ux03', 'worker-ux03', 'native-web')"
        )
        connection.execute(
            "INSERT INTO resource_aliases (project_id, physical_key_id, display_name, target_kind) VALUES (?, 'key-web-ux03', '웹 자원', 'web')",
            (project_id,),
        )
        connection.commit()
    return {
        "case_id": case_id,
        "version_v2": version_v2,
        "version_v4": version_v4,
        "approval_v2": approval_v2,
        "approval_v4": approval_v4,
        "environment": environment,
    }


def _promote_approval(database: Path, project_id: str, seed: dict[str, str]) -> None:
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE automation_cases SET current_approval_id = ? WHERE project_id = ? AND case_id = ?",
            (seed["approval_v4"], project_id, seed["case_id"]),
        )
        connection.commit()
