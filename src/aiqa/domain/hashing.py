"""canon-json-v1. Keys are sorted, output is UTF-8 and compact, and money stays a string."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from aiqa.contracts.cases import JsonObject

SCHEMA_VERSION = "canon-json-v1"
_EXCLUDED = {
    "availability",
    "file_availability",
    "name",
    "secret",
    "secret_plaintext",
    "secret_value",
    "tags",
    "tc_pointer",
    "tc_reference",
}


class CanonicalJsonError(ValueError):
    """The value cannot be hashed as canon-json-v1."""


def canonical_hash(body: JsonObject, schema_version: str) -> str:
    if schema_version != SCHEMA_VERSION:
        raise CanonicalJsonError("schema_version must be canon-json-v1")
    text = canonical_json({"body": body, "schema_version": schema_version})
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_json(value: object) -> str:
    return _canonical(value)


def content_body(body: JsonObject) -> JsonObject:
    stripped = _strip(body)
    if not isinstance(stripped, dict):
        raise CanonicalJsonError("content body must be an object")
    return stripped



def execution_snapshot_hash(
    definition: JsonObject,
    settings: JsonObject,
    recorded_steps: list[object],
    *,
    source_manifest_hash: str | None = None,
    replay_package_hash: str | None = None,
) -> str:
    """Hash execution content, independently of projection and provenance row IDs.

    Source/package bodies identify their inputs without including the produced
    version hash, so incorporating their hashes here cannot create a cycle.
    """
    # Metadata lives at the snapshot boundary. A variable/selector/secret alias
    # named "name" or "tags" is still execution content and must not disappear.
    return canonical_hash({
        "definition": {key: value for key, value in definition.items() if key not in _EXCLUDED},
        "settings": {key: value for key, value in settings.items() if key not in _EXCLUDED},
        "recorded_steps": _recorded_content(recorded_steps),
        "source_manifest_hash": source_manifest_hash,
        "replay_package_hash": replay_package_hash,
    }, SCHEMA_VERSION)


def _recorded_content(value: object, *, artifact: bool = False) -> object:
    """Project known artifact metadata, preserving arbitrary execution aliases."""
    if isinstance(value, Mapping):
        if any(key in value for key in ('secret_plaintext', 'secret_value')):
            raise CanonicalJsonError('recorded steps cannot contain actual secret values')
        return {
            key: _recorded_content(item, artifact=artifact or key in {
                'artifact', 'artifacts', 'before_ref', 'after_ref', 'log_ref', 'error_ref',
            })
            for key, item in value.items()
            if not (artifact and key in {'availability', 'file_availability', 'storage_state', 'custody'})
        }
    if isinstance(value, (list, tuple)):
        return [_recorded_content(item, artifact=artifact) for item in value]
    return value


def _strip(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _strip(item) for key, item in value.items() if str(key) not in _EXCLUDED}
    if isinstance(value, list):
        return [_strip(item) for item in value]
    return value


def _canonical(value: object) -> str:
    if isinstance(value, Mapping):
        parts: list[str] = []
        for key in sorted(value, key=lambda item: str(item)):
            if not isinstance(key, str):
                raise CanonicalJsonError("object keys must be strings")
            parts.append(_canonical(key) + ":" + _canonical(value[key]))
        return "{" + ",".join(parts) + "}"
    if isinstance(value, list | tuple):
        return "[" + ",".join(_canonical(item) for item in value) + "]"
    if value is None:
        return "null"
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is int:
        return str(value)
    if type(value) is str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    raise CanonicalJsonError("numbers must be finite integers or decimal strings")
