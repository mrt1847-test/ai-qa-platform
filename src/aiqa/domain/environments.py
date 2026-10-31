"""Immutable Web and Android environment revisions. This does not launch a device."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from uuid import UUID, uuid4

from aiqa.domain.hashing import SCHEMA_VERSION, canonical_hash, canonical_json
from aiqa.store.database import Store
from aiqa.store.models import EnvironmentRevisionInput, EnvironmentRevisionView

_store: ContextVar[Store] = ContextVar("aiqa_environment_store")


class EnvironmentNotFound(Exception):
    """The environment revision is not in this project."""


@contextmanager
def bind_environment_store(store: Store) -> Iterator[None]:
    token = _store.set(store)
    try:
        yield
    finally:
        _store.reset(token)


def save_environment_revision(revision: EnvironmentRevisionInput) -> EnvironmentRevisionView:
    document = _document(revision)
    canonical_json(document)
    content_hash = canonical_hash(document, SCHEMA_VERSION)
    revision_id = uuid4()
    created_at = datetime.now(timezone.utc).isoformat()
    with _bound_store().transaction() as connection:
        if revision.environment_id is None:
            if revision.name.strip() == "":
                raise ValueError("environment name is required")
            environment_id = uuid4()
            number = 1
            connection.execute(
                """
                INSERT INTO environments (
                    project_id, environment_id, name, next_revision, latest_revision_id
                ) VALUES (?, ?, ?, 2, ?)
                """,
                (str(revision.project_id), str(environment_id), revision.name, str(revision_id)),
            )
        else:
            environment_id = revision.environment_id
            current = connection.execute(
                "SELECT next_revision FROM environments WHERE project_id = ? AND environment_id = ?",
                (str(revision.project_id), str(environment_id)),
            ).fetchone()
            if current is None:
                raise EnvironmentNotFound("environment was not found")
            number = int(current[0])
            connection.execute(
                """
                UPDATE environments SET next_revision = ?, latest_revision_id = ?
                WHERE project_id = ? AND environment_id = ?
                """,
                (number + 1, str(revision_id), str(revision.project_id), str(environment_id)),
            )
        connection.execute(
            """
            INSERT INTO environment_revisions (
                project_id, environment_id, revision_id, revision, body_json, content_hash, actor_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(revision.project_id),
                str(environment_id),
                str(revision_id),
                number,
                canonical_json(document),
                content_hash,
                str(revision.actor_id),
                created_at,
            ),
        )
    return EnvironmentRevisionView(
        project_id=revision.project_id,
        environment_id=environment_id,
        id=revision_id,
        revision=number,
        target_kind=revision.target_kind,
        locale=revision.locale,
        content_hash=content_hash,
    )


def get_environment_revision(project_id: UUID, environment_id: UUID, revision_id: UUID) -> EnvironmentRevisionView:
    row = _bound_store()._connection.execute(
        """
        SELECT revision, body_json, content_hash
        FROM environment_revisions
        WHERE project_id = ? AND environment_id = ? AND revision_id = ?
        """,
        (str(project_id), str(environment_id), str(revision_id)),
    ).fetchone()
    if row is None:
        raise EnvironmentNotFound("environment was not found")
    body = json.loads(str(row[1]))
    return EnvironmentRevisionView(
        project_id=project_id,
        environment_id=environment_id,
        id=revision_id,
        revision=int(row[0]),
        target_kind=str(body["target_kind"]),
        locale=str(body["locale"]),
        content_hash=str(row[2]),
    )


def _document(revision: EnvironmentRevisionInput) -> dict[str, object]:
    if revision.target_kind not in {"web", "android"}:
        raise ValueError("invalid environment")
    if not revision.allowlist or any(type(item) is not str or item.strip() == "" for item in revision.allowlist):
        raise ValueError("invalid environment")
    width = revision.viewport.get("width")
    height = revision.viewport.get("height")
    if type(width) is not int or type(height) is not int or width < 1 or height < 1:
        raise ValueError("invalid environment")
    if revision.locale.strip() == "" or revision.reset_policy.strip() == "":
        raise ValueError("invalid environment")
    budget = revision.limits.get("budget")
    currency = revision.limits.get("currency")
    timeout = revision.limits.get("timeout_seconds")
    actions = revision.limits.get("max_actions")
    if type(budget) is not str or type(currency) is not str or type(timeout) is not int or type(actions) is not int:
        raise ValueError("invalid environment")
    return {
        "allowlist": list(revision.allowlist),
        "limits": {
            "budget": budget,
            "currency": currency,
            "max_actions": actions,
            "timeout_seconds": timeout,
        },
        "locale": revision.locale,
        "reset_policy": revision.reset_policy,
        "target_kind": revision.target_kind,
        "viewport": {"height": height, "width": width},
    }


def _bound_store() -> Store:
    try:
        return _store.get()
    except LookupError as exc:
        raise RuntimeError("environment store is not bound") from exc
