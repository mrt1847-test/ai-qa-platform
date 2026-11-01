"""Healing stays off until an approved snapshot exists, and a running snapshot stays put."""

from __future__ import annotations

from uuid import uuid4

from aiqa.contracts.cases import CaseDefinition, CaseVersion, PathPolicy
from aiqa.contracts.healing import ApprovedHealingPolicy, HealingRequest, Limits
from aiqa.healing.policy import resolve_healing_policy


def test_w31_01() -> None:
    denied = resolve_healing_policy(_version(False, False, "screen"), _request(True, "regression", "screen"), Limits())
    default = resolve_healing_policy(_version(False, False, ""), HealingRequest(False), Limits())
    trial = resolve_healing_policy(_version(True, True, "screen"), _request(True, "trial", "screen"), Limits())
    missing_key = resolve_healing_policy(_version(True, False, "screen"), _request(True, "regression", "screen"), Limits())
    wider = resolve_healing_policy(_version(True, True, "screen"), _request(True, "regression", "device"), Limits())
    accepted = resolve_healing_policy(
        _version(True, True, "screen"),
        _request(True, "regression", "screen"),
        Limits(max_model_calls_per_item=1),
    )
    changed = resolve_healing_policy(
        _version(True, True, "device", calls=2),
        HealingRequest(True, "device", 1, 2, 30, "regression", True, accepted),
        Limits(max_model_calls_per_item=2),
    )
    observed = {
        "default_enabled": default.default_enabled,
        "capability_false_on_rejected": denied.rejected is True and denied.effective_enabled is False,
        "trial_enabled": trial.effective_enabled,
        "running_snapshot_mutated": changed.resolution_hash != accepted.resolution_hash,
    }
    assert missing_key.rejected is True and missing_key.effective_enabled is False
    assert wider.rejected is True and wider.effective_enabled is False
    assert accepted.effective_enabled is True
    assert accepted.effective_limits["max_model_calls_per_item"] == 1
    assert observed == {
        "default_enabled": False,
        "capability_false_on_rejected": True,
        "trial_enabled": False,
        "running_snapshot_mutated": False,
    }


def _version(allowed: bool, key_present: bool, scope: str, calls: int = 2) -> CaseVersion:
    return CaseVersion(
        id=uuid4(),
        project_id=uuid4(),
        case_id=uuid4(),
        definition=CaseDefinition("", "", (), {}, {}, (), (), PathPolicy()),
        replay_package_id=None,
        approval_id=uuid4(),
        creation_kind="recorded",
        content_hash="version-hash",
        verification_digest="digest",
        approved_healing=ApprovedHealingPolicy(
            allowed=allowed,
            scope=scope,
            model_binding_ref="bind-1" if key_present else "",
            binding_revision="rev-1" if key_present else "",
            healer_key_present=key_present,
            max_model_calls_per_item=calls,
            default_enabled=False,
        ),
    )


def _request(enabled: bool, purpose: str, scope: str) -> HealingRequest:
    return HealingRequest(enabled, scope, 1, 2, 30, purpose, False, None)
