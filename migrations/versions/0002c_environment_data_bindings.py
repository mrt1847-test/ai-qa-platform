"""Immutable dataset, environment, and model-binding revisions."""


def apply(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS datasets (
            project_id TEXT NOT NULL REFERENCES projects(project_id),
            dataset_id TEXT NOT NULL,
            name TEXT NOT NULL,
            next_revision INTEGER NOT NULL,
            latest_version_id TEXT,
            PRIMARY KEY (project_id, dataset_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS dataset_versions (
            project_id TEXT NOT NULL,
            dataset_id TEXT NOT NULL,
            version_id TEXT NOT NULL,
            revision INTEGER NOT NULL,
            body_json TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (project_id, dataset_id, version_id),
            UNIQUE (dataset_id, revision),
            UNIQUE (project_id, version_id),
            FOREIGN KEY (project_id, dataset_id) REFERENCES datasets(project_id, dataset_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS environments (
            project_id TEXT NOT NULL REFERENCES projects(project_id),
            environment_id TEXT NOT NULL,
            name TEXT NOT NULL,
            next_revision INTEGER NOT NULL,
            latest_revision_id TEXT,
            PRIMARY KEY (project_id, environment_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS environment_revisions (
            project_id TEXT NOT NULL,
            environment_id TEXT NOT NULL,
            revision_id TEXT NOT NULL,
            revision INTEGER NOT NULL,
            body_json TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (project_id, environment_id, revision_id),
            UNIQUE (environment_id, revision),
            UNIQUE (project_id, revision_id),
            FOREIGN KEY (project_id, environment_id) REFERENCES environments(project_id, environment_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS model_bindings (
            project_id TEXT NOT NULL REFERENCES projects(project_id),
            binding_id TEXT NOT NULL,
            name TEXT NOT NULL,
            next_revision INTEGER NOT NULL,
            latest_revision_id TEXT,
            PRIMARY KEY (project_id, binding_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS binding_revisions (
            project_id TEXT NOT NULL,
            binding_id TEXT NOT NULL,
            revision_id TEXT NOT NULL,
            revision INTEGER NOT NULL,
            role TEXT NOT NULL,
            provider TEXT NOT NULL,
            endpoint_kind TEXT NOT NULL,
            endpoint TEXT NOT NULL,
            model TEXT NOT NULL,
            key_ref_id TEXT NOT NULL,
            key_revision INTEGER NOT NULL,
            prompt_hash TEXT NOT NULL,
            tariff_id TEXT NOT NULL,
            compatibility_status TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (project_id, binding_id, revision_id),
            UNIQUE (binding_id, revision),
            UNIQUE (project_id, revision_id),
            FOREIGN KEY (project_id, binding_id) REFERENCES model_bindings(project_id, binding_id)
        )
        """
    )
    for table in ("dataset_versions", "environment_revisions", "binding_revisions"):
        connection.execute(
            f"""
            CREATE TRIGGER IF NOT EXISTS {table}_no_update
            BEFORE UPDATE ON {table}
            BEGIN
                SELECT RAISE(ABORT, '{table} content is immutable');
            END
            """
        )
        connection.execute(
            f"""
            CREATE TRIGGER IF NOT EXISTS {table}_no_delete
            BEFORE DELETE ON {table}
            BEGIN
                SELECT RAISE(ABORT, '{table} content is immutable');
            END
            """
        )
