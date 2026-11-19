"""Keep an explicit execution exclusion with the run that omitted it."""


def apply(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS execution_exclusions (
            project_id TEXT NOT NULL,
            execution_id TEXT NOT NULL,
            entry_id TEXT NOT NULL,
            reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
            PRIMARY KEY (project_id, execution_id, entry_id),
            FOREIGN KEY (project_id, execution_id)
                REFERENCES executions(project_id, execution_id)
        )
        """
    )
