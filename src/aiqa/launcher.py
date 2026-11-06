"""Local API and worker processes. Closing a browser tab does not stop them."""

from __future__ import annotations

import ctypes
import json
import os
import secrets
import shutil
import socket
import ssl
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
class HostedServerConfig:
    """API-only hosted entry behind a reverse proxy. Workers use HTTPS, not SQLite."""

    host: str
    port: int
    runtime_root: str
    public_origin: str
    trusted_proxies: tuple[str, ...]


def worker_database_grant(settings: object) -> None:
    """Servers never hand workers a SQLite path. Always None."""

    return None


def build_hosted_env(config: HostedServerConfig) -> dict[str, str]:
    """Environment for the hosted API process. No bootstrap nonce is issued here."""

    if config.host != "127.0.0.1":
        raise ValueError("hosted API still binds loopback behind the proxy")
    if not config.trusted_proxies:
        raise ValueError("trusted_proxies is required")
    return {
        "AIQA_HOST": config.host,
        "AIQA_PORT": str(config.port),
        "AIQA_RUNTIME_ROOT": config.runtime_root,
        "AIQA_PROFILE": "hosted",
        "AIQA_PUBLIC_ORIGIN": config.public_origin.rstrip("/"),
        "AIQA_TRUSTED_PROXIES": ",".join(config.trusted_proxies),
    }


def start_hosted_server(config: HostedServerConfig, *, spawn: bool = True) -> LocalServiceStatus:
    """Open the hosted API entry. Does not start a co-located worker or grant DB paths."""

    env = build_hosted_env(config)
    from aiqa.config import load_settings

    settings = load_settings(env)
    if worker_database_grant(settings) is not None:
        raise RuntimeError("worker DB grant must stay closed")
    if not spawn:
        return LocalServiceStatus(
            api_instances=0,
            worker_instances=0,
            state="configured",
            explanation="hosted API 설정이 준비됐습니다. reverse proxy HTTPS만 공개합니다.",
            command=_API_COMMAND.format(port=config.port),
            publish=False,
            tab_close_cancels=False,
            api_pid=0,
            worker_pid=0,
        )
    api_pid = _spawn_hosted_api(config, env)
    record = {
        "host": config.host,
        "port": config.port,
        "api_pid": api_pid,
        "worker_pid": 0,
        "state": "running",
        "explanation": "hosted API만 실행 중입니다. worker DB 접근은 없습니다.",
        "command": _API_COMMAND.format(port=config.port),
        "publish": False,
        "vm_ready": False,
        "profile": "hosted",
    }
    path = Path(config.runtime_root) / "launcher.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, sort_keys=True), encoding="utf-8")
    return LocalServiceStatus(
        api_instances=1 if _alive(api_pid) else 0,
        worker_instances=0,
        state="running",
        explanation=str(record["explanation"]),
        command=str(record["command"]),
        publish=False,
        tab_close_cancels=False,
        api_pid=api_pid,
        worker_pid=0,
    )


def _spawn_hosted_api(config: HostedServerConfig, env: dict[str, str]) -> int:
    process_env = os.environ.copy()
    process_env.update(env)
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
        env=process_env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    return int(process.pid)


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
    if not _wait_health(config):
        _stop_pids(api_pid, 0)
        return _status(config, None, "worker_missing", "worker가 없습니다.")
    # The worker only speaks HTTPS. Without a loopback TLS origin it cannot connect, so the
    # API stays up and /ui/local explains the gap. Nothing here marks vm_ready or ready.
    try:
        management = _prepare_management(config)
    except LauncherSetupError as error:
        reason = f"worker가 없습니다. worker 연결 설정이 없습니다: {error}"
        record = _record(config, api_pid, 0, "worker_missing", explanation=reason)
        return _status(config, record, "worker_missing", reason)
    tls_pid = _spawn_api(config, port=management.port, tls=management)
    if not _wait_health_tls(management):
        _stop_pids(api_pid, 0, tls_pid)
        reason = "worker가 없습니다. 로컬 관리 HTTPS 연결을 열지 못했습니다."
        return _status(config, None, "worker_missing", reason)
    worker_pid = _spawn_worker(config, management)
    if not _wait_worker_alive(worker_pid):
        _stop_pids(api_pid, worker_pid, tls_pid)
        return _status(config, None, "worker_missing", "worker가 없습니다.")
    record = _record(
        config,
        api_pid,
        worker_pid,
        "running",
        management=management,
        tls_pid=tls_pid,
    )
    return _status(config, record, "running", str(record["explanation"]))


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
        _stop_pids(
            int(existing["api_pid"]),
            int(existing["worker_pid"]),
            int(existing.get("management_pid", 0)),
        )
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
    """Run the independent worker consume loop. This does not open the server DB."""

    if argv[1:] != ["worker"]:
        return 2
    from aiqa.worker.runtime import run_worker_process

    return run_worker_process()


def _require_loopback(config: LauncherConfig) -> None:
    if config.host != "127.0.0.1":
        raise ValueError("host must be 127.0.0.1")


class LauncherSetupError(RuntimeError):
    """A prerequisite for the worker connection is missing. The message is user-facing."""


@dataclass(frozen=True, slots=True)
class _Management:
    """Loopback HTTPS management origin the worker dials. Never a SQLite grant."""

    port: int
    cert: Path
    key: Path
    token: str
    registered: bool

    @property
    def origin(self) -> str:
        return f"https://127.0.0.1:{self.port}"


def _spawn_api(
    config: LauncherConfig, *, port: int | None = None, tls: _Management | None = None
) -> int:
    env = os.environ.copy()
    listen = config.port if port is None else port
    env["AIQA_HOST"] = config.host
    env["AIQA_PORT"] = str(listen)
    env["AIQA_RUNTIME_ROOT"] = config.runtime_root
    args = [
        sys.executable,
        "-m",
        "uvicorn",
        "aiqa.api.app:create_app",
        "--factory",
        "--host",
        config.host,
        "--port",
        str(listen),
    ]
    if tls is not None:
        args += ["--ssl-certfile", str(tls.cert), "--ssl-keyfile", str(tls.key), "--no-proxy-headers"]
    process = subprocess.Popen(
        args,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    return int(process.pid)


def _spawn_worker(config: LauncherConfig, management: _Management) -> int:
    env = os.environ.copy()
    env["AIQA_MANAGEMENT_BASE_URL"] = management.origin
    env["AIQA_WORKER_TOKEN"] = management.token
    env["AIQA_WORKER_CA_BUNDLE"] = str(management.cert)
    env.pop("AIQA_WORKER_VERIFY_TLS", None)
    env.setdefault("AIQA_WORKER_RUNTIME_ROOT", str(Path(config.runtime_root) / "worker" / "runtime"))
    process = subprocess.Popen(
        [sys.executable, "-m", "aiqa.launcher", "worker"],
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    return int(process.pid)


def _prepare_management(config: LauncherConfig) -> _Management:
    """Resolve the worker token and a loopback TLS identity, or raise LauncherSetupError."""

    root = Path(config.runtime_root)
    token = _enrolled_token(root)
    registered = token is not None
    if token is None:
        # No PC enrollment yet: the worker polls with a token the server will not accept.
        # It reports unregistered until a registration code is exchanged. Never a ready state.
        token = secrets.token_urlsafe(32)
    cert, key = _tls_identity(root / "tls")
    return _Management(_free_port(config.host), cert, key, token, registered)


def _enrolled_token(root: Path) -> str | None:
    """Enrolled worker token: AIQA_WORKER_TOKEN, else <runtime>/worker/token written at enrollment."""

    raw = os.environ.get("AIQA_WORKER_TOKEN", "").strip()
    if raw:
        return raw
    path = root / "worker" / "token"
    if path.is_file():
        text = path.read_text(encoding="utf-8").strip()
        if text:
            return text
    return None


def _tls_identity(folder: Path) -> tuple[Path, Path]:
    cert_env = os.environ.get("AIQA_LOCAL_TLS_CERT", "").strip()
    key_env = os.environ.get("AIQA_LOCAL_TLS_KEY", "").strip()
    if cert_env or key_env:
        cert, key = Path(cert_env), Path(key_env)
        if not (cert_env and key_env and cert.is_file() and key.is_file()):
            raise LauncherSetupError("AIQA_LOCAL_TLS_CERT와 AIQA_LOCAL_TLS_KEY 파일이 필요합니다.")
        return cert, key
    cert, key = folder / "loopback-cert.pem", folder / "loopback-key.pem"
    if cert.is_file() and key.is_file():
        return cert, key
    openssl = _find_openssl()
    if openssl is None:
        raise LauncherSetupError(
            "로컬 TLS 인증서를 만들 수 없습니다. openssl이 없으면 "
            "AIQA_LOCAL_TLS_CERT/AIQA_LOCAL_TLS_KEY를 지정하세요."
        )
    folder.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-keyout", str(key), "-out", str(cert), "-days", "365",
            "-subj", "/CN=127.0.0.1",
            "-addext", "subjectAltName=IP:127.0.0.1",
            "-addext", "basicConstraints=critical,CA:TRUE",
        ],
        check=False,
        capture_output=True,
        timeout=60,
        stdin=subprocess.DEVNULL,
    )
    if result.returncode != 0 or not cert.is_file() or not key.is_file():
        raise LauncherSetupError("로컬 TLS 인증서 생성에 실패했습니다.")
    return cert, key


def _find_openssl() -> str | None:
    found = shutil.which("openssl")
    if found:
        return found
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", "")):
        if not base:
            continue
        for relative in (r"Git\usr\bin\openssl.exe", r"Git\mingw64\bin\openssl.exe"):
            candidate = Path(base) / relative
            if candidate.is_file():
                return str(candidate)
    return None


def _free_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((host, 0))
        return int(probe.getsockname()[1])


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


def _wait_health_tls(management: _Management) -> bool:
    context = ssl.create_default_context(cafile=str(management.cert))
    url = f"{management.origin}/api/v1/health"
    for _ in range(40):
        try:
            with urllib.request.urlopen(url, timeout=1, context=context) as response:
                if response.status == 200:
                    return True
        except OSError:
            time.sleep(0.25)
    return False


def _wait_worker_alive(pid: int) -> bool:
    """A worker that exits on bad settings dies within a second or two of spawn."""

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if not _alive(pid):
            return False
        time.sleep(0.1)
    return _alive(pid)


def _record(
    config: LauncherConfig,
    api_pid: int,
    worker_pid: int,
    state: str,
    *,
    explanation: str | None = None,
    management: _Management | None = None,
    tls_pid: int = 0,
) -> dict[str, object]:
    text = explanation
    if text is None:
        text = {
            "running": "API와 worker가 실행 중입니다. 탭을 닫아도 프로세스는 유지됩니다.",
            "worker_missing": "worker가 없습니다.",
        }[state]
        if state == "running" and not config.vm_ready:
            text = f"{text} VM 미준비."
        if state == "running" and management is not None and not management.registered:
            text = f"{text} PC 등록 전이라 worker는 미등록 상태입니다."
    payload = {
        "host": config.host,
        "port": config.port,
        "api_pid": api_pid,
        "worker_pid": worker_pid,
        "state": state,
        "explanation": text,
        "command": _API_COMMAND.format(port=config.port),
        "publish": False,
        "vm_ready": config.vm_ready,
    }
    if management is not None:
        payload["management_origin"] = management.origin
        payload["management_pid"] = tls_pid
        payload["worker_registered"] = management.registered
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


def _stop_pids(api_pid: int, worker_pid: int, management_pid: int = 0) -> None:
    for pid in (api_pid, worker_pid, management_pid):
        if pid > 0:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
