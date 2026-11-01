"""USB dispatch gate. Importing this module does not open a device or an ADB server."""

from __future__ import annotations

from aiqa.replay.targets import TargetResolution


def allow_dispatch(resolution: TargetResolution) -> bool:
    """Allow one already resolved target. A blocked or ambiguous target stays closed."""

    return resolution.dispatched and not resolution.blocked
