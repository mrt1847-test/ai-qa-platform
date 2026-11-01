"""Preflight an Android target. This runner does not send a tap or open a device."""

from __future__ import annotations

from aiqa.contracts.actions import Observation
from aiqa.environments.usb_android import allow_dispatch
from aiqa.replay.targets import TargetBinding, TargetResolution, resolve_recorded_target


class AndroidPreflight:
    """Count only a resolved dispatch. A guessed coordinate never increments."""

    def __init__(self) -> None:
        self.dispatches = 0
        self.guessed_coordinate_dispatches = 0

    def dispatch(self, binding: TargetBinding, observation: Observation) -> TargetResolution:
        resolution = resolve_recorded_target(binding, observation)
        if allow_dispatch(resolution):
            self.dispatches += 1
        return resolution
