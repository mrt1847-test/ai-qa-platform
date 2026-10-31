"""Late events after expiry or a terminal job. They do not change the attempt cursor."""


def apply(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS stale_event_inbox (
            project_id TEXT NOT NULL,
            inbox_id TEXT NOT NULL,
            attempt_id TEXT,
            job_id TEXT NOT NULL,
            generation INTEGER NOT NULL,
            local_seq INTEGER NOT NULL,
            payload_hash TEXT NOT NULL,
            body_hash TEXT NOT NULL,
            reason TEXT NOT NULL CHECK (reason IN ('expired', 'terminal')),
            received_at TEXT NOT NULL,
            PRIMARY KEY (project_id, inbox_id)
        )
        """
    )
