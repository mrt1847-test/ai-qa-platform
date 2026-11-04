"""SQLite layout for the API process. Importing this module does not open a database."""

from __future__ import annotations

import importlib.util
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from aiqa.config import AppSettings


class StorageError(ValueError):
    """The runtime path or migration entry cannot be used."""


@dataclass(frozen=True, slots=True)
class StorageConfig:
    runtime_root: Path
    database_path: Path
    artifacts_dir: Path
    spool_dir: Path
    backups_dir: Path | None = None

    @classmethod
    def from_settings(cls, settings: AppSettings) -> StorageConfig:
        root = settings.runtime_root
        if any(part.casefold().startswith("onedrive") for part in root.parts):
            raise StorageError("runtime root must stay outside OneDrive")
        return cls(
            runtime_root=root,
            database_path=root / "db" / "aiqa.sqlite",
            artifacts_dir=settings.artifacts_dir,
            spool_dir=root / "spool",
            backups_dir=settings.backups_dir,
        )


@dataclass(frozen=True, slots=True)
class SchemaRevision:
    id: str


class Store:
    def __init__(self, config: StorageConfig, connection: sqlite3.Connection) -> None:
        self.config = config
        self._connection = connection
        # SQLite REPLACE performs an implicit DELETE. Its immutable-row guards
        # only run when recursive triggers are enabled on every connection.
        connection.execute('PRAGMA recursive_triggers=ON')

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            yield self._connection
            self._connection.execute("COMMIT")
        except BaseException:
            if self._connection.in_transaction:
                self._connection.execute("ROLLBACK")
            raise

    def put_project_row(self, project_id: str, name: str) -> None:
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO project_rows (project_id, name) VALUES (?, ?)",
                (project_id, name),
            )

    def get_project_row(self, project_id: str) -> tuple[str, str] | None:
        row = self._connection.execute(
            "SELECT project_id, name FROM project_rows WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        if row is None:
            return None
        return (str(row[0]), str(row[1]))

    def put_note(self, project_id: str, note: str) -> None:
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO project_row_notes (project_id, note) VALUES (?, ?)",
                (project_id, note),
            )

    def foreign_keys_enabled(self) -> int:
        row = self._connection.execute("PRAGMA foreign_keys").fetchone()
        return int(row[0])

    def journal_mode(self) -> str:
        row = self._connection.execute("PRAGMA journal_mode").fetchone()
        return str(row[0])

    def in_transaction(self) -> bool:
        return bool(self._connection.in_transaction)

    def close(self) -> None:
        self._connection.close()

    def on_rollback(self, callback) -> None:
        """Standalone transactions have already committed at registration time.

        A request-owned Store overrides this hook to compensate external writes
        if the surrounding business/receipt transaction subsequently rolls back.
        """


def open_store(config: StorageConfig) -> Store:
    config.database_path.parent.mkdir(parents=True, exist_ok=True)
    config.artifacts_dir.mkdir(parents=True, exist_ok=True)
    config.spool_dir.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(config.database_path, isolation_level=None)
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=2000")
    mode = connection.execute("PRAGMA journal_mode=WAL").fetchone()
    if mode is None or str(mode[0]).lower() != "wal":
        connection.close()
        raise StorageError("SQLite journal_mode must be WAL")
    return Store(config, connection)


def migrate_store(store: Store) -> SchemaRevision:
    module = _migration_env()
    latest = ""
    with store.transaction() as connection:
        module.ensure_history(connection)
        applied = {
            str(row[0])
            for row in connection.execute("SELECT id FROM schema_migrations")
        }
        for revision_id, apply in module.revisions():
            latest = revision_id
            if revision_id in applied:
                continue
            apply(connection)
            connection.execute(
                "INSERT INTO schema_migrations (id, applied_at) VALUES (?, ?)",
                (revision_id, datetime.now(timezone.utc).isoformat()),
            )
    if not latest:
        raise StorageError("no schema revisions are registered")
    return SchemaRevision(id=latest)


def _migration_env():
    env_path = Path(__file__).resolve().parents[3] / "migrations" / "env.py"
    if not env_path.is_file():
        raise StorageError(f"migration env is missing: {env_path}")
    spec = importlib.util.spec_from_file_location("aiqa_migration_env", env_path)
    if spec is None or spec.loader is None:
        raise StorageError("migration env cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
