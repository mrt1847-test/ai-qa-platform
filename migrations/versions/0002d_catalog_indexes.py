"""Case list indexes and classification links. Open recordings are only an archive conflict marker."""


def apply(connection):
    connection.execute("ALTER TABLE automation_cases ADD COLUMN priority TEXT")
    connection.execute("ALTER TABLE automation_cases ADD COLUMN assignee_id TEXT")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS case_tag_links (
            project_id TEXT NOT NULL,
            case_id TEXT NOT NULL,
            tag_id TEXT NOT NULL,
            PRIMARY KEY (project_id, case_id, tag_id),
            FOREIGN KEY (project_id, case_id) REFERENCES automation_cases(project_id, case_id),
            FOREIGN KEY (project_id, tag_id) REFERENCES tags(project_id, tag_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS case_clone_provenance (
            project_id TEXT NOT NULL,
            case_id TEXT NOT NULL,
            source_case_id TEXT NOT NULL,
            source_version_id TEXT,
            created_at TEXT NOT NULL,
            PRIMARY KEY (project_id, case_id),
            FOREIGN KEY (project_id, case_id) REFERENCES automation_cases(project_id, case_id),
            FOREIGN KEY (project_id, source_case_id) REFERENCES automation_cases(project_id, case_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS case_open_recordings (
            project_id TEXT NOT NULL,
            recording_id TEXT NOT NULL,
            case_id TEXT NOT NULL,
            status TEXT NOT NULL,
            PRIMARY KEY (project_id, recording_id),
            FOREIGN KEY (project_id, case_id) REFERENCES automation_cases(project_id, case_id)
        )
        """
    )
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS tags_project_name ON tags(project_id, name)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS automation_cases_name ON automation_cases(project_id, name, case_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS automation_cases_folder ON automation_cases(project_id, folder_id, case_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS case_tag_links_tag ON case_tag_links(project_id, tag_id, case_id)"
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS case_open_recordings_case
        ON case_open_recordings(project_id, case_id, status)
        """
    )
