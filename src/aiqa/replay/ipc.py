"""Typed web IPC. A script message cannot carry a browser or CDP handle.

The compiler emits only these calls. Parsing a message does not execute it.
"""

from __future__ import annotations

from dataclasses import dataclass

WEB_ACTION_TYPES = frozenset({"click", "fill", "scroll", "select"})
_ALLOWED_FIELDS = frozenset({"type", "selector", "value"})
_HANDLE_FIELDS = frozenset(
    {
        "cdp",
        "cdp_url",
        "websocket",
        "ws_url",
        "endpoint",
        "page",
        "browser",
        "context",
        "handle",
        "devtools",
    }
)


@dataclass(frozen=True)
class TypedAction:
    type: str
    selector: str = ""
    value: str = ""


def parse_ipc_message(payload: dict) -> TypedAction:
    if not isinstance(payload, dict):
        raise ValueError("ipc payload must be an object")
    leaked = _HANDLE_FIELDS.intersection(payload)
    if leaked:
        raise ValueError("ipc refuses a browser or CDP handle")
    unknown = set(payload).difference(_ALLOWED_FIELDS)
    if unknown:
        raise ValueError("ipc refuses fields outside the typed action")
    action_type = payload.get("type")
    if action_type not in WEB_ACTION_TYPES:
        raise ValueError("ipc action type is outside the web subset")
    selector = payload.get("selector", "")
    value = payload.get("value", "")
    if not isinstance(selector, str) or not isinstance(value, str):
        raise ValueError("ipc selector and value must be strings")
    return TypedAction(type=action_type, selector=selector, value=value)


def runtime_call(action: TypedAction) -> str:
    """Render one allowed action as a qa_runtime call. The selector and value stay unchanged."""

    if action.type not in WEB_ACTION_TYPES:
        raise ValueError("ipc action type is outside the web subset")
    if action.type in {"fill", "select"}:
        return f"qa_runtime.{action.type}({action.selector!r}, {action.value!r})"
    return f"qa_runtime.{action.type}({action.selector!r})"
