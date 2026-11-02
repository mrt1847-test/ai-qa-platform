"""AD-01: real observation logic with a test-only ADB process boundary."""
from __future__ import annotations

import binascii
import importlib
import importlib.util
from pathlib import Path
import struct
import subprocess
import sys
import zlib

import pytest


def provider_module():
    assert importlib.util.find_spec('aiqa.environments.android_observation') is not None, 'AD-01 observation provider is missing'
    return importlib.import_module('aiqa.environments.android_observation')


def png(width=24, height=48, color=2, extra=None):
    def chunk(kind, body):
        return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', binascii.crc32(kind + body) & 0xffffffff)
    channels = {2: 3, 3: 1, 6: 4}[color]
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, color, 0, 0, 0)) + (chunk(*extra) if extra else b'') + chunk(b'IDAT', zlib.compress((b'\x00' + b'\x00' * width * channels) * height)) + chunk(b'IEND', b'')


class AdbBoundary:
    def __init__(self):
        self.calls = []
        self.state = 'device'
        self.avd = 'AIQA_API36'
        self.booted = '1'
        self.pixels = png()
        self.size = b'Physical size: 24x48\n'
        self.rotation = 0
        self.capture_seen = False
        self.changed = False
        self.timeout = False

    def __call__(self, argv, **kwargs):
        assert isinstance(argv, list) and argv[1:3] == ['-s', 'emulator-5580']
        assert kwargs.get('shell', False) is False
        assert 0 < kwargs['timeout'] <= 10
        self.calls.append(tuple(argv[3:]))
        command = tuple(argv[3:])
        if self.timeout:
            raise subprocess.TimeoutExpired(argv, kwargs['timeout'], stderr=b'PRIVATE DIAGNOSTIC')
        code, error = 0, b''
        if command == ('get-state',):
            output = self.state.encode()
            if self.state != 'device': code, error = 1, f'error: device {self.state} PRIVATE'.encode()
        elif command == ('emu', 'avd', 'name'):
            output = (self.avd + '\nOK\n').encode()
        elif command[:2] == ('shell', 'getprop'):
            output = {'sys.boot_completed': self.booted, 'ro.build.version.release': '16', 'ro.build.version.sdk': '36', 'ro.product.model': 'sdk_gphone64_x86_64'}[command[2]].encode()
        elif command == ('shell', 'wm', 'size'):
            output = self.size
        elif command == ('shell', 'wm', 'density'):
            output = b'Physical density: 160\n'
        elif command == ('shell', 'dumpsys', 'input'):
            rotation = 1 if self.capture_seen and self.changed else self.rotation
            w, h = (48, 24) if rotation % 2 else (24, 48)
            output = f'Viewport INTERNAL: displayId=0, orientation={rotation}, logicalFrame=[0, 0, {w}, {h}], isActive=[1]\n'.encode()
        elif command == ('exec-out', 'screencap', '-p'):
            self.capture_seen = True
            output = self.pixels
        else:
            raise AssertionError(f'Unexpected ADB command: {command}')
        return subprocess.CompletedProcess(argv, code, output, error)


@pytest.fixture
def boundary(monkeypatch):
    fake = AdbBoundary()
    monkeypatch.setattr(provider_module(), '_run_bounded', fake)
    return fake


def observe(boundary, **options):
    module = provider_module()
    return module.AndroidObservationProvider(Path('C:/sdk/adb.exe'), 'emulator-5580', expected_avd='AIQA_API36').observe(**options)


def test_ready_observation_has_matching_valid_png_and_explicit_serial(boundary):
    result = observe(boundary)
    assert result.state == 'ready' and result.reason == 'observed'
    assert result.serial == 'emulator-5580' and result.device_kind == 'android_emulator'
    assert result.avd_name == 'AIQA_API36' and result.api_level == 36 and result.android_release == '16'
    assert result.observation.capture_ok is True
    assert result.observation.geometry.physical_width == 24
    assert result.observation.geometry.physical_height == 48
    assert result.observation.geometry.rotation == 0
    assert result.observation.geometry.content_bounds == (0, 0, 24, 48)
    assert result.observation.png == png() and result.sanitized is False
    assert result.observation.captured_at.endswith('+00:00')
    assert result.observation.reasoning == '' and result.observation.stdout == ''
    assert boundary.calls.count(('exec-out', 'screencap', '-p')) == 1


@pytest.mark.parametrize('state', ['offline', 'unauthorized', 'not found'])
def test_unavailable_device_stops_without_fallback_or_capture(boundary, state):
    boundary.state = state
    result = observe(boundary)
    assert result.state == ('unauthorized' if state == 'unauthorized' else 'offline')
    assert result.observation is None and len(boundary.calls) == 1
    assert 'PRIVATE' not in result.reason


def test_booting_and_wrong_avd_do_not_capture(boundary):
    boundary.booted = ''
    assert observe(boundary).state == 'booting'
    boundary.booted = '1'; boundary.avd = 'Other_AVD'
    assert observe(boundary).reason == 'avd_mismatch'
    assert not boundary.capture_seen


@pytest.mark.parametrize('invalid', [b'', b'not a PNG', png(48, 24), png()[:-6]])
def test_corrupt_or_wrong_geometry_capture_is_not_ready(boundary, invalid):
    boundary.pixels = invalid
    result = observe(boundary)
    assert result.state == 'capture_unavailable' and result.observation is None


def test_geometry_change_during_capture_discards_pixels_without_retry(boundary):
    boundary.changed = True
    result = observe(boundary)
    assert result.reason == 'geometry_changed' and result.observation is None
    assert boundary.calls.count(('exec-out', 'screencap', '-p')) == 1


def test_unknown_rotation_does_not_guess_or_capture(boundary, monkeypatch):
    original = boundary.__class__.__call__
    def unknown(self, argv, **kwargs):
        response = original(self, argv, **kwargs)
        if argv[3:] == ['shell', 'dumpsys', 'input']:
            response.stdout = b'unknown default display geometry'
        return response
    monkeypatch.setattr(boundary.__class__, '__call__', unknown)
    result = observe(boundary)
    assert result.reason == 'geometry_unavailable' and not boundary.capture_seen


def test_rotated_display_uses_observed_dimensions(boundary):
    boundary.rotation = 1; boundary.pixels = png(48, 24)
    result = observe(boundary)
    assert result.state == 'ready'
    assert (result.observation.geometry.physical_width, result.observation.geometry.physical_height, result.observation.geometry.rotation) == (48, 24, 90)


def test_explicit_override_size_is_used_instead_of_natural_size(boundary):
    boundary.size = b'Physical size: 48x96\nOverride size: 24x48\n'
    result = observe(boundary)
    assert result.state == 'ready' and result.geometry.physical_width == 24


def test_whole_observation_budget_stops_before_capture(boundary, monkeypatch):
    module = provider_module()
    clock = [0.0]
    original = boundary.__class__.__call__
    def advance(self, argv, **kwargs):
        response = original(self, argv, **kwargs)
        clock[0] += 0.06
        return response
    monkeypatch.setattr(boundary.__class__, '__call__', advance)
    monkeypatch.setattr(module.time, 'monotonic', lambda: clock[0])
    result = module.AndroidObservationProvider(Path('C:/sdk/adb.exe'), 'emulator-5580', expected_avd='AIQA_API36', observation_timeout=0.1).observe()
    assert result.reason == 'observation_timeout' and not boundary.capture_seen
    assert len(boundary.calls) == 2


def test_device_disconnect_after_capture_does_not_return_stale_pixels(boundary, monkeypatch):
    original = boundary.__class__.__call__
    def disconnect(self, argv, **kwargs):
        response = original(self, argv, **kwargs)
        if self.capture_seen: self.state = 'offline'
        return response
    monkeypatch.setattr(boundary.__class__, '__call__', disconnect)
    result = observe(boundary)
    assert result.state == 'offline' and result.observation is None


def test_capture_can_be_omitted_for_metadata_only_inventory(boundary):
    result = observe(boundary, capture=False)
    assert result.state == 'ready' and result.observation is None
    assert result.geometry.physical_width == 24 and not boundary.capture_seen


def test_timeout_is_bounded_and_diagnostics_are_not_returned(boundary):
    boundary.timeout = True
    result = observe(boundary)
    assert result.state == 'unavailable' and result.reason == 'command_timeout'
    assert result.observation is None and len(boundary.calls) == 1


def test_explicit_target_and_finite_deadlines_required_without_process(boundary):
    module = provider_module()
    for serial in ['', '-s', 'emulator-5580 other', 'emulator-5580\n']:
        with pytest.raises(ValueError): module.AndroidObservationProvider(Path('C:/sdk/adb.exe'), serial, expected_avd='AIQA_API36')
    for timeout in [0, -1, float('nan'), float('inf'), True]:
        with pytest.raises(ValueError): module.AndroidObservationProvider(Path('C:/sdk/adb.exe'), 'emulator-5580', expected_avd='AIQA_API36', command_timeout=timeout)
    with pytest.raises(ValueError): module.AndroidObservationProvider(Path('C:/sdk/adb.exe'), 'emulator-5580')
    assert boundary.calls == []


def test_import_has_no_adb_side_effects(monkeypatch):
    calls = []
    def forbidden_process(*args, **kwargs):
        calls.append(args)
        raise AssertionError('Import must not launch a process')
    monkeypatch.setattr(subprocess, 'Popen', forbidden_process)
    importlib.reload(provider_module())
    assert calls == []


@pytest.mark.parametrize('malformed', [png(color=3), png(extra=(b'BOOM', b'unknown critical chunk'))])
def test_unsupported_png_structures_are_not_valid_screenshots(boundary, malformed):
    boundary.pixels = malformed
    assert observe(boundary).state == 'capture_unavailable'


def test_unknown_active_default_viewport_is_not_ignored(boundary, monkeypatch):
    original = boundary.__class__.__call__
    def ambiguous(self, argv, **kwargs):
        response = original(self, argv, **kwargs)
        if argv[3:] == ['shell', 'dumpsys', 'input']:
            response.stdout += b'Viewport INTERNAL: displayId=0, orientation=4, logicalFrame=[0, 0, 24, 48], isActive=[1]\n'
        return response
    monkeypatch.setattr(boundary.__class__, '__call__', ambiguous)
    result = observe(boundary)
    assert result.reason == 'geometry_unavailable' and not boundary.capture_seen


@pytest.mark.parametrize('command', [('shell', 'getprop', 'ro.build.version.sdk'), ('shell', 'wm', 'size'), ('shell', 'wm', 'density')])
def test_oversized_numeric_metadata_returns_structured_failure(boundary, monkeypatch, command):
    original = boundary.__class__.__call__
    def oversized(self, argv, **kwargs):
        response = original(self, argv, **kwargs)
        if tuple(argv[3:]) == command:
            value = b'9' * 5000
            response.stdout = (b'Physical size: ' + value + b'x48' if command[-1] == 'size' else b'Physical density: ' + value if command[-1] == 'density' else value)
        return response
    monkeypatch.setattr(boundary.__class__, '__call__', oversized)
    result = observe(boundary)
    assert result.state == 'unavailable' and result.observation is None
    assert result.reason in {'metadata_unavailable', 'geometry_unavailable'}


@pytest.mark.parametrize('stream,count', [('stdout', 9_000_000), ('stderr', 100_000)])
def test_process_reader_bounds_both_streams_and_reaps_on_overflow(monkeypatch, stream, count):
    module = provider_module()
    assert hasattr(module, '_run_bounded'), 'Subprocess streams need limits while reading'
    processes = []
    original = subprocess.Popen
    def tracked(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process
    monkeypatch.setattr(subprocess, 'Popen', tracked)
    script = f'import sys,time;sys.{stream}.buffer.write(b"x"*{count});sys.{stream}.flush();time.sleep(30)'
    with pytest.raises(module._ReadFailure) as error:
        module._run_bounded([sys.executable, '-c', script], timeout=5)
    assert error.value.reason == 'response_too_large'
    assert len(processes) == 1 and processes[0].poll() is not None


def test_process_reader_reaps_timed_out_child(monkeypatch):
    module = provider_module()
    processes = []
    original = subprocess.Popen
    def tracked(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process
    monkeypatch.setattr(subprocess, 'Popen', tracked)
    with pytest.raises(subprocess.TimeoutExpired):
        module._run_bounded([sys.executable, '-c', 'import time;time.sleep(20)'], timeout=0.1)
    assert len(processes) == 1 and processes[0].poll() is not None
