"""Immutable proposal bodies and one append-only adoption event."""

import sqlite3


def apply(connection: sqlite3.Connection) -> None:
    connection.execute("ALTER TABLE repair_proposals ADD COLUMN accepted_target_json TEXT NOT NULL DEFAULT ''")
    connection.execute("ALTER TABLE repair_proposals ADD COLUMN diff_json TEXT NOT NULL DEFAULT ''")
    connection.execute("ALTER TABLE repair_proposals ADD COLUMN evidence_hash TEXT NOT NULL DEFAULT ''")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS repair_adoptions (
            project_id TEXT NOT NULL,
            adoption_id TEXT NOT NULL,
            proposal_id TEXT NOT NULL,
            case_id TEXT NOT NULL,
            recording_id TEXT NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (project_id, adoption_id),
            UNIQUE (project_id, proposal_id),
            FOREIGN KEY (project_id, proposal_id) REFERENCES repair_proposals(project_id, proposal_id),
            FOREIGN KEY (project_id, case_id) REFERENCES automation_cases(project_id, case_id),
            FOREIGN KEY (project_id, recording_id) REFERENCES recordings(project_id, recording_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS repair_adoptions_no_update
        BEFORE UPDATE ON repair_adoptions
        BEGIN
            SELECT RAISE(ABORT, 'adoption is append-only');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS repair_adoptions_no_delete
        BEFORE DELETE ON repair_adoptions
        BEGIN
            SELECT RAISE(ABORT, 'adoption is append-only');
        END
        """
    )
