"""Permanent enqueue receipts. The same key and body return the original job."""


def apply(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS job_receipts (
            project_id TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            operation TEXT NOT NULL,
            request_key TEXT NOT NULL,
            body_hash TEXT NOT NULL,
            job_id TEXT NOT NULL,
            purpose TEXT NOT NULL,
            recording_id TEXT,
            execution_id TEXT,
            case_run_id TEXT,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (project_id, actor_id, operation, request_key),
            FOREIGN KEY (project_id, job_id) REFERENCES jobs(project_id, job_id),
            FOREIGN KEY (project_id, recording_id) REFERENCES recordings(project_id, recording_id),
            FOREIGN KEY (project_id, case_run_id) REFERENCES case_runs(project_id, case_run_id)
        )
        """
    )
