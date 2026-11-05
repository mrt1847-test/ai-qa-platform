"""Immutable model-binding revisions and explicit connection checks.

Revision writes do not call a provider. Connection checks use an injected probe only.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from aiqa.domain.hashing import SCHEMA_VERSION, canonical_hash
from aiqa.store.database import Store
from aiqa.store.models import ModelBindingInput, ModelBindingView, SecretRef

_store: ContextVar[Store] = ContextVar("aiqa_model_binding_store")
_PROMPT_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
_ROLES = {"authoring", "verification", "healing", "maintenance"}
_COMPATIBILITY = {"unchecked", "compatible", "incompatible"}
_CHECK_STATUSES = frozenset(
    {
        "compatible",
        "incompatible",
        "key_missing",
        "unauthorized",
        "rate_limited",
        "timeout",
        "unchecked",
    }
)
_last_checks: dict[str, CompatibilityReport] = {}


class BindingNotFound(Exception):
    """The model binding revision is not in this project."""


class ForeignSecret(Exception):
    """The key ref belongs to another project."""


class ModelCheckBlocked(Exception):
    """The connection check was refused before a provider call."""


@dataclass(frozen=True, slots=True)
class CompatibilityReport:
    project_id: UUID
    binding_id: UUID
    role: str
    model: str
    endpoint: str
    status: str
    reason: str
    checked_at: str | None
    actual_model: str | None
    key_present: bool
    metered_calls: int
    qa: None = None
    replay_requires_model_check: bool = False


@dataclass(frozen=True, slots=True)
class ModelCheckOutcome:
    status: str
    reason: str
    actual_model: str | None
    metered_calls: int
    checked_at: str
    qa: None = None


@dataclass
class ModelCheckProbe:
    """Fixture probe for connection checks. Modes never store secret material."""

    mode: str = "ok"
    calls: int = 0

    def probe(self, *, model: str, role: str, secret: str | None) -> ModelCheckOutcome:
        stamp = datetime.now(timezone.utc).isoformat()
        if secret is None or type(secret) is not str or secret.strip() == "":
            return ModelCheckOutcome("key_missing", "key_missing", None, 0, stamp, None)
        self.calls += 1
        if self.mode == "unauthorized":
            return ModelCheckOutcome("unauthorized", "provider_unauthorized", None, 1, stamp, None)
        if self.mode == "rate_limited":
            return ModelCheckOutcome("rate_limited", "provider_quota", None, 1, stamp, None)
        if self.mode == "timeout":
            return ModelCheckOutcome("timeout", "provider_timeout", None, 1, stamp, None)
        if self.mode == "incompatible":
            return ModelCheckOutcome("incompatible", "model_incompatible", model, 1, stamp, None)
        return ModelCheckOutcome("compatible", "observed", model, 1, stamp, None)


@contextmanager
def bind_model_store(store: Store) -> Iterator[None]:
    token = _store.set(store)
    try:
        yield
    finally:
        _store.reset(token)


def current_model_store() -> Store:
    """Return the store bound for model-binding work."""

    return _bound_store()


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


def approved_deterministic_replay_requires_model_check() -> bool:
    """Approved deterministic/OFF replay does not require a live model connection check."""

    return False


def load_binding_row(project_id: UUID, binding_id: UUID) -> dict[str, object]:
    """Load the latest revision fields for one binding. Does not open a provider."""

    with _bound_store().transaction() as connection:
        row = connection.execute(
            """
            SELECT binding_revisions.role, binding_revisions.model, binding_revisions.endpoint,
                   binding_revisions.compatibility_status, binding_revisions.key_ref_id,
                   binding_revisions.key_revision, binding_revisions.provider,
                   binding_revisions.prompt_hash, binding_revisions.tariff_id
            FROM binding_revisions
            JOIN model_bindings
              ON model_bindings.project_id = binding_revisions.project_id
             AND model_bindings.binding_id = binding_revisions.binding_id
             AND model_bindings.latest_revision_id = binding_revisions.revision_id
            WHERE binding_revisions.project_id = ? AND binding_revisions.binding_id = ?
            """,
            (str(project_id), str(binding_id)),
        ).fetchone()
    if row is None:
        raise BindingNotFound("binding was not found")
    return {
        "role": str(row[0]),
        "model": str(row[1]),
        "endpoint": str(row[2]),
        "compatibility_status": str(row[3]),
        "key_ref_id": UUID(str(row[4])),
        "key_revision": int(row[5]),
        "provider": str(row[6]),
        "prompt_hash": str(row[7]),
        "tariff_id": str(row[8]),
    }


def run_model_binding_check(
    project_id: UUID,
    binding_id: UUID,
    *,
    secret: str | None,
    probe: ModelCheckProbe,
) -> CompatibilityReport:
    """Run one explicit connection check. Key plaintext is never stored on the report."""

    detail = load_binding_row(project_id, binding_id)
    outcome = probe.probe(model=str(detail["model"]), role=str(detail["role"]), secret=secret)
    if outcome.status not in _CHECK_STATUSES:
        raise ModelCheckBlocked("check status is invalid")
    status = outcome.status
    report = CompatibilityReport(
        project_id=project_id,
        binding_id=binding_id,
        role=str(detail["role"]),
        model=str(detail["model"]),
        endpoint=str(detail["endpoint"]),
        status=status,
        reason=outcome.reason,
        checked_at=outcome.checked_at,
        actual_model=outcome.actual_model,
        key_present=secret is not None and type(secret) is str and secret.strip() != "",
        metered_calls=outcome.metered_calls,
        qa=None,
        replay_requires_model_check=approved_deterministic_replay_requires_model_check(),
    )
    _last_checks[f"{project_id}:{binding_id}"] = report
    return report


def get_compatibility(project_id: UUID, binding_id: UUID) -> CompatibilityReport:
    """Return the newest check report, or an unchecked snapshot from the binding."""

    key = f"{project_id}:{binding_id}"
    stored = _last_checks.get(key)
    if stored is not None:
        return stored
    detail = load_binding_row(project_id, binding_id)
    return CompatibilityReport(
        project_id=project_id,
        binding_id=binding_id,
        role=str(detail["role"]),
        model=str(detail["model"]),
        endpoint=str(detail["endpoint"]),
        status=str(detail["compatibility_status"]),
        reason="unchecked",
        checked_at=None,
        actual_model=None,
        key_present=False,
        metered_calls=0,
        qa=None,
        replay_requires_model_check=approved_deterministic_replay_requires_model_check(),
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
