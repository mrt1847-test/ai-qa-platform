"""SQLite layout for the API process. Importing this module does not open a database."""

from __future__ import annotations

import importlib.util
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from aiqa.config import PROFILE_HOSTED, AppSettings
from aiqa.security.receipt_digest import EnvironmentReceiptKey


class StorageError(ValueError):
    """The runtime path or migration entry cannot be used."""


@dataclass(frozen=True, slots=True)
class StorageConfig:
    runtime_root: Path
    database_path: Path
    artifacts_dir: Path
    spool_dir: Path
    backups_dir: Path | None = None
    receipt_key_provider: EnvironmentReceiptKey | None = field(default=None, repr=False, compare=False)
    database_backend: str = 'sqlite'
    database_url: str | None = field(default=None, repr=False, compare=False)
    database_schema: str = 'aiqa'

    @classmethod
    def from_settings(cls, settings: AppSettings) -> StorageConfig:
        root = settings.runtime_root
        if any(part.casefold().startswith("onedrive") for part in root.parts):
            raise StorageError("runtime root must stay outside OneDrive")
        from aiqa.store.object_storage import artifact_root

        root_artifacts = artifact_root(settings.artifacts_dir, backend=settings.artifact_backend,
            supabase_url=settings.supabase_url, service_key=settings.supabase_service_key,
            bucket=settings.supabase_bucket)
        return cls(
            runtime_root=root,
            database_path=root / "db" / "aiqa.sqlite",
            artifacts_dir=root_artifacts,
            spool_dir=root / "spool",
            backups_dir=settings.backups_dir,
            receipt_key_provider=EnvironmentReceiptKey() if settings.profile == PROFILE_HOSTED else None,
            database_backend=settings.database_backend,
            database_url=settings.database_url,
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
        if config.database_backend == 'sqlite':
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

    @contextmanager
    def read_transaction(self):
        """Snapshot reads do not take the management writer fence.

        Nested callers join the existing transaction via a savepoint; the outer
        transaction remains authoritative about whether writes are permitted.
        """
        connection = self._connection
        nested = connection.in_transaction
        savepoint = 'aiqa_read_' + uuid4().hex
        prior_query_only = None
        if nested:
            connection.execute('SAVEPOINT ' + savepoint)
        elif self.config.database_backend == 'postgres':
            connection.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
        else:
            prior_query_only = connection.execute('PRAGMA query_only').fetchone()[0]
            connection.execute('PRAGMA query_only=ON')
            connection.execute('BEGIN')
        try:
            yield connection
            connection.execute('RELEASE ' + savepoint if nested else 'COMMIT')
        except BaseException:
            if nested:
                connection.execute('ROLLBACK TO ' + savepoint)
                connection.execute('RELEASE ' + savepoint)
            elif connection.in_transaction:
                connection.execute('ROLLBACK')
            raise
        finally:
            if prior_query_only is not None:
                connection.execute('PRAGMA query_only=' + str(int(prior_query_only)))

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
    if config.database_backend == 'postgres':
        from aiqa.store.postgres import connect_postgres

        connection = connect_postgres(config)
        config.spool_dir.mkdir(parents=True, exist_ok=True)
        getattr(config.artifacts_dir, 'cache_dir', config.artifacts_dir).mkdir(parents=True, exist_ok=True)
        return Store(config, connection)
    if config.database_backend != 'sqlite':
        raise StorageError('database backend is invalid')
    config.database_path.parent.mkdir(parents=True, exist_ok=True)
    getattr(config.artifacts_dir, 'cache_dir', config.artifacts_dir).mkdir(parents=True, exist_ok=True)
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
    if store.config.database_backend == 'postgres':
        from aiqa.store.postgres import migrate_postgres

        return SchemaRevision(migrate_postgres(store))
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
