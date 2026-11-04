"""OIDC identity link and project membership roles for hosted login."""


def apply(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS oidc_identities (
            identity_id TEXT PRIMARY KEY,
            issuer TEXT NOT NULL,
            subject TEXT NOT NULL,
            actor_id TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            UNIQUE (issuer, subject)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS project_memberships (
            project_id TEXT NOT NULL REFERENCES projects(project_id),
            actor_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('viewer', 'operator', 'admin')),
            created_at TEXT NOT NULL,
            revoked_at TEXT,
            PRIMARY KEY (project_id, actor_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS oidc_login_states (
            state TEXT PRIMARY KEY,
            nonce TEXT NOT NULL,
            code_challenge TEXT NOT NULL,
            code_verifier TEXT NOT NULL,
            redirect_uri TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            used_at TEXT
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS oidc_auth_codes (
            code_hash TEXT PRIMARY KEY,
            state TEXT NOT NULL,
            nonce TEXT NOT NULL,
            code_challenge TEXT NOT NULL,
            issuer TEXT NOT NULL,
            subject TEXT NOT NULL,
            audience TEXT NOT NULL,
            redirect_uri TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            used_at TEXT
        )
        """
    )
