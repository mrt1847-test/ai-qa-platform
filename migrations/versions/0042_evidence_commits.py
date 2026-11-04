"""Idempotent evidence commits and late recovery artifact inbox."""


def apply(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS evidence_commit_requests (
            project_id TEXT NOT NULL,
            job_id TEXT NOT NULL,
            generation INTEGER NOT NULL,
            worker_id TEXT NOT NULL,
            request_key TEXT NOT NULL,
            body_hash TEXT NOT NULL,
            response_body TEXT,
            created_at TEXT NOT NULL,
            PRIMARY KEY (project_id, job_id, generation, worker_id, request_key),
            FOREIGN KEY (project_id, job_id) REFERENCES jobs(project_id, job_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS late_evidence_inbox (
            project_id TEXT NOT NULL,
            inbox_id TEXT NOT NULL,
            attempt_id TEXT NOT NULL,
            job_id TEXT NOT NULL,
            generation INTEGER NOT NULL,
            content_hash TEXT NOT NULL,
            media_type TEXT NOT NULL,
            role TEXT NOT NULL,
            filename TEXT NOT NULL,
            reason TEXT NOT NULL,
            received_at TEXT NOT NULL,
            PRIMARY KEY (project_id, inbox_id),
            UNIQUE (project_id, attempt_id, content_hash, role, filename),
            FOREIGN KEY (project_id, attempt_id) REFERENCES attempts(project_id, attempt_id)
        )
        """
    )
