"""USB dispatch gate and read-only installed-app listing.

Importing this module does not open a device or an ADB server.
"""

from __future__ import annotations

import math
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath

from aiqa.replay.targets import TargetResolution

_PACKAGE_LINE = re.compile(
    r"^package:(?P<path>.+?)=(?P<package>[A-Za-z0-9_.]+)\s*$"
)
_VERSION_NAME = re.compile(r"versionName=([^\s]+)")
_SERIAL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_FORBIDDEN = (
    "install",
    "uninstall",
    "pm clear",
    "factory",
    "wipe",
    "reboot",
    "push",
    "pull",
    "am start",
    "cmd package install",
)


@dataclass(frozen=True, slots=True)
class InstalledAppView:
    """One installed package from a read-only ADB listing. Byte hash stays unknown."""

    package: str
    version_name: str | None
    api_level: int | None
    abi: str | None
    content_hash: str


@dataclass(frozen=True, slots=True)
class InstalledAppsObservation:
    """Result of one dedicated-serial installed-apps probe. Install/reset stay at zero."""

    serial: str
    state: str
    reason: str
    observed_at: str
    apps: tuple[InstalledAppView, ...]
    install_calls: int
    reset_calls: int


def allow_dispatch(resolution: TargetResolution) -> bool:
    """Allow one already resolved target. A blocked or ambiguous target stays closed."""

    return resolution.dispatched and not resolution.blocked


def require_dedicated_serial(expected: str, observed: str) -> bool:
    """Inventory and dispatch stay on the enrolled serial only."""

    if type(expected) is not str or type(observed) is not str:
        return False
    if expected.strip() == "" or observed.strip() == "":
        return False
    return expected == observed


def list_installed_apps(
    adb_path: Path,
    serial: str,
    *,
    expected_serial: str,
    run: Callable[..., subprocess.CompletedProcess] | None = None,
    command_timeout: float = 10.0,
) -> InstalledAppsObservation:
    """List packages on one enrolled serial. Never installs, resets, or opens another device."""

    stamp = datetime.now(timezone.utc).isoformat()
    if not require_dedicated_serial(expected_serial, serial):
        return InstalledAppsObservation(
            serial=serial if type(serial) is str else "",
            state="unavailable",
            reason="serial_mismatch",
            observed_at=stamp,
            apps=(),
            install_calls=0,
            reset_calls=0,
        )
    path = Path(adb_path)
    if path.name.lower() not in {"adb", "adb.exe"} or not (
        path.is_absolute() or PureWindowsPath(str(path)).is_absolute()
    ):
        raise ValueError("an explicit absolute ADB executable path is required")
    if type(serial) is not str or _SERIAL.fullmatch(serial) is None:
        raise ValueError("an explicit serial without whitespace or options is required")
    if type(command_timeout) not in (int, float) or not math.isfinite(command_timeout) or not 0 < command_timeout <= 90:
        raise ValueError("finite positive deadlines up to 90 seconds are required")

    if run is None:
        from aiqa.environments import android_observation

        runner = android_observation._run_bounded
    else:
        runner = run
    install_calls = 0
    reset_calls = 0

    def invoke(*command: str) -> subprocess.CompletedProcess:
        joined = " ".join(command).lower()
        for token in _FORBIDDEN:
            if token in joined:
                raise RuntimeError(f"read-only probe refused mutating command: {token}")
        argv = [str(path), "-s", serial, *command]
        return runner(argv, timeout=command_timeout)

    try:
        state_response = invoke("get-state")
    except subprocess.TimeoutExpired:
        return InstalledAppsObservation(serial, "unavailable", "command_timeout", stamp, (), 0, 0)
    except OSError:
        return InstalledAppsObservation(serial, "unavailable", "adb_unavailable", stamp, (), 0, 0)

    diagnostic = (state_response.stderr or b"").lower()
    state_text = (state_response.stdout or b"").decode("utf-8", errors="replace").strip()
    if b"unauthorized" in diagnostic or state_text == "unauthorized":
        return InstalledAppsObservation(serial, "unauthorized", "device_unauthorized", stamp, (), 0, 0)
    if (
        state_response.returncode
        or state_text != "device"
        or b"offline" in diagnostic
        or b"not found" in diagnostic
        or b"no devices" in diagnostic
    ):
        return InstalledAppsObservation(serial, "offline", "device_offline", stamp, (), 0, 0)

    try:
        listed = invoke("shell", "pm", "list", "packages", "-f")
        api_raw = invoke("shell", "getprop", "ro.build.version.sdk")
        abi_raw = invoke("shell", "getprop", "ro.product.cpu.abi")
    except subprocess.TimeoutExpired:
        return InstalledAppsObservation(serial, "unavailable", "command_timeout", stamp, (), 0, 0)
    except OSError:
        return InstalledAppsObservation(serial, "unavailable", "adb_unavailable", stamp, (), 0, 0)
    except RuntimeError as exc:
        return InstalledAppsObservation(serial, "unavailable", str(exc), stamp, (), install_calls, reset_calls)

    if listed.returncode:
        err = (listed.stderr or b"").lower()
        if b"unauthorized" in err or b"permission" in err or b"denied" in err:
            return InstalledAppsObservation(serial, "unauthorized", "permission_denied", stamp, (), 0, 0)
        return InstalledAppsObservation(serial, "unavailable", "adb_read_failed", stamp, (), 0, 0)

    api_level: int | None = None
    if api_raw.returncode == 0:
        text = api_raw.stdout.decode("utf-8", errors="replace").strip()
        if text.isdigit():
            api_level = int(text)
    abi = None
    if abi_raw.returncode == 0:
        value = abi_raw.stdout.decode("utf-8", errors="replace").strip()
        abi = value or None

    apps: list[InstalledAppView] = []
    packages: list[str] = []
    for line in listed.stdout.decode("utf-8", errors="replace").splitlines():
        match = _PACKAGE_LINE.match(line.strip())
        if match is None:
            continue
        packages.append(match.group("package"))

    for package in packages:
        version_name = None
        try:
            detail = invoke("shell", "dumpsys", "package", package)
        except (subprocess.TimeoutExpired, OSError, RuntimeError):
            detail = None
        if detail is not None and detail.returncode == 0:
            found = _VERSION_NAME.search(detail.stdout.decode("utf-8", errors="replace"))
            if found is not None:
                version_name = found.group(1)
        apps.append(
            InstalledAppView(
                package=package,
                version_name=version_name,
                api_level=api_level,
                abi=abi,
                content_hash="unknown",
            )
        )

    return InstalledAppsObservation(
        serial=serial,
        state="ready",
        reason="observed",
        observed_at=datetime.now(timezone.utc).isoformat(),
        apps=tuple(apps),
        install_calls=install_calls,
        reset_calls=reset_calls,
    )
