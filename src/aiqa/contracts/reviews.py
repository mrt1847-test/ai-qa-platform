"""Review, approval, and artifact protection types. Importing this module does not open a database."""

from __future__ import annotations

from aiqa.store.models import (
    ApprovalEvent,
    ArtifactProtection,
    ArtifactRef,
    ReviewEvidenceEntry,
    ReviewSnapshot,
)

ARTIFACT_OWNER_FIELDS = (
    "action_id",
    "check_id",
    "recording_id",
    "review_id",
    "build_id",
    "export_id",
    "package_id",
    "healing_id",
    "proposal_id",
    "resource_observation_id",
)

__all__ = [
    "ARTIFACT_OWNER_FIELDS",
    "ApprovalEvent",
    "ArtifactProtection",
    "ArtifactRef",
    "ReviewEvidenceEntry",
    "ReviewSnapshot",
]
