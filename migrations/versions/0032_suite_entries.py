"""Exact suite entry facts. Older versions stay immutable."""

import sqlite3


def apply(connection: sqlite3.Connection) -> None:
    connection.execute("ALTER TABLE suite_entries ADD COLUMN case_id TEXT NOT NULL DEFAULT ''")
    connection.execute("ALTER TABLE suite_entries ADD COLUMN case_version_id TEXT NOT NULL DEFAULT ''")
    connection.execute("ALTER TABLE suite_entries ADD COLUMN approval_id TEXT NOT NULL DEFAULT ''")
    connection.execute("ALTER TABLE suite_entries ADD COLUMN data_name TEXT NOT NULL DEFAULT ''")
    connection.execute("ALTER TABLE suite_entries ADD COLUMN environment_revision_id TEXT NOT NULL DEFAULT ''")
    connection.execute("ALTER TABLE suite_entries ADD COLUMN reset_policy TEXT NOT NULL DEFAULT ''")
    connection.execute("ALTER TABLE suite_entries ADD COLUMN failure_policy TEXT NOT NULL DEFAULT 'stop'")
    connection.execute("ALTER TABLE suite_entries ADD COLUMN resource_id TEXT NOT NULL DEFAULT ''")
    connection.execute("ALTER TABLE suite_entries ADD COLUMN target_kind TEXT NOT NULL DEFAULT 'web'")
    connection.execute("ALTER TABLE suite_receipts ADD COLUMN suite_version_id TEXT")
