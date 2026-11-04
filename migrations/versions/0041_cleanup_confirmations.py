"""Cleanup confirmations release leases only after attempt and fence match."""


def apply(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS cleanup_confirmations (
            project_id TEXT NOT NULL,
            attempt_id TEXT NOT NULL,
            job_id TEXT NOT NULL,
            generation INTEGER NOT NULL,
            worker_id TEXT NOT NULL,
            physical_key_id TEXT,
            released INTEGER NOT NULL,
            quarantined INTEGER NOT NULL,
            proof_refs TEXT NOT NULL,
            confirmed_at TEXT NOT NULL,
            PRIMARY KEY (project_id, attempt_id),
            FOREIGN KEY (project_id, attempt_id) REFERENCES attempts(project_id, attempt_id)
        )
        """
    )
