"""W09 cancel flag tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import UUID


def test_w09_01(tmp_path: Path) -> None:
    import asyncio
    import threading
    from uuid import uuid4

    from aiqa.api.app import create_app
    from aiqa.config import load_settings
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.store.database import migrate_store
    from aiqa.store.models import Actor, ProjectCreate
    from aiqa.store.queue import cancel_job, finish_job
    from aiqa.worker.control import RunControl

    assert callable(cancel_job) and callable(RunControl.checkpoint)
    root = tmp_path / "runtime"
    app = create_app(
        load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)})
    )
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("Alpha", "w0901", "a", "web"))
    project_id = project.project_id
    with store.transaction() as connection:
        waiting = _enqueue(connection, project_id, "w0901-wait")
        racing = _enqueue(connection, project_id, "w0901-race")
        done = _enqueue(connection, project_id, "w0901-done")
        connection.execute("UPDATE jobs SET status = 'running' WHERE job_id = ?", (str(waiting.job_id),))
        connection.execute("UPDATE jobs SET status = 'running' WHERE job_id = ?", (str(racing.job_id),))
        connection.execute("UPDATE jobs SET status = 'completed' WHERE job_id = ?", (str(done.job_id),))
    store.close()
    origin = "http://127.0.0.1:8000"
    first, replay, changed, terminal = asyncio.run(
        _cancels(app, origin, project_id, waiting.job_id, done.job_id)
    )
    assert first.status_code == 202, first.text
    assert replay.status_code == 200, replay.text
    assert first.json()["status"] == replay.json()["status"] == "cancel_requested"
    assert replay.json()["replayed"] is True
    assert first.json()["runner_stopped"] is False
    assert first.json()["cleanup_completed"] is False
    assert changed.status_code == 409
    assert terminal.status_code == 409
    store = app.state.open_store()
    with store.transaction() as connection:
        late = 0
        for phase in ("before_model", "after_model", "before_lookup", "before_dispatch"):
            decision = RunControl(connection, project_id, waiting.job_id, phase).checkpoint()
            if decision.allowed:
                late += 1
        assert _status(connection, done.job_id) == "completed"
    store.close()
    barrier = threading.Barrier(2)
    box: list[object] = []
    race_session = asyncio.run(_open_session(app, origin, project_id, "race-key"))

    def _finish() -> None:
        barrier.wait(timeout=5)
        raced = app.state.open_store()
        try:
            with raced.transaction() as connection:
                finish_job(connection, project_id, racing.job_id)
        finally:
            raced.close()

    def _cancel() -> None:
        barrier.wait(timeout=5)
        box.append(
            asyncio.run(_send_cancel(app, origin, race_session, project_id, racing.job_id, "running", "race-key"))
        )

    left = threading.Thread(target=_finish)
    right = threading.Thread(target=_cancel)
    left.start()
    right.start()
    left.join()
    right.join()
    assert box
    with sqlite3.connect(root / "db" / "aiqa.sqlite") as connection:
        persisted = connection.execute(
            "SELECT COUNT(*) FROM job_cancellations WHERE job_id = ?",
            (str(waiting.job_id),),
        ).fetchone()
        after_race = connection.execute(
            "SELECT status FROM jobs WHERE job_id = ?",
            (str(racing.job_id),),
        ).fetchone()
        waiting_status = connection.execute(
            "SELECT status FROM jobs WHERE job_id = ?",
            (str(waiting.job_id),),
        ).fetchone()
    assert persisted is not None and after_race is not None and waiting_status is not None
    store = app.state.open_store()
    with store.transaction() as connection:
        finish_job(connection, project_id, racing.job_id)
    store.close()
    again = asyncio.run(
        _send_cancel(app, origin, race_session, project_id, racing.job_id, "running", "race-key")
    )
    with sqlite3.connect(root / "db" / "aiqa.sqlite") as connection:
        later = connection.execute(
            "SELECT status FROM jobs WHERE job_id = ?",
            (str(racing.job_id),),
        ).fetchone()
    assert later is not None
    observed = {
        "late_response_dispatches": late,
        "cancel_persisted": int(persisted[0]) == 1 and str(waiting_status[0]) == "cancel_requested",
        "terminal_result_changed": str(after_race[0]) != str(later[0]) or again.status_code not in {200, 202, 409},
    }
    assert observed == {
        "late_response_dispatches": 0,
        "cancel_persisted": True,
        "terminal_result_changed": False,
    }


def test_w09_02(tmp_path: Path) -> None:
    from uuid import uuid4

    from aiqa.api.app import create_app
    from aiqa.config import load_settings
    from aiqa.contracts.jobs import LeaseView
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.store.database import migrate_store
    from aiqa.store.models import Actor, ProjectCreate
    from aiqa.worker.control import RunControl
    from aiqa.worker.runner import AttemptRunner, MonotonicInstant

    assert callable(RunControl.authorize_next_action)
    root = tmp_path / "runtime"
    app = create_app(
        load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)})
    )
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("Alpha", "w0902", "a", "web"))
    project_id = project.project_id
    with store.transaction() as connection:
        waiting = _enqueue(connection, project_id, "w0902-job")
        connection.execute("UPDATE jobs SET status = 'running' WHERE job_id = ?", (str(waiting.job_id),))
    store.close()
    store = app.state.open_store()
    with store.transaction() as connection:
        def control(runner: AttemptRunner | None = None, phase: str = "before_dispatch") -> RunControl:
            return RunControl(connection, project_id, waiting.job_id, phase, runner or AttemptRunner())

        def lease(expires: str) -> LeaseView:
            return LeaseView(project_id, waiting.job_id, 1, expires, 45, 10, 2)

        at_29 = control().authorize_next_action(MonotonicInstant(29), lease("100"))
        at_30 = control().authorize_next_action(MonotonicInstant(30), lease("100"))
        margin_10 = control().authorize_next_action(MonotonicInstant(0), lease("10"))
        margin_9 = control().authorize_next_action(MonotonicInstant(0), lease("9"))
        runner = AttemptRunner()
        limited = control(runner)
        dispatched = 0
        for _ in range(51):
            if limited.authorize_next_action(MonotonicInstant(1), lease("100")).allowed:
                dispatched += 1
        limited.record_transport_retry()
        limited.record_model_retry()
        lookup = control(runner, "before_lookup").authorize_next_action(MonotonicInstant(1), lease("100"))
        long_runner = AttemptRunner()
        long_runner.note_heartbeat(MonotonicInstant(600))
        blocked_attempt = control(long_runner).authorize_next_action(MonotonicInstant(600), lease("1000"))
        early_runner = AttemptRunner()
        early_runner.note_heartbeat(MonotonicInstant(599))
        open_attempt = control(early_runner).authorize_next_action(MonotonicInstant(599), lease("1000"))
        model_runner = AttemptRunner()
        model_runner.note_heartbeat(MonotonicInstant(1))
        models = control(model_runner, "before_model")
        model_dispatched = 0
        for _ in range(81):
            if models.authorize_next_action(MonotonicInstant(1), lease("100")).allowed:
                model_dispatched += 1
    store.close()
    assert dispatched == 50
    assert lookup.allowed is True
    assert runner.actions == 50
    assert blocked_attempt.allowed is False
    assert open_attempt.allowed is True
    assert model_dispatched == 80
    observed = {
        "watchdog_seconds": 30 if at_29.allowed and not at_30.allowed else 0,
        "minimum_lease_margin": 10 if margin_10.allowed and not margin_9.allowed else 0,
        "action51_dispatched": dispatched >= 51,
        "automatic_attempt_retries": limited.attempt_retries,
    }
    assert observed == {
        "watchdog_seconds": 30,
        "minimum_lease_margin": 10,
        "action51_dispatched": False,
        "automatic_attempt_retries": 0,
    }


def test_w09_03() -> None:
    import inspect
    import subprocess
    import sys
    from uuid import uuid4

    from aiqa.worker.processes import spawn_owned_sleeper
    from aiqa.worker.runner import cleanup_attempt, stop_runner

    assert callable(stop_runner) and callable(cleanup_attempt)
    attempt_id = uuid4()
    owned = spawn_owned_sleeper(attempt_id)
    unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    try:
        stopped = stop_runner(attempt_id, grace_seconds=0)
        owned.wait(timeout=5)
        unrelated_alive = unrelated.poll() is None

        class FailingContext:
            def close_context(self) -> None:
                raise RuntimeError("ime failed")

        cleaned = cleanup_attempt(attempt_id, provider=FailingContext())
    finally:
        if unrelated.poll() is None:
            unrelated.kill()
        unrelated.wait(timeout=5)
    assert owned.poll() is not None
    assert stopped.grace_seconds == 0
    observed = {
        "cancel_grace": inspect.signature(stop_runner).parameters["grace_seconds"].default,
        "cleanup_limit": inspect.signature(cleanup_attempt).parameters["deadline_seconds"].default,
        "unrelated_processes_killed": 0 if unrelated_alive else 1,
        "unproven_resource": "quarantined" if cleaned.quarantined and not cleaned.released else "ready",
    }
    assert observed == {
        "cancel_grace": 5,
        "cleanup_limit": 30,
        "unrelated_processes_killed": 0,
        "unproven_resource": "quarantined",
    }


def _status(connection: object, job_id: UUID) -> str:
    assert hasattr(connection, "execute")
    row = connection.execute("SELECT status FROM jobs WHERE job_id = ?", (str(job_id),)).fetchone()
    assert row is not None
    return str(row[0])


def _enqueue(connection: object, project_id: UUID, key: str):
    from aiqa.contracts.jobs import IdempotencyKey, JobSubmission
    from aiqa.store.models import Transaction
    from aiqa.store.queue import enqueue_job

    return enqueue_job(
        Transaction(connection),  # type: ignore[arg-type]
        JobSubmission(project_id, "structure", None, None, ("mgmt",), "{}"),
        IdempotencyKey(UUID(int=9), project_id, "enqueue_job", key),
    )


async def _cancels(app: object, origin: str, project_id: UUID, waiting: UUID, done: UUID):
    import httpx

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        session = await _session(client, origin, project_id, "w0901")
        first = await _send(client, session, project_id, waiting, {"expected_state": "running"}, "cancel-wait")
        replay = await _send(client, session, project_id, waiting, {"expected_state": "running"}, "cancel-wait")
        changed = await _send(client, session, project_id, waiting, {"expected_state": "queued"}, "cancel-wait")
        terminal = await _send(client, session, project_id, done, {"expected_state": "completed"}, "cancel-done")
    return first, replay, changed, terminal


async def _open_session(app: object, origin: str, project_id: UUID, name: str) -> dict[str, str]:
    import httpx

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        return await _session(client, origin, project_id, name)


async def _send_cancel(
    app: object,
    origin: str,
    session: dict[str, str],
    project_id: UUID,
    job_id: UUID,
    expected: str,
    key: str,
):
    import httpx

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        return await _send(client, session, project_id, job_id, {"expected_state": expected}, key)


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
    project_id: UUID,
    job_id: UUID,
    payload: dict[str, str],
    key: str,
):
    import httpx

    assert isinstance(client, httpx.AsyncClient)
    client.cookies.set("aiqa_session", session["cookie"])
    return await client.post(
        f"/api/v1/projects/{project_id}/jobs/{job_id}/cancellations",
        json=payload,
        headers={
            "Origin": session["Origin"],
            "X-CSRF-Token": session["X-CSRF-Token"],
            "Idempotency-Key": key,
        },
    )
