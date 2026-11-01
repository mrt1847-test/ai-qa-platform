"""Compare an Android hierarchy fixture with a deterministic check. This does not open a device."""

from __future__ import annotations

from aiqa.contracts.actions import Observation
from aiqa.contracts.checks import CheckResult, CheckSpec
from aiqa.validation.paths import compare, node, unknown


def evaluate_android(check: CheckSpec, observation: Observation) -> CheckResult:
    """Match resource id, text, value, or state. Engine completion is ignored."""

    found = node(observation.stdout, "resource_id", check.subject)
    if found is None:
        return unknown(check, "observation is missing", observation.captured_at)
    return compare(check, found, observation.captured_at)
