"""Separate project alias ids from shared physical resource keys used for leases."""

from uuid import uuid4


def apply(connection):
    connection.execute("ALTER TABLE resource_aliases ADD COLUMN alias_id TEXT")
    rows = connection.execute(
        "SELECT project_id, physical_key_id FROM resource_aliases WHERE alias_id IS NULL OR alias_id = ''"
    ).fetchall()
    for project_id, physical_key_id in rows:
        connection.execute(
            "UPDATE resource_aliases SET alias_id = ? WHERE project_id = ? AND physical_key_id = ?",
            (str(uuid4()), project_id, physical_key_id),
        )
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS resource_aliases_alias_id
        ON resource_aliases (alias_id)
        """
    )
