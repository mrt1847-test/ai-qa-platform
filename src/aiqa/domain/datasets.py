"""Immutable dataset revisions. Row values must match the saved schema."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from uuid import UUID, uuid4

from aiqa.domain.hashing import SCHEMA_VERSION, canonical_hash, canonical_json
from aiqa.store.database import Store
from aiqa.store.models import DatasetRevisionInput, DatasetVersionView, SecretRef

_store: ContextVar[Store] = ContextVar("aiqa_dataset_store")


class DatasetNotFound(Exception):
    """The dataset revision is not in this project."""


class ForeignSecret(Exception):
    """The secret ref belongs to another project."""


@contextmanager
def bind_dataset_store(store: Store) -> Iterator[None]:
    token = _store.set(store)
    try:
        yield
    finally:
        _store.reset(token)


def save_dataset_revision(revision: DatasetRevisionInput) -> DatasetVersionView:
    _validate_rows(revision.row_schema, revision.rows)
    document = {
        "rows": [dict(row) for row in revision.rows],
        "schema": revision.row_schema,
        "secret_ref": _secret_document(revision.secret_ref),
    }
    canonical_json(document)
    content_hash = canonical_hash(document, SCHEMA_VERSION)
    version_id = uuid4()
    created_at = datetime.now(timezone.utc).isoformat()
    with _bound_store().transaction() as connection:
        _require_local_secret(connection, revision.project_id, revision.secret_ref)
        if revision.dataset_id is None:
            if revision.name.strip() == "":
                raise ValueError("dataset name is required")
            dataset_id = uuid4()
            number = 1
            connection.execute(
                """
                INSERT INTO datasets (project_id, dataset_id, name, next_revision, latest_version_id)
                VALUES (?, ?, ?, 2, ?)
                """,
                (str(revision.project_id), str(dataset_id), revision.name, str(version_id)),
            )
        else:
            dataset_id = revision.dataset_id
            current = connection.execute(
                "SELECT next_revision FROM datasets WHERE project_id = ? AND dataset_id = ?",
                (str(revision.project_id), str(dataset_id)),
            ).fetchone()
            if current is None:
                raise DatasetNotFound("dataset was not found")
            number = int(current[0])
            connection.execute(
                """
                UPDATE datasets SET next_revision = ?, latest_version_id = ?
                WHERE project_id = ? AND dataset_id = ?
                """,
                (number + 1, str(version_id), str(revision.project_id), str(dataset_id)),
            )
        connection.execute(
            """
            INSERT INTO dataset_versions (
                project_id, dataset_id, version_id, revision, body_json, content_hash, actor_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(revision.project_id),
                str(dataset_id),
                str(version_id),
                number,
                canonical_json(document),
                content_hash,
                str(revision.actor_id),
                created_at,
            ),
        )
    return DatasetVersionView(
        project_id=revision.project_id,
        dataset_id=dataset_id,
        id=version_id,
        revision=number,
        content_hash=content_hash,
        secret_ref=revision.secret_ref,
    )


def get_dataset_revision(project_id: UUID, dataset_id: UUID, version_id: UUID) -> DatasetVersionView:
    row = _bound_store()._connection.execute(
        """
        SELECT revision, body_json, content_hash
        FROM dataset_versions
        WHERE project_id = ? AND dataset_id = ? AND version_id = ?
        """,
        (str(project_id), str(dataset_id), str(version_id)),
    ).fetchone()
    if row is None:
        raise DatasetNotFound("dataset was not found")
    return DatasetVersionView(
        project_id=project_id,
        dataset_id=dataset_id,
        id=version_id,
        revision=int(row[0]),
        content_hash=str(row[2]),
        secret_ref=None,
    )


def _validate_rows(schema: dict[str, object], rows: tuple[dict[str, object], ...]) -> None:
    columns = schema.get("columns")
    if type(columns) is not list or not columns:
        raise ValueError("invalid schema")
    types: dict[str, str] = {}
    for column in columns:
        if type(column) is not dict:
            raise ValueError("invalid schema")
        name = column.get("name")
        kind = column.get("type")
        if type(name) is not str or name.strip() == "" or kind not in {"string", "int", "bool"} or name in types:
            raise ValueError("invalid schema")
        types[name] = str(kind)
    seen: set[str] = set()
    if not rows:
        raise ValueError("invalid rows")
    for row in rows:
        row_id = row.get("id")
        values = row.get("values")
        if type(row_id) is not str or row_id.strip() == "" or row_id in seen or type(values) is not dict:
            raise ValueError("invalid rows")
        seen.add(row_id)
        if set(values) != set(types):
            raise ValueError("invalid rows")
        for name, value in values.items():
            if types[name] == "string" and type(value) is not str:
                raise ValueError("invalid rows")
            if types[name] == "int" and type(value) is not int:
                raise ValueError("invalid rows")
            if types[name] == "bool" and type(value) is not bool:
                raise ValueError("invalid rows")


def _secret_document(ref: SecretRef | None) -> dict[str, object] | None:
    if ref is None:
        return None
    return {"ref_id": str(ref.ref_id), "revision": ref.revision}


def _require_local_secret(connection, project_id: UUID, ref: SecretRef | None) -> None:
    if ref is None:
        return
    if ref.project_id != project_id:
        raise ForeignSecret("secret ref belongs to another project")
    row = connection.execute(
        "SELECT 1 FROM secret_refs WHERE project_id = ? AND ref_id = ? AND revision = ?",
        (str(project_id), str(ref.ref_id), ref.revision),
    ).fetchone()
    if row is None:
        raise ForeignSecret("secret ref belongs to another project")


def _bound_store() -> Store:
    try:
        return _store.get()
    except LookupError as exc:
        raise RuntimeError("dataset store is not bound") from exc
