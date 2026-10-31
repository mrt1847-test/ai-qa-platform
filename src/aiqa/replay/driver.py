"""Trusted web driver. The CDP endpoint stays on this object and is not serialized."""

from __future__ import annotations

from aiqa.replay.ipc import TypedAction, parse_ipc_message


class TrustedWebDriver:
    def __init__(self, cdp_endpoint: str) -> None:
        if not isinstance(cdp_endpoint, str) or not cdp_endpoint:
            raise ValueError("driver requires a CDP endpoint")
        self._cdp_endpoint = cdp_endpoint

    def public_view(self) -> dict[str, object]:
        return {"owns_cdp": True}

    def dispatch(self, payload: dict) -> TypedAction:
        return parse_ipc_message(payload)
