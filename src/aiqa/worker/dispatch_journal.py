"""Append-only dispatch journal. A record is durable only after flush."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from aiqa.contracts.evidence import require_dispatch_state
from aiqa.worker.files import file_lock
from aiqa.worker.runner import ACTION_LIMIT, ATTEMPT_LIMIT_SECONDS


def _local_state(state: str) -> str:
    # not_sent is a local terminal proof, never a wire evidence dispatch state.
    return state if state == "not_sent" else require_dispatch_state(state)


class JournalWriteError(OSError):
    """The next state was not flushed, so the command must not run."""


class DispatchJournal:
    """Local jsonl journal. Reopening the same path reads what was flushed."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._fail_state: str | None = None

    def fail_on(self, state: str) -> None:
        self._fail_state = _local_state(state)

    def append(self, attempt_id: str, action_id: str, state: str) -> None:
        checked = _local_state(state)
        if not attempt_id or not action_id:
            raise JournalWriteError("dispatch identity is required")
        if checked == self._fail_state:
            self._fail_state = None
            raise JournalWriteError("journal flush failed")
        try:
            with file_lock(self.path.with_suffix(self.path.suffix + '.lock')):
                prior = self.states(action_id, attempt_id)
                last = prior[-1] if prior else None
                if checked == 'planned' and last == 'planned':
                    return
                allowed = {
                    'planned': last is None or (last == 'lookup_failed' and prior.count('planned') < 2),
                    'lookup_failed': last == 'planned',
                    'dispatch_started': last == 'planned',
                    'acknowledged': last == 'dispatch_started',
                    'unknown': last == 'dispatch_started',
                    'not_sent': last == 'dispatch_started',
                    'observed': last in {'acknowledged', 'unknown'},
                }
                if not allowed[checked]:
                    raise JournalWriteError('dispatch transition is not permitted')
                now = time.time()
                if checked == 'dispatch_started':
                    rows = [json.loads(line) for line in self.path.read_text(encoding='utf-8').splitlines() if line]
                    attempt_rows = [row for row in rows if row.get('attempt_id') == attempt_id]
                    if sum(row.get('state') == 'dispatch_started' for row in attempt_rows) >= ACTION_LIMIT:
                        raise JournalWriteError('attempt action limit reached')
                    if any('recorded_at' not in row for row in attempt_rows):
                        raise JournalWriteError('legacy dispatch journal cannot resume actions')
                    age = now - min(float(row['recorded_at']) for row in attempt_rows)
                    if age < 0 or age >= ATTEMPT_LIMIT_SECONDS:
                        raise JournalWriteError('attempt time limit reached')
                record = {"action_id": action_id, "attempt_id": attempt_id, "state": checked, 'recorded_at': now}
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, sort_keys=True) + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
        except (OSError, ValueError) as exc:
            raise JournalWriteError('dispatch journal unavailable') from exc

    def states(self, action_id: str, attempt_id: str | None = None) -> tuple[str, ...]:
        if not self.path.exists():
            return ()
        found: list[str] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line == "":
                continue
            try:
                record = json.loads(line)
            except ValueError as exc:
                raise JournalWriteError('dispatch journal is corrupt') from exc
            if str(record["action_id"]) == action_id and (attempt_id is None or record.get('attempt_id') == attempt_id):
                found.append(str(record["state"]))
        return tuple(found)

    def mark_started_only_unknown(self, attempt_id: str, action_id: str) -> str | None:
        """Record STARTED-only interrupted work as ambiguous/unknown. No command retry."""

        prior = self.states(action_id, attempt_id)
        if prior == () or prior[-1] != "dispatch_started":
            return None
        self.append(attempt_id, action_id, "unknown")
        return "unknown"

    def is_ambiguous(self, attempt_id: str, action_id: str) -> bool:
        prior = self.states(action_id, attempt_id)
        return prior != () and prior[-1] in {"dispatch_started", "unknown"}
