"""Local API and worker processes. Closing a browser tab does not stop them."""

from __future__ import annotations

import ctypes
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

_API_COMMAND = (
    "python -m uvicorn aiqa.api.app:create_app --factory --host 127.0.0.1 --port {port}"
)
_PROCESS_QUERY = 0x1000


@dataclass(frozen=True, slots=True)
class LauncherConfig:
    """One loopback start. vm_ready does not open a VM."""

    host: str
    port: int
    runtime_root: str
    vm_ready: bool = False
    start_worker: bool = True


@dataclass(frozen=True, slots=True)
class LocalServiceStatus:
    """Process counts and the reason the last start returned."""

    api_instances: int
    worker_instances: int
    state: str
    explanation: str
    command: str
    publish: bool
    tab_close_cancels: bool
    api_pid: int
    worker_pid: int


def start_local_services(config: LauncherConfig) -> LocalServiceStatus:
    """Start one API and one worker, or explain why this call did not."""

    _require_loopback(config)
    existing = _read(config)
    if existing is not None and _same(config, existing) and _alive(int(existing["api_pid"])):
        return _status(config, existing, "already_running", "이미 실행 중입니다.")
    if _port_busy(config.host, config.port):
        return _status(config, None, "port_conflict", "다른 프로세스가 이 포트를 사용 중입니다.")
    if not config.start_worker:
        api_pid = _spawn_api(config)
        record = _record(config, api_pid, 0, "worker_missing")
        return _status(config, record, "worker_missing", "worker가 없습니다.")
    api_pid = _spawn_api(config)
    worker_pid = _spawn_worker()
    if not _wait_health(config) or not _alive(worker_pid):
        _stop_pids(api_pid, worker_pid)
        return _status(config, None, "worker_missing", "worker가 없습니다.")
    record = _record(config, api_pid, worker_pid, "running")
    explanation = "API와 worker가 실행 중입니다. 탭을 닫아도 프로세스는 유지됩니다."
    if not config.vm_ready:
        explanation = f"{explanation} VM 미준비."
    return _status(config, record, "running", explanation)


def acknowledge_tab_closed(config: LauncherConfig) -> LocalServiceStatus:
    """Record that the management tab closed. The processes stay."""

    existing = _read(config)
    if existing is None:
        return _status(config, None, "stopped", "시작 전입니다.")
    return _status(config, existing, str(existing["state"]), "탭을 닫아도 프로세스는 유지됩니다.")


@dataclass(frozen=True, slots=True)
class ServiceStopRequest:
    """A requested stop. work_in_progress leaves a durable flag."""

    config: LauncherConfig
    action: str
    work_in_progress: bool = False


def stop_local_services(request: ServiceStopRequest | LauncherConfig) -> LocalServiceStatus:
    """Stop the recorded processes. A busy stop records cleanup and no resume."""

    if isinstance(request, LauncherConfig):
        request = ServiceStopRequest(request, "stop", False)
    if request.action not in {"stop", "cancel"}:
        raise ValueError("stop action must be stop or cancel")
    config = request.config
    existing = _read(config)
    explanation = "시작 전입니다."
    if request.work_in_progress:
        explanation = (
            "진행 작업을 종료합니다. 취소와 정리 영향이 있습니다. "
            "자동 재개는 없습니다. PC 중단 동안 실행 유지를 보장하지 않습니다."
        )
        _write_stop_flag(config, request.action)
    if existing is not None:
        _stop_pids(int(existing["api_pid"]), int(existing["worker_pid"]))
        path = _lock(config)
        if path.exists():
            path.unlink()
    return _status(config, None, "stopped", explanation)


def enter_maintenance(runtime_root: str) -> None:
    """Record whole-PC maintenance and drop the recorded worker session.

    This does not stop a process. The API storage service discards worker tokens.
    """

    root = Path(runtime_root)
    root.mkdir(parents=True, exist_ok=True)
    (root / "maintenance.json").write_text(
        json.dumps(
            {
                "automatic_resume": 0,
                "mode": "maintenance",
                "scope": "이 PC 전체 저장소",
                "worker_sessions": "discarded",
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    lock = root / "launcher.json"
    if not lock.is_file():
        return
    payload = json.loads(lock.read_text(encoding="utf-8"))
    if type(payload) is not dict:
        return
    payload["worker_pid"] = 0
    payload["state"] = "maintenance"
    payload["explanation"] = "유지보수 모드입니다. worker 세션은 폐기되었습니다."
    lock.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def read_stop_notice(runtime_root: str) -> dict[str, object] | None:
    """Read the durable stop flag. This does not start or stop a process."""

    path = Path(runtime_root) / "stop-flag.json"
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if type(payload) is not dict:
        return None
    return payload


def read_local_status(runtime_root: str) -> LocalServiceStatus:
    """Read the lock written by the launcher. This does not start a process."""

    config = LauncherConfig("127.0.0.1", 0, runtime_root)
    existing = _read(config)
    if existing is None:
        return _status(config, None, "stopped", "시작 전입니다.")
    return _status(config, existing, str(existing["state"]), str(existing["explanation"]))


def main(argv: list[str]) -> int:
    """Keep a worker process until it is stopped. This does not open a device."""

    if argv[1:] != ["worker"]:
        return 2
    while True:
        time.sleep(3600)
    return 0


def _require_loopback(config: LauncherConfig) -> None:
    if config.host != "127.0.0.1":
        raise ValueError("host must be 127.0.0.1")


def _spawn_api(config: LauncherConfig) -> int:
    env = os.environ.copy()
    env["AIQA_HOST"] = config.host
    env["AIQA_PORT"] = str(config.port)
    env["AIQA_RUNTIME_ROOT"] = config.runtime_root
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "aiqa.api.app:create_app",
            "--factory",
            "--host",
            config.host,
            "--port",
            str(config.port),
        ],
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    return int(process.pid)


def _spawn_worker() -> int:
    process = subprocess.Popen(
        [sys.executable, "-m", "aiqa.launcher", "worker"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    return int(process.pid)


def _wait_health(config: LauncherConfig) -> bool:
    url = f"http://{config.host}:{config.port}/api/v1/health"
    for _ in range(40):
        try:
            with urllib.request.urlopen(url, timeout=0.5) as response:
                if response.status == 200:
                    return True
        except OSError:
            time.sleep(0.25)
    return False


def _record(config: LauncherConfig, api_pid: int, worker_pid: int, state: str) -> dict[str, object]:
    explanation = {
        "running": "API와 worker가 실행 중입니다. 탭을 닫아도 프로세스는 유지됩니다.",
        "worker_missing": "worker가 없습니다.",
    }[state]
    if state == "running" and not config.vm_ready:
        explanation = f"{explanation} VM 미준비."
    payload = {
        "host": config.host,
        "port": config.port,
        "api_pid": api_pid,
        "worker_pid": worker_pid,
        "state": state,
        "explanation": explanation,
        "command": _API_COMMAND.format(port=config.port),
        "publish": False,
        "vm_ready": config.vm_ready,
    }
    path = _lock(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    package = path.parent / "launcher-package.json"
    package.write_text(
        json.dumps({"command": payload["command"], "publish": False}, sort_keys=True),
        encoding="utf-8",
    )
    return payload


def _status(
    config: LauncherConfig,
    existing: dict[str, object] | None,
    state: str,
    explanation: str,
) -> LocalServiceStatus:
    api_pid = 0 if existing is None else int(existing["api_pid"])
    worker_pid = 0 if existing is None else int(existing["worker_pid"])
    command = _API_COMMAND.format(port=config.port if config.port else 8000)
    if existing is not None:
        command = str(existing["command"])
    return LocalServiceStatus(
        api_instances=1 if _alive(api_pid) else 0,
        worker_instances=1 if _alive(worker_pid) else 0,
        state=state,
        explanation=explanation,
        command=command,
        publish=False,
        tab_close_cancels=False,
        api_pid=api_pid,
        worker_pid=worker_pid,
    )


def _same(config: LauncherConfig, existing: dict[str, object]) -> bool:
    return existing["host"] == config.host and int(existing["port"]) == config.port


def _read(config: LauncherConfig) -> dict[str, object] | None:
    path = _lock(config)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if type(payload) is not dict:
        return None
    return payload


def _lock(config: LauncherConfig) -> Path:
    return Path(config.runtime_root) / "launcher.json"


def _write_stop_flag(config: LauncherConfig, action: str) -> None:
    path = Path(config.runtime_root) / "stop-flag.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "action": action,
                "cleanup": True,
                "automatic_resume": 0,
                "unknown_success": False,
                "summary": "진행 작업을 종료합니다. 취소와 정리 영향이 있습니다.",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _port_busy(host: str, port: int) -> bool:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind((host, port))
    except OSError:
        return True
    finally:
        probe.close()
    return False


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    handle = ctypes.windll.kernel32.OpenProcess(_PROCESS_QUERY, False, pid)
    if not handle:
        return False
    ctypes.windll.kernel32.CloseHandle(handle)
    return True


def _stop_pids(api_pid: int, worker_pid: int) -> None:
    for pid in (api_pid, worker_pid):
        if pid > 0:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
