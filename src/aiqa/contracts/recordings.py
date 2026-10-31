"""Recording schema types. Importing this module does not open a database."""

from __future__ import annotations

from aiqa.store.models import MaterializationReceipt, RecordingManifest, RecordingSession

CREATION_KIND = "recorded"
MANIFEST_KINDS = frozenset({"original", "recovery", "package_rebuild"})

__all__ = [
    "CREATION_KIND",
    "MANIFEST_KINDS",
    "MaterializationReceipt",
    "RecordingManifest",
    "RecordingSession",
    "require_manifest_kind",
]


def require_manifest_kind(kind: str) -> str:
    """package_rebuild is a manifest kind. It is not a recording creation_kind."""

    if kind not in MANIFEST_KINDS:
        raise ValueError("manifest kind is invalid")
    return kind
