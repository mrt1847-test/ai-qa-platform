"""GC claims and typed pin receipts. A pending claim blocks a new approval pin."""

import sqlite3


def apply(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS gc_claims (
            project_id TEXT NOT NULL,
            claim_id TEXT NOT NULL,
            artifact_id TEXT NOT NULL,
            state TEXT NOT NULL CHECK (state IN ('delete_pending')),
            claimed_at TEXT NOT NULL,
            PRIMARY KEY (project_id, claim_id),
            FOREIGN KEY (project_id, artifact_id) REFERENCES artifact_refs(project_id, artifact_id)
        )
        """
    )
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS gc_claims_one_pending
        ON gc_claims(project_id, artifact_id)
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS retention_command_receipts (
            project_id TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            operation TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            body_hash TEXT NOT NULL,
            protection_id TEXT NOT NULL,
            PRIMARY KEY (project_id, actor_id, operation, idempotency_key),
            FOREIGN KEY (project_id) REFERENCES projects(project_id)
        )
        """
    )
