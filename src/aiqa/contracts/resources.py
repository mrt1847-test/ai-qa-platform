"""Physical resource key and project alias types. Importing this module does not open a database."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from aiqa.store.models import PhysicalResourceKey, ResourceAlias, ResourceObservation

TARGET_KINDS = frozenset({"web", "android"})
INVENTORY_STATES = frozenset({"offline", "unauthorized", "busy", "ready"})

__all__ = [
    "INVENTORY_STATES",
    "TARGET_KINDS",
    "InventoryReceipt",
    "InventoryReport",
    "ResourcePreviewView",
    "PhysicalResourceKey",
    "ResourceAlias",
    "ResourceObservation",
    "require_target_kind",
    "resource_key",
]


@dataclass(frozen=True, slots=True)
class InventoryReport:
    native_id: str
    target_kind: str
    state: str
    os_build: str
    geometry: str
    permissions: str
    ime: str
    observed_at: str
    display_name: str
    raw_handle: str | None = None


@dataclass(frozen=True, slots=True)
class InventoryReceipt:
    physical_key_id: UUID
    resource_key: str
    state: str
    project_id: UUID


@dataclass(frozen=True, slots=True)
class ResourcePreviewView:
    resource_id: UUID
    state: str
    observed_at: str | None
    geometry: str
    artifact_id: str | None
    reason: str
    raw_control: bool


def resource_key(worker_id: UUID, native_id: str) -> str:
    """One host or serial identity. This does not open a device."""

    if native_id.strip() == "":
        raise ValueError("native id is required")
    return f"{worker_id}:{native_id}"


def require_target_kind(kind: str) -> str:
    """A project alias names web or android. It does not open a device."""

    if kind not in TARGET_KINDS:
        raise ValueError("target kind is invalid")
    return kind
