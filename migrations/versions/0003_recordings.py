"""Recording, manifest, and receipt rows. A recording belongs to one case."""


def apply(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS recordings (
            project_id TEXT NOT NULL,
            case_id TEXT NOT NULL,
            recording_id TEXT NOT NULL,
            creation_kind TEXT NOT NULL CHECK (creation_kind = 'recorded'),
            input_case_version_id TEXT NOT NULL,
            base_case_version_id TEXT,
            parent_recording_id TEXT,
            source_recording_id TEXT,
            storage_status TEXT NOT NULL CHECK (storage_status IN ('local', 'spooling', 'stored')),
            stop_status TEXT NOT NULL CHECK (stop_status IN ('running', 'stopped')),
            completion_status TEXT NOT NULL CHECK (completion_status IN ('open', 'completed', 'interrupted', 'error')),
            evidence_status TEXT NOT NULL CHECK (evidence_status IN ('incomplete', 'complete')),
            PRIMARY KEY (project_id, recording_id),
            UNIQUE (project_id, case_id, recording_id),
            FOREIGN KEY (project_id, case_id) REFERENCES automation_cases(project_id, case_id),
            FOREIGN KEY (project_id, case_id, input_case_version_id)
                REFERENCES case_versions(project_id, case_id, version_id),
            FOREIGN KEY (project_id, case_id, base_case_version_id)
                REFERENCES case_versions(project_id, case_id, version_id),
            FOREIGN KEY (project_id, case_id, parent_recording_id)
                REFERENCES recordings(project_id, case_id, recording_id),
            FOREIGN KEY (project_id, case_id, source_recording_id)
                REFERENCES recordings(project_id, case_id, recording_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS recording_manifests (
            project_id TEXT NOT NULL,
            case_id TEXT NOT NULL,
            recording_id TEXT NOT NULL,
            manifest_id TEXT NOT NULL,
            revision INTEGER NOT NULL,
            kind TEXT NOT NULL CHECK (kind IN ('original', 'recovery', 'package_rebuild')),
            prior_manifest_id TEXT,
            input_version_hash TEXT NOT NULL,
            source_artifact_hashes TEXT NOT NULL,
            action_mapping TEXT NOT NULL,
            evidence_completeness TEXT NOT NULL,
            request_key TEXT NOT NULL,
            body_hash TEXT NOT NULL,
            PRIMARY KEY (project_id, manifest_id),
            UNIQUE (project_id, recording_id, revision),
            UNIQUE (project_id, recording_id, request_key),
            FOREIGN KEY (project_id, case_id, recording_id)
                REFERENCES recordings(project_id, case_id, recording_id),
            FOREIGN KEY (project_id, prior_manifest_id)
                REFERENCES recording_manifests(project_id, manifest_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS materialization_receipts (
            project_id TEXT NOT NULL,
            receipt_id TEXT NOT NULL,
            manifest_id TEXT NOT NULL,
            produced_version_id TEXT NOT NULL,
            body_hash TEXT NOT NULL,
            PRIMARY KEY (project_id, receipt_id),
            UNIQUE (project_id, manifest_id),
            UNIQUE (project_id, produced_version_id),
            FOREIGN KEY (project_id, manifest_id)
                REFERENCES recording_manifests(project_id, manifest_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS recording_notes (
            project_id TEXT NOT NULL,
            recording_id TEXT NOT NULL,
            note_id TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            commit_seq INTEGER NOT NULL,
            body TEXT NOT NULL,
            request_key TEXT NOT NULL,
            PRIMARY KEY (project_id, recording_id, note_id),
            UNIQUE (project_id, recording_id, commit_seq),
            UNIQUE (project_id, recording_id, request_key),
            FOREIGN KEY (project_id, recording_id) REFERENCES recordings(project_id, recording_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS recordings_protect_identity
        BEFORE UPDATE OF input_case_version_id, base_case_version_id, parent_recording_id,
            source_recording_id, creation_kind, case_id ON recordings
        BEGIN
            SELECT RAISE(ABORT, 'recording identity is immutable');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS recording_manifests_no_update
        BEFORE UPDATE ON recording_manifests
        BEGIN
            SELECT RAISE(ABORT, 'manifest is immutable');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS recording_notes_no_update
        BEFORE UPDATE ON recording_notes
        BEGIN
            SELECT RAISE(ABORT, 'recording note is append-only');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS recording_notes_no_delete
        BEFORE DELETE ON recording_notes
        BEGIN
            SELECT RAISE(ABORT, 'recording note is append-only');
        END
        """
    )
