"""Owned process trees. Stopping uses a recorded pid, never an image name."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class StopReport:
    attempt_id: UUID
    grace_seconds: int
    stopped_pids: tuple[int, ...]


_OWNED: dict[UUID, list[subprocess.Popen[bytes]]] = {}


def spawn_owned_sleeper(attempt_id: UUID) -> subprocess.Popen[bytes]:
    """Start one sleeper whose pid belongs to this attempt."""

    flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)"],
        creationflags=flags,
    )
    _OWNED.setdefault(attempt_id, []).append(process)
    return process


def stop_owned_tree(attempt_id: UUID, grace_seconds: int) -> StopReport:
    """Wait out the cancel grace, then stop only this attempt's pid tree."""

    if isinstance(grace_seconds, bool) or type(grace_seconds) is not int or grace_seconds < 0:
        raise ValueError("cancel grace is invalid")
    time.sleep(grace_seconds)
    stopped: list[int] = []
    for process in _OWNED.get(attempt_id, ()):
        if process.poll() is None:
            _kill_pid_tree(process.pid)
            process.wait(timeout=5)
        stopped.append(process.pid)
    return StopReport(attempt_id=attempt_id, grace_seconds=grace_seconds, stopped_pids=tuple(stopped))


def _kill_pid_tree(pid: int) -> None:
    if pid <= 0 or pid == os.getpid():
        raise ValueError("refusing to stop this process")
    subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"],
        capture_output=True,
        check=False,
    )
