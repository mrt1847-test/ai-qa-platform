"""Validate a server-fixed healing pin without opening the server DB or a model."""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from uuid import UUID

from aiqa.contracts.healing import ResolvedHealingPolicy
from aiqa.domain.hashing import canonical_hash

_HASH = re.compile(r"sha256:[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class WorkerHealingPin:
    enabled: bool
    policy: ResolvedHealingPolicy | None
    binding: dict[str, object] | None


def _integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError("healing pin invalid")
    return value


def _money(value):
    if type(value) is not str:
        raise ValueError("healing pin invalid")
    try:
        money = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("healing pin invalid") from exc
    if not money.is_finite() or money <= 0:
        raise ValueError("healing pin invalid")
    return money


def resolve_claim_healing_pin(snapshot: dict[str, object]) -> WorkerHealingPin:
    """OFF/legacy needs no healer metadata; explicit ON requires a complete pin.

    The management HTTPS claim authenticates the source. This checks internal
    consistency and hard caps; it is not an independent credential/approval probe.
    Runtime providers still reserve episodes/calls and respect lease/deadline guards.
    """
    enabled = snapshot.get("self_healing_enabled", False)
    if type(enabled) is not bool:
        raise ValueError("healing pin invalid")
    limits = snapshot.get("limits", {})
    if type(limits) is not dict:
        if enabled:
            raise ValueError("healing pin invalid")
        return WorkerHealingPin(False, None, None)
    markers = any(name in limits for name in ("healing_schema", "healing_resolution", "healing_binding")) or str(limits.get("policy_ref", "")).startswith("healing-admission-v1:") or str(snapshot.get("policy_ref", "")).startswith("healing-admission-v1:")
    if not enabled:
        if markers or limits.get("self_healing_enabled", False) is not False:
            raise ValueError("healing pin invalid")
        return WorkerHealingPin(False, None, None)
    if (snapshot.get("purpose") != "regression" or limits.get("self_healing_enabled") is not True
        or limits.get("healing_schema") != "healing-admission-v1"):
        raise ValueError("healing pin invalid")
    raw, binding = limits.get("healing_resolution"), limits.get("healing_binding")
    if type(raw) is not dict or type(binding) is not dict:
        raise ValueError("healing pin invalid")
    if set(raw) != {"requested_enabled", "effective_enabled", "approved_policy_hash", "effective_limits", "binding_revision", "resolution_hash", "default_enabled", "rejected"}:
        raise ValueError("healing pin invalid")
    if (raw["requested_enabled"] is not True or raw["effective_enabled"] is not True
        or raw["default_enabled"] is not False or raw["rejected"] is not False or binding.get("role") != "healing"):
        raise ValueError("healing pin invalid")
    for name in ("binding_id", "revision_id", "key_ref_id"):
        if type(binding.get(name)) is not str:
            raise ValueError("healing pin invalid")
        UUID(binding[name])
    _integer(binding.get("revision"), 1, 2**31-1)
    _integer(binding.get("key_revision"), 1, 2**31-1)
    if raw["binding_revision"] != binding["revision_id"]:
        raise ValueError("healing pin invalid")
    for value in (binding.get("content_hash"), raw["approved_policy_hash"]):
        if type(value) is not str or _HASH.fullmatch(value) is None:
            raise ValueError("healing pin invalid")
    caps = raw["effective_limits"]
    if type(caps) is not dict or set(caps) != {"budget", "max_episodes_per_item", "max_model_calls_per_item", "max_seconds", "timeout_seconds"}:
        raise ValueError("healing pin invalid")
    _integer(caps["max_episodes_per_item"], 1, 1)
    total_calls = _integer(limits.get("max_model_calls"), 1, 80)
    _integer(caps["max_model_calls_per_item"], 1, min(2, total_calls))
    _integer(caps["max_seconds"], 1, 30)
    timeout = _integer(caps["timeout_seconds"], 1, 600)
    if timeout != limits.get("timeout_seconds") or type(limits.get("timeout_seconds")) is not int:
        raise ValueError("healing pin invalid")
    if limits.get("currency") != "USD" or _money(caps["budget"]) > min(_money(limits.get("budget")), Decimal("2.00")):
        raise ValueError("healing pin invalid")
    for name in ("replay_package_id", "replay_package_hash"):
        if type(snapshot.get(name)) is not str or not snapshot[name] or snapshot[name] != limits.get(name):
            raise ValueError("healing pin invalid")
    document = {name: raw[name] for name in ("approved_policy_hash", "binding_revision", "default_enabled", "effective_enabled", "effective_limits", "requested_enabled")}
    digest = canonical_hash(document, "canon-json-v1")
    if any(value != digest for value in (raw["resolution_hash"], limits.get("healing_snapshot"), limits.get("healing_policy_hash"))):
        raise ValueError("healing pin invalid")
    policy_ref = "healing-admission-v1:" + canonical_hash({name:limits.get(name) for name in ("healing_schema","healing_resolution","healing_binding","healing_policy_hash")},"canon-json-v1")
    if snapshot.get("policy_ref") != policy_ref or limits.get("policy_ref") != policy_ref:
        raise ValueError("healing pin invalid")
    policy = ResolvedHealingPolicy(**{**raw, "effective_limits": dict(caps)})
    return WorkerHealingPin(True, policy, dict(binding))
