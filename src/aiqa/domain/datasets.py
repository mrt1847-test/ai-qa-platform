"""Immutable dataset revisions. Row values must match the saved schema."""

from __future__ import annotations

import json
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
    document: dict[str, object] = {
        "rows": [dict(row) for row in revision.rows],
        "schema": revision.row_schema,
        "secret_ref": _secret_document(revision.secret_ref),
    }
    if revision.case_id is not None:
        document["case_id"] = str(revision.case_id)
    canonical_json(document)
    content_hash = canonical_hash(document, SCHEMA_VERSION)
    version_id = uuid4()
    created_at = datetime.now(timezone.utc).isoformat()
    with _bound_store().transaction() as connection:
        _require_local_secret(connection, revision.project_id, revision.secret_ref)
        _require_case(connection, revision.project_id, revision.case_id)
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


def list_datasets(project_id: UUID) -> tuple[dict[str, object], ...]:
    """List dataset names and row diffs. Secret text is not selected."""

    with _bound_store().transaction() as connection:
        rows = connection.execute(
            """
            SELECT datasets.dataset_id, datasets.name, versions.revision, versions.body_json, versions.content_hash, versions.version_id
            FROM datasets
            JOIN dataset_versions AS versions
              ON versions.project_id = datasets.project_id
             AND versions.version_id = datasets.latest_version_id
            WHERE datasets.project_id = ?
            ORDER BY datasets.name
            """,
            (str(project_id),),
        ).fetchall()
        listed = []
        for row in rows:
            body = json.loads(str(row[3]))
            previous = None
            if int(row[2]) > 1:
                older = connection.execute(
                    """
                    SELECT body_json FROM dataset_versions
                    WHERE project_id = ? AND dataset_id = ? AND revision = ?
                    """,
                    (str(project_id), str(row[0]), int(row[2]) - 1),
                ).fetchone()
                previous = None if older is None else json.loads(str(older[0]))
            view = _public_dataset(str(row[0]), str(row[1]), int(row[2]), str(row[4]), body, previous)
            view["id"] = str(row[5])
            view['version_id'] = str(row[5])
            view["row_schema"] = body.get("schema", {})
            view["secret_ref"] = body.get("secret_ref")
            listed.append(view)
    return tuple(listed)


def read_dataset_version(project_id: UUID, dataset_id: UUID, version_id: UUID) -> dict[str, object]:
    """Return one stored revision. The body never includes secret text."""

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
    body = json.loads(str(row[1]))
    view = _public_dataset(str(dataset_id), "", int(row[0]), str(row[2]), body, None)
    view["rows"] = body.get("rows", [])
    view["id"] = str(version_id)
    view['version_id'] = str(version_id)
    view["row_schema"] = body.get("schema", {})
    view["secret_ref"] = body.get("secret_ref")
    return view


def _public_dataset(
    dataset_id: str,
    name: str,
    revision: int,
    content_hash: str,
    body: dict[str, object],
    previous: dict[str, object] | None,
) -> dict[str, object]:
    rows = body.get("rows", [])
    return {
        "dataset_id": dataset_id,
        "name": name,
        "revision": revision,
        "content_hash": content_hash,
        "case_id": body.get("case_id"),
        "rows": rows,
        "secret_ref": body.get("secret_ref"),
        "changes": _changes(previous, rows),
    }


def _changes(previous: dict[str, object] | None, rows: object) -> list[str]:
    if previous is None or type(rows) is not list:
        return []
    older = {str(item.get("id")): item.get("values") for item in previous.get("rows", []) if type(item) is dict}
    changed = []
    for item in rows:
        if type(item) is not dict:
            continue
        row_id = str(item.get("id"))
        if row_id in older and older[row_id] != item.get("values"):
            changed.append(row_id)
    return changed


def _require_case(connection, project_id: UUID, case_id: UUID | None) -> None:
    if case_id is None:
        return
    row = connection.execute(
        "SELECT 1 FROM automation_cases WHERE project_id = ? AND case_id = ?",
        (str(project_id), str(case_id)),
    ).fetchone()
    if row is None:
        raise ValueError("case was not found")


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
