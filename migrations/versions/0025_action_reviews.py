"""Append-only opinions for one exact review entry. QA rows are not touched."""

import sqlite3


def apply(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS action_reviews (
            project_id TEXT NOT NULL,
            opinion_id TEXT NOT NULL,
            review_id TEXT NOT NULL,
            entry_id TEXT NOT NULL,
            owner_kind TEXT NOT NULL CHECK (owner_kind IN ('REC', 'ITEM')),
            owner_id TEXT NOT NULL,
            attempt_id TEXT NOT NULL,
            action_id TEXT NOT NULL,
            evidence_digest TEXT NOT NULL,
            state TEXT NOT NULL CHECK (state IN ('reviewed', 'needs_change', 'evidence_missing')),
            actor_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            comment TEXT NOT NULL,
            PRIMARY KEY (project_id, opinion_id),
            FOREIGN KEY (project_id, review_id) REFERENCES reviews(project_id, review_id),
            FOREIGN KEY (project_id, entry_id) REFERENCES review_evidence_entries(project_id, entry_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS action_reviews_no_update
        BEFORE UPDATE ON action_reviews
        BEGIN
            SELECT RAISE(ABORT, 'action review is append-only');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS action_reviews_no_delete
        BEFORE DELETE ON action_reviews
        BEGIN
            SELECT RAISE(ABORT, 'action review is append-only');
        END
        """
    )
