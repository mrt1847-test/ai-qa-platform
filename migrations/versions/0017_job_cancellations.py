"""Permanent cancel flags. A repeated key returns the original receipt."""


def apply(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS job_cancellations (
            project_id TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            request_key TEXT NOT NULL,
            job_id TEXT NOT NULL,
            expected_state TEXT NOT NULL,
            body_hash TEXT NOT NULL,
            status_after TEXT NOT NULL,
            requested_at TEXT NOT NULL,
            runner_stopped INTEGER NOT NULL CHECK (runner_stopped IN (0, 1)),
            cleanup_completed INTEGER NOT NULL CHECK (cleanup_completed IN (0, 1)),
            PRIMARY KEY (project_id, actor_id, request_key),
            UNIQUE (project_id, job_id),
            FOREIGN KEY (project_id, job_id) REFERENCES jobs(project_id, job_id)
        )
        """
    )
