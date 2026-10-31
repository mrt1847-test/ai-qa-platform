"""Latest reported device facts. Credentials are not columns."""


def apply(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS resource_inventory (
            physical_key_id TEXT PRIMARY KEY
                REFERENCES physical_resource_keys(physical_key_id),
            state TEXT NOT NULL CHECK (state IN ('offline', 'unauthorized', 'busy', 'ready')),
            os_build TEXT NOT NULL,
            geometry TEXT NOT NULL,
            permissions TEXT NOT NULL,
            ime TEXT NOT NULL,
            observed_at TEXT NOT NULL
        )
        """
    )
