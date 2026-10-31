"""Decide whether a typed action may be considered. This module does not dispatch."""

from __future__ import annotations

from urllib.parse import urlsplit

from aiqa.contracts.actions import (
    ANDROID_ACTIONS,
    RAW_ACTIONS,
    WEB_ACTIONS,
    ActionDecision,
    ActionProposal,
    LiteralInput,
    StepContext,
)


class PolicyGate:
    """Allow only a typed action that stays on the approved path and target list."""

    def authorize(self, proposal: ActionProposal, context: StepContext) -> ActionDecision:
        reasons: list[str] = []
        if proposal.source != "typed":
            reasons.append("screen_not_authority")
        if proposal.helper_command is not None or proposal.type in RAW_ACTIONS:
            reasons.append("raw_command")
        allowed_types = WEB_ACTIONS if context.platform == "web" else ANDROID_ACTIONS
        if context.platform not in {"web", "android"} or proposal.type not in allowed_types:
            if "raw_command" not in reasons:
                reasons.append("unknown_action")
        if proposal.step_id not in context.required_steps or proposal.approved_path_ref != context.approved_path_ref:
            reasons.append("path_rejected")
        if proposal.navigation_url is not None and not _origin_allowed(proposal.navigation_url, context.allowed_origins):
            reasons.append("url_out_of_scope")
        if proposal.target_package is not None and proposal.target_package not in context.allowed_packages:
            reasons.append("package_out_of_scope")
        if proposal.input is not None and not _input_approved(proposal.input, context):
            reasons.append("input_changed")
        if proposal.coordinates is not None and not _inside(proposal.coordinates, context.content_bounds):
            reasons.append("target_out_of_scope")
        if reasons:
            return ActionDecision(False, False, tuple(reasons))
        return ActionDecision(True, True, ())


def _origin_allowed(url: str, allowlist: tuple[str, ...]) -> bool:
    origin = _origin(url)
    if origin is None:
        return False
    return origin in {_origin(item) for item in allowlist}


def _origin(url: str) -> str | None:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or parts.username or parts.password or parts.hostname is None:
        return None
    port = parts.port
    if port is None:
        port = 443 if parts.scheme == "https" else 80
    return f"{parts.scheme}://{parts.hostname.lower()}:{port}"


def _input_approved(value: LiteralInput | tuple[object, object, object], context: StepContext) -> bool:
    if type(value) is LiteralInput:
        return value.text in context.approved_literals
    if type(value) is tuple and len(value) == 3:
        return value in context.approved_secrets
    return False


def _inside(point: tuple[int, int], bounds: tuple[int, int, int, int] | None) -> bool:
    if bounds is None:
        return False
    left, top, width, height = bounds
    x, y = point
    return left <= x < left + width and top <= y < top + height
