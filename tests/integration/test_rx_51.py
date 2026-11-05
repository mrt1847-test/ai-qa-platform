"""RX-51: trial/regression claims pin package id/digest; worker uses claim not env."""

from __future__ import annotations

import binascii
import hashlib
import json
import sqlite3
import struct
import subprocess
import zlib
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from worker_presence_support import seed_presence

from aiqa.adapters.mobile_agent_android import MobileAgentAndroidAdapter, recording_broker
from aiqa.api.app import create_app
from aiqa.api.worker import _claim_payload
from aiqa.config import load_settings
from aiqa.contracts.actions import CaptureGeometry, Observation
from aiqa.contracts.jobs import ControlDecision
from aiqa.contracts.models import OwnedCheck, RoleBinding
from aiqa.domain.executions import validate_claim_snapshot
from aiqa.domain.projects import bind_store, create_project
from aiqa.models.broker import ModelBroker, ModelTransport
from aiqa.recording.manifests import RecordingFinishInput
from aiqa.recording.service import finish_recording, materialize_android_recording
from aiqa.replay.android_runner import AndroidDeterministicDriver
from aiqa.replay.packages import load_package_digest, resolve_claim_package_pin
from aiqa.store.database import migrate_store
from aiqa.store.models import Actor, JobSpec, ProjectCreate, WorkerScope
from aiqa.store.queue import claim_with_receipt
from aiqa.worker.android_jobs import (
    AndroidReplayContext,
    AndroidReplayHandler,
    resolve_claim_replay_pin,
)
from aiqa.worker.control import RemoteLeaseGuard
from aiqa.worker.dispatch_journal import DispatchJournal
from aiqa.worker.spool import EvidenceSpool


def _png(width: int = 100, height: int = 200) -> bytes:
    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body))
            + kind
            + body
            + struct.pack(">I", binascii.crc32(kind + body) & 0xFFFFFFFF)
        )

    row = b"\x00" + b"\x00" * width * 3
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(row * height))
        + chunk(b"IEND", b"")
    )


def _geometry(*, physical=(100, 200), model=(1000, 2000), rotation=0) -> CaptureGeometry:
    pw, ph = physical
    mw, mh = model
    return CaptureGeometry(pw, ph, mw, mh, "scale", rotation, (0, 0, pw, ph))


def _observation() -> Observation:
    geo = _geometry()
    return Observation(
        str(uuid4()),
        datetime.now(timezone.utc).isoformat(),
        geo,
        _png(geo.physical_width, geo.physical_height),
        '{"nodes":[{"locator":"#ok","text":"ok","value":"","state":"visible"}]}',
        "[]",
        (),
        "",
        True,
        "android",
    )


def _action(action: str, action_id: str, line: int) -> dict[str, object]:
    return {
        "kind": "action",
        "action": action,
        "intent": "open",
        "target": f"resource_id={action_id}",
        "action_id": action_id,
        "line": line,
        "geometry": {"rotation": 0, "content_bounds": [0, 0, 1000, 2000]},
    }


def _mapping(events: list[object]) -> str:
    return json.dumps({"events": events}, ensure_ascii=False, separators=(",", ":"))


class _Allow:
    def checkpoint(self) -> ControlDecision:
        return ControlDecision(True, "before_model")

    def allow_model_action(self, *, late: bool) -> ControlDecision:
        return ControlDecision(not late, "before_model")


class _Script(ModelTransport):
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, check_id: str) -> str:
        self.calls += 1
        return '{"status":"satisfied","reason":"ok"}'


def test_rx_51_claim_pins_packages_blocks_forge_and_ignores_env(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    app = create_app(
        load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)})
    )
    owner = Actor(uuid4(), None, True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("시범회귀", "rx51", "녹화", "android"))
        other = create_project(owner, ProjectCreate("다른프로젝트", "rx51b", "녹화", "android"))
    project_id = project.project_id
    other_id = other.project_id
    actor = Actor(owner.actor_id, project_id, True)
    database = root / "db" / "aiqa.sqlite"
    worker_id = "worker-rx51"
    resource_id = str(uuid4())
    now = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)

    case_a, version_a, pkg_a, digest_a = _seed_ready_case(
        app, store, project_id, actor, name="케이스A", key="rx51-a", events=[_action("tap", "a1", 1)]
    )
    case_b, version_b, pkg_b, digest_b = _seed_ready_case(
        app,
        store,
        project_id,
        actor,
        name="케이스B",
        key="rx51-b",
        events=[_action("tap", "b1", 1), _action("swipe", "b2", 2)],
    )
    assert digest_a != digest_b and pkg_a != pkg_b

    with store.transaction() as connection:
        connection.execute(
            "INSERT INTO worker_enrollments (enrollment_id, worker_id, project_id, created_at) VALUES (?, ?, ?, ?)",
            ("enroll-rx51", worker_id, str(project_id), now.isoformat()),
        )
        seed_presence(connection, str(project_id), worker_id, now=now)
        connection.execute(
            "INSERT INTO physical_resource_keys (physical_key_id, worker_id, native_id) VALUES (?, ?, ?)",
            (resource_id, worker_id, "emulator-5580"),
        )
        connection.execute(
            "INSERT INTO resource_aliases (project_id, physical_key_id, display_name, target_kind) VALUES (?, ?, ?, ?)",
            (str(project_id), resource_id, "AVD", "android"),
        )
        connection.execute(
            """
            INSERT INTO resource_inventory (
                physical_key_id, state, os_build, geometry, permissions, ime, observed_at
            ) VALUES (?, 'ready', '', '1000x2000@0', '[]', '', ?)
            """,
            (resource_id, now.isoformat()),
        )
        trial_job = _insert_replay_job(
            connection,
            project_id,
            purpose="trial",
            package_id=pkg_a,
            package_hash=digest_a,
            resource_id=resource_id,
            case_id=case_a,
            version_id=version_a,
            worker_id=worker_id,
            now=now,
        )
        regression_job = _insert_replay_job(
            connection,
            project_id,
            purpose="regression",
            package_id=pkg_b,
            package_hash=digest_b,
            resource_id=resource_id,
            case_id=case_b,
            version_id=version_b,
            worker_id=worker_id,
            now=now,
        )

        forged = JobSpec(
            project_id,
            UUID(trial_job),
            "trial",
            None,
            None,
            "payload",
            "[]",
            json.dumps(
                {
                    "replay_package_id": pkg_a,
                    "replay_package_hash": "sha256:forged",
                    "resource_id": resource_id,
                    "self_healing_enabled": False,
                }
            ),
            "queued",
        )
        missing = JobSpec(
            project_id,
            UUID(trial_job),
            "trial",
            None,
            None,
            "payload",
            "[]",
            json.dumps(
                {
                    "replay_package_id": str(uuid4()),
                    "replay_package_hash": digest_a,
                    "resource_id": resource_id,
                    "self_healing_enabled": False,
                }
            ),
            "queued",
        )
        foreign = JobSpec(
            other_id,
            UUID(trial_job),
            "trial",
            None,
            None,
            "payload",
            "[]",
            json.dumps(
                {
                    "replay_package_id": pkg_a,
                    "replay_package_hash": digest_a,
                    "resource_id": resource_id,
                    "self_healing_enabled": False,
                }
            ),
            "queued",
        )
        ok_spec = JobSpec(
            project_id,
            UUID(trial_job),
            "trial",
            None,
            None,
            "payload",
            "[]",
            json.dumps(
                {
                    "replay_package_id": pkg_a,
                    "replay_package_hash": digest_a,
                    "resource_id": resource_id,
                    "self_healing_enabled": False,
                }
            ),
            "queued",
        )
        assert validate_claim_snapshot(forged, connection).status == "BLOCKED"
        assert validate_claim_snapshot(missing, connection).status == "BLOCKED"
        assert validate_claim_snapshot(foreign, connection).status == "BLOCKED"
        assert validate_claim_snapshot(ok_spec, connection).status == "ALLOWED"
        assert resolve_claim_package_pin(
            connection,
            other_id,
            package_id=pkg_a,
            package_hash=digest_a,
            purpose="trial",
        ) is None

        worker = WorkerScope(worker_id, (project_id,), ("trial", "regression", "recording"))
        trial_claim = claim_with_receipt(
            connection, worker, now, request_key="rx51-trial", boot_id="fixture-boot"
        )
        assert trial_claim is not None
        trial_payload = _claim_payload(trial_claim, native_id="emulator-5580")
        trial_snap = trial_payload["snapshot"]
        assert isinstance(trial_snap, dict)
        assert trial_snap["purpose"] == "trial"
        assert trial_snap["replay_package_id"] == pkg_a
        assert trial_snap["replay_package_hash"] == digest_a
        assert trial_snap["approved_digest"] == digest_a
        assert trial_snap["self_healing_enabled"] is False
        assert "click(" in str(trial_snap.get("approved_plan") or "")

        _release_claim(connection, project_id, trial_job)
        regression_claim = claim_with_receipt(
            connection, worker, now, request_key="rx51-regression", boot_id="fixture-boot"
        )
        assert regression_claim is not None
        regression_payload = _claim_payload(regression_claim, native_id="emulator-5580")
        reg_snap = regression_payload["snapshot"]
        assert isinstance(reg_snap, dict)
        assert reg_snap["purpose"] == "regression"
        assert reg_snap["replay_package_id"] == pkg_b
        assert reg_snap["replay_package_hash"] == digest_b
        assert reg_snap["replay_package_id"] != trial_snap["replay_package_id"]
        assert reg_snap["replay_package_hash"] != trial_snap["replay_package_hash"]

    store.close()

    pin = resolve_claim_replay_pin(trial_snap)
    assert pin.package_hash == digest_a and pin.healing_enabled is False

    calls: list = []
    handler = _handler(tmp_path, calls, env_digest="sha256:env-wrong", healing_enabled=True)
    result = handler.handle(trial_payload)
    assert result.outcome == "completed" and result.actions == 1
    assert handler.authoring_calls_seen == 0
    assert handler.healer_calls == 0
    assert handler.package_digest_after == digest_a
    assert calls and calls[-1][4:8] == ("input", "tap", "50", "100")

    forged_claim = {
        **trial_payload,
        "snapshot": {
            **trial_snap,
            "approved_digest": "sha256:forged-live",
            "replay_package_hash": digest_a,
        },
    }
    denied = _handler(tmp_path / "forge", [], env_digest="sha256:env-wrong").handle(forged_claim)
    assert denied.actions == 0

    with sqlite3.connect(database) as connection:
        packages = connection.execute(
            "SELECT COUNT(DISTINCT body_hash) FROM replay_packages WHERE project_id = ? AND ready = 1",
            (str(project_id),),
        ).fetchone()
    observed = {
        "two_cases_two_packages": pkg_a != pkg_b and digest_a != digest_b,
        "claim_pins_differ": trial_snap["replay_package_hash"] != reg_snap["replay_package_hash"],
        "trial_healing_off": trial_snap["self_healing_enabled"] is False,
        "authoring_zero": handler.authoring_calls_seen == 0,
        "env_digest_ignored": result.actions == 1,
        "forge_blocked": denied.actions == 0,
        "distinct_ready_digests": int(packages[0]),
        "case_a": case_a,
        "case_b": case_b,
        "regression_job": regression_job,
    }
    assert observed == {
        "two_cases_two_packages": True,
        "claim_pins_differ": True,
        "trial_healing_off": True,
        "authoring_zero": True,
        "env_digest_ignored": True,
        "forge_blocked": True,
        "distinct_ready_digests": 2,
        "case_a": case_a,
        "case_b": case_b,
        "regression_job": regression_job,
    }


def _handler(
    tmp_path: Path,
    calls: list,
    *,
    env_digest: str,
    healing_enabled: bool = False,
) -> AndroidReplayHandler:
    def runner(argv, timeout):
        calls.append(tuple(argv))
        return subprocess.CompletedProcess(list(argv), 0, b"", b"")

    verify_broker = ModelBroker(
        "item-1",
        (RoleBinding("verification", 1, "fixture-v", "ref"), RoleBinding("healing", 1, "fixture-h", "ref")),
        (OwnedCheck("check-1", "item-1"),),
        (),
    )
    return AndroidReplayHandler(
        adapter=MobileAgentAndroidAdapter(),
        driver=AndroidDeterministicDriver(
            Path("C:/platform-tools/adb.exe"),
            "emulator-5580",
            runner=runner,
            spool=EvidenceSpool(tmp_path / "spool"),
        ),
        broker=recording_broker(),
        guard=RemoteLeaseGuard(),
        journal=DispatchJournal(tmp_path / "journal.jsonl"),
        spool=EvidenceSpool(tmp_path / "evidence"),
        context=AndroidReplayContext(
            expected_serial="emulator-5580",
            approved_digest=env_digest,
            approved_plan="click(1, 1)",
            before=_observation(),
            after=_observation(),
            lease_remaining_seconds=60.0,
            mono_seconds=100.0,
            healing_enabled=healing_enabled,
            heal_budget_remaining=0,
            checks=(),
            verify_broker=verify_broker,
            verify_transport=_Script(),
            verify_control=_Allow(),
        ),
    )


def _seed_ready_case(
    app: object,
    store: object,
    project_id: UUID,
    actor: Actor,
    *,
    name: str,
    key: str,
    events: list[object],
) -> tuple[str, str, str, str]:
    import asyncio

    import httpx

    async def create() -> tuple[str, str]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            origin = "http://127.0.0.1"
            nonce = await client.post(
                "/api/v1/session/nonces",
                json={"origin": origin, "project_id": str(project_id)},
                headers={"Origin": origin, "Idempotency-Key": f"{key}-nonce"},
            )
            boot = await client.post(
                "/api/v1/session/bootstrap",
                json={"nonce": nonce.json()["nonce"]},
                headers={"Origin": origin, "Idempotency-Key": f"{key}-boot"},
            )
            headers = {
                "Origin": origin,
                "X-CSRF-Token": boot.json()["csrf_token"],
                "Idempotency-Key": f"{key}-case",
            }
            created = await client.post(
                f"/api/v1/projects/{project_id}/cases",
                json={"name": name, "tc_reference": None},
                headers=headers,
            )
            case_id = created.json()["case_id"]
            version = await client.post(
                f"/api/v1/projects/{project_id}/cases/{case_id}/versions",
                json={
                    "definition": {
                        "raw_text": name,
                        "objective": name,
                        "preconditions": [],
                        "variables": {},
                        "secret_refs": {},
                        "steps": [{"id": "s1", "instruction": "tap", "point": [1, 2], "expected": []}],
                        "final_expected": [{"id": "exp-1", "kind": "text", "expected": "ok"}],
                        "path_policy": {"must_use": [], "forbidden": []},
                    },
                    "settings": {
                        "target_kind": "android",
                        "android_package": "com.example.app",
                        "limits": {"timeout_seconds": 60},
                    },
                },
                headers={**headers, "Idempotency-Key": f"{key}-version"},
            )
            return case_id, version.json()["id"]

    case_id, version_id = asyncio.run(create())
    recording_id = uuid4()
    artifact_id = uuid4()
    mapping = _mapping(events)
    digest = hashlib.sha256(mapping.encode("utf-8")).hexdigest()
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
        job_id = str(uuid4())
        attempt_id = str(uuid4())
        connection.execute(
            """
            INSERT INTO jobs (
                project_id, job_id, purpose, recording_id, payload_hash, source_refs, limits, status
            ) VALUES (?, ?, 'recording', ?, ?, '[]', '{}', 'completed')
            """,
            (str(project_id), job_id, str(recording_id), f"hash-{key}"),
        )
        connection.execute(
            """
            INSERT INTO attempts (project_id, attempt_id, job_id, generation, physical_key_id)
            VALUES (?, ?, ?, 1, NULL)
            """,
            (str(project_id), attempt_id, job_id),
        )
        connection.execute(
            "INSERT INTO artifact_refs (project_id, artifact_id, recording_id) VALUES (?, ?, ?)",
            (str(project_id), str(artifact_id), str(recording_id)),
        )
        connection.execute(
            """
            INSERT INTO artifact_objects (
                project_id, artifact_id, object_key, content_hash, byte_length, media_type,
                owner_id, status, acked, custody, stored_at,
                owner_kind, attempt_id, action_id, check_id, role, job_id, generation
            ) VALUES (?, ?, ?, ?, 4, 'image/png', ?, 'ready', 1, 'stored', '2026-11-05T00:00:00+00:00',
                      'REC', ?, NULL, NULL, 'source', ?, 1)
            """,
            (
                str(project_id),
                str(artifact_id),
                str(artifact_id),
                f"hash-{key}",
                str(recording_id),
                attempt_id,
                job_id,
            ),
        )
        finished = finish_recording(
            connection,
            actor,
            project_id,
            RecordingFinishInput(
                recording_id,
                "completed",
                2,
                (str(artifact_id),),
                f"{key}-finish",
                mapping,
            ),
        )
        materialized = materialize_android_recording(
            connection, actor, project_id, finished.manifest_id
        )
        assert materialized.replay_package_id is not None
        package_id = str(materialized.replay_package_id)
        body_hash = load_package_digest(connection, project_id, materialized.replay_package_id)
        assert body_hash is not None
    return case_id, version_id, package_id, body_hash


def _insert_replay_job(
    connection: object,
    project_id: UUID,
    *,
    purpose: str,
    package_id: str,
    package_hash: str,
    resource_id: str,
    case_id: str,
    version_id: str,
    worker_id: str,
    now: datetime,
) -> str:
    job_id = str(uuid4())
    case_run_id = str(uuid4())
    execution_id = str(uuid4())
    limits = json.dumps(
        {
            "replay_package_id": package_id,
            "replay_package_hash": package_hash,
            "resource_id": resource_id,
            "self_healing_enabled": False,
            "case_version_id": version_id,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    connection.execute(  # type: ignore[attr-defined]
        """
        INSERT INTO executions (
            project_id, execution_id, name, purpose, source, suite_version_id, scope_requested_at
        ) VALUES (?, ?, ?, ?, 'single', NULL, ?)
        """,
        (str(project_id), execution_id, purpose, purpose, now.isoformat()),
    )
    connection.execute(  # type: ignore[attr-defined]
        """
        INSERT INTO case_runs (
            project_id, execution_id, case_run_id, case_id, case_version_id, purpose, requested_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (str(project_id), execution_id, case_run_id, case_id, version_id, purpose, now.isoformat()),
    )
    connection.execute(  # type: ignore[attr-defined]
        """
        INSERT INTO jobs (
            project_id, job_id, purpose, case_run_id, payload_hash, source_refs, limits, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'queued')
        """,
        (str(project_id), job_id, purpose, case_run_id, f"payload-{purpose}", json.dumps([resource_id]), limits),
    )
    return job_id


def _release_claim(connection: object, project_id: UUID, job_id: str) -> None:
    connection.execute(  # type: ignore[attr-defined]
        "DELETE FROM leases WHERE project_id = ? AND job_id = ?",
        (str(project_id), job_id),
    )
    connection.execute(  # type: ignore[attr-defined]
        "UPDATE jobs SET status = 'completed' WHERE project_id = ? AND job_id = ?",
        (str(project_id), job_id),
    )
