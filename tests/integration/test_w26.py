"""Retention windows leave identity, hash, and past statistics."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

from aiqa.domain.projects import bind_store, create_project
from aiqa.store.models import Actor, ProjectCreate


def test_w26_01(tmp_path: Path) -> None:
    import asyncio

    from aiqa.api.app import create_app
    from aiqa.config import load_settings
    from aiqa.store.database import migrate_store
    from aiqa.store.retention import RetentionPolicy, RetentionSubject, UtcInstant, apply_retention, plan_retention

    now = datetime(2026, 11, 1, tzinfo=timezone.utc)
    root = tmp_path / "runtime"
    app = create_app(load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}))
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("보관", "w2601", "retention", "web"))
    project_id = str(project.project_id)
    artifact_id = str(uuid4())
    original_hash = "sha256:kept-detail"
    final_hash = "sha256:kept-final"
    seeded = _seed(root, project_id, str(owner.actor_id), artifact_id, original_hash, final_hash, now)
    policy = RetentionPolicy(
        (
            RetentionSubject("core_fact", seeded["run"], _ago(now, days=120), final_hash),
            RetentionSubject("approval", seeded["approval"], _ago(now, days=120), "sha256:approval"),
            RetentionSubject("manifest", seeded["manifest"], _ago(now, days=120), "sha256:manifest"),
            RetentionSubject("lineage", seeded["lineage"], _ago(now, days=120), "sha256:lineage"),
            RetentionSubject("content_hash", seeded["event"], _ago(now, days=120), original_hash),
            RetentionSubject("ledger", seeded["usage"], _ago(now, days=120), "sha256:ledger"),
            RetentionSubject("detail", seeded["event"], _ago(now, days=90), original_hash),
            RetentionSubject("detail", seeded["fresh_event"], _ago(now, days=90) + timedelta(seconds=1), "sha256:fresh"),
            RetentionSubject("png", artifact_id, _ago(now, days=30), "sha256:png", path=seeded["png"]),
            RetentionSubject("png", seeded["young_png"], _ago(now, days=30) + timedelta(seconds=1), "sha256:young", path=seeded["young_path"]),
            RetentionSubject("png", seeded["pinned"], _ago(now, days=40), "sha256:pinned", path=seeded["pinned_path"], protected=True),
            RetentionSubject("acked_spool", seeded["acked"], _ago(now, days=7), "sha256:acked", path=seeded["acked_path"], acked=True),
            RetentionSubject("unacked_spool", seeded["unacked"], _ago(now, days=8), "sha256:unacked", path=seeded["unacked_path"], acked=False),
            RetentionSubject("debug", seeded["debug"], _ago(now, hours=24), "sha256:debug", path=seeded["debug_path"]),
            RetentionSubject("debug", seeded["fresh_log"], _ago(now, hours=24) + timedelta(seconds=1), "sha256:log", path=seeded["log_path"]),
        )
    )
    plan = plan_retention(policy, UtcInstant(now))
    with sqlite3.connect(root / "db" / "aiqa.sqlite") as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        apply_retention(connection, project.project_id, plan, root / "artifacts", root / "spool", now)
        detail = connection.execute(
            "SELECT payload_hash, detail_payload, minimum_facts FROM attempt_events WHERE event_id = ?",
            (seeded["event"],),
        ).fetchone()
        fresh = connection.execute(
            "SELECT detail_payload FROM attempt_events WHERE event_id = ?",
            (seeded["fresh_event"],),
        ).fetchone()
        final = connection.execute(
            "SELECT content_hash FROM item_finalizations WHERE case_run_id = ?",
            (seeded["run"],),
        ).fetchone()
        usage = connection.execute(
            "SELECT amount FROM usage_adjustments WHERE adjustment_id = ?",
            (seeded["usage"],),
        ).fetchone()
        tombstone = connection.execute(
            "SELECT content_hash FROM retention_tombstones WHERE subject_id = ?",
            (seeded["event"],),
        ).fetchone()
    store.close()
    page = asyncio.run(_retention_page(app, project_id, artifact_id))
    unacked_path = root / "spool" / seeded["unacked_path"]
    observed = {
        "core_facts_deleted": plan.core_facts_deleted,
        "expired_has_tombstone": plan.expired_has_tombstone and tombstone is not None and tombstone[0] == original_hash,
        "unacked_spool_deleted": 0 if unacked_path.is_file() else 1,
        "old_stats_available": plan.old_stats_available and final is not None and final[0] == final_hash and usage[0] == "1.00",
    }
    assert detail == (original_hash, None, "최소 사실")
    assert fresh[0] == "아직 상세"
    assert not (root / "artifacts" / seeded["png"]).exists()
    assert (root / "artifacts" / seeded["young_path"]).is_file()
    assert (root / "artifacts" / seeded["pinned_path"]).is_file()
    assert page["tombstone"] is True and page["windows"]["detail_days"] == 90 and page["windows"]["file_days"] == 30
    assert observed == {
        "core_facts_deleted": 0,
        "expired_has_tombstone": True,
        "unacked_spool_deleted": 0,
        "old_stats_available": True,
    }


def _ago(now: datetime, days: int = 0, hours: int = 0) -> datetime:
    return now - timedelta(days=days, hours=hours)


def _seed(
    root: Path,
    project_id: str,
    actor_id: str,
    artifact_id: str,
    original_hash: str,
    final_hash: str,
    now: datetime,
) -> dict[str, str]:
    execution_id, run_id, case_id, version_id, job_id, attempt_id = (str(uuid4()) for _ in range(6))
    event_id, fresh_event = str(uuid4()), str(uuid4())
    usage_id = str(uuid4())
    stamp = now.isoformat()
    paths = {
        "png": f"{project_id}/{artifact_id}.png",
        "young_path": f"{project_id}/young.png",
        "pinned_path": f"{project_id}/pinned.png",
        "acked_path": "acked/item.log",
        "unacked_path": "open/item.log",
        "debug_path": "debug/note.txt",
        "log_path": "debug/fresh.txt",
    }
    for name in paths.values():
        folder = root / ("artifacts" if name.startswith(project_id) else "spool")
        target = folder / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"kept")
    with sqlite3.connect(root / "db" / "aiqa.sqlite") as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            """
            INSERT INTO executions (project_id, execution_id, name, purpose, source, suite_version_id, scope_requested_at)
            VALUES (?, ?, '보관', 'regression', 'selection', NULL, ?)
            """,
            (project_id, execution_id, stamp),
        )
        connection.execute(
            """
            INSERT INTO automation_cases (
                project_id, case_id, name, folder_id, tc_reference, next_revision,
                latest_draft_version_id, current_approval_id, lock_version, archived_at
            ) VALUES (?, ?, '보관', NULL, NULL, 2, NULL, NULL, 0, NULL)
            """,
            (project_id, case_id),
        )
        connection.execute(
            """
            INSERT INTO case_versions (
                project_id, case_id, version_id, revision, creation_kind, parent_version_id, base_version_id,
                is_branch, definition_json, settings_json, recorded_steps_json, content_hash, verification_digest,
                source_manifest_id, replay_package_id, readiness_json, actor_id, reason, created_at
            ) VALUES (?, ?, ?, 1, 'recorded', NULL, NULL, 0, '{}', '{}', '[]', ?, ?, NULL, NULL, '{}', ?, 'recorded', ?)
            """,
            (project_id, case_id, version_id, final_hash, "digest-w26", actor_id, stamp),
        )
        connection.execute(
            """
            INSERT INTO case_runs (
                project_id, execution_id, case_run_id, case_id, case_version_id, purpose, requested_at
            ) VALUES (?, ?, ?, ?, ?, 'regression', ?)
            """,
            (project_id, execution_id, run_id, case_id, version_id, stamp),
        )
        connection.execute(
            """
            INSERT INTO jobs (
                project_id, job_id, purpose, recording_id, case_run_id, payload_hash, source_refs, limits, status
            ) VALUES (?, ?, 'regression', NULL, ?, 'payload', '["source"]', '{}', 'completed')
            """,
            (project_id, job_id, run_id),
        )
        connection.execute(
            """
            INSERT INTO attempts (project_id, attempt_id, job_id, generation, physical_key_id)
            VALUES (?, ?, ?, 1, NULL)
            """,
            (project_id, attempt_id, job_id),
        )
        for event, payload, digest, captured in (
            (event_id, "오래된 상세", original_hash, _ago(now, days=90).isoformat()),
            (fresh_event, "아직 상세", "sha256:fresh", _ago(now, days=89).isoformat()),
        ):
            connection.execute(
                """
                INSERT INTO attempt_events (
                    project_id, event_id, attempt_id, local_seq, captured_at, event_type,
                    minimum_facts, payload_hash, body_hash, detail_payload, sealed
                ) VALUES (?, ?, ?, ?, ?, 'observed', '최소 사실', ?, ?, ?, 0)
                """,
                (project_id, event, attempt_id, 1 if event == event_id else 2, captured, digest, digest, payload),
            )
        connection.execute(
            """
            INSERT INTO item_finalizations (
                project_id, case_run_id, created_seq, finalized_seq, release_label, content_hash, core_result, denominator
            ) VALUES (?, ?, 10, 20, '', ?, 'FAIL', 1)
            """,
            (project_id, run_id, final_hash),
        )
        connection.execute(
            """
            INSERT INTO usage_adjustments (
                project_id, adjustment_id, case_run_id, commit_seq, role, measurement_status, amount, currency
            ) VALUES (?, ?, ?, 20, 'verification', 'measured', '1.00', 'USD')
            """,
            (project_id, usage_id, run_id),
        )
        connection.execute(
            """
            INSERT INTO artifact_objects (
                project_id, artifact_id, object_key, content_hash, byte_length, media_type, owner_id,
                status, acked, custody, stored_at
            ) VALUES (?, ?, ?, 'sha256:png', 4, 'image/png', ?, 'quarantine', 0, 'stored', ?)
            """,
            (project_id, artifact_id, paths["png"], str(uuid4()), _ago(now, days=30).isoformat()),
        )
    return {
        "run": run_id,
        "event": event_id,
        "fresh_event": fresh_event,
        "usage": usage_id,
        "approval": str(uuid4()),
        "manifest": str(uuid4()),
        "lineage": str(uuid4()),
        "young_png": str(uuid4()),
        "pinned": str(uuid4()),
        "acked": str(uuid4()),
        "unacked": str(uuid4()),
        "debug": str(uuid4()),
        "fresh_log": str(uuid4()),
        **paths,
    }


async def _retention_page(app: object, project_id: str, artifact_id: str) -> dict[str, object]:
    import httpx

    origin = "http://127.0.0.1"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        issued = await client.post(
            "/api/v1/session/nonces",
            json={"origin": origin, "project_id": project_id},
            headers={"Idempotency-Key": "w2601-nonce", "Origin": origin},
        )
        booted = await client.post(
            "/api/v1/session/bootstrap",
            json={"nonce": issued.json()["nonce"]},
            headers={"Idempotency-Key": "w2601-boot", "Origin": origin},
        )
        client.cookies.set("aiqa_session", booted.cookies["aiqa_session"])
        page = await client.get(f"/api/v1/artifacts/{artifact_id}/retention")
    assert page.status_code == 200, page.text
    return page.json()


def test_w26_02(tmp_path: Path) -> None:
    import asyncio

    from aiqa.api.app import create_app
    from aiqa.config import load_settings
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.store.artifacts import claim_gc_artifact, protect_for_approval
    from aiqa.store.database import migrate_store
    from aiqa.store.models import Actor, ProjectCreate
    from aiqa.store.retention import UtcInstant

    now = datetime(2026, 11, 1, tzinfo=timezone.utc)
    root = tmp_path / "runtime"
    app = create_app(load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}))
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("보호", "w2602", "pins", "web"))
    store.close()
    project_id = str(project.project_id)
    seeded = _ready_artifacts(root, project_id, str(owner.actor_id), now)
    pinned, released, approval_status = asyncio.run(_pin_flow(app, project_id, seeded))
    with sqlite3.connect(root / "db" / "aiqa.sqlite") as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        before = connection.execute("SELECT COUNT(*) FROM artifact_refs").fetchone()[0]
        claim = claim_gc_artifact(connection, project.project_id, UtcInstant(now))
        approved = True
        try:
            protect_for_approval(connection, project.project_id, UUID(seeded["open"]))
        except Exception:
            approved = False
        connection.commit()
        after = connection.execute("SELECT COUNT(*) FROM artifact_refs").fetchone()[0]
        review_left = connection.execute(
            "SELECT 1 FROM artifact_protections WHERE protection_id = ? AND kind = 'review'",
            (seeded["review_pin"],),
        ).fetchone()
        approval_left = connection.execute(
            "SELECT 1 FROM artifact_protections WHERE protection_id = ?",
            (seeded["approval_pin"],),
        ).fetchone()
    blocked = asyncio.run(_pin_open(app, project_id, seeded["open"]))
    observed = {
        "valid_old_approval_gc": claim is not None and str(claim.artifact_id) == seeded["old"],
        "one_release_ignores_other_pin": review_left is None or (claim is not None and str(claim.artifact_id) == seeded["shared"]),
        "delete_pending_approve": approved or blocked == 201,
        "provenance_deleted": after < before,
        "manual_can_release_approval_pin": approval_status == 201 or approval_left is None,
    }
    assert pinned.status_code == 201, pinned.text
    assert released.status_code == 201, released.text
    assert claim is not None and claim.state == "delete_pending" and str(claim.artifact_id) == seeded["open"]
    assert observed == {
        "valid_old_approval_gc": False,
        "one_release_ignores_other_pin": False,
        "delete_pending_approve": False,
        "provenance_deleted": False,
        "manual_can_release_approval_pin": False,
    }


def _ready_artifacts(root: Path, project_id: str, actor_id: str, now: datetime) -> dict[str, str]:
    case_id, version_id = str(uuid4()), str(uuid4())
    old, shared, open_id = str(uuid4()), str(uuid4()), str(uuid4())
    approval_pin, review_pin = str(uuid4()), str(uuid4())
    stamp = now.isoformat()
    with sqlite3.connect(root / "db" / "aiqa.sqlite") as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            """
            INSERT INTO automation_cases (
                project_id, case_id, name, folder_id, tc_reference, next_revision,
                latest_draft_version_id, current_approval_id, lock_version, archived_at
            ) VALUES (?, ?, '보호', NULL, NULL, 2, NULL, NULL, 0, NULL)
            """,
            (project_id, case_id),
        )
        connection.execute(
            """
            INSERT INTO case_versions (
                project_id, case_id, version_id, revision, creation_kind, parent_version_id, base_version_id,
                is_branch, definition_json, settings_json, recorded_steps_json, content_hash, verification_digest,
                source_manifest_id, replay_package_id, readiness_json, actor_id, reason, created_at
            ) VALUES (?, ?, ?, 1, 'recorded', NULL, NULL, 0, '{}', '{}', '[]', 'sha256:case', 'digest-w26',
                NULL, NULL, '{}', ?, 'recorded', ?)
            """,
            (project_id, case_id, version_id, actor_id, stamp),
        )
        for artifact_id, digest in ((old, "sha256:old"), (shared, "sha256:shared"), (open_id, "sha256:open")):
            recording_id, job_id, attempt_id = str(uuid4()), str(uuid4()), str(uuid4())
            connection.execute(
                """
                INSERT INTO recordings (
                    project_id, case_id, recording_id, creation_kind, input_case_version_id,
                    base_case_version_id, parent_recording_id, source_recording_id,
                    storage_status, stop_status, completion_status, evidence_status
                ) VALUES (?, ?, ?, 'recorded', ?, NULL, NULL, NULL, 'stored', 'stopped', 'completed', 'complete')
                """,
                (project_id, case_id, recording_id, version_id),
            )
            connection.execute(
                """
                INSERT INTO jobs (
                    project_id, job_id, purpose, recording_id, case_run_id, payload_hash, source_refs, limits, status
                ) VALUES (?, ?, 'recording', ?, NULL, 'payload', '[]', '{}', 'completed')
                """,
                (project_id, job_id, recording_id),
            )
            connection.execute(
                "INSERT INTO attempts (project_id, attempt_id, job_id, generation, physical_key_id) VALUES (?, ?, ?, 1, NULL)",
                (project_id, attempt_id, job_id),
            )
            connection.execute(
                """
                INSERT INTO actions (
                    project_id, attempt_id, action_seq, step_id, action_id, package_step_id, proposal_hash,
                    dispatch_state, case_id, case_version_id, outcome_known
                ) VALUES (?, ?, 1, 'step-1', 'A001', NULL, 'proposal', 'observed', ?, ?, 1)
                """,
                (project_id, attempt_id, case_id, version_id),
            )
            connection.execute(
                """
                INSERT INTO artifact_refs (
                    project_id, artifact_id, attempt_id, action_id, check_id, recording_id, review_id, build_id,
                    export_id, package_id, healing_id, proposal_id, resource_observation_id
                ) VALUES (?, ?, ?, 'A001', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL)
                """,
                (project_id, artifact_id, attempt_id),
            )
            connection.execute(
                """
                INSERT INTO artifact_objects (
                    project_id, artifact_id, object_key, content_hash, byte_length, media_type, owner_id, status, acked,
                    owner_kind, attempt_id, action_id, check_id, role, job_id, generation
                ) VALUES (?, ?, ?, ?, 4, 'image/png', ?, 'ready', 1, 'REC', ?, 'A001', NULL, 'before', ?, 1)
                """,
                (project_id, artifact_id, artifact_id, digest, recording_id, attempt_id, job_id),
            )
        connection.execute(
            """
            INSERT INTO artifact_protections (
                project_id, protection_id, artifact_id, kind, backup_receipt_id, build_id, manual_request_id
            ) VALUES (?, ?, ?, 'approval', NULL, NULL, NULL)
            """,
            (project_id, approval_pin, old),
        )
        connection.execute(
            """
            INSERT INTO artifact_protections (
                project_id, protection_id, artifact_id, kind, backup_receipt_id, build_id, manual_request_id
            ) VALUES (?, ?, ?, 'review', NULL, NULL, NULL)
            """,
            (project_id, review_pin, shared),
        )
    return {"old": old, "shared": shared, "open": open_id, "approval_pin": approval_pin, "review_pin": review_pin}


async def _pin_flow(app: object, project_id: str, seeded: dict[str, str]):
    import httpx

    origin = "http://127.0.0.1"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        headers = await _headers(client, origin, project_id)
        pinned = await client.post(
            f"/api/v1/artifacts/{seeded['shared']}/retention-protections",
            params={"project_id": project_id},
            headers={**headers, "Idempotency-Key": "w2602-pin"},
            json={"kind": "manual"},
        )
        manual_id = pinned.json()["protection_id"]
        released = await client.post(
            f"/api/v1/retention-protections/{manual_id}/release",
            params={"project_id": project_id},
            headers={**headers, "Idempotency-Key": "w2602-release"},
        )
        again = await client.post(
            f"/api/v1/retention-protections/{manual_id}/release",
            params={"project_id": project_id},
            headers={**headers, "Idempotency-Key": "w2602-release-again"},
        )
        approval = await client.post(
            f"/api/v1/retention-protections/{seeded['approval_pin']}/release",
            params={"project_id": project_id},
            headers={**headers, "Idempotency-Key": "w2602-approval-release"},
        )
    assert again.status_code == 409, again.text
    return pinned, released, approval.status_code


async def _pin_open(app: object, project_id: str, artifact_id: str) -> int:
    import httpx

    origin = "http://127.0.0.1"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        headers = await _headers(client, origin, project_id)
        blocked = await client.post(
            f"/api/v1/artifacts/{artifact_id}/retention-protections",
            params={"project_id": project_id},
            headers={**headers, "Idempotency-Key": "w2602-pending"},
            json={"kind": "manual"},
        )
    return blocked.status_code


async def _headers(client: object, origin: str, project_id: str, key: str = "pin") -> dict[str, str]:
    issued = await client.post(  # type: ignore[attr-defined]
        "/api/v1/session/nonces",
        json={"origin": origin, "project_id": project_id},
        headers={"Idempotency-Key": "w2602-" + key + "-nonce", "Origin": origin},
    )
    booted = await client.post(  # type: ignore[attr-defined]
        "/api/v1/session/bootstrap",
        json={"nonce": issued.json()["nonce"]},
        headers={"Idempotency-Key": "w2602-" + key + "-boot", "Origin": origin},
    )
    client.cookies.set("aiqa_session", booted.cookies["aiqa_session"])  # type: ignore[attr-defined]
    return {"Origin": origin, "X-CSRF-Token": booted.json()["csrf_token"]}


def test_w26_03(tmp_path: Path) -> None:
    import asyncio

    from aiqa.api.app import create_app
    from aiqa.config import load_settings
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.store.artifacts import PROJECT_BYTE_LIMIT
    from aiqa.store.database import migrate_store
    from aiqa.store.models import Actor, ProjectCreate

    root = tmp_path / "runtime"
    app = create_app(load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}))
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("공간", "w2603", "storage", "web"))
        other = create_project(owner, ProjectCreate("다른", "w2603b", "other", "web"))
    store.close()
    project_id = str(project.project_id)
    seeded = _space(root, project_id, str(owner.actor_id))
    stored, preview, page, hidden, release = asyncio.run(_space_flow(app, project_id, str(other.project_id), seeded))
    with sqlite3.connect(root / "db" / "aiqa.sqlite") as connection:
        kept = connection.execute(
            "SELECT byte_length FROM artifact_objects WHERE artifact_id = ?",
            (seeded["partial"],),
        ).fetchone()
        protected = connection.execute(
            "SELECT COUNT(*) FROM artifact_protections WHERE artifact_id = ?",
            (seeded["huge"],),
        ).fetchone()
    observed = {
        "protected_files_auto_deleted": preview["protected_files_auto_deleted"],
        "quota_stops_new_actions": stored["quota_stops_new_actions"] is True and stored["protected_count"] == 1,
        "partial_record_saved": stored["partial_record_saved"] is True and kept is not None and int(kept[0]) == 499 * 1024 * 1024,
        "purge_button_present": "<button" in page and "purge" in page.lower(),
    }
    assert stored["item_accepts_499"] is True and stored["item_accepts_500"] is True and stored["item_stops_after_500"] is True
    assert stored["total_bytes"] >= stored["project_bytes"] > PROJECT_BYTE_LIMIT
    assert "전체 20GB" in page and "이 프로젝트" in page and "500MB" in page and "만료된 증거" in page
    assert "최소 사실" in page and "새 행동을 멈춥니다" in page and "일부 기록은 남습니다" in page and "승인" in page
    assert hidden == 404 and release == 422 and protected[0] == 1
    assert observed == {
        "protected_files_auto_deleted": 0,
        "quota_stops_new_actions": True,
        "partial_record_saved": True,
        "purge_button_present": False,
    }


def _space(root: Path, project_id: str, actor_id: str) -> dict[str, str]:
    from aiqa.store.artifacts import PROJECT_BYTE_LIMIT

    case_id, version_id, recording_id = str(uuid4()), str(uuid4()), str(uuid4())
    huge, partial, approval = str(uuid4()), str(uuid4()), str(uuid4())
    stamp = "2026-11-01T00:00:00+00:00"
    with sqlite3.connect(root / "db" / "aiqa.sqlite") as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            """
            INSERT INTO automation_cases (
                project_id, case_id, name, folder_id, tc_reference, next_revision,
                latest_draft_version_id, current_approval_id, lock_version, archived_at
            ) VALUES (?, ?, '공간', NULL, NULL, 2, NULL, NULL, 0, NULL)
            """,
            (project_id, case_id),
        )
        connection.execute(
            """
            INSERT INTO case_versions (
                project_id, case_id, version_id, revision, creation_kind, parent_version_id, base_version_id,
                is_branch, definition_json, settings_json, recorded_steps_json, content_hash, verification_digest,
                source_manifest_id, replay_package_id, readiness_json, actor_id, reason, created_at
            ) VALUES (?, ?, ?, 1, 'recorded', NULL, NULL, 0, '{}', '{}', '[]', 'sha256:space', 'digest-space',
                NULL, NULL, '{}', ?, 'recorded', ?)
            """,
            (project_id, case_id, version_id, actor_id, stamp),
        )
        connection.execute(
            """
            INSERT INTO recordings (
                project_id, case_id, recording_id, creation_kind, input_case_version_id,
                base_case_version_id, parent_recording_id, source_recording_id,
                storage_status, stop_status, completion_status, evidence_status
            ) VALUES (?, ?, ?, 'recorded', ?, NULL, NULL, NULL, 'stored', 'stopped', 'completed', 'complete')
            """,
            (project_id, case_id, recording_id, version_id),
        )
        for artifact_id, length, custody in (
            (huge, PROJECT_BYTE_LIMIT + 1, "stored"),
            (partial, 499 * 1024 * 1024, "expired"),
        ):
            connection.execute(
                """
                INSERT INTO artifact_refs (
                    project_id, artifact_id, attempt_id, action_id, check_id, recording_id, review_id, build_id,
                    export_id, package_id, healing_id, proposal_id, resource_observation_id
                ) VALUES (?, ?, NULL, NULL, NULL, ?, NULL, NULL, NULL, NULL, NULL, NULL, NULL)
                """,
                (project_id, artifact_id, recording_id),
            )
            connection.execute(
                """
                INSERT INTO artifact_objects (
                    project_id, artifact_id, object_key, content_hash, byte_length, media_type, owner_id,
                    status, acked, custody, stored_at
                ) VALUES (?, ?, ?, ?, ?, 'image/png', ?, 'quarantine', 0, ?, ?)
                """,
                (project_id, artifact_id, artifact_id, "sha256:" + artifact_id, length, recording_id, custody, stamp),
            )
        connection.execute(
            """
            INSERT INTO artifact_protections (
                project_id, protection_id, artifact_id, kind, backup_receipt_id, build_id, manual_request_id
            ) VALUES (?, ?, ?, 'approval', NULL, NULL, NULL)
            """,
            (project_id, approval, huge),
        )
        connection.execute(
            """
            INSERT INTO gc_claims (project_id, claim_id, artifact_id, state, claimed_at)
            VALUES (?, ?, ?, 'delete_pending', ?)
            """,
            (project_id, str(uuid4()), partial, stamp),
        )
    return {"huge": huge, "partial": partial, "approval": approval}


async def _space_flow(app: object, project_id: str, other_id: str, seeded: dict[str, str]):
    import httpx

    origin = "http://127.0.0.1"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        headers = await _headers(client, origin, project_id, "space")
        stored = await client.get(f"/api/v1/projects/{project_id}/storage", headers=headers)
        preview = await client.post(
            f"/api/v1/projects/{project_id}/retention-previews",
            headers={**headers, "Idempotency-Key": "w2603-preview"},
        )
        page = await client.get(f"/ui/projects/{project_id}/settings")
        approval = await client.post(
            f"/api/v1/retention-protections/{seeded['approval']}/release",
            params={"project_id": project_id},
            headers={**headers, "Idempotency-Key": "w2603-release"},
        )
        other_headers = await _headers(client, origin, other_id, "other")
        hidden = await client.get(f"/api/v1/projects/{project_id}/storage", headers=other_headers)
    assert stored.status_code == 200, stored.text
    assert preview.status_code == 200, preview.text
    assert page.status_code == 200, page.text
    return stored.json(), preview.json(), page.text, hidden.status_code, approval.status_code


def test_w26_04(tmp_path: Path) -> None:
    import asyncio
    import hashlib

    from aiqa.api.app import create_app
    from aiqa.config import load_settings
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.store.artifacts import claim_gc_artifact
    from aiqa.store.backup import copy_snapshot_bytes
    from aiqa.store.database import migrate_store
    from aiqa.store.models import Actor, ProjectCreate
    from aiqa.store.retention import UtcInstant

    root = tmp_path / "runtime"
    app = create_app(load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}))
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("백업", "w2604", "backup", "web"))
        other = create_project(owner, ProjectCreate("다른저장소", "w2604b", "other", "web"))
    store.close()
    project_id = str(project.project_id)
    artifact_id = _ready_missing(root, project_id, str(owner.actor_id))
    secret = b"backup-secret-plain"
    secret_path = root / "secrets" / "plain.bin"
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    secret_path.write_bytes(secret)
    now = datetime(2026, 11, 1, tzinfo=timezone.utc)
    with sqlite3.connect(root / "db" / "aiqa.sqlite") as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            "INSERT INTO gc_pause (pause_id, reason, created_at) VALUES ('pause', 'backup', ?)",
            (now.isoformat(),),
        )
        paused = claim_gc_artifact(connection, project.project_id, UtcInstant(now))
        connection.execute("DELETE FROM gc_pause WHERE pause_id = 'pause'")
        connection.commit()
    created, page, hidden, download = asyncio.run(_backup_flow(app, project_id, str(other.project_id)))
    with sqlite3.connect(root / "db" / "aiqa.sqlite") as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        after = claim_gc_artifact(connection, project.project_id, UtcInstant(now))
        verdict = connection.execute(
            "SELECT verdict FROM job_finish_facts WHERE job_id = ?",
            (created["job_id"],),
        ).fetchone()
        connection.commit()
    snapshot = root / "backups" / created["receipt_id"] / "snapshot.sqlite"
    with sqlite3.connect(snapshot) as copied:
        integrity = copied.execute("PRAGMA integrity_check").fetchone()[0]
        found = {
            str(row[0])
            for row in copied.execute("SELECT project_id FROM projects").fetchall()
        }
    copied_bytes = b"".join(path.read_bytes() for path in (root / "backups").rglob("*") if path.is_file())
    opens: list[object] = []
    real_connect = sqlite3.connect

    def _spy(*args: object, **kwargs: object):
        opens.append(args)
        return real_connect(*args, **kwargs)  # type: ignore[arg-type]

    sqlite3.connect = _spy  # type: ignore[assignment]
    try:
        copy_snapshot_bytes(b"copy", root / "backups" / "worker-copy.bin")
    finally:
        sqlite3.connect = real_connect  # type: ignore[assignment]
    observed = {
        "consistent_db_snapshot": integrity == "ok" and project_id in found and str(other.project_id) in found,
        "project_only_actor_allowed": hidden == 201,
        "worker_opens_sqlite": len(opens) > 0,
        "plain_secret_in_backup": secret in copied_bytes,
        "missing_file_backup_complete": created["state"] == "complete",
        "backup_job_qa": None if verdict is None else verdict[0],
    }
    assert paused is None and after is not None and str(after.artifact_id) == artifact_id
    assert "이 PC 전체 저장소 백업" in page and "프로젝트 경로는 요청 이력입니다" in page and "비밀 원문은 복사하지 않습니다" in page
    assert download.startswith(b"SQLite format 3")
    assert observed == {
        "consistent_db_snapshot": True,
        "project_only_actor_allowed": False,
        "worker_opens_sqlite": False,
        "plain_secret_in_backup": False,
        "missing_file_backup_complete": False,
        "backup_job_qa": None,
    }


def _ready_missing(root: Path, project_id: str, actor_id: str) -> str:
    case_id, version_id, recording_id = str(uuid4()), str(uuid4()), str(uuid4())
    job_id, attempt_id, artifact_id = str(uuid4()), str(uuid4()), str(uuid4())
    stamp = "2026-11-01T00:00:00+00:00"
    with sqlite3.connect(root / "db" / "aiqa.sqlite") as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            """
            INSERT INTO automation_cases (
                project_id, case_id, name, folder_id, tc_reference, next_revision,
                latest_draft_version_id, current_approval_id, lock_version, archived_at
            ) VALUES (?, ?, '백업', NULL, NULL, 2, NULL, NULL, 0, NULL)
            """,
            (project_id, case_id),
        )
        connection.execute(
            """
            INSERT INTO case_versions (
                project_id, case_id, version_id, revision, creation_kind, parent_version_id, base_version_id,
                is_branch, definition_json, settings_json, recorded_steps_json, content_hash, verification_digest,
                source_manifest_id, replay_package_id, readiness_json, actor_id, reason, created_at
            ) VALUES (?, ?, ?, 1, 'recorded', NULL, NULL, 0, '{}', '{}', '[]', 'sha256:backup', 'digest-backup',
                NULL, NULL, '{}', ?, 'recorded', ?)
            """,
            (project_id, case_id, version_id, actor_id, stamp),
        )
        connection.execute(
            """
            INSERT INTO recordings (
                project_id, case_id, recording_id, creation_kind, input_case_version_id,
                base_case_version_id, parent_recording_id, source_recording_id,
                storage_status, stop_status, completion_status, evidence_status
            ) VALUES (?, ?, ?, 'recorded', ?, NULL, NULL, NULL, 'stored', 'stopped', 'completed', 'complete')
            """,
            (project_id, case_id, recording_id, version_id),
        )
        connection.execute(
            """
            INSERT INTO jobs (
                project_id, job_id, purpose, recording_id, case_run_id, payload_hash, source_refs, limits, status
            ) VALUES (?, ?, 'recording', ?, NULL, 'payload', '[]', '{}', 'completed')
            """,
            (project_id, job_id, recording_id),
        )
        connection.execute(
            "INSERT INTO attempts (project_id, attempt_id, job_id, generation, physical_key_id) VALUES (?, ?, ?, 1, NULL)",
            (project_id, attempt_id, job_id),
        )
        connection.execute(
            """
            INSERT INTO actions (
                project_id, attempt_id, action_seq, step_id, action_id, package_step_id, proposal_hash,
                dispatch_state, case_id, case_version_id, outcome_known
            ) VALUES (?, ?, 1, 'step-1', 'A001', NULL, 'proposal', 'observed', ?, ?, 1)
            """,
            (project_id, attempt_id, case_id, version_id),
        )
        connection.execute(
            """
            INSERT INTO artifact_refs (
                project_id, artifact_id, attempt_id, action_id, check_id, recording_id, review_id, build_id,
                export_id, package_id, healing_id, proposal_id, resource_observation_id
            ) VALUES (?, ?, ?, 'A001', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL)
            """,
            (project_id, artifact_id, attempt_id),
        )
        connection.execute(
            """
            INSERT INTO artifact_objects (
                project_id, artifact_id, object_key, content_hash, byte_length, media_type, owner_id, status, acked,
                owner_kind, attempt_id, action_id, check_id, role, job_id, generation
            ) VALUES (?, ?, ?, 'sha256:missing', 4, 'image/png', ?, 'ready', 1, 'REC', ?, 'A001', NULL, 'before', ?, 1)
            """,
            (project_id, artifact_id, artifact_id, recording_id, attempt_id, job_id),
        )
    return artifact_id


async def _backup_flow(app: object, project_id: str, other_id: str):
    import hashlib

    import httpx

    origin = "http://127.0.0.1"
    session_id = str(uuid4())
    token = "project-only-csrf"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        headers = await _headers(client, origin, project_id, "backup")
        created = await client.post(
            f"/api/v1/projects/{project_id}/backups",
            headers={**headers, "Idempotency-Key": "w2604-backup"},
        )
        page = await client.get(f"/ui/projects/{project_id}/settings")
        store = app.state.open_store()  # type: ignore[attr-defined]
        from aiqa.store.database import migrate_store

        migrate_store(store)
        with store.transaction() as connection:
            connection.execute(
                """
                INSERT INTO browser_sessions (
                    session_id, origin, csrf_hash, actor_id, project_scope, is_local_owner, expires_at
                ) VALUES (?, ?, ?, ?, ?, 0, '2026-12-01T00:00:00+00:00')
                """,
                (session_id, origin, hashlib.sha256(token.encode("utf-8")).hexdigest(), str(uuid4()), project_id),
            )
        store.close()
        client.cookies.set("aiqa_session", session_id)
        hidden = await client.post(
            f"/api/v1/projects/{project_id}/backups",
            headers={"Origin": origin, "X-CSRF-Token": token, "Idempotency-Key": "w2604-hidden"},
        )
        client.cookies.set("aiqa_session", "")
        owner = await _headers(client, origin, project_id, "backup-read")
        download = await client.get(
            f"/api/v1/backups/{created.json()['receipt_id']}/download",
            params={"project_id": project_id},
            headers=owner,
        )
    assert created.status_code == 201, created.text
    assert page.status_code == 200, page.text
    assert download.status_code == 200, download.text
    return created.json(), page.text, hidden.status_code, download.content


def test_w26_05(tmp_path: Path) -> None:
    import asyncio
    import hashlib
    import json

    from aiqa.api.app import create_app
    from aiqa.config import load_settings
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.store.database import migrate_store
    from aiqa.store.models import Actor, ProjectCreate

    root = tmp_path / "runtime"
    app = create_app(load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}))
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("복원", "w2605", "restore", "web"))
        other = create_project(owner, ProjectCreate("다른복원", "w2605b", "other", "web"))
    store.close()
    project_id = str(project.project_id)
    other_id = str(other.project_id)
    secret = b"restore-secret-plain"
    secret_path = root / "secrets" / "plain.bin"
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    secret_path.write_bytes(secret)
    queued_id, running_id, lease_key = _progress(root, project_id, other_id, str(owner.actor_id))
    (root / "launcher.json").write_text(
        json.dumps({"worker_pid": 4242, "api_pid": 0, "state": "running", "host": "127.0.0.1", "port": 8000}),
        encoding="utf-8",
    )
    created, good, damaged, drifted, hidden, invalid, activated, page = asyncio.run(
        _restore_flow(app, root, project_id, other_id)
    )
    with sqlite3.connect(root / "db" / "aiqa.sqlite") as connection:
        replayed = connection.execute(
            "SELECT COUNT(*) FROM jobs WHERE status IN ('queued', 'running', 'preparing', 'finalizing')"
        ).fetchone()[0]
        leases = connection.execute("SELECT COUNT(*) FROM leases").fetchone()[0]
        tokens = connection.execute("SELECT COUNT(*) FROM worker_tokens").fetchone()[0]
        quarantine = connection.execute(
            "SELECT reason FROM resource_quarantine WHERE physical_key_id = ?",
            (lease_key,),
        ).fetchone()
        recording = connection.execute(
            "SELECT stop_status, completion_status FROM recordings WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        marker = connection.execute("SELECT request_id FROM manual_retention_requests").fetchone()
        queued_status = connection.execute(
            "SELECT status FROM jobs WHERE job_id = ?",
            (queued_id,),
        ).fetchone()[0]
        running_status = connection.execute(
            "SELECT status FROM jobs WHERE job_id = ?",
            (running_id,),
        ).fetchone()[0]
    copied_bytes = b"".join(path.read_bytes() for path in (root / "restores").rglob("*") if path.is_file())
    maintenance = json.loads((root / "maintenance.json").read_text(encoding="utf-8"))
    launcher = json.loads((root / "launcher.json").read_text(encoding="utf-8"))
    observed = {
        "auto_replayed_jobs": activated["auto_replayed_jobs"] if replayed == 0 else replayed,
        "old_leases_reused": leases > 0,
        "secret_reset_required": good["secret_reset_required"] is True,
        "invalid_restore_activated": invalid == 201 or damaged["accepted"] is True,
        "project_only_actor_can_activate": hidden == 201,
    }
    assert created["state"] == "complete"
    assert good["accepted"] is True and good["separate_path"] != str(root / "db" / "aiqa.sqlite")
    assert drifted["accepted"] is False and drifted["schema_ok"] is False and drifted["missing_count"] == 1
    assert damaged["integrity_ok"] is False
    assert secret not in copied_bytes
    assert tokens == 0 and quarantine[0] == "dead_runner"
    assert recording == ("stopped", "interrupted")
    assert marker is not None and queued_status == "cancelled" and running_status == "cancelled"
    assert maintenance["worker_sessions"] == "discarded" and launcher["worker_pid"] == 0
    assert "실행 중인 저장소와 다른 경로" in page
    assert "명시적으로 확인" in page and "키는 다시 설정해야 합니다" in page
    assert "다시 시작하지 않습니다" in page
    assert observed == {
        "auto_replayed_jobs": 0,
        "old_leases_reused": False,
        "secret_reset_required": True,
        "invalid_restore_activated": False,
        "project_only_actor_can_activate": False,
    }


def _progress(root: Path, project_id: str, other_id: str, actor_id: str) -> tuple[str, str, str]:
    case_id, version_id, recording_id = str(uuid4()), str(uuid4()), str(uuid4())
    queued_id, running_id, other_job = str(uuid4()), str(uuid4()), str(uuid4())
    enroll_id, worker_id, key_id = str(uuid4()), str(uuid4()), str(uuid4())
    stamp = "2026-11-01T00:00:00+00:00"
    with sqlite3.connect(root / "db" / "aiqa.sqlite") as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            """
            INSERT INTO automation_cases (
                project_id, case_id, name, folder_id, tc_reference, next_revision,
                latest_draft_version_id, current_approval_id, lock_version, archived_at
            ) VALUES (?, ?, '복원', NULL, NULL, 2, NULL, NULL, 0, NULL)
            """,
            (project_id, case_id),
        )
        connection.execute(
            """
            INSERT INTO case_versions (
                project_id, case_id, version_id, revision, creation_kind, parent_version_id, base_version_id,
                is_branch, definition_json, settings_json, recorded_steps_json, content_hash, verification_digest,
                source_manifest_id, replay_package_id, readiness_json, actor_id, reason, created_at
            ) VALUES (?, ?, ?, 1, 'recorded', NULL, NULL, 0, '{}', '{}', '[]', 'sha256:restore', 'digest-restore',
                NULL, NULL, '{}', ?, 'recorded', ?)
            """,
            (project_id, case_id, version_id, actor_id, stamp),
        )
        connection.execute(
            """
            INSERT INTO recordings (
                project_id, case_id, recording_id, creation_kind, input_case_version_id,
                base_case_version_id, parent_recording_id, source_recording_id,
                storage_status, stop_status, completion_status, evidence_status
            ) VALUES (?, ?, ?, 'recorded', ?, NULL, NULL, NULL, 'local', 'running', 'open', 'incomplete')
            """,
            (project_id, case_id, recording_id, version_id),
        )
        connection.execute(
            "INSERT INTO worker_enrollments (enrollment_id, worker_id, project_id, created_at) VALUES (?, ?, ?, ?)",
            (enroll_id, worker_id, project_id, stamp),
        )
        connection.execute(
            """
            INSERT INTO worker_tokens (token_id, enrollment_id, token_hash, purpose, created_at)
            VALUES (?, ?, ?, 'recording', ?)
            """,
            (str(uuid4()), enroll_id, "hash-token", stamp),
        )
        connection.execute(
            "INSERT INTO physical_resource_keys (physical_key_id, worker_id, native_id) VALUES (?, ?, ?)",
            (key_id, worker_id, "native-restore"),
        )
        connection.execute(
            """
            INSERT INTO jobs (
                project_id, job_id, purpose, recording_id, case_run_id, payload_hash, source_refs, limits, status
            ) VALUES (?, ?, 'recording', ?, NULL, 'payload', '[]', '{}', 'running')
            """,
            (project_id, running_id, recording_id),
        )
        connection.execute(
            """
            INSERT INTO leases (project_id, job_id, generation, worker_id, physical_key_id, expires_at)
            VALUES (?, ?, 1, ?, ?, ?)
            """,
            (project_id, running_id, worker_id, key_id, stamp),
        )
        connection.execute(
            """
            INSERT INTO jobs (
                project_id, job_id, purpose, recording_id, case_run_id, payload_hash, source_refs, limits, status
            ) VALUES (?, ?, 'resource_probe', NULL, NULL, 'payload', '["probe"]', '{}', 'queued')
            """,
            (project_id, queued_id),
        )
        connection.execute(
            """
            INSERT INTO jobs (
                project_id, job_id, purpose, recording_id, case_run_id, payload_hash, source_refs, limits, status
            ) VALUES (?, ?, 'resource_probe', NULL, NULL, 'payload', '["probe"]', '{}', 'queued')
            """,
            (other_id, other_job),
        )
    return queued_id, running_id, key_id


async def _restore_flow(app: object, root: Path, project_id: str, other_id: str):
    import hashlib
    import json
    import sqlite3
    from uuid import uuid4

    import httpx

    origin = "http://127.0.0.1"
    session_id = str(uuid4())
    token = "project-only-csrf"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        headers = await _headers(client, origin, project_id, "restore")
        created = await client.post(
            f"/api/v1/projects/{project_id}/backups",
            headers={**headers, "Idempotency-Key": "w2605-backup"},
        )
        assert created.status_code == 201, created.text
        receipt_id = created.json()["receipt_id"]
        store = app.state.open_store()  # type: ignore[attr-defined]
        from aiqa.store.database import migrate_store

        migrate_store(store)
        with store.transaction() as connection:
            connection.execute(
                "INSERT INTO manual_retention_requests (project_id, request_id, created_at) VALUES (?, 'live-marker', ?)",
                (project_id, "2026-11-01T01:00:00+00:00"),
            )
        store.close()
        good = await client.post(
            f"/api/v1/backups/{receipt_id}/restore-validations",
            params={"project_id": project_id},
            headers={**headers, "Idempotency-Key": "w2605-good"},
        )
        damaged_id = _mutated_receipt(root, project_id, receipt_id, "damaged")
        drifted_id = _mutated_receipt(root, project_id, receipt_id, "schema")
        damaged = await client.post(
            f"/api/v1/backups/{damaged_id}/restore-validations",
            params={"project_id": project_id},
            headers={**headers, "Idempotency-Key": "w2605-damaged"},
        )
        drifted = await client.post(
            f"/api/v1/backups/{drifted_id}/restore-validations",
            params={"project_id": project_id},
            headers={**headers, "Idempotency-Key": "w2605-schema"},
        )
        owner_cookie = next(
            cookie.value for cookie in client.cookies.jar if cookie.name == "aiqa_session"
        )
        store = app.state.open_store()  # type: ignore[attr-defined]
        migrate_store(store)
        with store.transaction() as connection:
            connection.execute(
                """
                INSERT INTO browser_sessions (
                    session_id, origin, csrf_hash, actor_id, project_scope, is_local_owner, expires_at
                ) VALUES (?, ?, ?, ?, ?, 0, '2026-12-01T00:00:00+00:00')
                """,
                (session_id, origin, hashlib.sha256(token.encode("utf-8")).hexdigest(), str(uuid4()), project_id),
            )
        store.close()
        client.cookies.clear()
        client.cookies.set("aiqa_session", session_id)
        hidden = await client.post(
            f"/api/v1/restore-validations/{good.json()['validation_id']}/activations",
            params={"project_id": project_id},
            headers={"Origin": origin, "X-CSRF-Token": token, "Idempotency-Key": "w2605-hidden"},
            json={"confirmed": True},
        )
        client.cookies.clear()
        client.cookies.set("aiqa_session", owner_cookie)
        invalid = await client.post(
            f"/api/v1/restore-validations/{drifted.json()['validation_id']}/activations",
            params={"project_id": project_id},
            headers={**headers, "Idempotency-Key": "w2605-invalid"},
            json={"confirmed": True},
        )
        activated = await client.post(
            f"/api/v1/restore-validations/{good.json()['validation_id']}/activations",
            params={"project_id": project_id},
            headers={**headers, "Idempotency-Key": "w2605-activate"},
            json={"confirmed": True},
        )
        page = await client.get(f"/ui/projects/{project_id}/restore")
    assert good.status_code == 201, good.text
    assert damaged.status_code == 201, damaged.text
    assert drifted.status_code == 201, drifted.text
    assert activated.status_code == 201, activated.text
    assert page.status_code == 200, page.text
    unused = other_id
    assert unused
    return (
        created.json(),
        good.json(),
        damaged.json(),
        drifted.json(),
        hidden.status_code,
        invalid.status_code,
        activated.json(),
        page.text,
    )


def _mutated_receipt(root: Path, project_id: str, source_receipt: str, kind: str) -> str:
    import json
    import shutil

    receipt_id = str(uuid4())
    job_id = str(uuid4())
    source = root / "backups" / source_receipt
    target = root / "backups" / receipt_id
    shutil.copytree(source, target)
    with sqlite3.connect(root / "db" / "aiqa.sqlite") as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        row = connection.execute(
            "SELECT content_hash, byte_length FROM backup_snapshots WHERE project_id = ? AND receipt_id = ?",
            (project_id, source_receipt),
        ).fetchone()
        connection.execute(
            """
            INSERT INTO jobs (
                project_id, job_id, purpose, recording_id, case_run_id, payload_hash, source_refs, limits, status
            ) VALUES (?, ?, 'backup', NULL, NULL, ?, '["pc-store"]', '{}', 'completed')
            """,
            (project_id, job_id, row[0]),
        )
        connection.execute(
            "INSERT INTO backup_receipts (project_id, receipt_id, created_at) VALUES (?, ?, ?)",
            (project_id, receipt_id, "2026-11-01T02:00:00+00:00"),
        )
        connection.execute(
            """
            INSERT INTO backup_snapshots (
                project_id, receipt_id, job_id, byte_length, content_hash, state, missing_count, created_at
            ) VALUES (?, ?, ?, ?, ?, 'complete', 0, ?)
            """,
            (project_id, receipt_id, job_id, row[1], row[0], "2026-11-01T02:00:00+00:00"),
        )
    if kind == "damaged":
        (target / "snapshot.sqlite").write_bytes(b"damaged-sqlite")
    else:
        with sqlite3.connect(target / "snapshot.sqlite") as copied:
            copied.execute("CREATE TABLE schema_drift (id TEXT)")
            copied.commit()
            copied.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        manifest_path = target / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["missing_count"] = 1
        manifest["missing"] = ["shot.png"]
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return receipt_id




