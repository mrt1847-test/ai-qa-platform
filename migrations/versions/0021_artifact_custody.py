"""Operational custody for a ready file. The content hash column stays unchanged."""


def apply(connection):
    columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(artifact_objects)").fetchall()}
    if "custody" not in columns:
        connection.execute(
            "ALTER TABLE artifact_objects ADD COLUMN custody TEXT NOT NULL DEFAULT 'stored'"
        )
    if "stored_at" not in columns:
        connection.execute(
            "ALTER TABLE artifact_objects ADD COLUMN stored_at TEXT NOT NULL DEFAULT ''"
        )
