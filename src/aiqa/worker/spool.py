"""Durable sanitized evidence spool. Unacked files are kept, and pressure stops new actions."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID
from functools import wraps
from aiqa.worker.files import atomic_write, file_lock

from aiqa.contracts.evidence import (
    AckState,
    EvidenceCommitAck,
    EvidenceEnvelope,
    IngestReceipt,
    LocalReceipt,
)

ACK_RETENTION = timedelta(days=7)


class SpoolError(ValueError):
    """The envelope cannot be appended."""


def _locked(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with file_lock(self.root / 'journal.lock'):
            self._records = self._read_journal()
            self._pressure = (self.root / 'pressure').exists()
            return method(self, *args, **kwargs)
    return call


class EvidenceSpool:
    """Append-only local journal. Cleanup requires a contiguous server hash."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.unacked_deleted = 0
        self.duplicate_actions_from_upload = 0
        self.pressure_stops_actions = False
        self._records = self._read_journal()
        self._pressure = (root / "pressure").exists()

    @_locked
    def append(self, envelope: EvidenceEnvelope) -> LocalReceipt:
        if type(envelope.local_seq) is not int or envelope.local_seq < 1:
            raise SpoolError('positive local sequence required')
        appended_at = _clock(envelope.appended_at)
        digest = evidence_hash(envelope.local_seq, envelope.png, envelope.log_text)
        existing = _find(self._records, envelope.attempt_id, envelope.local_seq)
        if existing is not None:
            if existing['payload_hash'] != digest:
                raise SpoolError('sequence already has a different payload')
            return LocalReceipt(envelope.attempt_id, envelope.local_seq, str(existing["payload_hash"]), True)
        if self._pressure:
            self.pressure_stops_actions = True
            return LocalReceipt(envelope.attempt_id, envelope.local_seq, digest, False)
        folder = self._attempt_dir(envelope.attempt_id)
        folder.mkdir(parents=True, exist_ok=True)
        png_name = f"{envelope.local_seq}.png"
        log_name = f"{envelope.local_seq}.log"
        _write_bytes(folder / png_name, envelope.png)
        _write_bytes(folder / log_name, envelope.log_text.encode("utf-8"))
        record = {
            "acked": False,
            "appended_at": appended_at.isoformat(),
            "attempt_id": str(envelope.attempt_id),
            "local_seq": envelope.local_seq,
            "log_name": log_name,
            "payload_hash": digest,
            "png_name": png_name,
            "sent": False,
        }
        self._records.append(record)
        self._write_journal()
        return LocalReceipt(envelope.attempt_id, envelope.local_seq, digest, True)

    @_locked
    def mark_sent(self, attempt_id: UUID, local_seq: int) -> None:
        record = _find(self._records, attempt_id, local_seq)
        if record is None:
            raise SpoolError("evidence is not in the spool")
        record["sent"] = True
        self._write_journal()

    @_locked
    def acknowledge(self, receipt: IngestReceipt) -> AckState:
        rows = _rows(self._records, receipt.attempt_id)
        contiguous = _contiguous(rows)
        if receipt.committed_seq < 1 or receipt.committed_seq > len(contiguous):
            return AckState(receipt.attempt_id, _acked_through(rows), False, "gap")
        expected = prefix_hash(contiguous[: receipt.committed_seq])
        if receipt.committed_hash != expected:
            return AckState(receipt.attempt_id, _acked_through(rows), False, "hash")
        for record in contiguous[: receipt.committed_seq]:
            record["acked"] = True
        self._write_journal()
        return AckState(receipt.attempt_id, receipt.committed_seq, True, "acked")

    def apply_commit_ack(self, ack: EvidenceCommitAck) -> AckState:
        """Map wire (contiguous_seq, prefix_hash) onto the local spool ack."""

        return self.acknowledge(
            IngestReceipt(ack.attempt_id, ack.contiguous_seq, ack.prefix_hash, ack.stale_count)
        )

    @_locked
    def purge(self, now: datetime) -> int:
        clock = _clock(now.isoformat())
        kept: list[dict[str, object]] = []
        for record in self._records:
            appended = _clock(str(record["appended_at"]))
            expired = clock - appended >= ACK_RETENTION
            if bool(record["acked"]) and expired:
                folder = self._attempt_dir(UUID(str(record["attempt_id"])))
                for name in (str(record["png_name"]), str(record["log_name"])):
                    path = folder / name
                    if path.exists():
                        path.unlink()
                record['purged'] = True
            kept.append(record)
        self._records = kept
        self._write_journal()
        return self.unacked_deleted

    @_locked
    def note_pressure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        _write_bytes(self.root / "pressure", b"1")
        self._pressure = True

    @_locked
    def prefix_hash(self, attempt_id: UUID, through_seq: int) -> str:
        rows = _contiguous(_rows(self._records, attempt_id))
        return prefix_hash(rows[:through_seq])

    @_locked
    def has_file(self, attempt_id: UUID, local_seq: int) -> bool:
        record = _find(self._records, attempt_id, local_seq)
        if record is None:
            return False
        folder = self._attempt_dir(attempt_id)
        return (folder / str(record["png_name"])).exists() and (folder / str(record["log_name"])).exists()

    def _attempt_dir(self, attempt_id: UUID) -> Path:
        return self.root / str(attempt_id)

    def _read_journal(self) -> list[dict[str, object]]:
        path = self.root / "journal.jsonl"
        if not path.exists():
            return []
        rows: list[dict[str, object]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line != "":
                rows.append(json.loads(line))
        return rows

    def _write_journal(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        text = "".join(json.dumps(record, sort_keys=True) + "\n" for record in self._records)
        atomic_write(self.root / "journal.jsonl", text.encode("utf-8"))


def evidence_hash(local_seq: int, png: bytes, log_text: str) -> str:
    body = str(local_seq).encode("utf-8") + b"\n" + png + b"\n" + log_text.encode("utf-8")
    return "sha256:" + hashlib.sha256(body).hexdigest()


def prefix_hash(records: list[dict[str, object]]) -> str:
    joined = "|".join(str(record["payload_hash"]) for record in records)
    return "sha256:" + hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _find(records: list[dict[str, object]], attempt_id: UUID, local_seq: int) -> dict[str, object] | None:
    for record in records:
        if str(record["attempt_id"]) == str(attempt_id) and int(record["local_seq"]) == local_seq:
            return record
    return None


def _rows(records: list[dict[str, object]], attempt_id: UUID) -> list[dict[str, object]]:
    rows = [record for record in records if str(record["attempt_id"]) == str(attempt_id)]
    return sorted(rows, key=lambda record: int(record["local_seq"]))


def _contiguous(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    expected = 1
    for record in rows:
        if int(record["local_seq"]) != expected:
            break
        found.append(record)
        expected += 1
    return found


def _acked_through(rows: list[dict[str, object]]) -> int:
    through = 0
    for record in _contiguous(rows):
        if not bool(record["acked"]):
            break
        through = int(record["local_seq"])
    return through


def _clock(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SpoolError("clock time must include a timezone")
    return parsed


def _write_bytes(path: Path, payload: bytes) -> None:
    atomic_write(path, payload)
