"""Resolve one healing snapshot. A running item keeps the snapshot it already accepted."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from aiqa.contracts.cases import CaseVersion
from aiqa.contracts.healing import HealingRequest, Limits, ResolvedHealingPolicy
from aiqa.domain.hashing import canonical_hash


def reserve_window(policy: ResolvedHealingPolicy, job_seconds: int, lease_seconds: int) -> tuple[int, int] | None:
    """Keep the stricter call and time cap. An off policy reserves nothing."""

    if policy.effective_enabled is not True:
        return None
    calls = min(2, int(policy.effective_limits["max_model_calls_per_item"]))
    seconds = min(30, int(policy.effective_limits["max_seconds"]), job_seconds, lease_seconds)
    if calls < 1 or seconds < 1:
        return None
    return calls, seconds


def resolve_healing_policy(
    version: CaseVersion, request: HealingRequest, global_limits: Limits
) -> ResolvedHealingPolicy:
    """Intersect the approved policy with the narrower global cap. Trial stays off."""

    if request.running and request.accepted is not None:
        return request.accepted
    approved = version.approved_healing
    allowed = False if approved is None else approved.allowed is True
    scope = "" if approved is None else approved.scope
    binding = "" if approved is None else approved.model_binding_ref
    revision = "" if approved is None else approved.binding_revision
    key_present = False if approved is None else approved.healer_key_present is True
    episodes = 1 if approved is None else approved.max_episodes_per_item
    calls = 2 if approved is None else approved.max_model_calls_per_item
    seconds = 30 if approved is None else approved.max_seconds
    rejected = False
    if request.requested_enabled and not allowed:
        rejected = True
    if request.scope not in {"", scope}:
        rejected = True
    if request.requested_enabled and (not key_present or binding.strip() == ""):
        rejected = True
    if (
        request.max_episodes_per_item > episodes
        or request.max_model_calls_per_item > calls
        or request.max_seconds > seconds
    ):
        rejected = True
    effective_limits = {
        "budget": _narrow_budget(global_limits.budget),
        "max_episodes_per_item": _narrow(episodes, request.max_episodes_per_item, global_limits.max_episodes_per_item, 1),
        "max_model_calls_per_item": _narrow(calls, request.max_model_calls_per_item, global_limits.max_model_calls_per_item, 2),
        "max_seconds": _narrow(seconds, request.max_seconds, global_limits.max_seconds, 30),
        "timeout_seconds": min(global_limits.timeout_seconds, 600),
    }
    effective = request.purpose != "trial" and request.requested_enabled and allowed and not rejected
    approved_hash = canonical_hash(
        {
            "allowed": allowed,
            "binding": binding,
            "calls": calls,
            "default_enabled": False,
            "episodes": episodes,
            "scope": scope,
            "seconds": seconds,
        },
        "canon-json-v1",
    )
    document = {
        "approved_policy_hash": approved_hash,
        "binding_revision": revision if effective else "",
        "default_enabled": False,
        "effective_enabled": effective,
        "effective_limits": effective_limits,
        "requested_enabled": request.requested_enabled,
    }
    return ResolvedHealingPolicy(
        requested_enabled=request.requested_enabled,
        effective_enabled=effective,
        approved_policy_hash=approved_hash,
        effective_limits=effective_limits,
        binding_revision=revision if effective else "",
        resolution_hash=canonical_hash(document, "canon-json-v1"),
        default_enabled=False,
        rejected=rejected or (request.requested_enabled and not effective and request.purpose != "trial"),
    )


def _narrow(approved: int, requested: int, global_limit: int, hard: int) -> int:
    values = [approved, requested, global_limit, hard]
    positive = [value for value in values if type(value) is int and value >= 0]
    return 0 if positive == [] else min(positive)


def _narrow_budget(global_budget: str) -> str:
    try:
        requested = Decimal(global_budget)
    except InvalidOperation:
        return "2.00"
    if requested < 0:
        return "0.00"
    return str(min(requested, Decimal("2.00")))
