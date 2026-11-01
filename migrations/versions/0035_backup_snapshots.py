"""Backup pause and private snapshot facts. A project path does not limit the copy."""

import sqlite3


def apply(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS gc_pause (
            pause_id TEXT NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (pause_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS backup_snapshots (
            project_id TEXT NOT NULL,
            receipt_id TEXT NOT NULL,
            job_id TEXT NOT NULL,
            byte_length INTEGER NOT NULL,
            content_hash TEXT NOT NULL,
            state TEXT NOT NULL CHECK (state IN ('complete', 'incomplete')),
            missing_count INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (project_id, receipt_id),
            FOREIGN KEY (project_id, receipt_id) REFERENCES backup_receipts(project_id, receipt_id),
            FOREIGN KEY (project_id, job_id) REFERENCES jobs(project_id, job_id)
        )
        """
    )
