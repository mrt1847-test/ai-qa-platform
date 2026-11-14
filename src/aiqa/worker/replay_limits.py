"""Detached caps from a server replay claim; no database or model authority."""
from __future__ import annotations

import math
from dataclasses import dataclass

from aiqa.worker.runner import ACTION_LIMIT, ATTEMPT_LIMIT_SECONDS, MODEL_LIMIT


@dataclass(frozen=True, slots=True)
class ReplayLimits:
    max_actions: int
    max_model_calls: int
    timeout_seconds: float


def _integer(value: object, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError('replay limit invalid')
    return value


def resolve_replay_limits(snapshot, *, worker_actions, worker_seconds):
    """Legacy development snapshots have no caps. Partial/new caps fail closed."""
    raw = snapshot.get('limits', {})
    names = {'max_actions', 'max_model_calls', 'timeout_seconds'}
    if type(raw) is not dict:
        raise ValueError('replay limits invalid')
    if not names.intersection(raw):
        return None
    actions = _integer(raw.get('max_actions'), 0, ACTION_LIMIT)
    models = _integer(raw.get('max_model_calls'), 0, MODEL_LIMIT)
    seconds = _integer(raw.get('timeout_seconds'), 1, ATTEMPT_LIMIT_SECONDS)
    worker_actions = _integer(worker_actions, 0, ACTION_LIMIT)
    if worker_seconds is not None and (
        type(worker_seconds) not in (int, float)
        or not math.isfinite(worker_seconds) or worker_seconds <= 0
    ):
        raise ValueError('worker replay time limit invalid')
    worker_timeout = ATTEMPT_LIMIT_SECONDS if worker_seconds is None else worker_seconds
    return ReplayLimits(min(actions, worker_actions), models, float(min(seconds, worker_timeout)))
