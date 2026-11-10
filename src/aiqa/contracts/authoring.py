"""Versioned, secret-free recording admission metadata shared with the worker."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from aiqa.domain.hashing import canonical_hash

AUTHORING_SCHEMA = "authoring-admission-v1"
_FIELDS = ("authoring_schema", "authoring_binding", "input_case_version_id", "input_version_hash",
           "timeout_seconds", "max_actions", "max_model_calls", "budget", "currency")


def authoring_policy_ref(limits: dict[str, object]) -> str:
    return AUTHORING_SCHEMA + ":" + canonical_hash({name: limits.get(name) for name in _FIELDS}, "canon-json-v1")


def validate_authoring_pin(snapshot: dict[str, object]) -> dict[str, object] | None:
    """Return a detached pin, or None for old jobs. The HTTPS claim is the authority.

    This checks consistency, not credential access or actual runtime consumption.
    Retaining the outer policy_ref prevents a partial pin being treated as legacy.
    """
    limits = snapshot.get("limits", {})
    outer = str(snapshot.get("policy_ref", ""))
    markers = outer.startswith(AUTHORING_SCHEMA + ":") or (type(limits) is dict and (
        str(limits.get("policy_ref", "")).startswith(AUTHORING_SCHEMA + ":") or any(
            name in limits for name in ("authoring_schema", "authoring_binding", "input_version_hash"))))
    if not markers:
        return None
    def reject():
        raise ValueError("authoring pin invalid")
    if snapshot.get("purpose") != "recording" or type(limits) is not dict:
        reject()
    if limits.get("authoring_schema") != AUTHORING_SCHEMA:
        reject()
    binding = limits.get("authoring_binding")
    if type(binding) is not dict or set(binding) != {"binding_id", "revision_id", "revision", "role", "content_hash", "key_ref_id", "key_revision"}:
        reject()
    if binding["role"] != "authoring":
        reject()
    for name in ("binding_id", "revision_id", "content_hash", "key_ref_id"):
        if type(binding[name]) is not str or not binding[name].strip():
            reject()
    for name in ("revision", "key_revision"):
        if type(binding[name]) is not int or binding[name] < 1:
            reject()
    for name, maximum in (("timeout_seconds", 600), ("max_actions", 50), ("max_model_calls", 80)):
        value = limits.get(name)
        if type(value) is not int or not (0 if name == "max_actions" else 1) <= value <= maximum:
            reject()
    if type(limits.get("budget")) is not str or limits.get("currency") != "USD":
        reject()
    try:
        money = Decimal(limits["budget"])
    except InvalidOperation:
        reject()
    if not money.is_finite() or not 0 < money <= Decimal("2.00"):
        reject()
    for name in ("input_case_version_id", "input_version_hash"):
        if type(limits.get(name)) is not str or not limits[name].strip():
            reject()
    intent = snapshot.get("intent")
    if (type(intent) is not dict or intent.get("case_version_id") != limits["input_case_version_id"]
        or intent.get("content_hash") != limits["input_version_hash"]):
        reject()
    expected = authoring_policy_ref(limits)
    if limits.get("policy_ref") != expected or snapshot.get("policy_ref") != expected:
        reject()
    return {**limits, "authoring_binding": dict(binding)}
