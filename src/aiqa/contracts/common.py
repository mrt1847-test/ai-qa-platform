"""C01 types owned by this package. Only fields needed by current callers."""

from dataclasses import dataclass


@dataclass(frozen=True)
class EngineRef:
    source_sha: str
    patch_hash: str
    dependency_lock_hash: str
    adapter_version: str
