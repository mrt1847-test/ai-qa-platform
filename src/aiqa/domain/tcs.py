"""Optional TC documents. Referencing one does not revise the case."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from uuid import UUID, uuid4

from aiqa.domain.hashing import SCHEMA_VERSION, canonical_hash, canonical_json
from aiqa.domain.versions import assign_tc_reference
from aiqa.store.database import Store
from aiqa.store.models import Actor, CaseMetadataView, TcRevisionInput, TcVersionView

_store: ContextVar[Store] = ContextVar("aiqa_tc_store")
_actor: ContextVar[Actor] = ContextVar("aiqa_tc_actor")


class TcNotFound(Exception):
    """The TC is not in this project."""


@contextmanager
def bind_tc_store(store: Store) -> Iterator[None]:
    token = _store.set(store)
    try:
        yield
    finally:
        _store.reset(token)


@contextmanager
def bind_tc_actor(actor: Actor) -> Iterator[None]:
    token = _actor.set(actor)
    try:
        yield
    finally:
        _actor.reset(token)


def save_tc_revision(revision: TcRevisionInput) -> TcVersionView:
    if revision.name.strip() == "" and revision.tc_id is None:
        raise ValueError("tc name is required")
    canonical_json(revision.body)
    content_hash = canonical_hash(revision.body, SCHEMA_VERSION)
    version_id = uuid4()
    created_at = datetime.now(timezone.utc).isoformat()
    with _bound_store().transaction() as connection:
        if revision.tc_id is None:
            tc_id = uuid4()
            number = 1
            connection.execute(
                """
                INSERT INTO test_cases (
                    project_id, tc_id, name, next_revision, latest_version_id, archived_at
                ) VALUES (?, ?, ?, 2, ?, NULL)
                """,
                (str(revision.project_id), str(tc_id), revision.name, str(version_id)),
            )
            archived_at = None
            name = revision.name
        else:
            tc_id = revision.tc_id
            current = connection.execute(
                """
                SELECT name, next_revision, archived_at
                FROM test_cases
                WHERE project_id = ? AND tc_id = ?
                """,
                (str(revision.project_id), str(tc_id)),
            ).fetchone()
            if current is None:
                raise TcNotFound("tc was not found")
            name = str(current[0])
            number = int(current[1])
            archived_at = None if current[2] is None else str(current[2])
            connection.execute(
                """
                UPDATE test_cases
                SET next_revision = ?, latest_version_id = ?
                WHERE project_id = ? AND tc_id = ?
                """,
                (number + 1, str(version_id), str(revision.project_id), str(tc_id)),
            )
        connection.execute(
            """
            INSERT INTO tc_versions (
                project_id, tc_id, version_id, revision, body_json, content_hash,
                actor_id, reason, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(revision.project_id),
                str(tc_id),
                str(version_id),
                number,
                canonical_json(revision.body),
                content_hash,
                str(revision.actor_id),
                revision.reason,
                created_at,
            ),
        )
    return TcVersionView(
        project_id=revision.project_id,
        tc_id=tc_id,
        id=version_id,
        revision=number,
        name=name,
        content_hash=content_hash,
        archived_at=archived_at,
    )


def clone_tc(source_tc_id: UUID) -> TcVersionView:
    actor = _actor.get()
    if actor.project_scope is None:
        raise TcNotFound("tc was not found")
    with _bound_store().transaction() as connection:
        source = connection.execute(
            """
            SELECT test_cases.name, tc_versions.body_json
            FROM test_cases
            JOIN tc_versions ON tc_versions.version_id = test_cases.latest_version_id
            WHERE test_cases.project_id = ? AND test_cases.tc_id = ?
            """,
            (str(actor.project_scope), str(source_tc_id)),
        ).fetchone()
    if source is None:
        raise TcNotFound("tc was not found")
    body = json.loads(str(source[1]))
    if type(body) is not dict:
        raise ValueError("tc body is invalid")
    return save_tc_revision(
        TcRevisionInput(
            project_id=actor.project_scope,
            actor_id=actor.actor_id,
            name=str(source[0]),
            body=body,
            reason="clone",
        )
    )


def archive_tc(tc_id: UUID) -> TcVersionView:
    actor = _actor.get()
    if actor.project_scope is None:
        raise TcNotFound("tc was not found")
    archived_at = datetime.now(timezone.utc).isoformat()
    with _bound_store().transaction() as connection:
        updated = connection.execute(
            """
            UPDATE test_cases
            SET archived_at = ?
            WHERE project_id = ? AND tc_id = ? AND archived_at IS NULL
            """,
            (archived_at, str(actor.project_scope), str(tc_id)),
        )
        if updated.rowcount != 1:
            raise TcNotFound("tc was not found")
        row = connection.execute(
            """
            SELECT test_cases.name, test_cases.latest_version_id, tc_versions.revision, tc_versions.content_hash
            FROM test_cases
            JOIN tc_versions ON tc_versions.version_id = test_cases.latest_version_id
            WHERE test_cases.project_id = ? AND test_cases.tc_id = ?
            """,
            (str(actor.project_scope), str(tc_id)),
        ).fetchone()
    if row is None or row[1] is None:
        raise TcNotFound("tc was not found")
    return TcVersionView(
        project_id=actor.project_scope,
        tc_id=tc_id,
        id=UUID(str(row[1])),
        revision=int(row[2]),
        name=str(row[0]),
        content_hash=str(row[3]),
        archived_at=archived_at,
    )


def set_tc_reference(case_id: UUID, tc_version_id: UUID | None) -> CaseMetadataView:
    return assign_tc_reference(_actor.get(), case_id, tc_version_id)


def read_tc_reference(case_id: UUID) -> CaseMetadataView:
    actor = _actor.get()
    if actor.project_scope is None:
        raise TcNotFound("case was not found")
    row = _bound_store()._connection.execute(
        """
        SELECT name, tc_reference, current_approval_id, latest_draft_version_id, lock_version
        FROM automation_cases
        WHERE project_id = ? AND case_id = ?
        """,
        (str(actor.project_scope), str(case_id)),
    ).fetchone()
    if row is None:
        raise TcNotFound("case was not found")
    return _metadata(actor, case_id, row)


def _metadata(actor: Actor, case_id: UUID, row: tuple[object, ...]) -> CaseMetadataView:
    return CaseMetadataView(
        project_id=actor.project_scope if actor.project_scope is not None else case_id,
        case_id=case_id,
        name=str(row[0]),
        tc_reference=None if row[1] is None else UUID(str(row[1])),
        current_approval_id=None if row[2] is None else UUID(str(row[2])),
        latest_draft_version_id=None if row[3] is None else UUID(str(row[3])),
        lock_version=int(row[4]),
    )


def _bound_store() -> Store:
    try:
        return _store.get()
    except LookupError as exc:
        raise RuntimeError("tc store is not bound") from exc
