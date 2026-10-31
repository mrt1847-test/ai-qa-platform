"""Migration entry for the API store. Later revisions live in migrations/versions."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

RevisionStep = tuple[str, Callable[[sqlite3.Connection], None]]


def ensure_history(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )


def apply_0000_storage(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS project_rows (
            project_id TEXT PRIMARY KEY,
            name TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS project_row_notes (
            project_id TEXT NOT NULL REFERENCES project_rows(project_id),
            note TEXT NOT NULL
        )
        """
    )


def revisions() -> list[RevisionStep]:
    steps: list[RevisionStep] = [("0000_storage", apply_0000_storage)]
    versions = Path(__file__).resolve().parent / "versions"
    if not versions.is_dir():
        return steps
    for path in sorted(versions.glob("[0-9]*.py")):
        if path.name == "__init__.py":
            continue
        namespace: dict[str, object] = {}
        exec(path.read_text(encoding="utf-8"), namespace)  # noqa: S102
        apply = namespace.get("apply")
        if not callable(apply):
            raise RuntimeError(f"{path.name} must define apply(connection)")
        steps.append((path.stem, apply))
    return steps
