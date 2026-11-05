"""RX-50: sealed Android recording manifests become immutable replay packages."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from uuid import UUID, uuid4

from aiqa.api.app import create_app
from aiqa.config import load_settings
from aiqa.domain.projects import bind_store, create_project
from aiqa.recording.manifests import RecordingFinishInput
from aiqa.recording.service import (
    PreflightRejected,
    finish_recording,
    materialize_android_recording,
    rebuild_android_package,
)
from aiqa.replay.android_plan import PlanRejected, compile_android_plan
from aiqa.replay.packages import load_package_digest
from aiqa.store.database import migrate_store
from aiqa.store.models import Actor, ProjectCreate, RecordingManifest

_GEOMETRY = {"rotation": 0, "content_bounds": [0, 0, 1080, 1920]}


def _action(action: str, action_id: str, line: int, **extra: object) -> dict[str, object]:
    event: dict[str, object] = {
        "kind": "action",
        "action": action,
        "intent": "open",
        "target": "resource_id=login",
        "action_id": action_id,
        "line": line,
        "geometry": _GEOMETRY,
    }
    event.update(extra)
    return event


def _supported_events() -> list[object]:
    return [
        _action("tap", "a1", 1),
        _action("swipe", "a2", 2, intent="scroll", target="resource_id=list"),
    ]


def _mapping(events: list[object]) -> str:
    return json.dumps({"events": events}, ensure_ascii=False, separators=(",", ":"))


def _manifest_model(events: list[object], *, artifact_id: str) -> tuple[RecordingManifest, str]:
    mapping = _mapping(events)
    digest = hashlib.sha256(mapping.encode("utf-8")).hexdigest()
    manifest_id = uuid4()
    source = RecordingManifest(
        uuid4(),
        uuid4(),
        uuid4(),
        manifest_id,
        1,
        "original",
        None,
        "a" * 64,
        json.dumps([artifact_id, digest]),
        mapping,
        "complete",
        "rx50",
        "b" * 64,
    )
    return source, digest


def test_rx_50_same_source_blocks_bad_actions_and_preserves_digest(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    app = create_app(
        load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)})
    )
    owner = Actor(uuid4(), None, True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("재생패키지", "rx50", "녹화", "android"))
    project_id = project.project_id
    actor = Actor(owner.actor_id, project_id, True)
    database = root / "db" / "aiqa.sqlite"

    case_id, version_id, recording_id, artifact_id = _seed_case(app, store, project_id, actor)
    mapping = _mapping(_supported_events())
    digest = hashlib.sha256(mapping.encode("utf-8")).hexdigest()
    with store.transaction() as connection:
        _seed_artifact(connection, project_id, recording_id, artifact_id)
        first = finish_recording(
            connection,
            actor,
            project_id,
            RecordingFinishInput(
                recording_id,
                "completed",
                2,
                (str(artifact_id),),
                "rx50-finish",
                mapping,
            ),
        )
        second = finish_recording(
            connection,
            actor,
            project_id,
            RecordingFinishInput(
                recording_id,
                "completed",
                2,
                (str(artifact_id),),
                "rx50-finish",
                mapping,
            ),
        )
        assert first.manifest_id == second.manifest_id
        assert first.replayed is False and second.replayed is True
        again = materialize_android_recording(connection, actor, project_id, first.manifest_id)
        assert again.replayed is True
        assert again.replay_package_id is not None
        package_id = again.replay_package_id
        before_digest = load_package_digest(connection, project_id, package_id)
        assert before_digest is not None and before_digest != ""

        rebuilt = rebuild_android_package(
            connection, actor, project_id, recording_id, "rx50-rebuild"
        )
        assert rebuilt.replay_package_id is not None
        assert rebuilt.replay_package_id != package_id
        after_digest = load_package_digest(connection, project_id, package_id)
        assert after_digest == before_digest
        rebuilt_digest = load_package_digest(connection, project_id, rebuilt.replay_package_id)
        assert rebuilt_digest is not None and rebuilt_digest != before_digest
        try:
            materialize_android_recording(connection, actor, project_id, uuid4())
            missing_ok = False
        except PreflightRejected as exc:
            missing_ok = "manifest" in str(exc.reason)

    blocked = 0
    for events in (
        [_action("shell", "bad", 1)],
        [_action("tap", "g1", 1, geometry=None)],
        [_action("type", "s1", 1, secret_literal="password-literal")],
        [],
    ):
        try:
            compile_android_plan(_manifest_model(events, artifact_id=str(artifact_id))[0])
        except PlanRejected:
            blocked += 1
            continue
        raise AssertionError(events)
    assert blocked == 4
    store.close()

    with sqlite3.connect(database) as connection:
        packages = connection.execute(
            "SELECT COUNT(*), COUNT(DISTINCT body_hash) FROM replay_packages WHERE ready = 1"
        ).fetchone()
        versions = connection.execute(
            """
            SELECT COUNT(*) FROM case_versions
            WHERE project_id = ? AND case_id = ? AND replay_package_id IS NOT NULL
            """,
            (str(project_id), case_id),
        ).fetchone()[0]
        sealed = connection.execute(
            """
            SELECT action_mapping, source_artifact_hashes FROM recording_manifests
            WHERE project_id = ? AND recording_id = ? AND kind = 'original'
            """,
            (str(project_id), str(recording_id)),
        ).fetchone()
    observed = {
        "same_source_same_package": again.replay_package_id == package_id,
        "blocked_bad_actions": blocked,
        "approved_digest_unchanged": after_digest == before_digest,
        "rebuild_new_version": versions >= 2 and rebuilt.replay_package_id != package_id,
        "ready_package_count": int(packages[0]),
        "distinct_digests": int(packages[1]),
        "missing_manifest_blocked": missing_ok,
        "mapping_digest_in_source": digest in json.loads(sealed[1]),
    }
    assert json.loads(sealed[0])["events"][0]["action"] == "tap"
    assert observed == {
        "same_source_same_package": True,
        "blocked_bad_actions": 4,
        "approved_digest_unchanged": True,
        "rebuild_new_version": True,
        "ready_package_count": 2,
        "distinct_digests": 2,
        "missing_manifest_blocked": True,
        "mapping_digest_in_source": True,
    }
    assert version_id


def _seed_case(app: object, store: object, project_id: UUID, actor: Actor) -> tuple[str, str, UUID, UUID]:
    import asyncio

    import httpx

    async def create() -> tuple[str, str]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            origin = "http://127.0.0.1"
            nonce = await client.post(
                "/api/v1/session/nonces",
                json={"origin": origin, "project_id": str(project_id)},
                headers={"Origin": origin, "Idempotency-Key": str(uuid4())},
            )
            boot = await client.post(
                "/api/v1/session/bootstrap",
                json={"nonce": nonce.json()["nonce"]},
                headers={"Origin": origin, "Idempotency-Key": str(uuid4())},
            )
            headers = {
                "Origin": origin,
                "X-CSRF-Token": boot.json()["csrf_token"],
                "Idempotency-Key": "rx50-case",
            }
            created = await client.post(
                f"/api/v1/projects/{project_id}/cases",
                json={"name": "로그인", "tc_reference": None},
                headers=headers,
            )
            case_id = created.json()["case_id"]
            version = await client.post(
                f"/api/v1/projects/{project_id}/cases/{case_id}/versions",
                json={
                    "definition": {
                        "raw_text": "로그인",
                        "objective": "로그인",
                        "preconditions": [],
                        "variables": {},
                        "secret_refs": {},
                        "steps": [{"id": "s1", "instruction": "tap", "point": [1, 2], "expected": []}],
                        "final_expected": [],
                        "path_policy": {"must_use": [], "forbidden": []},
                    },
                    "settings": {"target_kind": "android", "android_package": "com.example.app", "limits": {"timeout_seconds": 60}},
                },
                headers={**headers, "Idempotency-Key": "rx50-version"},
            )
            return case_id, version.json()["id"]

    case_id, version_id = asyncio.run(create())
    recording_id = uuid4()
    artifact_id = uuid4()
    with store.transaction() as connection:  # type: ignore[attr-defined]
        connection.execute(
            """
            INSERT INTO recordings (
                project_id, case_id, recording_id, creation_kind, input_case_version_id,
                storage_status, stop_status, completion_status, evidence_status
            ) VALUES (?, ?, ?, 'recorded', ?, 'stored', 'running', 'open', 'incomplete')
            """,
            (str(project_id), case_id, str(recording_id), version_id),
        )
    return case_id, version_id, recording_id, artifact_id


def _seed_artifact(connection: object, project_id: UUID, recording_id: UUID, artifact_id: UUID) -> None:
    job_id = str(uuid4())
    attempt_id = str(uuid4())
    connection.execute(  # type: ignore[attr-defined]
        """
        INSERT INTO jobs (
            project_id, job_id, purpose, recording_id, payload_hash, source_refs, limits, status
        ) VALUES (?, ?, 'recording', ?, 'hash-rx50', '[]', '{}', 'completed')
        """,
        (str(project_id), job_id, str(recording_id)),
    )
    connection.execute(  # type: ignore[attr-defined]
        """
        INSERT INTO attempts (project_id, attempt_id, job_id, generation, physical_key_id)
        VALUES (?, ?, ?, 1, NULL)
        """,
        (str(project_id), attempt_id, job_id),
    )
    connection.execute(  # type: ignore[attr-defined]
        """
        INSERT INTO artifact_refs (project_id, artifact_id, recording_id)
        VALUES (?, ?, ?)
        """,
        (str(project_id), str(artifact_id), str(recording_id)),
    )
    connection.execute(  # type: ignore[attr-defined]
        """
        INSERT INTO artifact_objects (
            project_id, artifact_id, object_key, content_hash, byte_length, media_type,
            owner_id, status, acked, custody, stored_at,
            owner_kind, attempt_id, action_id, check_id, role, job_id, generation
        ) VALUES (?, ?, ?, 'hash-rx50', 4, 'image/png', ?, 'ready', 1, 'stored', '2026-11-05T00:00:00+00:00',
            'REC', ?, NULL, NULL, 'source', ?, 1)
        """,
        (str(project_id), str(artifact_id), str(artifact_id), str(recording_id), attempt_id, job_id),
    )
