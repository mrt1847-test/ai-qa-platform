"""Secret reference metadata. Plaintext and plaintext hashes are not stored here."""


def apply(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS secret_refs (
            project_id TEXT NOT NULL REFERENCES projects(project_id),
            ref_id TEXT NOT NULL,
            revision INTEGER NOT NULL,
            name TEXT NOT NULL,
            availability TEXT NOT NULL,
            created_at TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            PRIMARY KEY (project_id, ref_id, revision)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS secret_ref_audits (
            project_id TEXT NOT NULL,
            ref_id TEXT NOT NULL,
            revision INTEGER NOT NULL,
            commit_seq INTEGER NOT NULL,
            actor_id TEXT NOT NULL,
            action TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (project_id, ref_id, revision)
                REFERENCES secret_refs(project_id, ref_id, revision)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS secret_ref_snapshots (
            project_id TEXT NOT NULL,
            ref_id TEXT NOT NULL,
            revision INTEGER NOT NULL,
            commit_seq INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (project_id, ref_id, revision)
                REFERENCES secret_refs(project_id, ref_id, revision)
        )
        """
    )
