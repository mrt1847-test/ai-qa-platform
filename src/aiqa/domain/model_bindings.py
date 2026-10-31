"""Immutable model-binding revisions. This module does not call a provider."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from uuid import UUID, uuid4

from aiqa.domain.hashing import SCHEMA_VERSION, canonical_hash
from aiqa.store.database import Store
from aiqa.store.models import ModelBindingInput, ModelBindingView, SecretRef

_store: ContextVar[Store] = ContextVar("aiqa_model_binding_store")
_PROMPT_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
_ROLES = {"authoring", "verification", "healing", "maintenance"}
_COMPATIBILITY = {"unchecked", "compatible", "incompatible"}


class BindingNotFound(Exception):
    """The model binding revision is not in this project."""


class ForeignSecret(Exception):
    """The key ref belongs to another project."""


@contextmanager
def bind_model_store(store: Store) -> Iterator[None]:
    token = _store.set(store)
    try:
        yield
    finally:
        _store.reset(token)


def save_model_binding_revision(revision: ModelBindingInput) -> ModelBindingView:
    _validate(revision)
    document = {
        "compatibility_status": revision.compatibility_status,
        "endpoint": revision.endpoint,
        "endpoint_kind": revision.endpoint_kind,
        "key_ref": {"ref_id": str(revision.key_ref.ref_id), "revision": revision.key_ref.revision},
        "model": revision.model,
        "prompt_hash": revision.prompt_hash,
        "provider": revision.provider,
        "role": revision.role,
        "tariff_id": revision.tariff_id,
    }
    content_hash = canonical_hash(document, SCHEMA_VERSION)
    revision_id = uuid4()
    created_at = datetime.now(timezone.utc).isoformat()
    with _bound_store().transaction() as connection:
        _require_local_secret(connection, revision.project_id, revision.key_ref)
        if revision.binding_id is None:
            if revision.name.strip() == "":
                raise ValueError("binding name is required")
            binding_id = uuid4()
            number = 1
            connection.execute(
                """
                INSERT INTO model_bindings (
                    project_id, binding_id, name, next_revision, latest_revision_id
                ) VALUES (?, ?, ?, 2, ?)
                """,
                (str(revision.project_id), str(binding_id), revision.name, str(revision_id)),
            )
        else:
            binding_id = revision.binding_id
            current = connection.execute(
                "SELECT next_revision FROM model_bindings WHERE project_id = ? AND binding_id = ?",
                (str(revision.project_id), str(binding_id)),
            ).fetchone()
            if current is None:
                raise BindingNotFound("binding was not found")
            number = int(current[0])
            connection.execute(
                """
                UPDATE model_bindings SET next_revision = ?, latest_revision_id = ?
                WHERE project_id = ? AND binding_id = ?
                """,
                (number + 1, str(revision_id), str(revision.project_id), str(binding_id)),
            )
        connection.execute(
            """
            INSERT INTO binding_revisions (
                project_id, binding_id, revision_id, revision, role, provider, endpoint_kind,
                endpoint, model, key_ref_id, key_revision, prompt_hash, tariff_id,
                compatibility_status, content_hash, actor_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(revision.project_id),
                str(binding_id),
                str(revision_id),
                number,
                revision.role,
                revision.provider,
                revision.endpoint_kind,
                revision.endpoint,
                revision.model,
                str(revision.key_ref.ref_id),
                revision.key_ref.revision,
                revision.prompt_hash,
                revision.tariff_id,
                revision.compatibility_status,
                content_hash,
                str(revision.actor_id),
                created_at,
            ),
        )
    return ModelBindingView(
        project_id=revision.project_id,
        binding_id=binding_id,
        id=revision_id,
        revision=number,
        role=revision.role,
        model=revision.model,
        content_hash=content_hash,
        compatibility_status=revision.compatibility_status,
    )


def _validate(revision: ModelBindingInput) -> None:
    if revision.role not in _ROLES or revision.compatibility_status not in _COMPATIBILITY:
        raise ValueError("invalid binding")
    for value in (revision.provider, revision.endpoint_kind, revision.endpoint, revision.model, revision.tariff_id):
        if type(value) is not str or value.strip() == "":
            raise ValueError("invalid binding")
    if _PROMPT_HASH.fullmatch(revision.prompt_hash) is None:
        raise ValueError("invalid binding")


def _require_local_secret(connection, project_id: UUID, ref: SecretRef) -> None:
    if ref.project_id != project_id:
        raise ForeignSecret("key ref belongs to another project")
    row = connection.execute(
        "SELECT 1 FROM secret_refs WHERE project_id = ? AND ref_id = ? AND revision = ?",
        (str(project_id), str(ref.ref_id), ref.revision),
    ).fetchone()
    if row is None:
        raise ForeignSecret("key ref belongs to another project")


def _bound_store() -> Store:
    try:
        return _store.get()
    except LookupError as exc:
        raise RuntimeError("model binding store is not bound") from exc
