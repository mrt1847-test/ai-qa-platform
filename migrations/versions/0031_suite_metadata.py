"""Suite list metadata and one receipt per browser command. Versions stay immutable."""

import sqlite3


def apply(connection: sqlite3.Connection) -> None:
    connection.execute("ALTER TABLE suites ADD COLUMN description TEXT NOT NULL DEFAULT ''")
    connection.execute("ALTER TABLE suites ADD COLUMN target_kind TEXT NOT NULL DEFAULT 'web'")
    connection.execute("ALTER TABLE suites ADD COLUMN owner_name TEXT NOT NULL DEFAULT ''")
    connection.execute("ALTER TABLE suites ADD COLUMN classification TEXT NOT NULL DEFAULT ''")
    connection.execute("ALTER TABLE suites ADD COLUMN head_version_id TEXT")
    connection.execute("ALTER TABLE suites ADD COLUMN archived_at TEXT")
    connection.execute("ALTER TABLE suites ADD COLUMN created_at TEXT NOT NULL DEFAULT ''")
    connection.execute("ALTER TABLE suites ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS suite_receipts (
            project_id TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            operation TEXT NOT NULL,
            request_key TEXT NOT NULL,
            body_hash TEXT NOT NULL,
            suite_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (project_id, actor_id, operation, request_key),
            FOREIGN KEY (project_id, suite_id) REFERENCES suites(project_id, suite_id)
        )
        """
    )
