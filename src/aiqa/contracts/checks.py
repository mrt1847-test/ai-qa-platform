"""Deterministic check types. Importing this module does not open a device or a model."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CheckSpec:
    id: str
    kind: str
    expected: str
    subject: str = ""
    required: bool = True
    method: str = "deterministic"
    step_id: str | None = None
    allow_unknown_supplement: bool = False


@dataclass(frozen=True, slots=True)
class CheckResult:
    check_id: str
    status: str
    method: str
    expected_snapshot: str
    sanitized_observed: str
    reason: str
    observed_at: str
    latch: str = ""
