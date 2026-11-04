"""Action, check, event, and model-call fact types. Importing this module does not open a database."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from aiqa.store.models import ActionEnvelope, CheckResult, EventEnvelope, ModelCallFact

DISPATCH_STATES = frozenset(
    {"planned", "lookup_failed", "dispatch_started", "acknowledged", "observed", "unknown"}
)
MODEL_ROLES = frozenset({"authoring", "verification", "healing", "maintenance"})

__all__ = [
    "DISPATCH_STATES",
    "MODEL_ROLES",
    "ActionEnvelope",
    "ActionObservation",
    "AckState",
    "CheckResult",
    "EventEnvelope",
    "EvidenceCommitAck",
    "EvidenceEnvelope",
    "IngestReceipt",
    "LocalReceipt",
    "ModelCallFact",
    "require_dispatch_state",
]


@dataclass(frozen=True, slots=True)
class IngestReceipt:
    attempt_id: UUID
    committed_seq: int
    committed_hash: str
    stale_count: int


@dataclass(frozen=True, slots=True)
class EvidenceCommitAck:
    """Wire ACK after a contiguous sanitized prefix is committed."""

    attempt_id: UUID
    contiguous_seq: int
    prefix_hash: str
    stale_count: int
    late: bool
    artifact_count: int


@dataclass(frozen=True, slots=True)
class ActionObservation:
    """Sanitized after-capture linked to one action. A fixture is not device evidence."""

    action_id: str
    before_ref: str | None
    after_ref: str | None
    captured_at: str | None
    rotation: int | None
    command_result: str
    error_ref: str | None
    check_refs: tuple[str, ...]
    timing: str
    outcome: str
    native_evidence: bool


@dataclass(frozen=True, slots=True)
class EvidenceEnvelope:
    attempt_id: UUID
    local_seq: int
    png: bytes
    log_text: str
    appended_at: str


@dataclass(frozen=True, slots=True)
class LocalReceipt:
    attempt_id: UUID
    local_seq: int
    payload_hash: str
    durable: bool


@dataclass(frozen=True, slots=True)
class AckState:
    attempt_id: UUID
    acked_through: int
    accepted: bool
    reason: str


def require_dispatch_state(state: str) -> str:
    """lookup_failed is only valid before dispatch_started is journaled."""

    if state not in DISPATCH_STATES:
        raise ValueError("dispatch state is invalid")
    return state
