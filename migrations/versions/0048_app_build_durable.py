"""RX-74: durable APK metadata and artifact object key on app_builds."""

_COLUMNS = (
    ("filename", "TEXT NOT NULL DEFAULT ''"),
    ("package_name", "TEXT NOT NULL DEFAULT ''"),
    ("version_name", "TEXT NOT NULL DEFAULT ''"),
    ("min_sdk", "TEXT NOT NULL DEFAULT ''"),
    ("abi", "TEXT NOT NULL DEFAULT ''"),
    ("signature_status", "TEXT NOT NULL DEFAULT 'unknown'"),
    ("ready", "INTEGER NOT NULL DEFAULT 0"),
    ("object_key", "TEXT"),
    ("byte_length", "INTEGER NOT NULL DEFAULT 0"),
    ("artifact_id", "TEXT"),
    ("inspect_job_id", "TEXT"),
    ("created_at", "TEXT NOT NULL DEFAULT ''"),
)


def apply(connection):
    existing = {str(row[1]) for row in connection.execute("PRAGMA table_info(app_builds)")}
    for name, definition in _COLUMNS:
        if name not in existing:
            connection.execute(f"ALTER TABLE app_builds ADD COLUMN {name} {definition}")
    # Only published rows (object_key set) are unique per hash. Install-enqueue pin rows
    # keep the old (build_id, content_hash) shape and may share a hash.
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS app_builds_project_content_hash
        ON app_builds (project_id, content_hash)
        WHERE content_hash != '' AND object_key IS NOT NULL
        """
    )
