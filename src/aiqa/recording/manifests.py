"""Sealed recording manifests. A missing compiler does not invent a package."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from aiqa.domain.hashing import canonical_hash


class FinishConflict(Exception):
    """The same finish key arrived with a different body."""


@dataclass(frozen=True, slots=True)
class RecordingFinishInput:
    """One seal. outcome is completed or error. Stop uses interrupted separately."""

    recording_id: UUID
    outcome: str
    final_seq: int
    artifact_ids: tuple[str, ...]
    request_key: str
    action_mapping: str = "{}"


@dataclass(frozen=True, slots=True)
class ManifestReceipt:
    """The sealed manifest. replayed is the earlier same body."""

    manifest_id: UUID
    recording_id: UUID
    body_hash: str
    replayed: bool


@dataclass(frozen=True, slots=True)
class MaterializationReceipt:
    """The draft saved for a manifest. The package stays empty until a compiler exists."""

    receipt_id: UUID
    manifest_id: UUID
    produced_version_id: UUID
    replay_package_id: UUID | None
    replayed: bool


@dataclass(frozen=True, slots=True)
class RecordingView:
    """The preserved recording. Engine completion is not an approval."""

    recording_id: UUID
    completion_status: str
    stop_status: str
    approval_id: None


def finish_body_hash(spec: RecordingFinishInput) -> str:
    """Hash the seal body. A different seq or artifact is a different request."""

    return canonical_hash(
        {
            "action_mapping": spec.action_mapping,
            "artifact_ids": list(spec.artifact_ids),
            "final_seq": spec.final_seq,
            "outcome": spec.outcome,
            "recording_id": str(spec.recording_id),
        },
        "canon-json-v1",
    )
