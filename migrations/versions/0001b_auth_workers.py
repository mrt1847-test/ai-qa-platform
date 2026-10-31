"""Browser nonce, session, and worker token references. Raw secrets are not stored."""


def apply(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS browser_nonces (
            nonce_hash TEXT PRIMARY KEY,
            origin TEXT NOT NULL,
            project_id TEXT NOT NULL REFERENCES projects(project_id),
            expires_at TEXT NOT NULL,
            used_at TEXT
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS browser_sessions (
            session_id TEXT PRIMARY KEY,
            origin TEXT NOT NULL,
            csrf_hash TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            project_scope TEXT NOT NULL REFERENCES projects(project_id),
            is_local_owner INTEGER NOT NULL,
            expires_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS worker_enrollments (
            enrollment_id TEXT PRIMARY KEY,
            worker_id TEXT NOT NULL,
            project_id TEXT NOT NULL REFERENCES projects(project_id),
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS worker_tokens (
            token_id TEXT PRIMARY KEY,
            enrollment_id TEXT NOT NULL REFERENCES worker_enrollments(enrollment_id),
            token_hash TEXT NOT NULL UNIQUE,
            purpose TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
