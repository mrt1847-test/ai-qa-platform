"""Confirm a required path from the action journal. A goal reached another way is a violation."""

from __future__ import annotations

import json

from aiqa.contracts.actions import Observation
from aiqa.contracts.checks import CheckResult, CheckSpec


def node(raw: str, key: str, subject: str) -> dict[str, object] | None:
    """Find one fixture node. This does not parse a live page."""

    try:
        parsed = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        return None
    if type(parsed) is not dict or type(parsed.get("nodes")) is not list:
        return None
    for item in parsed["nodes"]:
        if type(item) is dict and item.get(key) == subject:
            return item
    return None


def compare(check: CheckSpec, found: dict[str, object], observed_at: str) -> CheckResult:
    """Compare one observed field. An engine completion message is not a field."""

    field = {"text": "text", "value": "value", "state": "state", "locator": "locator"}.get(check.kind)
    if field is None:
        return unknown(check, "check kind is missing", observed_at)
    observed = found.get(field)
    if type(observed) is not str:
        return unknown(check, "observation is missing", observed_at)
    if observed == check.expected:
        return result(check, "satisfied", observed, "observed value matches", observed_at)
    return result(check, "violated", observed, "observed value differs", observed_at)


def unknown(check: CheckSpec, reason: str, observed_at: str) -> CheckResult:
    return result(check, "unknown", "", reason, observed_at)


def result(check: CheckSpec, status: str, observed: str, reason: str, observed_at: str) -> CheckResult:
    return CheckResult(check.id, status, check.method, check.expected, observed, reason, observed_at)


def evaluate_path(check: CheckSpec, observation: Observation) -> CheckResult:
    """Require the journal steps in order. An engine completion message is not a step."""

    required = tuple(part.strip() for part in check.expected.split(",") if part.strip() != "")
    journal = tuple(message for message in observation.messages if message != "engine-done")
    if required == ():
        return CheckResult(check.id, "unknown", check.method, check.expected, "", "path is missing", observation.captured_at)
    if all(step in journal for step in required):
        indexes = [journal.index(step) for step in required]
        if indexes == sorted(indexes):
            return CheckResult(
                check.id, "satisfied", check.method, check.expected, ",".join(journal), "path was observed", observation.captured_at
            )
        return CheckResult(
            check.id, "violated", check.method, check.expected, ",".join(journal), "path order differs", observation.captured_at
        )
    if _goal_visible(observation, check.subject):
        return CheckResult(
            check.id,
            "violated",
            check.method,
            check.expected,
            ",".join(journal),
            "path was bypassed",
            observation.captured_at,
        )
    return CheckResult(check.id, "unknown", check.method, check.expected, ",".join(journal), "path was not observed", observation.captured_at)


def _goal_visible(observation: Observation, subject: str) -> bool:
    raw = observation.dom if observation.platform == "web" else observation.stdout
    try:
        parsed = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        return False
    if type(parsed) is not dict or type(parsed.get("nodes")) is not list:
        return False
    return any(type(item) is dict and item.get("text") == subject for item in parsed["nodes"])
