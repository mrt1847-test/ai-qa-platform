"""Read one explicitly selected Android device. Raw pixels stay in memory."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
from pathlib import Path, PureWindowsPath
import re
import subprocess
import struct
import threading
import time
from uuid import uuid4

from aiqa.contracts.actions import CaptureGeometry, Observation
from aiqa.security.redaction import RedactionError, _validate_png


@dataclass(frozen=True, slots=True)
class AndroidObservationResult:
    serial: str
    state: str
    reason: str
    observed_at: str
    device_kind: str
    avd_name: str | None = None
    android_release: str | None = None
    api_level: int | None = None
    model: str | None = None
    density: int | None = None
    geometry: CaptureGeometry | None = None
    observation: Observation | None = field(default=None, repr=False)
    sanitized: bool = False


class _ReadFailure(Exception):
    def __init__(self, state: str, reason: str):
        self.state, self.reason = state, reason


def _run_bounded(argv: list[str], *, timeout: float) -> subprocess.CompletedProcess:
    """Drain both pipes with byte limits and reap this exact child on failure."""
    process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, shell=False, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    buffers = [bytearray(), bytearray()]
    overflow, read_error = threading.Event(), threading.Event()
    deadline = time.monotonic() + timeout

    def stop():
        try:
            process.kill()
        except OSError:
            pass

    def drain(stream, buffer, limit):
        try:
            while chunk := stream.read1(65536):
                if len(buffer) + len(chunk) > limit:
                    overflow.set()
                    stop()
                    return
                buffer.extend(chunk)
        except OSError:
            read_error.set()
            stop()
        finally:
            stream.close()

    readers = [threading.Thread(target=drain, args=(stream, buffer, limit), daemon=True)
        for stream, buffer, limit in zip((process.stdout, process.stderr), buffers, (8_000_000, 65536), strict=True)]
    for reader in readers:
        reader.start()
    try:
        process.wait(timeout=max(0.001, deadline - time.monotonic()))
        for reader in readers:
            reader.join(timeout=max(0, deadline - time.monotonic()))
        if any(reader.is_alive() for reader in readers):
            raise subprocess.TimeoutExpired(argv, timeout)
        if overflow.is_set():
            raise _ReadFailure('unavailable', 'response_too_large')
        if read_error.is_set():
            raise _ReadFailure('unavailable', 'adb_read_failed')
        return subprocess.CompletedProcess(argv, process.returncode, bytes(buffers[0]), bytes(buffers[1]))
    finally:
        if process.poll() is None:
            stop()
            process.wait(timeout=1)
        for reader in readers:
            reader.join(timeout=0.2)


def _validate_screenshot(pixels: bytes, width: int, height: int) -> None:
    """Accept the bounded RGB/RGBA8 screenshot subset, not arbitrary PNG variants."""
    _validate_png(pixels, width, height)
    if pixels[24] != 8 or pixels[25] not in (2, 6):
        raise RedactionError('unsupported screenshot format')
    channels = 3 if pixels[25] == 2 else 4
    offset, started, seen = 8, False, set()
    while offset < len(pixels):
        size = struct.unpack_from('>I', pixels, offset)[0]
        kind = pixels[offset + 4:offset + 8]
        body = pixels[offset + 8:offset + 8 + size]
        if kind == b'IDAT':
            started = True
        elif kind in (b'sRGB', b'sBIT'):
            if started or kind in seen:
                raise RedactionError('invalid screenshot chunk order')
            if kind == b'sRGB' and (size != 1 or body[0] > 3):
                raise RedactionError('invalid screenshot color space')
            if kind == b'sBIT' and (size != channels or any(not 1 <= bit <= 8 for bit in body)):
                raise RedactionError('invalid screenshot precision')
        elif kind not in (b'IHDR', b'IEND'):
            raise RedactionError('unsupported screenshot chunk')
        seen.add(kind)
        offset += size + 12


class AndroidObservationProvider:
    """Bounded, read-only ADB observation; no discovery, retry, upload or dispatch.

    Geometry describes the whole default display, not app-content bounds. Valid
    PNG bytes are raw observations: validation does not prove pixel redaction or
    that FLAG_SECURE content can be captured. Consumers must retain that gate.
    """

    def __init__(self, adb_path: Path, serial: str, *, expected_avd: str | None = None,
                 command_timeout: float = 10.0, observation_timeout: float = 30.0):
        path = Path(adb_path)
        if path.name.lower() not in {'adb', 'adb.exe'} or not (path.is_absolute() or PureWindowsPath(str(path)).is_absolute()):
            raise ValueError('an explicit absolute ADB executable path is required')
        if type(serial) is not str or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,127}', serial) is None:
            raise ValueError('an explicit serial without whitespace or options is required')
        if serial.startswith('emulator-') and (not expected_avd or re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', expected_avd) is None):
            raise ValueError('an expected AVD name is required for an emulator')
        for value in (command_timeout, observation_timeout):
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 90:
                raise ValueError('finite positive deadlines up to 90 seconds are required')
        self.adb_path, self.serial, self.expected_avd = path, serial, expected_avd
        self.command_timeout, self.observation_timeout = command_timeout, observation_timeout

    def observe(self, *, capture: bool = True) -> AndroidObservationResult:
        if type(capture) is not bool:
            raise ValueError('capture must be a boolean')
        deadline = time.monotonic() + self.observation_timeout
        metadata: dict[str, object] = {}

        def run(*command: str) -> bytes:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _ReadFailure('unavailable', 'observation_timeout')
            try:
                response = _run_bounded([str(self.adb_path), '-s', self.serial, *command],
                    timeout=min(self.command_timeout, remaining))
            except subprocess.TimeoutExpired:
                raise _ReadFailure('unavailable', 'command_timeout') from None
            except OSError:
                raise _ReadFailure('unavailable', 'adb_unavailable') from None
            if response.returncode:
                diagnostic = response.stderr.lower()
                if b'unauthorized' in diagnostic:
                    raise _ReadFailure('unauthorized', 'device_unauthorized')
                if b'offline' in diagnostic or b'not found' in diagnostic or b'no devices' in diagnostic:
                    raise _ReadFailure('offline', 'device_offline')
                reason = 'capture_failed' if command == ('exec-out', 'screencap', '-p') else 'adb_read_failed'
                raise _ReadFailure('capture_unavailable' if reason == 'capture_failed' else 'unavailable', reason)
            return response.stdout

        def text(*command: str) -> str:
            return run(*command).decode('utf-8', errors='replace').strip()

        def target():
            state = text('get-state')
            if state != 'device':
                raise _ReadFailure('unauthorized' if state == 'unauthorized' else 'offline', 'device_unavailable')
            if self.serial.startswith('emulator-'):
                name = text('emu', 'avd', 'name').splitlines()
                if not name or name[0] != self.expected_avd:
                    raise _ReadFailure('unavailable', 'avd_mismatch')
                metadata['avd_name'] = name[0]

        def display() -> tuple[CaptureGeometry, int]:
            sizes = re.findall(r'(?:Physical|Override) size:\s*([0-9]{1,5})x([0-9]{1,5})(?![0-9])', text('shell', 'wm', 'size'))
            densities = re.findall(r'(?:Physical|Override) density:\s*([0-9]{1,5})(?![0-9])', text('shell', 'wm', 'density'))
            viewports = set()
            for line in text('shell', 'dumpsys', 'input').splitlines():
                if 'Viewport ' not in line or re.search(r'\bdisplayId\s*=\s*0\b', line) is None or re.search(r'isActive\s*=\s*\[0\]', line):
                    continue
                match = re.search(r'orientation\s*=\s*([0-3])\s*,.*logicalFrame=\[\s*([0-9]{1,5}),\s*([0-9]{1,5}),\s*([0-9]{1,5}),\s*([0-9]{1,5})\]', line)
                if match is None:
                    raise _ReadFailure('unavailable', 'geometry_unavailable')
                viewports.add(tuple(map(int, match.groups())))
            if not sizes or not densities or len(viewports) != 1:
                raise _ReadFailure('unavailable', 'geometry_unavailable')
            rotation, left, top, width, height = viewports.pop()
            natural = tuple(map(int, sizes[-1]))
            expected = natural[::-1] if rotation % 2 else natural
            density = int(densities[-1])
            if left or top or (width, height) != expected or min(width, height, density) < 1 or width * height > 16_000_000:
                raise _ReadFailure('unavailable', 'geometry_unavailable')
            return CaptureGeometry(width, height, width, height, 'identity', rotation * 90, (0, 0, width, height)), density

        def result(state: str, reason: str, geometry=None, density=None, observation=None):
            if state == 'ready' and time.monotonic() >= deadline:
                state, reason, geometry, density, observation = 'unavailable', 'observation_timeout', None, None, None
            return AndroidObservationResult(self.serial, state, reason, datetime.now(timezone.utc).isoformat(),
                'android_emulator' if self.serial.startswith('emulator-') else 'android_usb',
                geometry=geometry, density=density, observation=observation, **metadata)

        try:
            target()
            if text('shell', 'getprop', 'sys.boot_completed') != '1':
                return result('booting', 'boot_incomplete')
            release = text('shell', 'getprop', 'ro.build.version.release')
            api = text('shell', 'getprop', 'ro.build.version.sdk')
            model = text('shell', 'getprop', 'ro.product.model')
            if not 1 <= len(api) <= 3 or not api.isascii() or not api.isdigit() or not 1 <= int(api) <= 999 or not release or not model or max(len(release), len(model)) > 256:
                raise _ReadFailure('unavailable', 'metadata_unavailable')
            metadata.update(android_release=release, api_level=int(api), model=model)
            geometry, density = display()
            if not capture:
                return result('ready', 'metadata_only', geometry, density)
            captured_at = datetime.now(timezone.utc).isoformat()
            pixels = run('exec-out', 'screencap', '-p')
            try:
                _validate_screenshot(pixels, geometry.physical_width, geometry.physical_height)
            except RedactionError:
                raise _ReadFailure('capture_unavailable', 'capture_invalid') from None
            target()
            if display() != (geometry, density):
                raise _ReadFailure('unavailable', 'geometry_changed')
            observation = Observation(str(uuid4()), captured_at, geometry, pixels, '', '', (), '', True, 'android')
            return result('ready', 'observed', geometry, density, observation)
        except _ReadFailure as exc:
            return result(exc.state, exc.reason)


class AndroidGeometryError(ValueError):
    """Capture geometry cannot be used for parse or rescale."""


def require_usable_geometry(observation: Observation):
    """Reject missing or inconsistent capture geometry before parse/rescale."""

    if observation.geometry is None or not observation.capture_ok:
        raise AndroidGeometryError("geometry is invalid")
    geo = observation.geometry
    if geo.physical_width < 1 or geo.physical_height < 1:
        raise AndroidGeometryError("geometry is invalid")
    if geo.model_width < 1 or geo.model_height < 1:
        raise AndroidGeometryError("geometry is invalid")
    if geo.rotation not in {0, 90, 180, 270}:
        raise AndroidGeometryError("geometry is invalid")
    left, top, right, bottom = geo.content_bounds
    if (
        left < 0
        or top < 0
        or right > geo.physical_width
        or bottom > geo.physical_height
        or left >= right
        or top >= bottom
    ):
        raise AndroidGeometryError("geometry is invalid")
    return geo
