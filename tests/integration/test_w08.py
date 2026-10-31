"""W08 job queue tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import UUID

from aiqa.contracts.cases import CaseDefinition, CaseRevisionInput, CaseSettings, CheckSpec, PathPolicy, StepSpec
from aiqa.store.models import Actor, ProjectCreate


def test_w08_01(tmp_path: Path) -> None:
    import asyncio

    import httpx

    from aiqa.api.app import create_app
    from aiqa.config import load_settings
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.domain.versions import bind_case_store, create_case, save_case_revision
    from aiqa.contracts.jobs import JobSubmission
    from aiqa.store.database import migrate_store
    from aiqa.store.queue import enqueue_job

    assert callable(enqueue_job)
    root = tmp_path / "runtime"
    app = create_app(
        load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)})
    )
    owner = Actor(actor_id=UUID(int=1), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("Alpha", "w0801", "a", "web"))
    actor = Actor(owner.actor_id, project.project_id, True)
    with bind_case_store(store):
        case = create_case(actor, "Pay", None)
        version = save_case_revision(actor, case.case_id, _revision(), None)
    store.close()
    origin = "http://127.0.0.1:8000"
    body = {
        "purpose": "recording",
        "case_id": str(case.case_id),
        "case_version_id": str(version.id),
        "source_refs": [],
        "limits": {"timeout_seconds": 600},
    }
    changed = {**body, "limits": {"timeout_seconds": 1}}
    unknown = {**body, "purpose": "explore"}
    result = asyncio.run(_submit(app, origin, project.project_id, body, changed, unknown))
    restarted = create_app(
        load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)})
    )
    queued = asyncio.run(_read_job(restarted, origin, project.project_id, result["job_id"]))
    assert queued["status"] == "queued"
    assert queued["job_id"] == result["job_id"]
    assert queued["recording_id"] == result["recording_id"]
    _force_gap(root, project.project_id, case.case_id, version.id)
    with sqlite3.connect(root / "db" / "aiqa.sqlite") as connection:
        jobs = connection.execute(
            "SELECT COUNT(*) FROM jobs WHERE project_id = ? AND purpose = 'recording'",
            (str(project.project_id),),
        ).fetchone()
        partial = connection.execute(
            """
            SELECT
                (
                    SELECT COUNT(*) FROM recordings AS recording
                    WHERE NOT EXISTS (
                        SELECT 1 FROM jobs
                        WHERE jobs.project_id = recording.project_id
                          AND jobs.recording_id = recording.recording_id
                    )
                )
                +
                (
                    SELECT COUNT(*) FROM jobs
                    WHERE recording_id IS NOT NULL
                      AND NOT EXISTS (
                        SELECT 1 FROM recordings AS recording
                        WHERE recording.project_id = jobs.project_id
                          AND recording.recording_id = jobs.recording_id
                    )
                )
            """
        ).fetchone()
    assert jobs is not None and partial is not None
    observed = {
        "same_key_job_count": int(jobs[0]),
        "different_body_status": result["different_body_status"],
        "unknown_purpose_status": result["unknown_purpose_status"],
        "partial_owner_rows": int(partial[0]),
    }
    assert observed == {
        "same_key_job_count": 1,
        "different_body_status": 409,
        "unknown_purpose_status": 422,
        "partial_owner_rows": 0,
    }
    assert JobSubmission is not None


def _force_gap(root: Path, project_id: UUID, case_id: UUID, version_id: UUID) -> None:
    import sqlite3

    from aiqa.contracts.jobs import IdempotencyKey, JobSubmission
    from aiqa.store.database import StorageConfig, migrate_store, open_store
    from aiqa.store.models import Transaction
    from aiqa.store.queue import enqueue_job

    store = open_store(StorageConfig.from_settings(_settings(root)))
    migrate_store(store)
    try:
        with store.transaction() as connection:
            connection.execute(
                """
                CREATE TEMP TRIGGER abort_job_insert
                BEFORE INSERT ON jobs
                BEGIN
                    SELECT RAISE(ABORT, 'forced gap');
                END
                """
            )
            enqueue_job(
                Transaction(connection),
                JobSubmission(
                    project_id,
                    "recording",
                    case_id,
                    version_id,
                    (),
                    '{"timeout_seconds":600}',
                ),
                IdempotencyKey(UUID(int=2), project_id, "enqueue_job", "gap"),
            )
    except sqlite3.Error:
        return
    finally:
        store.close()
    raise AssertionError("recording and job did not roll back together")


def _settings(root: Path):
    from aiqa.config import load_settings

    return load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)})


async def _submit(
    app: object,
    origin: str,
    project_id: UUID,
    body: dict[str, object],
    changed: dict[str, object],
    unknown: dict[str, object],
) -> dict[str, object]:
    import httpx

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        session = await _session(client, origin, project_id, "w0801")
        first = await _send(client, session, "POST", f"/api/v1/projects/{project_id}/jobs", body, "same-body")
        second = await _send(client, session, "POST", f"/api/v1/projects/{project_id}/jobs", body, "same-body")
        conflict = await _send(client, session, "POST", f"/api/v1/projects/{project_id}/jobs", changed, "same-body")
        rejected = await _send(client, session, "POST", f"/api/v1/projects/{project_id}/jobs", unknown, "unknown")
    assert first.status_code == 202, first.text
    assert second.status_code == 200, second.text
    assert first.json()["job_id"] == second.json()["job_id"]
    assert first.json()["recording_id"] == second.json()["recording_id"]
    assert second.json()["replayed"] is True
    return {
        "job_id": first.json()["job_id"],
        "recording_id": first.json()["recording_id"],
        "different_body_status": conflict.status_code,
        "unknown_purpose_status": rejected.status_code,
    }


async def _read_job(app: object, origin: str, project_id: UUID, job_id: str) -> dict[str, object]:
    import httpx

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        session = await _session(client, origin, project_id, "w0801-again")
        loaded = await _send(
            client,
            session,
            "GET",
            f"/api/v1/projects/{project_id}/jobs/{job_id}",
            None,
            "read",
        )
    assert loaded.status_code == 200, loaded.text
    return loaded.json()


async def _session(client: object, origin: str, project_id: UUID, name: str) -> dict[str, str]:
    import httpx

    assert isinstance(client, httpx.AsyncClient)
    issued = await client.post(
        "/api/v1/session/nonces",
        json={"origin": origin, "project_id": str(project_id)},
        headers={"Idempotency-Key": f"{name}-nonce", "Origin": origin},
    )
    booted = await client.post(
        "/api/v1/session/bootstrap",
        json={"nonce": issued.json()["nonce"]},
        headers={"Idempotency-Key": f"{name}-boot", "Origin": origin},
    )
    return {"Origin": origin, "X-CSRF-Token": booted.json()["csrf_token"], "cookie": booted.cookies["aiqa_session"]}


async def _send(
    client: object,
    session: dict[str, str],
    method: str,
    path: str,
    payload: dict[str, object] | None,
    key: str,
) -> object:
    import httpx

    assert isinstance(client, httpx.AsyncClient)
    client.cookies.set("aiqa_session", session["cookie"])
    headers = {"Origin": session["Origin"], "X-CSRF-Token": session["X-CSRF-Token"], "Idempotency-Key": key}
    if method == "GET":
        return await client.get(path, headers=headers)
    return await client.post(path, json=payload, headers=headers)


def test_w08_02(tmp_path: Path) -> None:
    import asyncio
    import sqlite3
    import threading
    from uuid import uuid4

    import httpx

    from aiqa.api.app import create_app
    from aiqa.api.auth import bound_auth_store, enroll_worker
    from aiqa.config import load_settings
    from aiqa.contracts.jobs import IdempotencyKey, JobSubmission
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.domain.versions import bind_case_store, create_case, save_case_revision
    from aiqa.store.database import migrate_store
    from aiqa.store.models import Transaction
    from aiqa.store.queue import enqueue_job
    from aiqa.worker.service import claim_job

    assert callable(claim_job)
    root = tmp_path / "runtime"
    app = create_app(
        load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)})
    )
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project_a = create_project(owner, ProjectCreate("Alpha", "w0802a", "a", "web"))
        project_b = create_project(owner, ProjectCreate("Beta", "w0802b", "b", "web"))
    actor_a = Actor(owner.actor_id, project_a.project_id, True)
    actor_b = Actor(owner.actor_id, project_b.project_id, True)
    with bind_case_store(store):
        case_blocked = create_case(actor_a, "Blocked", None)
        version_blocked = save_case_revision(actor_a, case_blocked.case_id, _revision(), None)
        case_b = create_case(actor_b, "Beta", None)
        version_b = save_case_revision(actor_b, case_b.case_id, _revision(), None)
    worker_id = str(uuid4())
    with bound_auth_store(store):
        trial_a = enroll_worker(actor_a, worker_id, "trial")
        trial_b = enroll_worker(actor_b, worker_id, "trial")
        structure_a = enroll_worker(actor_a, worker_id, "structure")
        structure_b = enroll_worker(actor_b, worker_id, "structure")
    shared = str(uuid4())
    free = str(uuid4())
    with store.transaction() as connection:
        connection.execute(
            "INSERT INTO physical_resource_keys (physical_key_id, worker_id, native_id) VALUES (?, ?, ?)",
            (shared, worker_id, "SERIAL-W08-02"),
        )
        connection.execute(
            "INSERT INTO physical_resource_keys (physical_key_id, worker_id, native_id) VALUES (?, ?, ?)",
            (free, worker_id, "SERIAL-W08-02-FREE"),
        )
        connection.execute(
            """
            INSERT INTO resource_aliases (project_id, physical_key_id, display_name, target_kind)
            VALUES (?, ?, 'pixel-a', 'android'), (?, ?, 'pixel-b', 'android'), (?, ?, 'free-a', 'android')
            """,
            (str(project_a.project_id), shared, str(project_b.project_id), shared, str(project_a.project_id), free),
        )
        predecessor = _enqueue(
            connection,
            project_a.project_id,
            "trial",
            case_blocked.case_id,
            version_blocked.id,
            (shared,),
            "pred",
        )
        successor = _enqueue(
            connection,
            project_a.project_id,
            "trial",
            case_blocked.case_id,
            version_blocked.id,
            (free,),
            "next",
        )
        _enqueue(connection, project_b.project_id, "trial", case_b.case_id, version_b.id, (shared,), "beta")
        _enqueue(connection, project_a.project_id, "structure", None, None, ("mgmt-a",), "mgmt-a")
        _enqueue(connection, project_b.project_id, "structure", None, None, ("mgmt-b",), "mgmt-b")
        connection.execute(
            """
            UPDATE case_runs SET requested_at = ?
            WHERE project_id = ? AND case_run_id = ?
            """,
            ("2020-01-01T00:00:00+00:00", str(project_a.project_id), str(predecessor.case_run_id)),
        )
        connection.execute(
            """
            UPDATE executions SET scope_requested_at = ?
            WHERE project_id = ? AND execution_id = ?
            """,
            ("2020-01-01T00:00:00+00:00", str(project_a.project_id), str(predecessor.execution_id)),
        )
        connection.execute(
            "UPDATE jobs SET status = 'completed' WHERE project_id = ? AND job_id = ?",
            (str(project_a.project_id), str(predecessor.job_id)),
        )
        connection.execute(
            """
            INSERT INTO leases (project_id, job_id, generation, worker_id, physical_key_id, expires_at)
            VALUES (?, ?, 1, ?, ?, ?)
            """,
            (
                str(project_a.project_id),
                str(predecessor.job_id),
                worker_id,
                shared,
                "2026-11-01T00:00:30+00:00",
            ),
        )
    store.close()
    origin = "http://127.0.0.1:8000"
    refused = asyncio.run(_claim(app, origin, trial_a, "trial-a"))
    other_device = asyncio.run(_claim(app, origin, trial_b, "trial-b"))
    box: list[int] = []
    barrier = threading.Barrier(2)

    def race(token: str, key: str) -> None:
        barrier.wait(timeout=5)
        box.append(asyncio.run(_claim(app, origin, token, key)))

    first = threading.Thread(target=race, args=(structure_a, "slot-a"))
    second = threading.Thread(target=race, args=(structure_b, "slot-b"))
    first.start()
    second.start()
    first.join()
    second.join()
    with sqlite3.connect(root / "db" / "aiqa.sqlite") as connection:
        slots = connection.execute(
            """
            SELECT COUNT(*) FROM jobs
            WHERE status IN ('preparing', 'running', 'finalizing', 'cancel_requested')
            """
        ).fetchone()
        devices = connection.execute(
            "SELECT COUNT(*) FROM leases GROUP BY physical_key_id ORDER BY COUNT(*) DESC LIMIT 1"
        ).fetchone()
        doubled = connection.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT job_id FROM attempts GROUP BY project_id, job_id HAVING COUNT(*) > 1
            )
            """
        ).fetchone()
        successor_status = connection.execute(
            "SELECT status FROM jobs WHERE job_id = ?",
            (str(successor.job_id),),
        ).fetchone()
    assert slots is not None and devices is not None and doubled is not None and successor_status is not None
    assert refused == 204
    assert other_device == 204
    assert box.count(200) == 1
    observed = {
        "active_slots_max": int(slots[0]),
        "per_device_max": int(devices[0]),
        "double_claims": int(doubled[0]),
        "claim_before_cleanup": successor_status[0] != "queued",
    }
    assert observed == {
        "active_slots_max": 1,
        "per_device_max": 1,
        "double_claims": 0,
        "claim_before_cleanup": False,
    }


def test_w08_04(tmp_path: Path) -> None:
    import asyncio
    import sqlite3
    from uuid import uuid4

    from aiqa.api.app import create_app
    from aiqa.api.auth import bound_auth_store, enroll_worker
    from aiqa.config import load_settings
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.store.database import migrate_store
    from aiqa.worker.service import ingest_events

    assert callable(ingest_events)
    root = tmp_path / "runtime"
    app = create_app(
        load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)})
    )
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("Alpha", "w0804", "a", "web"))
    actor = Actor(owner.actor_id, project.project_id, True)
    with bound_auth_store(store):
        token = enroll_worker(actor, str(uuid4()), "structure")
    with store.transaction() as connection:
        _enqueue(connection, project.project_id, "structure", None, None, ("mgmt",), "w0804-job")
    store.close()
    origin = "http://127.0.0.1:8000"
    claimed = asyncio.run(
        _worker_post(app, origin, token, "/api/v1/worker/claims", {"now": "2026-11-01T01:00:00+00:00"}, "claim")
    )
    assert claimed.status_code == 200, claimed.text
    lease = claimed.json()
    common = {
        "project_id": lease["project_id"],
        "job_id": lease["job_id"],
        "generation": lease["generation"],
        "now": "2026-11-01T01:00:02+00:00",
    }
    attempt_id = lease["attempt_id"]
    gap = asyncio.run(
        _worker_post(
            app,
            origin,
            token,
            "/api/v1/worker/events",
            {**common, "events": [_event(attempt_id, 1, "one"), _event(attempt_id, 3, "three")]},
            "gap",
        )
    )
    filled = asyncio.run(
        _worker_post(
            app,
            origin,
            token,
            "/api/v1/worker/events",
            {**common, "events": [_event(attempt_id, 2, "two"), _event(attempt_id, 2, "two")]},
            "fill",
        )
    )
    replayed = asyncio.run(
        _worker_post(
            app,
            origin,
            token,
            "/api/v1/worker/events",
            {**common, "events": [_event(attempt_id, 3, "three")]},
            "same-3",
        )
    )
    changed = asyncio.run(
        _worker_post(
            app,
            origin,
            token,
            "/api/v1/worker/events",
            {**common, "events": [_event(attempt_id, 3, "other")]},
            "other-3",
        )
    )
    with sqlite3.connect(root / "db" / "aiqa.sqlite") as connection:
        connection.execute("UPDATE jobs SET status = 'completed' WHERE job_id = ?", (lease["job_id"],))
    late = asyncio.run(
        _worker_post(
            app,
            origin,
            token,
            "/api/v1/worker/events",
            {**common, "events": [_event(attempt_id, 4, "late")]},
            "late",
        )
    )
    assert gap.status_code == 200, gap.text
    assert filled.status_code == 200, filled.text
    assert replayed.status_code == 200, replayed.text
    assert late.status_code == 200, late.text
    observed = {
        "gap_ack_before_seq2": int(gap.json()["committed_seq"]),
        "contiguous_ack_after_seq2": int(replayed.json()["committed_seq"]),
        "changed_event_status": changed.status_code,
        "terminal_hash_unchanged": replayed.json()["committed_hash"] == late.json()["committed_hash"],
    }
    assert observed == {
        "gap_ack_before_seq2": 1,
        "contiguous_ack_after_seq2": 3,
        "changed_event_status": 409,
        "terminal_hash_unchanged": True,
    }


def _event(attempt_id: str, local_seq: int, name: str) -> dict[str, object]:
    from uuid import uuid5, NAMESPACE_URL

    return {
        "event_id": str(uuid5(NAMESPACE_URL, f"w0804-{local_seq}-{name}")),
        "attempt_id": attempt_id,
        "local_seq": local_seq,
        "captured_at": "2026-11-01T01:00:02+00:00",
        "event_type": "observation",
        "minimum_facts": "{}",
        "payload_hash": f"sha256:{name}",
        "body_hash": f"sha256:{name}",
    }


def test_w08_03(tmp_path: Path) -> None:
    import asyncio
    import sqlite3
    from datetime import datetime
    from uuid import uuid4

    from aiqa.api.app import create_app
    from aiqa.api.auth import bound_auth_store, enroll_worker
    from aiqa.config import load_settings
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.store.database import migrate_store
    from aiqa.worker.service import acknowledge_attempt, renew_lease

    assert callable(renew_lease) and callable(acknowledge_attempt)
    root = tmp_path / "runtime"
    app = create_app(
        load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)})
    )
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("Alpha", "w0803", "a", "web"))
    actor = Actor(owner.actor_id, project.project_id, True)
    worker_id = str(uuid4())
    with bound_auth_store(store):
        token = enroll_worker(actor, worker_id, "structure")
    with store.transaction() as connection:
        _enqueue(connection, project.project_id, "structure", None, None, ("mgmt",), "w0803-job")
    store.close()
    origin = "http://127.0.0.1:8000"
    start = "2026-11-01T01:00:00+00:00"
    claimed = asyncio.run(_worker_post(app, origin, token, "/api/v1/worker/claims", {"now": start}, "claim"))
    assert claimed.status_code == 200, claimed.text
    lease = claimed.json()
    nonce = str(uuid4())
    other = str(uuid4())
    body = {
        "project_id": lease["project_id"],
        "job_id": lease["job_id"],
        "generation": lease["generation"],
    }
    first = asyncio.run(
        _worker_post(
            app,
            origin,
            token,
            "/api/v1/worker/attempt-acks",
            {**body, "runner_nonce": nonce, "now": "2026-11-01T01:00:01+00:00"},
            "ack-1",
        )
    )
    delayed = asyncio.run(
        _worker_post(
            app,
            origin,
            token,
            "/api/v1/worker/attempt-acks",
            {**body, "runner_nonce": nonce, "now": "2026-11-01T01:00:04+00:00"},
            "ack-2",
        )
    )
    changed = asyncio.run(
        _worker_post(
            app,
            origin,
            token,
            "/api/v1/worker/attempt-acks",
            {**body, "runner_nonce": other, "now": "2026-11-01T01:00:05+00:00"},
            "ack-other",
        )
    )
    renewed = asyncio.run(
        _worker_post(
            app,
            origin,
            token,
            "/api/v1/worker/lease-renewals",
            {**body, "now": "2026-11-01T01:00:10+00:00", "model_wait": True},
            "heartbeat",
        )
    )
    assert renewed.status_code == 200, renewed.text
    renewed_at = datetime.fromisoformat(renewed.json()["expires_at"])
    heartbeat_now = datetime.fromisoformat("2026-11-01T01:00:10+00:00")
    stale = asyncio.run(
        _worker_post(
            app,
            origin,
            token,
            "/api/v1/worker/lease-renewals",
            {**body, "now": renewed.json()["expires_at"], "model_wait": False},
            "stale",
        )
    )
    with sqlite3.connect(root / "db" / "aiqa.sqlite") as connection:
        attempts = connection.execute(
            "SELECT COUNT(*) FROM attempts WHERE job_id = ?",
            (lease["job_id"],),
        ).fetchone()
    assert attempts is not None
    assert first.status_code == 200, first.text
    assert delayed.status_code == 200, delayed.text
    assert first.json()["attempt_id"] == delayed.json()["attempt_id"] == lease["attempt_id"]
    assert changed.status_code == 409
    observed = {
        "duplicate_ack_attempts": int(attempts[0]),
        "stale_generation_status": stale.status_code,
        "lease_seconds": int((renewed_at - heartbeat_now).total_seconds()),
        "heartbeat_seconds": int(renewed.json()["heartbeat_seconds"]),
    }
    assert observed == {
        "duplicate_ack_attempts": 1,
        "stale_generation_status": 409,
        "lease_seconds": 45,
        "heartbeat_seconds": 10,
    }


def test_w08_05(tmp_path: Path) -> None:
    import asyncio
    import sqlite3
    from datetime import datetime
    from uuid import uuid4

    from aiqa.api.app import create_app
    from aiqa.api.auth import bound_auth_store, enroll_worker
    from aiqa.api.lifecycle import start_api
    from aiqa.config import load_settings
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.store.database import migrate_store
    from aiqa.worker.service import reconcile_jobs

    assert callable(reconcile_jobs) and callable(start_api)
    root = tmp_path / "runtime"
    settings = load_settings(
        {"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}
    )
    app = create_app(settings)
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("Alpha", "w0805", "a", "web"))
    actor = Actor(owner.actor_id, project.project_id, True)
    worker_id = str(uuid4())
    with bound_auth_store(store):
        token = enroll_worker(actor, worker_id, "structure")
    with store.transaction() as connection:
        live = _enqueue(connection, project.project_id, "structure", None, None, ("live",), "w0805-live")
    store.close()
    origin = "http://127.0.0.1:8000"
    claimed = asyncio.run(
        _worker_post(app, origin, token, "/api/v1/worker/claims", {"now": "2026-11-01T01:00:00+00:00"}, "claim-live")
    )
    assert claimed.status_code == 200, claimed.text
    lease = claimed.json()
    acked = asyncio.run(
        _worker_post(
            app,
            origin,
            token,
            "/api/v1/worker/attempt-acks",
            {
                "project_id": lease["project_id"],
                "job_id": lease["job_id"],
                "generation": lease["generation"],
                "runner_nonce": str(uuid4()),
                "now": "2026-11-01T01:00:01+00:00",
            },
            "ack-live",
        )
    )
    assert acked.status_code == 200, acked.text
    physical = str(uuid4())
    dead_attempt = str(uuid4())
    reboot_attempt = str(uuid4())
    store = app.state.open_store()
    with store.transaction() as connection:
        queued = _enqueue(connection, project.project_id, "structure", None, None, ("queued",), "w0805-queued")
        dead = _enqueue(connection, project.project_id, "structure", None, None, ("dead",), "w0805-dead")
        reboot = _enqueue(connection, project.project_id, "structure", None, None, ("reboot",), "w0805-reboot")
        done = _enqueue(connection, project.project_id, "structure", None, None, ("done",), "w0805-done")
        connection.execute(
            "INSERT INTO physical_resource_keys (physical_key_id, worker_id, native_id) VALUES (?, ?, ?)",
            (physical, worker_id, "SERIAL-W08-05"),
        )
        connection.execute(
            "UPDATE jobs SET status = 'running' WHERE job_id = ?",
            (str(live.job_id),),
        )
        connection.execute(
            "UPDATE jobs SET status = 'completed' WHERE job_id = ?",
            (str(done.job_id),),
        )
        for job_id, attempt_id, key in (
            (dead.job_id, dead_attempt, None),
            (reboot.job_id, reboot_attempt, physical),
        ):
            connection.execute(
                "UPDATE jobs SET status = 'running' WHERE job_id = ?",
                (str(job_id),),
            )
            connection.execute(
                """
                INSERT INTO leases (
                    project_id, job_id, generation, worker_id, physical_key_id, expires_at
                ) VALUES (?, ?, 1, ?, ?, ?)
                """,
                (str(project.project_id), str(job_id), worker_id, key, "2026-11-01T01:10:00+00:00"),
            )
            connection.execute(
                """
                INSERT INTO attempts (project_id, attempt_id, job_id, generation, physical_key_id)
                VALUES (?, ?, ?, 1, ?)
                """,
                (str(project.project_id), attempt_id, str(job_id), key),
            )
        connection.execute(
            """
            INSERT INTO attempt_runners (project_id, attempt_id, runner_nonce, acked_at)
            VALUES (?, ?, ?, ?)
            """,
            (str(project.project_id), reboot_attempt, str(uuid4()), "2026-11-01T01:00:10+00:00"),
        )
        connection.execute(
            "INSERT INTO runner_hosts (project_id, attempt_id, boot_id) VALUES (?, ?, ?)",
            (str(project.project_id), reboot_attempt, "boot-from-previous-pc"),
        )
    store.close()
    now = datetime.fromisoformat("2026-11-01T01:00:20+00:00")
    start_api(settings, now)
    start_api(settings, now)
    with sqlite3.connect(root / "db" / "aiqa.sqlite") as connection:
        def status_of(job_id: UUID) -> str:
            row = connection.execute("SELECT status FROM jobs WHERE job_id = ?", (str(job_id),)).fetchone()
            assert row is not None
            return str(row[0])

        def attempts_of(job_id: UUID) -> int:
            row = connection.execute(
                "SELECT COUNT(*) FROM attempts WHERE job_id = ?",
                (str(job_id),),
            ).fetchone()
            assert row is not None
            return int(row[0])

        quarantine = connection.execute(
            "SELECT reason FROM resource_quarantine WHERE physical_key_id = ?",
            (physical,),
        ).fetchone()
        live_boot = connection.execute(
            """
            SELECT boot_id FROM runner_hosts
            WHERE attempt_id = (
                SELECT attempt_id FROM attempts WHERE job_id = ?
            )
            """,
            (str(live.job_id),),
        ).fetchone()
    assert live_boot is not None
    assert str(live_boot[0]) != "boot-from-previous-pc"
    assert status_of(live.job_id) == "running"
    assert attempts_of(live.job_id) == 1
    assert status_of(reboot.job_id) == "lost"
    assert attempts_of(reboot.job_id) == 1
    assert status_of(done.job_id) == "completed"
    observed = {
        "queued_preserved": status_of(queued.job_id) == "queued",
        "dead_runner_resumed": status_of(dead.job_id) in {
            "queued",
            "preparing",
            "running",
            "finalizing",
            "cancel_requested",
        }
        or attempts_of(dead.job_id) != 1,
        "expired_resource": "quarantined" if quarantine is not None else "open",
    }
    assert observed == {
        "queued_preserved": True,
        "dead_runner_resumed": False,
        "expired_resource": "quarantined",
    }


async def _worker_post(app: object, origin: str, token: str, path: str, payload: dict[str, object], key: str):
    import httpx

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        return await client.post(
            path,
            json=payload,
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": key},
        )


def _enqueue(
    connection: object,
    project_id: UUID,
    purpose: str,
    case_id: UUID | None,
    version_id: UUID | None,
    refs: tuple[str, ...],
    key: str,
):
    from aiqa.contracts.jobs import IdempotencyKey, JobSubmission
    from aiqa.store.models import Transaction
    from aiqa.store.queue import enqueue_job

    return enqueue_job(
        Transaction(connection),  # type: ignore[arg-type]
        JobSubmission(project_id, purpose, case_id, version_id, refs, "{}"),
        IdempotencyKey(UUID(int=8), project_id, "enqueue_job", key),
    )


async def _claim(app: object, origin: str, token: str, key: str) -> int:
    import httpx

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        response = await client.post(
            "/api/v1/worker/claims",
            json={"now": "2026-11-01T01:00:00+00:00"},
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": key},
        )
    return response.status_code


def _revision() -> CaseRevisionInput:
    definition = CaseDefinition(
        raw_text="pay",
        objective="pay",
        preconditions=("logged in",),
        variables={"amount": "1.10"},
        secret_refs={},
        steps=(StepSpec("step-1", "press pay", (CheckSpec("check-1", "text", "ok"),)),),
        final_expected=(),
        path_policy=PathPolicy(("pay",), ()),
    )
    return CaseRevisionInput(definition, CaseSettings("web"), (), None, None, "draft", False)
