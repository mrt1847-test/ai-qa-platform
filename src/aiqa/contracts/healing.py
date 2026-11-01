"""Healing policy types. Importing this module does not call a model."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Limits:
    timeout_seconds: int = 600
    max_actions: int = 50
    max_model_calls: int = 80
    max_action_retries: int = 1
    max_model_retries: int = 2
    max_attempt_retries: int = 0
    budget: str = "2.00"
    currency: str = "USD"
    max_episodes_per_item: int = 1
    max_model_calls_per_item: int = 2
    max_seconds: int = 30


@dataclass(frozen=True, slots=True)
class ApprovedHealingPolicy:
    allowed: bool
    scope: str
    model_binding_ref: str
    binding_revision: str
    healer_key_present: bool
    max_episodes_per_item: int = 1
    max_model_calls_per_item: int = 2
    max_seconds: int = 30
    default_enabled: bool = False


@dataclass(frozen=True, slots=True)
class ResolvedHealingPolicy:
    requested_enabled: bool
    effective_enabled: bool
    approved_policy_hash: str
    effective_limits: dict[str, object]
    binding_revision: str
    resolution_hash: str
    default_enabled: bool
    rejected: bool


@dataclass(frozen=True, slots=True)
class HealingRequest:
    requested_enabled: bool
    scope: str = ""
    max_episodes_per_item: int = 1
    max_model_calls_per_item: int = 2
    max_seconds: int = 30
    purpose: str = "regression"
    running: bool = False
    accepted: ResolvedHealingPolicy | None = None
