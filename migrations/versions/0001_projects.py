"""Project identity, composite audit scope, and the commit clock."""


def apply(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS projects (
            project_id TEXT PRIMARY KEY,
            key TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            target TEXT NOT NULL,
            created_at TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            actor_project_scope TEXT,
            actor_is_local_owner INTEGER NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS project_commit_clock (
            project_id TEXT PRIMARY KEY REFERENCES projects(project_id),
            commit_seq INTEGER NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS project_audits (
            project_id TEXT NOT NULL,
            audit_id TEXT NOT NULL,
            commit_seq INTEGER NOT NULL,
            actor_id TEXT NOT NULL,
            action TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (project_id, audit_id),
            FOREIGN KEY (project_id) REFERENCES projects(project_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS project_audit_links (
            project_id TEXT NOT NULL,
            audit_id TEXT NOT NULL,
            note TEXT NOT NULL,
            commit_seq INTEGER NOT NULL,
            PRIMARY KEY (project_id, audit_id),
            FOREIGN KEY (project_id, audit_id)
                REFERENCES project_audits(project_id, audit_id)
        )
        """
    )
