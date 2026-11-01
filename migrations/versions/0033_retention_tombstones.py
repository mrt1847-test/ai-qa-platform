"""Expiry leaves a tombstone and a retention event. Identity and hash stay."""

import sqlite3


def apply(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS retention_tombstones (
            project_id TEXT NOT NULL,
            tombstone_id TEXT NOT NULL,
            subject_kind TEXT NOT NULL,
            subject_id TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            expired_at TEXT NOT NULL,
            PRIMARY KEY (project_id, tombstone_id),
            UNIQUE (project_id, subject_kind, subject_id),
            FOREIGN KEY (project_id) REFERENCES projects(project_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS payload_retention_events (
            project_id TEXT NOT NULL,
            event_id TEXT NOT NULL,
            subject_kind TEXT NOT NULL,
            subject_id TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (project_id, event_id),
            FOREIGN KEY (project_id) REFERENCES projects(project_id)
        )
        """
    )
