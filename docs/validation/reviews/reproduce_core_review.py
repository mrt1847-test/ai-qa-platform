"""Read-only product review probes; prints observations, not a product PASS.

Run with the existing project venv from the repository root. All DB rows are in
memory and all files are in a TemporaryDirectory. No network, model, OS secret
store, user runtime DB, browser, native action, or device is used.
"""

from __future__ import annotations

import binascii
import json
import sqlite3
import struct
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from uuid import uuid4

from aiqa.api.auth import bound_auth_store, enroll_worker
from aiqa.contracts.actions import (
    ActionProposal,
    CaptureGeometry,
    Observation,
    PreparedAction,
)
from aiqa.contracts.cases import (
    CaseDefinition,
    CaseRevisionInput,
    CaseSettings,
    CheckSpec,
    PathPolicy,
    StepSpec,
)
from aiqa.contracts.evidence import EvidenceEnvelope, IngestReceipt
from aiqa.contracts.jobs import IdempotencyKey, JobSubmission, LeaseToken
from aiqa.domain.projects import bind_store, create_project
from aiqa.domain.versions import (
    StepEditCommand,
    apply_step_edit,
    bind_case_store,
    create_case,
    save_case_revision,
)
from aiqa.recording.action_executor import ActionExecutor
from aiqa.recording.recovery import EvidenceRecoverySpec, RecoveryCapture, apply_recovery
from aiqa.security.redaction import filter_capture
from aiqa.store.artifacts import ArtifactUpload, content_hash
from aiqa.store.database import StorageConfig, Store, migrate_store
from aiqa.store.evidence import (
    ArtifactBinding,
    bind_artifact_ingest,
    ingest_artifact,
    reset_artifact_ingest,
)
from aiqa.store.models import Actor, ProjectCreate, Transaction, WorkerScope
from aiqa.store.queue import enqueue_job
from aiqa.worker.dispatch_journal import DispatchJournal
from aiqa.worker.service import bind_claim_store, claim_job
from aiqa.worker.spool import EvidenceSpool


class ControlFixture:
    def __init__(self) -> None:
        self.allowed = True
        self.checks = 0

    def checkpoint(self):
        self.checks += 1
        return SimpleNamespace(allowed=self.allowed)


class CommandFixture:
    def __init__(self, cancel_on_lookup: ControlFixture | None = None) -> None:
        self.calls = 0
        self.control = cancel_on_lookup

    def lookup(self, prepared):
        if self.control is not None:
            self.control.allowed = False
        return True

    def execute(self, prepared):
        self.calls += 1
        raise TimeoutError("fixture: delivery is unknown")


def dispatch_probes(root: Path) -> dict:
    prepared = PreparedAction(
        ActionProposal("S1", "A1", "click", "fixture", "path"), "obs1", "before/ref", True
    )
    control = ControlFixture()
    command = CommandFixture()
    executor = ActionExecutor(journal=DispatchJournal(root / "duplicate.jsonl"), command=command)
    first = executor.dispatch_action(prepared, control)
    second = executor.dispatch_action(prepared, control)
    cancel = ControlFixture()
    cancel_command = CommandFixture(cancel)
    executor = ActionExecutor(journal=DispatchJournal(root / "cancel.jsonl"), command=cancel_command)
    executor.dispatch_action(prepared, cancel)
    return {
        "duplicate_unknown": {"calls": command.calls, "first": first.states, "second": second.states},
        "cancel_during_lookup": {"cancelled": not cancel.allowed, "calls": cancel_command.calls, "checks": cancel.checks},
    }


def spool_probes(root: Path) -> dict:
    spool = EvidenceSpool(root / "spool")
    attempt = uuid4()
    now = datetime.now(timezone.utc)
    old = (now - timedelta(days=8)).isoformat()
    first = spool.append(EvidenceEnvelope(attempt, 1, b"first", "log", old))
    other = spool.append(EvidenceEnvelope(attempt, 1, b"different", "log", old))
    spool.acknowledge(IngestReceipt(attempt, 1, spool.prefix_hash(attempt, 1), 0))
    spool.purge(now)
    spool.append(EvidenceEnvelope(attempt, 2, b"second", "log", now.isoformat()))
    ack = spool.acknowledge(IngestReceipt(attempt, 2, spool.prefix_hash(attempt, 2), 0))
    return {
        "different_body_durable": other.durable,
        "different_body_returns_old_hash": other.payload_hash == first.payload_hash,
        "ack_after_purge": {"accepted": ack.accepted, "reason": ack.reason},
    }


def png_probe() -> dict:
    glyphs = {
        "P": ["11110", "10001", "11110", "10000", "10000", "10000", "10000"],
        "I": ["11111", "00100", "00100", "00100", "00100", "00100", "11111"],
        "N": ["10001", "11001", "10101", "10011", "10001", "10001", "10001"],
        "1": ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
        "2": ["11110", "00001", "00001", "11110", "10000", "10000", "11111"],
        "3": ["11110", "00001", "00001", "01110", "00001", "00001", "11110"],
    }
    text = "PIN123"  # Synthetic fixture; no actual secret.
    raw = b""
    for y in range(7):
        row = b"".join(bytes(0 if bit == "1" else 255 for bit in glyphs[ch][y]) + b"\xff" for ch in text)
        raw += b"\x00" + row

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", binascii.crc32(kind + body) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 36, 7, 8, 0, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
    geometry = CaptureGeometry(36, 7, 36, 7, "identity", 0, (0, 0, 36, 7))
    observation = Observation("fixture", "2026-11-01T00:00:00+00:00", geometry, png, "", "", (), "", True, "web")
    cleaned = filter_capture(observation, (text,))
    return {"visible_fixture": text, "raw_text_absent": text.encode() not in png, "image_unchanged": cleaned.png == png}


def database_probes(root: Path) -> dict:
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.execute("PRAGMA foreign_keys=ON")
    store = Store(StorageConfig(root, root / "unused.sqlite", root / "artifacts", root / "spool"), connection)
    migrate_store(store)
    try:
        owner = Actor(uuid4(), None, True)
        with bind_store(store):
            project = create_project(owner, ProjectCreate("Review", "review", "r", "web"))
        actor = Actor(owner.actor_id, project.project_id, True)
        definition = CaseDefinition("pay", "pay", ("ready",), {}, {}, (StepSpec("S1", "pay", (CheckSpec("C1", "text", "ok"),)),), (), PathPolicy())
        with bind_case_store(store):
            case = create_case(actor, "Review", None)
            first = save_case_revision(actor, case.case_id, CaseRevisionInput(definition, CaseSettings("web")), None)
            second = save_case_revision(actor, case.case_id, CaseRevisionInput(definition, CaseSettings("android", document={"android_package": "com.two"}), ({"action": "tap", "x": 20, "y": 30},)), first.id)
            edited, _ = apply_step_edit(actor, case.case_id, StepEditCommand(action="add", expected_head=second.id, instruction="next", expected="ok"))
        settings, steps = connection.execute("SELECT settings_json, recorded_steps_json FROM case_versions WHERE version_id=?", (str(edited.id),)).fetchone()
        recording = uuid4()
        connection.execute("INSERT INTO recordings (project_id,case_id,recording_id,creation_kind,input_case_version_id,storage_status,stop_status,completion_status,evidence_status) VALUES (?,?,?,'recorded',?,'spooling','stopped','interrupted','incomplete')", (str(project.project_id), str(case.case_id), str(recording), str(first.id)))
        for key, body in (("first", b"original"), ("second", b"replacement")):
            with store.transaction() as tx:
                apply_recovery(tx, store.config.artifacts_dir, EvidenceRecoverySpec(project.project_id, recording, key, (RecoveryCapture("A1", "immediate", body),)))
        original_hashes = connection.execute("SELECT source_artifact_hashes FROM recording_manifests WHERE recording_id=? AND revision=1", (str(recording),)).fetchone()[0]

        with bound_auth_store(store):
            enroll_worker(actor, "review-worker", "structure")
        with store.transaction() as tx:
            enqueue_job(Transaction(tx), JobSubmission(project.project_id, "structure", None, None, ("mgmt",), "{}"), IdempotencyKey(actor.actor_id, project.project_id, "enqueue_job", "review-job"))
        worker = WorkerScope("review-worker", (project.project_id,), ("structure",))
        now = datetime(2026, 11, 1, tzinfo=timezone.utc)
        with bind_claim_store(store):
            job = claim_job(worker, now)
        # Seed existing ready metadata to isolate the dedup branch, not to claim
        # successful native upload or ready-file crash safety.
        body = b"fixture-ready"
        artifact = uuid4()
        connection.execute("INSERT INTO artifact_objects (project_id,artifact_id,object_key,content_hash,byte_length,media_type,owner_id,status,acked) VALUES (?,?,?,?,?,?,?,'ready',1)", (str(project.project_id), str(artifact), "fixture/no-file", content_hash(body), len(body), "image/png", str(uuid4())))
        token = bind_artifact_ingest(ArtifactBinding(store, worker, now))
        try:
            receipt = ingest_artifact(LeaseToken(job.project_id, job.job_id, job.generation), ArtifactUpload(project.project_id, uuid4(), "../invalid.exe", "application/x-msdownload", "sha256:" + "0" * 64, -1, body))
        finally:
            reset_artifact_ingest(token)
        return {
            "settings_and_procedure_change_same_hash": first.content_hash == second.content_hash,
            "step_edit_settings": json.loads(settings),
            "step_edit_recorded_steps": json.loads(steps),
            "recovery": {"original_manifest_hashes": json.loads(original_hashes), "file_now": (root / "artifacts" / "recovery" / str(recording) / "A1.png").read_bytes().decode()},
            "invalid_metadata_dedup": {"acked": receipt.acked, "ready": receipt.ready, "old_artifact": receipt.artifact_id == artifact},
        }
    finally:
        store.close()


if __name__ == "__main__":
    with TemporaryDirectory(prefix="aiqa-contract-review-") as directory:
        root = Path(directory)
        result = {"dispatch": dispatch_probes(root), "spool": spool_probes(root), "png": png_probe(), "database": database_probes(root)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
