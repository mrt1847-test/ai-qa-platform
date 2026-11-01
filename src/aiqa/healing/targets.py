"""Prove a typed healing target. This module does not call a model or open a device."""

from __future__ import annotations

import json
from dataclasses import dataclass

from aiqa.contracts.actions import Observation

_VISUAL = frozenset({"visual", "canvas", "guess"})


@dataclass(frozen=True, slots=True)
class TargetCandidate:
    role: str
    name: str
    container: str
    resource_id: str
    text: str
    context: str
    locator: str
    action: str
    input_value: str
    path: str
    coordinates: tuple[int, int] | None
    basis: str


@dataclass(frozen=True, slots=True)
class HealingContext:
    approved_role: str
    approved_name: str
    approved_container: str
    approved_resource_id: str
    approved_text: str
    approved_context: str
    approved_locator: str
    approved_action: str
    approved_input: str
    approved_path: str
    request: object
    payload: dict[str, object]


@dataclass(frozen=True, slots=True)
class HealingProposal:
    approved_role: str
    approved_name: str
    approved_container: str
    approved_resource_id: str
    approved_text: str
    approved_context: str
    approved_locator: str
    approved_action: str
    approved_input: str
    approved_path: str
    candidate: TargetCandidate | None
    admitted: bool


@dataclass(frozen=True, slots=True)
class HealingDecision:
    accepted: bool
    same_target: bool
    reasons: tuple[str, ...]


def validate_healing_proposal(proposal: HealingProposal, observation: Observation) -> HealingDecision:
    """Accept one unique visible target with the same action, input, and path."""

    candidate = proposal.candidate
    if not proposal.admitted or candidate is None or candidate.basis in _VISUAL or candidate.basis != "typed":
        return HealingDecision(False, False, ("untyped",))
    if candidate.action != proposal.approved_action:
        return HealingDecision(False, False, ("action",))
    if candidate.input_value != proposal.approved_input or candidate.path != proposal.approved_path:
        return HealingDecision(False, False, ("input",))
    if not _candidate_matches(candidate, proposal):
        return HealingDecision(False, False, ("identity",))
    matches = [item for item in _elements(observation) if _element_matches(item, proposal)]
    if len(matches) != 1:
        return HealingDecision(False, False, ("ambiguous" if len(matches) > 1 else "missing",))
    element = matches[0]
    if element.get("kind") in _VISUAL or element.get("visible") is not True or element.get("enabled") is not True:
        return HealingDecision(False, False, ("state",))
    if candidate.coordinates is not None and not _inside(candidate.coordinates, element.get("bounds")):
        return HealingDecision(False, False, ("bounds",))
    return HealingDecision(True, True, ())


def _candidate_matches(candidate: TargetCandidate, proposal: HealingProposal) -> bool:
    by_name = _filled(candidate.role, candidate.name, candidate.container) and (
        candidate.role,
        candidate.name,
        candidate.container,
    ) == (proposal.approved_role, proposal.approved_name, proposal.approved_container)
    by_resource = _filled(candidate.resource_id, candidate.text, candidate.context) and (
        candidate.resource_id,
        candidate.text,
        candidate.context,
    ) == (proposal.approved_resource_id, proposal.approved_text, proposal.approved_context)
    return by_name or by_resource


def _element_matches(element: dict[str, object], proposal: HealingProposal) -> bool:
    by_name = _filled(proposal.approved_role, proposal.approved_name, proposal.approved_container) and (
        element.get("role"),
        element.get("name"),
        element.get("container"),
    ) == (proposal.approved_role, proposal.approved_name, proposal.approved_container)
    by_resource = _filled(proposal.approved_resource_id, proposal.approved_text, proposal.approved_context) and (
        element.get("resource_id"),
        element.get("text"),
        element.get("context"),
    ) == (proposal.approved_resource_id, proposal.approved_text, proposal.approved_context)
    return by_name or by_resource


def _elements(observation: Observation) -> list[dict[str, object]]:
    try:
        parsed = json.loads(observation.dom) if observation.dom else None
    except json.JSONDecodeError:
        return []
    if type(parsed) is not dict or type(parsed.get("elements")) is not list:
        return []
    return [item for item in parsed["elements"] if type(item) is dict]


def _inside(point: tuple[int, int], bounds: object) -> bool:
    if type(bounds) is not list or len(bounds) != 4 or any(type(item) is not int for item in bounds):
        return False
    left, top, right, bottom = bounds
    return left <= point[0] <= right and top <= point[1] <= bottom


def _filled(first: str, second: str, third: str) -> bool:
    return bool(first) and bool(second) and bool(third)
