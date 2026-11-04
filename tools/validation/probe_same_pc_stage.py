"""Check a same-PC management API and worker over real TLS with disposable data."""

from __future__ import annotations

import argparse
import json
import os
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
import socket
import sqlite3
import ssl
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from uuid import uuid4

import httpx

from aiqa.api.auth import bound_auth_store, enroll_worker
from aiqa.config import load_settings
from aiqa.contracts.cases import CaseDefinition, CaseRevisionInput, CaseSettings, PathPolicy
from aiqa.contracts.jobs import IdempotencyKey, JobSubmission
from aiqa.domain.projects import bind_store, create_project
from aiqa.domain.versions import bind_case_store, create_case, save_case_revision
from aiqa.store.database import StorageConfig, migrate_store, open_store
from aiqa.store.models import Actor, ProjectCreate, Transaction
from aiqa.store.queue import enqueue_job
from aiqa.worker.presence import OFFLINE_AFTER, get_presence


def temporary_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


@contextmanager
def child(args, *, env, cwd):
    process = subprocess.Popen(
        [sys.executable, "-B", *args],
        env=env, cwd=cwd, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        yield process
    finally:
        if process.poll() is None:
            if os.name == "nt":
                # The Windows venv executable launches a child interpreter.
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8, check=False,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            else:
                process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=8)


def wait_for(probe, process, seconds: float, label: str):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"{label}: process exited with code {process.returncode}")
        result = probe()
        if result:
            return result
        time.sleep(0.25)
    raise RuntimeError(f"{label}: timed out after {seconds} seconds")


def run_probe(args, root: Path) -> dict:
    base_env = {key: value for key, value in os.environ.items() if not key.startswith("AIQA_")}
    port = args.port or temporary_port()
    origin = f"https://127.0.0.1:{port}"
    server_root, worker_root = root / "server", root / "worker"
    server_root.mkdir()
    worker_root.mkdir()
    settings = {
        "AIQA_HOST": "127.0.0.1", "AIQA_PORT": str(port),
        "AIQA_RUNTIME_ROOT": str(server_root), "AIQA_PROFILE": "local",
    }
    storage = StorageConfig.from_settings(load_settings(settings))
    worker_id = str(uuid4())
    boot_id = uuid4().hex
    purpose = "recording" if args.mode == "recording" else "resource_probe"
    store = open_store(storage)
    try:
        migrate_store(store)
        owner = Actor(uuid4(), None, True)
        with bind_store(store):
            project = create_project(owner, ProjectCreate("Same PC probe", "same-pc", "", "android"))
        actor = Actor(owner.actor_id, project.project_id, True)
        with bound_auth_store(store):
            token = enroll_worker(actor, worker_id, purpose)
        case = None
        version = None
        if args.mode == "recording":
            with bind_case_store(store):
                case = create_case(actor, "SamePC", None)
                version = save_case_revision(
                    actor,
                    case.case_id,
                    CaseRevisionInput(
                        CaseDefinition("open", "open", (), {}, {}, (), (), PathPolicy()),
                        CaseSettings("android"),
                    ),
                    None,
                )
    finally:
        store.close()

    worker_env = {
        **base_env,
        "AIQA_MANAGEMENT_BASE_URL": origin, "AIQA_WORKER_TOKEN": token,
        "AIQA_WORKER_CA_BUNDLE": str(args.ca), "AIQA_WORKER_BOOT_ID": boot_id,
        "AIQA_WORKER_PROJECT_ID": str(project.project_id), "AIQA_ADB_PATH": str(args.adb),
        "AIQA_ANDROID_SERIAL": args.serial, "AIQA_ANDROID_AVD": args.avd,
        "AIQA_WORKER_RUNTIME_ROOT": str(worker_root / "runtime"),
    }
    if args.mode == "recording":
        worker_env["AIQA_WORKER_MODEL_MODE"] = "fixture"
        worker_env["AIQA_WORKER_FIXTURE_RESPONSE"] = args.fixture_response
    tls = ssl.create_default_context(cafile=str(args.ca))
    db_uri = storage.database_path.as_uri() + "?mode=ro"
    artifacts_dir = storage.artifacts_dir

    def device_row():
        with closing(sqlite3.connect(db_uri, uri=True)) as connection:
            presence = get_presence(connection, worker_id, datetime.now(timezone.utc), project_id=project.project_id)
            row = connection.execute(
                """SELECT inventory.state, inventory.geometry, resource.physical_key_id
                   FROM resource_inventory AS inventory
                   JOIN physical_resource_keys AS resource USING (physical_key_id)
                   JOIN resource_aliases AS alias USING (physical_key_id)
                   WHERE alias.project_id = ? AND resource.worker_id = ? AND resource.native_id = ?""",
                (str(project.project_id), worker_id, args.serial),
            ).fetchone()
            return presence, row

    command = [
        "-m", "uvicorn", "aiqa.api.app:create_app", "--factory", "--host", "127.0.0.1",
        "--port", str(port), "--ssl-certfile", str(args.cert), "--ssl-keyfile", str(args.key),
        "--no-proxy-headers",
    ]
    with child(command, env={**base_env, **settings}, cwd=server_root) as api:
        with httpx.Client(base_url=origin, verify=tls, trust_env=False, timeout=2) as client:
            def healthy():
                try:
                    return client.get("/api/v1/health").status_code == 200
                except httpx.TransportError:
                    return False

            wait_for(healthy, api, 20, "TLS health")
            with child(["-m", "aiqa.launcher", "worker"], env=worker_env, cwd=worker_root) as worker:
                expected_state = "ready" if args.mode == "recording" else "offline"

                def registered():
                    presence, row = device_row()
                    if presence.boot_id == boot_id and presence.state == "online" and row:
                        return row
                    return None

                state, geometry, physical_key = wait_for(registered, worker, 60, "Android inventory")
                if state != expected_state or "x" not in geometry or "@" not in geometry:
                    raise RuntimeError(
                        f"Expected inventory state {expected_state} with geometry, got {state}/{geometry}"
                    )
                result = {
                    "api_pid": api.pid,
                    "worker_pid": worker.pid,
                    "tls_verified": True,
                    "android_serial": args.serial,
                    "geometry": geometry,
                    "inventory_state": state,
                    "mode": args.mode,
                }
                if args.mode == "recording":
                    now = datetime.now(timezone.utc)
                    store = open_store(storage)
                    try:
                        with store.transaction() as connection:
                            receipt = enqueue_job(
                                Transaction(connection),
                                JobSubmission(
                                    project.project_id,
                                    "recording",
                                    case.case_id,
                                    version.id,
                                    (str(physical_key),),
                                    "{}",
                                ),
                                IdempotencyKey(
                                    actor.actor_id, project.project_id, "enqueue_job", "same-pc-rec"
                                ),
                                now=now,
                            )
                        recording_id = str(receipt.recording_id)
                    finally:
                        store.close()

                    def recording_done():
                        with closing(sqlite3.connect(db_uri, uri=True)) as connection:
                            rec = connection.execute(
                                """
                                SELECT completion_status, evidence_status, stop_status
                                FROM recordings
                                WHERE project_id = ? AND recording_id = ?
                                """,
                                (str(project.project_id), recording_id),
                            ).fetchone()
                            objects = connection.execute(
                                """
                                SELECT artifact_id, object_key, byte_length, role, status, acked
                                FROM artifact_objects
                                WHERE project_id = ?
                                ORDER BY role
                                """,
                                (str(project.project_id),),
                            ).fetchall()
                            refs = connection.execute(
                                "SELECT COUNT(*) FROM artifact_refs WHERE project_id = ?",
                                (str(project.project_id),),
                            ).fetchone()[0]
                            actions = connection.execute(
                                "SELECT COUNT(*) FROM actions WHERE project_id = ?",
                                (str(project.project_id),),
                            ).fetchone()[0]
                            finish = connection.execute(
                                """
                                SELECT response_body FROM attempt_finish_requests
                                WHERE project_id = ?
                                ORDER BY created_at DESC LIMIT 1
                                """,
                                (str(project.project_id),),
                            ).fetchone()
                        if rec is None or str(rec[0]) != "completed" or str(rec[1]) != "complete":
                            return None
                        if len(objects) < 3 or int(refs) < 3 or int(actions) < 1 or finish is None:
                            return None
                        body = json.loads(str(finish[0]))
                        if body.get("approved") is not False:
                            return None
                        roles = {str(row[3]) for row in objects}
                        if not {"before", "after", "log"} <= roles:
                            return None
                        for row in objects:
                            if str(row[4]) != "ready" or int(row[5]) != 1 or int(row[2]) < 1:
                                return None
                            path = artifacts_dir / str(row[1])
                            if not path.is_file() or len(path.read_bytes()) != int(row[2]):
                                return None
                        return {
                            "recording_id": recording_id,
                            "artifact_count": len(objects),
                            "artifact_refs": int(refs),
                            "actions": int(actions),
                            "roles": sorted(roles),
                            "finish_approved": body.get("approved"),
                            "verdict": body.get("verdict"),
                            "sample_object_key": str(objects[0][1]),
                            "sample_bytes": int(objects[0][2]),
                        }

                    evidence = wait_for(recording_done, worker, 180, "recording evidence")
                    result.update(evidence)
                    result["review_pending"] = True
                    result["auto_approved"] = False

            if args.mode == "inventory":
                def offline():
                    presence, _ = device_row()
                    return presence.state == "offline" and healthy()

                wait_for(offline, api, OFFLINE_AFTER.total_seconds() + 5, "worker offline with API online")
                result["worker"] = "online_then_offline"
                result["api_healthy_after_worker_stop"] = True
            else:
                result["api_healthy_after_worker_stop"] = healthy()
                result["worker"] = "stopped_after_recording"
            return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("cert", "key", "ca", "adb"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--avd", required=True)
    parser.add_argument("--port", type=int)
    parser.add_argument("--mode", choices=("inventory", "recording"), default="inventory")
    parser.add_argument(
        "--fixture-response",
        default="swipe(360, 1200, 360, 400, 300)",
        help="Fixed Mobile-Agent style response used only when --mode recording",
    )
    args = parser.parse_args()
    if not args.serial.startswith("emulator-"):
        parser.error("Select a dedicated Android emulator by serial.")
    for name in ("cert", "key", "ca", "adb"):
        path = getattr(args, name).resolve()
        if not path.is_file():
            parser.error(f"--{name} must name an existing file.")
        setattr(args, name, path)
    with TemporaryDirectory(prefix="aiqa-same-pc-") as temp:
        print(json.dumps(run_probe(args, Path(temp)), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
