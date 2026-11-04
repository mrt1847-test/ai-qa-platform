"""USB dispatch gate. Importing this module does not open a device or an ADB server."""

from __future__ import annotations

from aiqa.replay.targets import TargetResolution


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
