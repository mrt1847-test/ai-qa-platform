"""Replay package, healing episode, and repair proposal types.

Importing this module does not open a database. The package hash body has no produced version hash.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from aiqa.store.models import HealingEpisode, PackageStep, RepairProposal, ReplayPackage, RuntimeOverride

__all__ = [
    "AndroidPlanStep",
    "HealingEpisode",
    "PackageStep",
    "PackageValidation",
    "RepairProposal",
    "ReplayPackage",
    "ReplayPackageBody",
    "RuntimeOverride",
    "StepMapping",
]


@dataclass(frozen=True, slots=True)
class AndroidPlanStep:
    """One immutable Android action. A model prompt is not a step."""

    kind: str
    action: str
    intent: str
    target: str
    action_id: str
    line: int
    rotation: int
    content_bounds: tuple[int, int, int, int]
    secret_ref: str | None = None
    maps_to: str | None = None
    expected: str | None = None


@dataclass(frozen=True, slots=True)
class StepMapping:
    """One step, action, and source line. A helper without this mapping is not ready."""

    step_id: str
    action_id: str
    line: int


@dataclass(frozen=True, slots=True)
class ReplayPackageBody:
    """The hashed package body. Produced version and compiled hash stay outside it."""

    schema_version: str
    source_manifest_id: UUID
    source_manifest_hash: str
    raw_source_hash: str
    approved_code_or_plan_hash: str
    runtime_ref: str
    compiler_ref: str
    lock_hash: str
    step_mapping_hash: str
    mappings: tuple[StepMapping, ...]
    helpers: tuple[str, ...] = ()
    produced_version_id: str | None = None
    produced_version_hash: str | None = None
    compiled_hash: str | None = None


@dataclass(frozen=True, slots=True)
class PackageValidation:
    """Whether the body may become ready. A false result names the first reasons."""

    ready: bool
    reasons: tuple[str, ...]
    body_hash: str
