"""Queued approval blocks and the 90-day grace for a released approval pin."""

import sqlite3


def apply(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS approval_queue_blocks (
            project_id TEXT NOT NULL,
            job_id TEXT NOT NULL,
            approval_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (project_id, job_id),
            FOREIGN KEY (project_id, job_id) REFERENCES jobs(project_id, job_id),
            FOREIGN KEY (project_id, approval_id) REFERENCES approval_events(project_id, approval_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS approval_queue_blocks_no_update
        BEFORE UPDATE ON approval_queue_blocks
        BEGIN
            SELECT RAISE(ABORT, 'approval queue block is permanent');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS approval_queue_blocks_no_delete
        BEFORE DELETE ON approval_queue_blocks
        BEGIN
            SELECT RAISE(ABORT, 'approval queue block is permanent');
        END
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS approval_pin_releases (
            project_id TEXT NOT NULL,
            release_id TEXT NOT NULL,
            protection_id TEXT NOT NULL,
            approval_id TEXT NOT NULL,
            released_at TEXT NOT NULL,
            grace_until TEXT NOT NULL,
            PRIMARY KEY (project_id, release_id),
            UNIQUE (project_id, protection_id),
            FOREIGN KEY (project_id, protection_id) REFERENCES artifact_protections(project_id, protection_id),
            FOREIGN KEY (project_id, approval_id) REFERENCES approval_events(project_id, approval_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS approval_pin_releases_no_update
        BEFORE UPDATE ON approval_pin_releases
        BEGIN
            SELECT RAISE(ABORT, 'approval pin grace is permanent');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS approval_pin_releases_no_delete
        BEFORE DELETE ON approval_pin_releases
        BEGIN
            SELECT RAISE(ABORT, 'approval pin grace is permanent');
        END
        """
    )
