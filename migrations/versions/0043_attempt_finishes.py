"""Idempotent worker attempt finishes. Approval stays on the user path."""


def apply(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS attempt_finish_requests (
            project_id TEXT NOT NULL,
            attempt_id TEXT NOT NULL,
            worker_id TEXT NOT NULL,
            request_key TEXT NOT NULL,
            body_hash TEXT NOT NULL,
            response_body TEXT,
            created_at TEXT NOT NULL,
            PRIMARY KEY (project_id, attempt_id, request_key),
            FOREIGN KEY (project_id, attempt_id) REFERENCES attempts(project_id, attempt_id)
        )
        """
    )
