"""Resolve approved healing metadata before admission; never reads a secret value.

Callers own the transaction and validate approval/package provenance. This boundary
only resolves the supplied immutable version settings, not a draft or latest binding.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, replace
from decimal import Decimal
from uuid import UUID

from aiqa.contracts.cases import CaseVersion
from aiqa.contracts.healing import ApprovedHealingPolicy, HealingRequest, Limits, ResolvedHealingPolicy
from aiqa.domain.versions import SettingsRejected, parse_case_settings
from aiqa.healing.policy import resolve_healing_policy


@dataclass(frozen=True, slots=True)
class HealingAdmission:
    policy: ResolvedHealingPolicy
    binding_pin: dict[str, object] | None
    blockers: tuple[str, ...]


def resolve_execution_healing(
    connection: sqlite3.Connection,
    project_id: UUID,
    version: CaseVersion,
    settings: dict[str, object],
    *,
    requested_enabled: bool = False,
    purpose: str = "regression",
    request_caps: dict[str, int] | None = None,
) -> HealingAdmission:
    """Intersect approved caps and resolve an exact healing-role/key revision.

    Available key metadata is not proof of provider/OS credential access. Those
    gates remain in the worker; no connection probe or model request happens here.
    """
    if type(requested_enabled) is not bool:
        raise ValueError("self_healing_enabled must be a boolean")
    if purpose not in {"trial", "regression", "reverification"}:
        raise ValueError("invalid healing purpose")
    off = not requested_enabled or purpose == "trial"
    blockers: list[str] = []
    try:
        normalized = parse_case_settings({"target_kind": "web", "limits": settings.get("limits", {}), "healing_policy": settings.get("healing_policy", {})}, project_id).document
    except SettingsRejected:
        normalized = {"healing_policy": {}, "limits": {"budget": "0.00", "max_model_calls": 0}}
        if not off:
            blockers.append("HEALING_POLICY_INVALID")
    raw = normalized["healing_policy"]
    limits = Limits(**normalized["limits"])
    caps = {name: int(raw.get(name, default)) for name, default in (("max_episodes_per_item", 1), ("max_model_calls_per_item", 2), ("max_seconds", 30))}
    requested = dict(caps)
    if request_caps is not None:
        if type(request_caps) is not dict or set(request_caps) - set(caps):
            raise ValueError("invalid healing request caps")
        for name, value in request_caps.items():
            if type(value) is not int or value < 0:
                raise ValueError("invalid healing request caps")
            requested[name] = value
            if not off and value > caps[name]:
                blockers.append("HEALING_REQUEST_EXCEEDS_APPROVAL")
    request = HealingRequest(not off, scope=str(raw.get("scope", "")),
                             max_episodes_per_item=requested["max_episodes_per_item"],
                             max_model_calls_per_item=min(requested["max_model_calls_per_item"], limits.max_model_calls),
                             max_seconds=requested["max_seconds"], purpose=purpose)
    approved = ApprovedHealingPolicy(allowed=raw.get("allowed") is True, scope=str(raw.get("scope", "")),
                                    model_binding_ref=str(raw.get("model_binding_ref", "")), binding_revision=str(raw.get("binding_revision", "")),
                                    healer_key_present=False, **caps)
    if off:
        # OFF never needs a healer key. Its immutable snapshot still describes
        # the saved approval/caps rather than whatever the caller prepopulated.
        request = replace(request, max_episodes_per_item=caps["max_episodes_per_item"],
                          max_model_calls_per_item=min(caps["max_model_calls_per_item"], limits.max_model_calls),
                          max_seconds=caps["max_seconds"])
        return HealingAdmission(resolve_healing_policy(replace(version, approved_healing=approved), request, limits), None, ())
    if version.project_id != project_id or version.approval_id is None or version.replay_package_id is None:
        blockers.append("HEALING_APPROVAL_REQUIRED")
    if raw.get("allowed") is not True or not str(raw.get("scope", "")).strip():
        blockers.append("HEALING_NOT_APPROVED")

    binding_pin = None
    binding_id = str(raw.get("model_binding_ref", ""))
    revision = str(raw.get("binding_revision", ""))
    # No latest-revision lookup: approval fixes the logical ID and revision.
    if not blockers:
        row = connection.execute(
            """SELECT binding_id, revision_id, revision, content_hash, key_ref_id, key_revision
               FROM binding_revisions WHERE project_id=? AND binding_id=?
                 AND (revision_id=? OR CAST(revision AS TEXT)=?)
                 AND role='healing' AND compatibility_status IN ('unchecked','compatible')""",
            (str(project_id), binding_id, revision, revision),
        ).fetchone() if binding_id and revision else None
        if row is None:
            blockers.append("HEALING_BINDING_UNAVAILABLE")
        else:
            key = connection.execute(
                "SELECT 1 FROM secret_refs WHERE project_id=? AND ref_id=? AND revision=? AND availability='available'",
                (str(project_id), str(row[4]), int(row[5])),
            ).fetchone()
            if key is None:
                blockers.append("HEALING_KEY_UNAVAILABLE")
            else:
                revision = str(row[1])
                binding_pin = {"binding_id": str(row[0]), "revision_id": revision, "revision": int(row[2]), "role": "healing", "content_hash": str(row[3]), "key_ref_id": str(row[4]), "key_revision": int(row[5])}

    approved = replace(approved, binding_revision=revision, healer_key_present=binding_pin is not None)
    if (Decimal(limits.budget) <= 0 or limits.max_model_calls <= 0 or limits.timeout_seconds <= 0
        or min(request.max_episodes_per_item, approved.max_episodes_per_item, limits.max_episodes_per_item) <= 0
        or min(request.max_model_calls_per_item, approved.max_model_calls_per_item, limits.max_model_calls_per_item) <= 0
        or min(request.max_seconds, approved.max_seconds, limits.max_seconds) <= 0):
        blockers.append("HEALING_BUDGET_UNAVAILABLE")
    if blockers:
        binding_pin = None
        approved = replace(approved, healer_key_present=False)
    policy = resolve_healing_policy(replace(version, approved_healing=approved), request, limits)
    return HealingAdmission(policy, binding_pin, tuple(blockers))
