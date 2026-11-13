"""Keep one acknowledged attempt live while a handler waits; never resume a failed fence."""
from __future__ import annotations

import math
import threading
import time
from datetime import datetime, timezone
from uuid import uuid4

from aiqa.contracts.jobs import ControlDecision
from aiqa.worker.checkpoints import WorkerAttemptCheckpoint


class WorkerAttemptKeepalive(WorkerAttemptCheckpoint):
    def __init__(self, client, claim, boot_id, *, interval=10.0, join_timeout=15.0, clock=time.monotonic):
        super().__init__(client,claim,clock=clock)
        if type(boot_id) is not str or not boot_id or claim.get('boot_id',boot_id)!=boot_id:
            raise ValueError('keepalive boot invalid')
        for value in (interval,join_timeout):
            if type(value) not in (int,float) or not math.isfinite(value) or value<=0:
                raise ValueError('keepalive timing invalid')
        if interval>10:
            raise ValueError('keepalive interval invalid')
        self.boot_id = boot_id
        self.interval = float(interval)
        self.join_timeout = float(join_timeout)
        self._stop = threading.Event()
        self._failed = threading.Event()
        self._thread = None

    @property
    def failed(self):
        return self._failed.is_set()

    def checkpoint(self, phase):
        if self._stop.is_set() or self.failed:
            return ControlDecision(False,'attempt_control_closed')
        decision = super().checkpoint(phase)
        if decision.allowed is not True:
            self._failed.set()
        if self._stop.is_set() or self.failed:
            return ControlDecision(False,'attempt_control_closed')
        return decision

    def pulse(self):
        if self._stop.is_set() or self.failed:
            return False
        try:
            heartbeat = self.client.heartbeat(self.boot_id)
            if type(heartbeat) is not dict or heartbeat.get('state')!='online':
                raise ValueError('worker heartbeat unavailable')
            if self._stop.is_set() or self.failed:
                return False
            if super().checkpoint('after_model').allowed is not True:
                raise ValueError('attempt fence unavailable')
            if self._stop.is_set() or self.failed:
                return False
            view = self.client.renew(project_id=self.owner['project_id'],job_id=self.owner['job_id'],
                generation=self.owner['generation'],now=datetime.now(timezone.utc).isoformat(),model_wait=True,
                idempotency_key='keepalive:'+str(uuid4()))
            if (type(view) is not dict or type(view.get('generation')) is not int
                or any(view.get(key)!=self.owner[key] for key in ('project_id','job_id','generation'))
                or datetime.fromisoformat(view['expires_at']).tzinfo is None):
                raise ValueError('lease renewal invalid')
        except Exception:
            # Failure latches for this attempt. A later network recovery cannot resume it.
            self._failed.set()
            return False
        return not self._stop.is_set() and not self.failed

    def _run(self):
        while not self._stop.wait(self.interval):
            if not self.pulse():
                break

    def start(self):
        if self._stop.is_set() or self.failed:
            raise ValueError('attempt control cannot restart')
        if self._thread is not None:
            return self
        self._thread = threading.Thread(target=self._run,name='aiqa-control-'+self.owner['attempt_id'],daemon=True)
        try:
            self._thread.start()
        except (RuntimeError,OSError):
            self._failed.set()
        return self

    def close(self):
        self._stop.set()
        if self._thread is not None and self._thread.is_alive():
            if self._thread is threading.current_thread():
                self._failed.set()
                return False
            self._thread.join(timeout=self.join_timeout)
            if self._thread.is_alive():
                self._failed.set()
                return False
        return True
