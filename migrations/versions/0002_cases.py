"""Case identity, immutable revisions, and the folder/tag tables metadata will reference."""


def apply(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS folders (
            project_id TEXT NOT NULL REFERENCES projects(project_id),
            folder_id TEXT NOT NULL,
            parent_folder_id TEXT,
            name TEXT NOT NULL,
            PRIMARY KEY (project_id, folder_id),
            FOREIGN KEY (project_id, parent_folder_id) REFERENCES folders(project_id, folder_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS tags (
            project_id TEXT NOT NULL REFERENCES projects(project_id),
            tag_id TEXT NOT NULL,
            name TEXT NOT NULL,
            PRIMARY KEY (project_id, tag_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS automation_cases (
            project_id TEXT NOT NULL REFERENCES projects(project_id),
            case_id TEXT NOT NULL,
            name TEXT NOT NULL,
            folder_id TEXT,
            tc_reference TEXT,
            next_revision INTEGER NOT NULL,
            latest_draft_version_id TEXT,
            current_approval_id TEXT,
            lock_version INTEGER NOT NULL,
            archived_at TEXT,
            PRIMARY KEY (project_id, case_id),
            FOREIGN KEY (project_id, folder_id) REFERENCES folders(project_id, folder_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS case_versions (
            project_id TEXT NOT NULL,
            case_id TEXT NOT NULL,
            version_id TEXT NOT NULL,
            revision INTEGER NOT NULL,
            creation_kind TEXT NOT NULL,
            parent_version_id TEXT,
            base_version_id TEXT,
            is_branch INTEGER NOT NULL,
            definition_json TEXT NOT NULL,
            settings_json TEXT NOT NULL,
            recorded_steps_json TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            verification_digest TEXT NOT NULL,
            source_manifest_id TEXT,
            replay_package_id TEXT,
            readiness_json TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (project_id, case_id, version_id),
            UNIQUE (case_id, revision),
            UNIQUE (project_id, version_id),
            FOREIGN KEY (project_id, case_id) REFERENCES automation_cases(project_id, case_id),
            FOREIGN KEY (project_id, case_id, parent_version_id)
                REFERENCES case_versions(project_id, case_id, version_id),
            FOREIGN KEY (project_id, case_id, base_version_id)
                REFERENCES case_versions(project_id, case_id, version_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS case_revision_audits (
            project_id TEXT NOT NULL,
            case_id TEXT NOT NULL,
            version_id TEXT NOT NULL,
            commit_seq INTEGER NOT NULL,
            actor_id TEXT NOT NULL,
            action TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS case_versions_no_update
        BEFORE UPDATE ON case_versions
        BEGIN
            SELECT RAISE(ABORT, 'case version content is immutable');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS case_versions_no_delete
        BEFORE DELETE ON case_versions
        BEGIN
            SELECT RAISE(ABORT, 'case version content is immutable');
        END
        """
    )
