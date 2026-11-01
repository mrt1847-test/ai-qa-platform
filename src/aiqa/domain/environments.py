"""Immutable Web and Android environment revisions. This does not launch a device."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from urllib.parse import urlparse
from uuid import UUID, uuid4

from aiqa.domain.hashing import SCHEMA_VERSION, canonical_hash, canonical_json
from aiqa.store.database import Store
from aiqa.store.models import EnvironmentRevisionInput, EnvironmentRevisionView

_store: ContextVar[Store] = ContextVar("aiqa_environment_store")
_PACKAGE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+$")
_UNSUPPORTED = frozenset({"multitab", "file", "rotation"})


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
    document = {
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
    _apply_profile(revision, document)
    return document


def _apply_profile(revision: EnvironmentRevisionInput, document: dict[str, object]) -> None:
    profile = revision.profile or {}
    selected = profile.get("capabilities", ())
    if type(selected) is not list and type(selected) is not tuple:
        raise ValueError("invalid environment")
    if any(item in _UNSUPPORTED for item in selected):
        raise ValueError("invalid environment")
    if revision.target_kind == "web":
        origins = {_origin(item) for item in revision.allowlist}
        start_url = profile.get("start_url")
        if start_url is not None:
            if type(start_url) is not str or _origin(start_url) not in origins:
                raise ValueError("invalid environment")
            document["start_url"] = start_url
        if "dpr" in profile and profile.get("dpr") != 1:
            raise ValueError("invalid environment")
        if "timezone" in profile and profile.get("timezone") != "Asia/Seoul":
            raise ValueError("invalid environment")
        if "dpr" in profile:
            document["dpr"] = 1
        if "timezone" in profile:
            document["timezone"] = "Asia/Seoul"
        return
    package = profile.get("package")
    if type(package) is not str or _PACKAGE.fullmatch(package) is None:
        raise ValueError("invalid environment")
    if profile.get("orientation", "portrait") != "portrait":
        raise ValueError("invalid environment")
    document["package"] = package
    document["orientation"] = "portrait"
    for key in ("setup", "reset", "cleanup", "account_ref"):
        value = profile.get(key)
        if value is not None:
            if type(value) is not str:
                raise ValueError("invalid environment")
            document[key] = value


def _origin(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
        raise ValueError("invalid environment")
    if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("invalid environment")
    port = "" if parsed.port is None else f":{parsed.port}"
    return f"{parsed.scheme}://{parsed.hostname}{port}"


def _bound_store() -> Store:
    try:
        return _store.get()
    except LookupError as exc:
        raise RuntimeError("environment store is not bound") from exc


def list_environment_profiles(project_id: UUID) -> tuple[dict[str, object], ...]:
    """Latest immutable profiles for this project only; no secret text."""
    rows = _bound_store()._connection.execute(
        """SELECT e.environment_id,e.name,r.revision_id,r.revision,r.body_json
        FROM environments e JOIN environment_revisions r
        ON r.project_id=e.project_id AND r.revision_id=e.latest_revision_id
        WHERE e.project_id=? ORDER BY e.name,e.environment_id""",(str(project_id),)
    ).fetchall()
    return tuple({"environment_id":str(r[0]),"name":str(r[1]),"id":str(r[2]),
        "revision":int(r[3]),"profile":json.loads(r[4])} for r in rows)
