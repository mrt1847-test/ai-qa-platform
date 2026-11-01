"""Terminal QA is stored apart from cleanup. A finish fact cannot be rewritten."""

import sqlite3


def apply(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS job_finish_facts (
            project_id TEXT NOT NULL,
            job_id TEXT NOT NULL,
            verdict TEXT CHECK (verdict IS NULL OR verdict IN ('FAIL', 'INCONCLUSIVE')),
            finish_reason TEXT NOT NULL CHECK (finish_reason IN ('lost', 'cancelled', 'crash')),
            cleanup_failed INTEGER NOT NULL CHECK (cleanup_failed IN (0, 1)),
            resource_state TEXT NOT NULL CHECK (resource_state IN ('unchanged', 'quarantine')),
            created_at TEXT NOT NULL,
            PRIMARY KEY (project_id, job_id),
            FOREIGN KEY (project_id, job_id) REFERENCES jobs(project_id, job_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS job_finish_facts_no_update
        BEFORE UPDATE ON job_finish_facts
        BEGIN
            SELECT RAISE(ABORT, 'job finish fact is permanent');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS job_finish_facts_no_delete
        BEFORE DELETE ON job_finish_facts
        BEGIN
            SELECT RAISE(ABORT, 'job finish fact is permanent');
        END
        """
    )
