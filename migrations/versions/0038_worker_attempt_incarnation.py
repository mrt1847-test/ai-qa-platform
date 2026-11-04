"""Store worker incarnation on attempts separately from server boot."""


def apply(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS attempt_incarnations (
            project_id TEXT NOT NULL,
            attempt_id TEXT NOT NULL,
            worker_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            boot_id TEXT NOT NULL,
            PRIMARY KEY (project_id, attempt_id),
            FOREIGN KEY (project_id, attempt_id) REFERENCES attempts(project_id, attempt_id)
        )
        """
    )
