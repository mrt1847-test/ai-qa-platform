"""One runner nonce per claimed attempt. A repeat ACK keeps that attempt."""


def apply(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS attempt_runners (
            project_id TEXT NOT NULL,
            attempt_id TEXT NOT NULL,
            runner_nonce TEXT NOT NULL,
            acked_at TEXT NOT NULL,
            PRIMARY KEY (project_id, attempt_id),
            FOREIGN KEY (project_id, attempt_id) REFERENCES attempts(project_id, attempt_id)
        )
        """
    )
