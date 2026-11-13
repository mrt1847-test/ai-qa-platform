"""Detached per-claim recording caps. These do not replace server model quota."""
from __future__ import annotations

import math
from dataclasses import dataclass

from aiqa.contracts.authoring import validate_authoring_pin
from aiqa.worker.runner import ACTION_LIMIT, ATTEMPT_LIMIT_SECONDS, MODEL_LIMIT


@dataclass(frozen=True, slots=True)
class RecordingLimits:
    max_actions: int
    max_model_calls: int
    timeout_seconds: float


def resolve_recording_limits(snapshot, *, worker_actions, worker_seconds):
    """New pins must validate; an old development claim retains its legacy context."""
    pin = validate_authoring_pin(snapshot)
    if pin is None:
        return None
    if type(worker_actions) is not int or not 0 <= worker_actions <= ACTION_LIMIT:
        raise ValueError('worker action limit invalid')
    if worker_seconds is not None and (
        type(worker_seconds) not in (int, float)
        or not math.isfinite(worker_seconds) or worker_seconds <= 0
    ):
        raise ValueError('worker time limit invalid')
    seconds = ATTEMPT_LIMIT_SECONDS if worker_seconds is None else worker_seconds
    return RecordingLimits(
        min(worker_actions, pin['max_actions'], ACTION_LIMIT),
        min(pin['max_model_calls'], MODEL_LIMIT),
        float(min(seconds, pin['timeout_seconds'], ATTEMPT_LIMIT_SECONDS)),
    )
