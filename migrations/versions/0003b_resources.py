"""Global physical resource keys and per-project aliases."""


def apply(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS physical_resource_keys (
            physical_key_id TEXT PRIMARY KEY,
            worker_id TEXT NOT NULL,
            native_id TEXT NOT NULL,
            UNIQUE (worker_id, native_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS resource_aliases (
            project_id TEXT NOT NULL REFERENCES projects(project_id),
            physical_key_id TEXT NOT NULL REFERENCES physical_resource_keys(physical_key_id),
            display_name TEXT NOT NULL,
            target_kind TEXT NOT NULL CHECK (target_kind IN ('web', 'android')),
            PRIMARY KEY (project_id, physical_key_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS physical_resource_keys_require_worker
        BEFORE INSERT ON physical_resource_keys
        WHEN NOT EXISTS (
            SELECT 1 FROM worker_enrollments WHERE worker_id = NEW.worker_id
        )
        BEGIN
            SELECT RAISE(ABORT, 'unknown worker');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS physical_resource_keys_identity
        BEFORE UPDATE OF worker_id, native_id ON physical_resource_keys
        BEGIN
            SELECT RAISE(ABORT, 'physical key is immutable');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS resource_aliases_require_enrollment
        BEFORE INSERT ON resource_aliases
        WHEN NOT EXISTS (
            SELECT 1
            FROM physical_resource_keys AS keys
            JOIN worker_enrollments AS enrollments
              ON enrollments.worker_id = keys.worker_id
             AND enrollments.project_id = NEW.project_id
            WHERE keys.physical_key_id = NEW.physical_key_id
        )
        BEGIN
            SELECT RAISE(ABORT, 'alias project does not enroll this worker');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS resource_aliases_binding_immutable
        BEFORE UPDATE OF project_id, physical_key_id ON resource_aliases
        BEGIN
            SELECT RAISE(ABORT, 'alias project binding is immutable');
        END
        """
    )
