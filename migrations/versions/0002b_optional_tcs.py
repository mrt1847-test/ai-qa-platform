"""Optional test-case documents. A case reference is metadata, not a new case revision."""


def apply(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS test_cases (
            project_id TEXT NOT NULL REFERENCES projects(project_id),
            tc_id TEXT NOT NULL,
            name TEXT NOT NULL,
            next_revision INTEGER NOT NULL,
            latest_version_id TEXT,
            archived_at TEXT,
            PRIMARY KEY (project_id, tc_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS tc_versions (
            project_id TEXT NOT NULL,
            tc_id TEXT NOT NULL,
            version_id TEXT NOT NULL,
            revision INTEGER NOT NULL,
            body_json TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (project_id, tc_id, version_id),
            UNIQUE (tc_id, revision),
            UNIQUE (project_id, version_id),
            FOREIGN KEY (project_id, tc_id) REFERENCES test_cases(project_id, tc_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS case_tc_references (
            project_id TEXT NOT NULL,
            case_id TEXT NOT NULL,
            tc_version_id TEXT,
            PRIMARY KEY (project_id, case_id),
            FOREIGN KEY (project_id, case_id) REFERENCES automation_cases(project_id, case_id),
            FOREIGN KEY (project_id, tc_version_id) REFERENCES tc_versions(project_id, version_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS case_tc_reference_audits (
            project_id TEXT NOT NULL,
            case_id TEXT NOT NULL,
            tc_version_id TEXT,
            action TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            commit_seq INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS tc_versions_no_update
        BEFORE UPDATE ON tc_versions
        BEGIN
            SELECT RAISE(ABORT, 'tc version content is immutable');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS tc_versions_no_delete
        BEFORE DELETE ON tc_versions
        BEGIN
            SELECT RAISE(ABORT, 'tc version content is immutable');
        END
        """
    )
