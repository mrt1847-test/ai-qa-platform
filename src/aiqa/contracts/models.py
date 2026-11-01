"""Model request and response types. Importing this module does not call a model."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

MODEL_ROLES = frozenset({"authoring", "verification", "healing", "maintenance"})


@dataclass(frozen=True, slots=True)
class ModelRequest:
    call_id: UUID
    role: str
    owner_kind: str
    owner_id: str
    binding_revision: int
    sanitized_inputs: tuple[str, ...]
    token_output_limit: int
    deadline: str
    check_id: str | None = None
    episode_id: str | None = None


@dataclass(frozen=True, slots=True)
class ModelResponse:
    call_id: UUID
    actual_model: str | None
    content: str
    measurement_status: str
    allowed: bool
    provider_request_id: str | None = None


@dataclass(frozen=True, slots=True)
class RoleBinding:
    role: str
    revision: int
    model: str
    secret_ref: str


@dataclass(frozen=True, slots=True)
class OwnedCheck:
    check_id: str
    item_id: str


@dataclass(frozen=True, slots=True)
class OwnedEpisode:
    episode_id: str
    item_id: str
