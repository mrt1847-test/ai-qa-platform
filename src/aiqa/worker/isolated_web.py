"""Probe whether this PC can separate a trusted web driver from a guest script.

The success flags stay unknown until a synthetic script has actually run inside
a disposable Linux VM. Host inventory is not that run.
"""

from __future__ import annotations

import shutil
import subprocess
import winreg
from dataclasses import dataclass

_HOST_COMMANDS = (
    ("wsl-status", ("wsl.exe", "--status")),
    ("vmms", ("sc.exe", "query", "vmms")),
    ("vmcompute", ("sc.exe", "query", "vmcompute")),
    ("lxss", ("sc.exe", "query", "LxssManager")),
    (
        "hypervisor-present",
        (
            "powershell.exe",
            "-NoProfile",
            "-Command",
            "(Get-CimInstance -ClassName Win32_ComputerSystem).HypervisorPresent",
        ),
    ),
)
_TOOL_NAMES = ("docker", "qemu-system-x86_64", "VBoxManage")


@dataclass(frozen=True)
class VmProbeConfig:
    backend: str
    destroy_after: bool


@dataclass(frozen=True)
class ProbeEvidence:
    kind: str
    name: str
    returncode: int | None
    detail: str


@dataclass(frozen=True)
class IsolationProbeReport:
    supported: bool
    vm_product: str
    vm_version: str
    prepare: str
    destroy: str
    driver_ipc: bool | None
    direct_cdp: bool | None
    script_model_network: bool | None
    host_secret_access: bool | None
    synthetic_script_ran: bool
    block_reason: str
    evidence: tuple[ProbeEvidence, ...]


def close_guest_context(provider: object | None) -> tuple[str, ...]:
    """Close a guest context only when the provider returns proof. Absence is unproven."""

    if provider is None:
        return ()
    close = getattr(provider, "close_context", None)
    if close is None:
        return ()
    result = close()
    if result is None:
        return ("context-closed",)
    return tuple(str(item) for item in result)


def _decode(raw: bytes) -> str:
    if not raw:
        return ""
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")) or (len(raw) > 3 and raw[1] == 0):
        text = raw.decode("utf-16-le", errors="replace")
    else:
        text = raw.decode("utf-8", errors="replace")
    text = text.replace("\x00", "").strip()
    if len(text) > 500:
        return text[:500]
    return text


def _run(command: tuple[str, ...]) -> ProbeEvidence:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return ProbeEvidence("host_command", command[0], None, str(exc))
    detail = "\n".join(part for part in (_decode(completed.stdout), _decode(completed.stderr)) if part)
    return ProbeEvidence("host_command", " ".join(command), completed.returncode, detail)


def _windows_edition() -> ProbeEvidence:
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows NT\CurrentVersion",
        ) as key:
            product, _ = winreg.QueryValueEx(key, "ProductName")
            edition, _ = winreg.QueryValueEx(key, "EditionID")
            display, _ = winreg.QueryValueEx(key, "DisplayVersion")
            build, _ = winreg.QueryValueEx(key, "CurrentBuild")
    except OSError as exc:
        return ProbeEvidence("host_command", "winreg", None, str(exc))
    detail = f"ProductName={product}; EditionID={edition}; DisplayVersion={display}; CurrentBuild={build}"
    return ProbeEvidence("host_command", "winreg", 0, detail)


def _tool_evidence() -> tuple[ProbeEvidence, ...]:
    rows = []
    for name in _TOOL_NAMES:
        found = shutil.which(name)
        rows.append(
            ProbeEvidence(
                "host_command",
                name,
                0 if found else 1,
                found or "absent",
            )
        )
    return tuple(rows)


def probe_web_isolation(config: VmProbeConfig) -> IsolationProbeReport:
    """Report live VM isolation. Unknown gates stay None."""
    if config.backend != "hyper-v":
        raise ValueError("only the hyper-v disposable Linux backend is in this probe")
    evidence = tuple(_run(command) for _, command in _HOST_COMMANDS)
    evidence += (_windows_edition(),)
    evidence += _tool_evidence()
    edition = next(item.detail for item in evidence if item.name == "winreg")
    block_reason = (
        "같은 PC의 disposable Linux VM을 만들지 못했다. "
        f"호스트는 {edition}. "
        "vmms/vmcompute/LxssManager 서비스가 없고, wsl --status는 하위 시스템이 없다고 반환했다. "
        "docker, qemu-system-x86_64, VBoxManage도 없다. "
        "Windows Home(EditionID Core)에서는 Hyper-V VM 역할을 켤 수 없다. "
        "합성 script의 CDP, model endpoint, host credential, subprocess 시도는 실행하지 않았다. "
        "HypervisorPresent만으로는 VM을 만든 근거가 아니다."
    )
    return IsolationProbeReport(
        supported=False,
        vm_product="",
        vm_version="",
        prepare="not executed",
        destroy="not executed" if config.destroy_after else "destroy_after was false; still not executed",
        driver_ipc=None,
        direct_cdp=None,
        script_model_network=None,
        host_secret_access=None,
        synthetic_script_ran=False,
        block_reason=block_reason,
        evidence=evidence,
    )


def require_web_ready(proof_ready: object | None) -> bool:
    """Web ready requires an isolation confirmation. Probe inventory alone is not enough."""

    return proof_ready is not None


def admit_recording_channel(kind: str) -> None:
    """Recording guest may use IPC only. Shell/CDP/host reads stay closed on the host adapter."""

    if kind != "ipc":
        raise ValueError(f"recording channel refused: {kind}")


def bind_web_vm_transport(
    gate: object,
    *,
    approved_endpoints: frozenset[str] | tuple[str, ...],
    allow_real_vm: bool = False,
    fail_connect: bool = False,
    limits: object | None = None,
    bindings: object = (),
) -> object:
    """Attach allowlisted VM IPC transport. Actual VM image acceptance remains RX-22.

    Optional local guest bindings (127.0.0.1) enable RX-35 process IPC without a real VM.
    """

    from aiqa.worker.web_isolation_backend import IsolationConfig, WebIsolationGate
    from aiqa.worker.web_vm_transport import GuestIpcLimits, open_web_vm_transport

    if not isinstance(gate, WebIsolationGate):
        raise ValueError("web isolation gate is required")
    if not isinstance(gate.config, IsolationConfig):
        raise ValueError("isolation config is required")
    resolved_limits = limits if isinstance(limits, GuestIpcLimits) else None
    return open_web_vm_transport(
        gate,
        approved_endpoints=approved_endpoints,
        allow_real_vm=allow_real_vm,
        fail_connect=fail_connect,
        limits=resolved_limits,
        bindings=bindings,  # type: ignore[arg-type]
    )


def transport_as_cleanup_provider(transport: object) -> object:
    """Expose close_context proof for attempt cleanup."""

    class _Provider:
        def close_context(self) -> tuple[str, ...]:
            close = getattr(transport, "close", None)
            if close is None:
                return ()
            return tuple(close())

    return _Provider()

