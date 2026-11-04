"""Idempotent claim receipts bound to worker incarnation and job snapshots."""


def apply(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS claim_receipts (
            project_id TEXT NOT NULL,
            worker_id TEXT NOT NULL,
            request_key TEXT NOT NULL,
            body_hash TEXT NOT NULL,
            job_id TEXT NOT NULL,
            attempt_id TEXT NOT NULL,
            generation INTEGER NOT NULL,
            physical_key_id TEXT,
            expires_at TEXT NOT NULL,
            session_id TEXT,
            boot_id TEXT,
            purpose TEXT NOT NULL,
            target_ref TEXT,
            revision_ref TEXT,
            policy_ref TEXT,
            digest TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (project_id, worker_id, request_key),
            FOREIGN KEY (project_id, attempt_id) REFERENCES attempts(project_id, attempt_id),
            FOREIGN KEY (project_id, job_id) REFERENCES jobs(project_id, job_id)
        )
        """
    )
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS claim_receipts_attempt
        ON claim_receipts (project_id, attempt_id)
        """
    )
