"""Ready artifact bytes. A row is acked only when the file is ready."""


def apply(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS artifact_objects (
            project_id TEXT NOT NULL,
            artifact_id TEXT NOT NULL,
            object_key TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            byte_length INTEGER NOT NULL,
            media_type TEXT NOT NULL,
            owner_id TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('ready', 'quarantine')),
            acked INTEGER NOT NULL CHECK (acked IN (0, 1)),
            PRIMARY KEY (project_id, artifact_id),
            FOREIGN KEY (project_id) REFERENCES projects(project_id),
            CHECK (
                (status = 'ready' AND acked = 1)
                OR (status = 'quarantine' AND acked = 0)
            )
        )
        """
    )
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS artifact_objects_ready_hash
        ON artifact_objects(project_id, content_hash)
        WHERE status = 'ready'
        """
    )
