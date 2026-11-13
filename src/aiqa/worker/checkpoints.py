"""Consume fresh management fence replies without DB access or reusable allow caches."""
from __future__ import annotations

import math
import time
from datetime import datetime
from uuid import UUID, uuid4

from aiqa.contracts.jobs import ControlDecision
from aiqa.worker.http_client import WorkerHttpError


class WorkerAttemptCheckpoint:
    def __init__(self, client, claim, *, clock=time.monotonic):
        self.client = client
        self.clock = clock
        self.owner = {name:str(UUID(claim[name])) for name in ('project_id','job_id','attempt_id')}
        generation = claim['generation']
        if type(generation) is not int or generation < 1:
            raise ValueError('checkpoint claim invalid')
        self.owner['generation'] = generation

    def checkpoint(self, phase):
        if phase not in ('before_model','after_model','before_lookup','before_dispatch'):
            return ControlDecision(False,'checkpoint_phase')
        try:
            start = self.clock()
            body = self.client.checkpoint(**self.owner,phase=phase,idempotency_key='checkpoint:'+str(uuid4()))
            latency = self.clock()-start
        except (WorkerHttpError,AttributeError):
            return ControlDecision(False,'checkpoint_unavailable')
        if type(body) is not dict or body.get('allowed') is not True or body.get('phase') != phase:
            return ControlDecision(False,'checkpoint_invalid')
        if (any(body.get(key)!=value for key,value in self.owner.items())
            or type(body.get('generation')) is not int):
            return ControlDecision(False,'checkpoint_scope')
        try:
            remaining = body['lease_remaining_seconds']
            if type(remaining) not in (int,float) or not math.isfinite(remaining) or not 10 <= remaining <=45:
                raise ValueError('lease remaining')
            server = datetime.fromisoformat(body['server_time'])
            deadline = datetime.fromisoformat(body['job_deadline'])
            if server.tzinfo is None or deadline.tzinfo is None:
                raise ValueError('time zone')
            job_remaining = (deadline-server).total_seconds()
            if not 0 < job_remaining <=600 or not math.isfinite(latency) or latency < 0:
                raise ValueError('deadline')
        except (KeyError,TypeError,ValueError,OverflowError):
            return ControlDecision(False,'checkpoint_invalid')
        # Subtract the entire round trip: positive replies can already be too old on arrival.
        if remaining-latency <10 or job_remaining-latency <=0:
            return ControlDecision(False,'checkpoint_expired')
        return ControlDecision(True,phase)
