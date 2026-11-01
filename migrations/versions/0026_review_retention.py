"""Append-only review protection events. The first expiry stays unchanged."""

import sqlite3


def apply(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS review_retention_events (
            project_id TEXT NOT NULL,
            event_id TEXT NOT NULL,
            review_id TEXT NOT NULL,
            protection_id TEXT NOT NULL,
            artifact_id TEXT NOT NULL,
            reason TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (project_id, event_id),
            FOREIGN KEY (project_id, review_id) REFERENCES reviews(project_id, review_id),
            FOREIGN KEY (project_id, protection_id) REFERENCES artifact_protections(project_id, protection_id),
            FOREIGN KEY (project_id, artifact_id) REFERENCES artifact_refs(project_id, artifact_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS review_retention_events_no_update
        BEFORE UPDATE ON review_retention_events
        BEGIN
            SELECT RAISE(ABORT, 'review retention is append-only');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS review_retention_events_no_delete
        BEFORE DELETE ON review_retention_events
        BEGIN
            SELECT RAISE(ABORT, 'review retention is append-only');
        END
        """
    )
