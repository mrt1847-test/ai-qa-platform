"""Android before-capture fixture. This module does not open a device or a shell."""

from __future__ import annotations

from dataclasses import replace

from aiqa.contracts.actions import ActionProposal, Observation


class MobileAgentAndroidAdapter:
    """Return the supplied in-memory fixture. Upstream capture is a later live gate."""

    def before_capture(self, proposal: ActionProposal, observation: Observation) -> Observation:
        if observation.platform != "android" or not observation.capture_ok:
            return replace(observation, capture_ok=False, png=b"")
        return observation
