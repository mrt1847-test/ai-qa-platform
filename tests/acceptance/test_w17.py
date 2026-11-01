"""Unapproved trial admission. A missing package or an AI key blocks the run."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from uuid import uuid4

from aiqa.store.models import Actor


def test_w17_01(tmp_path: Path) -> None:
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
        project = create_project(owner, ProjectCreate("시범", "w1701", "접수", "web"))
    store.close()
    project_id = str(project.project_id)
    bare_version, case_id = asyncio.run(_case(app, project_id))
    environment_id, resource_id = str(uuid4()), str(uuid4())
    ready_version, ai_version, package_id = _packages(root / "db" / "aiqa.sqlite", project_id, case_id, bare_version, environment_id, resource_id)
    ready = asyncio.run(_preview(app, project_id, ready_version, environment_id, resource_id, True))
    missing = asyncio.run(_preview(app, project_id, bare_version, environment_id, resource_id, True))
    blocked = asyncio.run(_preview(app, project_id, ai_version, environment_id, resource_id, False))
    created, replayed = asyncio.run(_enqueue_twice(app, project_id, ready))
    page = asyncio.run(_page(app, project_id, case_id))
    with sqlite3.connect(root / "db" / "aiqa.sqlite") as connection:
        approval = connection.execute(
            "SELECT current_approval_id FROM automation_cases WHERE case_id = ?",
            (case_id,),
        ).fetchone()[0]
        executions = connection.execute("SELECT COUNT(*) FROM executions").fetchone()[0]
        healing = connection.execute("SELECT limits FROM jobs WHERE purpose = 'trial'").fetchone()[0]
        secrets = connection.execute("SELECT COUNT(*) FROM secret_refs").fetchone()[0]
    observed = {
        "unapproved_ready_trial": ready["ready"] is True and approval is None and executions == 1,
        "no_package_trial": missing["ready"] is True,
        "trial_healing": json.loads(healing)["self_healing_enabled"],
        "deterministic_keyless": ready["ready"] is True and secrets == 0,
        "ai_required_keyless_blocked": blocked["ready"] is False
        and any(item["code"] == "MODEL_BINDING_UNAVAILABLE" for item in blocked["blockers"]),
    }
    assert created["replayed"] is False and replayed["replayed"] is True
    assert created["execution_id"] == replayed["execution_id"]
    assert ready["self_healing_enabled"] is False
    assert any(item["code"] == "PACKAGE_MISSING" for item in missing["blockers"])
    assert "시범" in page and "healing은 꺼져 있습니다." in page and "PASS" not in page
    assert package_id
    assert observed == {
        "unapproved_ready_trial": True,
        "no_package_trial": False,
        "trial_healing": False,
        "deterministic_keyless": True,
        "ai_required_keyless_blocked": True,
    }


async def _case(app: object, project_id: str) -> tuple[str, str]:
    import httpx

    origin = "http://127.0.0.1"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        headers = await _session(client, origin, project_id, "w1701-case")
        created = await client.post(
            f"/api/v1/projects/{project_id}/cases",
            json={"name": "로그인", "tc_reference": None},
            headers=headers,
        )
        headers["Idempotency-Key"] = "w1701-version"
        version = await client.post(
            f"/api/v1/projects/{project_id}/cases/{created.json()['case_id']}/versions",
            json={"definition": _definition(), "settings": {"target_kind": "web"}},
            headers=headers,
        )
    assert version.status_code == 201, version.text
    return version.json()["id"], created.json()["case_id"]


async def _preview(
    app: object, project_id: str, version_id: str, environment_id: str, resource_id: str, healing: bool
) -> dict[str, object]:
    import httpx

    origin = "http://127.0.0.1"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        headers = await _session(client, origin, project_id, f"w1701-preview-{version_id}")
        response = await client.post(
            f"/api/v1/projects/{project_id}/execution-previews",
            json=_selection(version_id, environment_id, resource_id, healing),
            headers=headers,
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert type(body) is dict
    return body


async def _enqueue_twice(app: object, project_id: str, preview: dict[str, object]) -> tuple[dict[str, object], dict[str, object]]:
    import httpx

    origin = "http://127.0.0.1"
    item = preview["resolved_items"][0]
    assert type(item) is dict
    body = {
        "name": "시범",
        "purpose": "trial",
        "source": "single",
        "failure_policy": "stop_on_non_pass",
        "self_healing_enabled": True,
        "preview_hash": preview["preview_hash"],
        "exclusions": [],
        "items": [item],
    }
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        headers = await _session(client, origin, project_id, "w1701-enqueue-session")
        headers["Idempotency-Key"] = "w1701-run"
        first = await client.post(f"/api/v1/projects/{project_id}/executions", json=body, headers=headers)
        second = await client.post(f"/api/v1/projects/{project_id}/executions", json=body, headers=headers)
    assert first.status_code == 201, first.text
    assert second.status_code == 200, second.text
    created, replayed = first.json(), second.json()
    assert type(created) is dict and type(replayed) is dict
    return created, replayed


async def _page(app: object, project_id: str, case_id: str) -> str:
    import httpx

    origin = "http://127.0.0.1"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        await _session(client, origin, project_id, "w1701-page")
        detail = await client.get(f"/ui/projects/{project_id}/cases/{case_id}/definition")
        setup = await client.get(f"/ui/projects/{project_id}/cases/{case_id}/execution-setup")
    assert detail.status_code == 200 and setup.status_code == 200
    assert "시범" in detail.text
    return setup.text


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


def _selection(version_id: str, environment_id: str, resource_id: str, healing: bool) -> dict[str, object]:
    return {
        "name": "시범",
        "purpose": "trial",
        "source": "single",
        "failure_policy": "stop_on_non_pass",
        "self_healing_enabled": healing,
        "exclusions": [],
        "selection": {
            "items": [
                {
                    "entry_id": "item-1",
                    "case_version_id": version_id,
                    "environment_revision_id": environment_id,
                    "resource_id": resource_id,
                    "install_policy": "none",
                }
            ]
        },
    }


def _definition() -> dict[str, object]:
    return {
        "raw_text": "",
        "objective": "",
        "preconditions": [],
        "variables": {},
        "secret_refs": {},
        "steps": [],
        "final_expected": [{"id": "exp-1", "kind": "text", "expected": "로그인됨"}],
        "path_policy": {"must_use": [], "forbidden": []},
    }


def _packages(
    database: Path, project_id: str, case_id: str, version_id: str, environment_id: str, resource_id: str
) -> tuple[str, str, str]:
    ready_version, ai_version, package_id, ai_package = str(uuid4()), str(uuid4()), str(uuid4()), str(uuid4())
    manifest_id, recording_id = str(uuid4()), str(uuid4())
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO worker_enrollments (enrollment_id, worker_id, project_id, created_at)
            VALUES ('enroll-w1701', 'worker-w1701', ?, '2026-11-01T00:00:00+00:00')
            """,
            (project_id,),
        )
        connection.execute(
            """
            INSERT INTO physical_resource_keys (physical_key_id, worker_id, native_id)
            VALUES (?, 'worker-w1701', 'native-w1701')
            """,
            (resource_id,),
        )
        connection.execute(
            """
            INSERT INTO resource_aliases (project_id, physical_key_id, display_name, target_kind)
            VALUES (?, ?, '브라우저', 'web')
            """,
            (project_id, resource_id),
        )
        connection.execute(
            """
            INSERT INTO environments (project_id, environment_id, name, next_revision, latest_revision_id)
            VALUES (?, 'env-w1701', '로컬', 2, ?)
            """,
            (project_id, environment_id),
        )
        connection.execute("INSERT INTO resource_inventory(physical_key_id,state,os_build,geometry,permissions,ime,observed_at) VALUES(?,'ready','','','[]','','2026-11-01')",(resource_id,))
        connection.execute(
            """
            INSERT INTO environment_revisions (
                project_id, environment_id, revision_id, revision, body_json, content_hash,
                actor_id, created_at
            ) VALUES (?, 'env-w1701', ?, 1, '{}', 'env-hash', 'actor', '2026-11-01T00:00:00+00:00')
            """,
            (project_id, environment_id),
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
            INSERT INTO recording_manifests (
                project_id, case_id, recording_id, manifest_id, revision, kind, prior_manifest_id,
                input_version_hash, source_artifact_hashes, action_mapping, evidence_completeness,
                request_key, body_hash
            ) VALUES (?, ?, ?, ?, 1, 'original', NULL, 'input-hash', '[]', '{}', 'complete', ?, 'manifest-hash')
            """,
            (project_id, case_id, recording_id, manifest_id, manifest_id),
        )
        names = [item[1] for item in connection.execute("PRAGMA table_info(case_versions)")]
        source = connection.execute(
            "SELECT * FROM case_versions WHERE version_id = ?",
            (version_id,),
        ).fetchone()
        values = dict(zip(names, source, strict=True))
        _insert_version(connection, names, values, ready_version, 2, manifest_id, package_id, None)
        _insert_package(connection, project_id, case_id, ready_version, package_id, manifest_id)
        ai_settings = json.loads(str(values["settings_json"]))
        ai_settings["verifier_bindings"] = [{"method": "ai_visual", "binding_id": "", "allow_unknown_supplement": False}]
        _insert_version(
            connection,
            names,
            values,
            ai_version,
            3,
            manifest_id,
            ai_package,
            json.dumps(ai_settings, ensure_ascii=False, separators=(",", ":")),
        )
        _insert_package(connection, project_id, case_id, ai_version, ai_package, manifest_id)
    return ready_version, ai_version, package_id


def _insert_version(
    connection: sqlite3.Connection,
    names: list[str],
    values: dict[str, object],
    version_id: str,
    revision: int,
    manifest_id: str,
    package_id: str,
    settings_json: str | None,
) -> None:
    copied = dict(values)
    copied["version_id"] = version_id
    copied["revision"] = revision
    copied["source_manifest_id"] = manifest_id
    copied["replay_package_id"] = package_id
    copied["is_branch"] = 1
    if settings_json is not None:
        copied["settings_json"] = settings_json
    connection.execute(
        f"INSERT INTO case_versions ({', '.join(names)}) VALUES ({', '.join('?' for _ in names)})",
        tuple(copied[name] for name in names),
    )


def _insert_package(
    connection: sqlite3.Connection, project_id: str, case_id: str, version_id: str, package_id: str, manifest_id: str
) -> None:
    connection.execute(
        """
        INSERT INTO replay_packages (
            project_id, package_id, case_id, case_version_id, ready, schema_version,
            source_manifest_id, source_manifest_hash, raw_source_hash, approved_code_hash,
            runtime_ref, compiler_ref, lock_hash, step_mapping_hash, body_hash
        ) VALUES (?, ?, ?, ?, 1, 'replay-package-v1', ?, 'manifest-hash', 'raw', 'code',
            'web', 'web-ipc-subset', 'lock', 'map', ?)
        """,
        (project_id, package_id, case_id, version_id, manifest_id, package_id),
    )
    connection.execute(
        """
        INSERT INTO package_version_links (project_id, case_id, version_id, package_id)
        VALUES (?, ?, ?, ?)
        """,
        (project_id, case_id, version_id, package_id),
    )
    connection.execute(
        """
        INSERT INTO package_steps (project_id, package_id, step_id, position, step_hash)
        VALUES (?, ?, 'step-1', 1, 'step-hash')
        """,
        (project_id, package_id),
    )
