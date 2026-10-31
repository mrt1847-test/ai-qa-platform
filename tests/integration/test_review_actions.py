"""Adversarial action boundary regressions from R07/R08/R09."""
from datetime import datetime, timedelta, timezone
import binascii
import sqlite3
import struct
import threading
import zlib
from pathlib import Path
from uuid import uuid4

import pytest

from aiqa.contracts.actions import ActionProposal, CaptureGeometry, Observation, PreparedAction
from aiqa.contracts.jobs import ControlDecision
from aiqa.recording.action_executor import ActionExecutor
from aiqa.security.redaction import RedactionError, filter_capture
from aiqa.worker.dispatch_journal import DispatchJournal
from aiqa.worker.runner import AttemptRunner, MonotonicInstant
from aiqa.worker.control import RunControl
from aiqa.contracts.jobs import LeaseView


def png_fixture(width=16, height=8):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', binascii.crc32(kind + data) & 0xffffffff)
    raw = b''.join(b'\0' + bytes((x * 17 + y * 7) % 256 for x in range(width)) for y in range(height))
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 0, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b'')


class Control:
    """Only substitutes the externally supplied control boundary."""
    def __init__(self, attempt='attempt-1'):
        self.allowed = True
        self.attempt_id = attempt
        self.runner = AttemptRunner()
        self.lease = LeaseView(uuid4(), uuid4(), 1, '100', 45, 10, 2)

    def checkpoint(self):
        return ControlDecision(self.allowed, 'fixture')

    def authorize_dispatch(self):
        return self.runner.authorize(MonotonicInstant(0), self.lease, 'before_dispatch') if self.allowed else self.checkpoint()


class Command:
    def __init__(self, cancel=None):
        self.calls = 0
        self.cancel = cancel

    def lookup(self, prepared):
        if self.cancel is not None:
            self.cancel.allowed = False
        return True

    def execute(self, prepared):
        self.calls += 1
        raise TimeoutError('delivery unknown')


def ready(action='A1', observation='O1'):
    return PreparedAction(ActionProposal('S1', action, 'click', 'fixture', 'path'), observation, 'before/ref', True)


def test_unknown_dispatch_is_not_repeated_after_reopening_journal(tmp_path):
    command = Command()
    control = Control()
    path = tmp_path / 'dispatch.jsonl'
    first = ActionExecutor(journal=DispatchJournal(path), command=command).dispatch_action(ready(), control)
    second = ActionExecutor(journal=DispatchJournal(path), command=command).dispatch_action(ready(observation='new-observation'), control)
    assert first.native_calls == 1
    assert command.calls == 1
    assert second.native_calls == 0


def test_action_ids_are_scoped_to_attempt(tmp_path):
    journal = DispatchJournal(tmp_path / 'dispatch.jsonl')
    command = Command()
    executor = ActionExecutor(journal=journal, command=command)
    executor.dispatch_action(ready(), Control('attempt-1'))
    receipt = executor.dispatch_action(ready(), Control('attempt-2'))
    assert command.calls == 2
    assert receipt.states == ('planned', 'dispatch_started', 'unknown')


def test_cancel_during_lookup_prevents_dispatch(tmp_path):
    control = Control()
    command = Command(control)
    result = ActionExecutor(journal=DispatchJournal(tmp_path / 'cancel.jsonl'), command=command).dispatch_action(ready(), control)
    assert command.calls == result.native_calls == 0


def test_actual_dispatch_uses_action_limit_and_lease_margin(tmp_path):
    control = Control()
    command = Command()
    executor = ActionExecutor(journal=DispatchJournal(tmp_path / 'limits.jsonl'), command=command)
    for i in range(51):
        executor.dispatch_action(ready(f'A{i}', f'O{i}'), control)
    assert command.calls == 50
    expired = Control('expired')
    expired.lease = LeaseView(uuid4(), uuid4(), 1, '9', 45, 10, 2)
    executor.dispatch_action(ready('expired'), expired)
    assert command.calls == 50


def test_concurrent_dispatch_reserves_delivery_once(tmp_path):
    command = Command()
    path = tmp_path / 'concurrent.jsonl'
    barrier = threading.Barrier(2)
    errors = []
    def dispatch():
        try:
            barrier.wait(timeout=5)
            ActionExecutor(journal=DispatchJournal(path), command=command).dispatch_action(ready(), Control())
        except BaseException as exc:
            errors.append(exc)
    threads = [threading.Thread(target=dispatch) for _ in range(2)]
    for t in threads: t.start()
    for t in threads: t.join(timeout=10)
    assert not errors
    assert not any(t.is_alive() for t in threads)
    assert command.calls == 1


def test_pixel_png_requires_provable_sanitization_with_secrets():
    png = png_fixture()
    capture = Observation('O1', '2026-11-01T00:00:00+00:00', CaptureGeometry(16, 8, 16, 8, 'identity', 0, (0, 0, 16, 8)), png, '', '', (), '', True, 'web')
    # Pixel data never contains the UTF-8 secret; byte replacement is no proof.
    assert b'PIN123' not in png
    with pytest.raises(RedactionError):
        filter_capture(capture, ('PIN123',))


def test_invalid_png_is_not_stored_as_sanitized_evidence():
    capture = Observation('O1', '2026-11-01T00:00:00+00:00', CaptureGeometry(16, 8, 16, 8, 'identity', 0, (0, 0, 16, 8)), b'pretend PNG', '', '', (), '', True, 'web')
    with pytest.raises(RedactionError):
        filter_capture(capture, ())


def test_real_run_control_enforces_bound_generation_and_dispatch_limit(review_recording, tmp_path):
    f = review_recording
    control = RunControl(f.con, f.project.project_id, f.job.job_id, 'before_dispatch', clock=lambda: 0, wall_clock=lambda: f.now)
    command = Command()
    executor = ActionExecutor(journal=DispatchJournal(tmp_path / 'real-limit.jsonl'), command=command)
    for i in range(51): executor.dispatch_action(ready(f'A{i}'), control)
    assert command.calls == 50
    stale = RunControl(f.con, f.project.project_id, f.job.job_id, 'before_dispatch', generation=2, clock=lambda: 0, wall_clock=lambda: f.now)
    executor.dispatch_action(ready('stale'), stale)
    assert command.calls == 50


def test_lease_expiring_during_journal_flush_prevents_command(review_recording, tmp_path):
    f = review_recording
    clock = {'age': 0}
    control = RunControl(f.con, f.project.project_id, f.job.job_id, 'before_dispatch', clock=lambda: clock['age'], wall_clock=lambda: f.now + timedelta(seconds=clock['age']))
    class SlowJournal(DispatchJournal):
        def append(self, attempt, action, state):
            super().append(attempt, action, state)
            if state == 'dispatch_started': clock['age'] = 36
    command = Command()
    receipt = ActionExecutor(journal=SlowJournal(tmp_path / 'slow.jsonl'), command=command).dispatch_action(ready(), control)
    assert receipt.native_calls == command.calls == 0


def test_phase_control_reopening_keeps_attempt_budget(review_recording):
    f = review_recording
    first = RunControl(f.con, f.project.project_id, f.job.job_id, 'before_dispatch', clock=lambda: 0, wall_clock=lambda: f.now)
    for _ in range(50): assert first.authorize_dispatch().allowed
    second = RunControl(f.con, f.project.project_id, f.job.job_id, 'before_dispatch', clock=lambda: 0, wall_clock=lambda: f.now)
    assert not second.authorize_dispatch().allowed


def test_persistent_journal_enforces_limit_even_with_new_external_control(tmp_path):
    command = Command()
    path = tmp_path / 'persistent-budget.jsonl'
    for index in range(51):
        # Each supplied external fixture starts with a fresh in-memory budget.
        ActionExecutor(journal=DispatchJournal(path), command=command).dispatch_action(ready(f'A{index}'), Control())
    assert command.calls == 50
