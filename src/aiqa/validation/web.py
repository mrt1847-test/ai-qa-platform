"""Compare a web fixture node with a deterministic check. This does not open a browser."""

from __future__ import annotations

from aiqa.contracts.actions import Observation
from aiqa.contracts.checks import CheckResult, CheckSpec
from aiqa.validation.android import evaluate_android
from aiqa.validation.paths import evaluate_path, node, unknown


class Validator:
    """Evaluate one check against a supplied observation fixture."""

    def evaluate(self, check: CheckSpec, observation: Observation | None) -> CheckResult:
        if observation is None or not observation.capture_ok:
            return unknown(check, "observation is missing", "")
        if check.kind == "path":
            return evaluate_path(check, observation)
        if observation.platform == "android":
            return evaluate_android(check, observation)
        return evaluate_web(check, observation)


def evaluate_web(check: CheckSpec, observation: Observation) -> CheckResult:
    """Match locator, text, value, or state in a web fixture. Engine completion is ignored."""

    from aiqa.validation.paths import compare

    found = node(observation.dom, "locator", check.subject)
    if found is None:
        return unknown(check, "observation is missing", observation.captured_at)
    return compare(check, found, observation.captured_at)
