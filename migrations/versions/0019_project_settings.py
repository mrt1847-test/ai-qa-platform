"""Project defaults. A case approval is not stored in this table."""


def apply(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS project_settings (
            project_id TEXT PRIMARY KEY,
            lock_version INTEGER NOT NULL,
            failure_policy TEXT NOT NULL,
            retention TEXT NOT NULL,
            timeout_seconds INTEGER NOT NULL,
            healing_scope TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(project_id)
        )
        """
    )
