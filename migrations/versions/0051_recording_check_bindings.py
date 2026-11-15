"""Immutable logical-check annotations for derived recording candidates."""
def apply(connection):
    connection.execute("""CREATE TABLE IF NOT EXISTS recording_check_bindings (
        project_id TEXT NOT NULL, recording_id TEXT NOT NULL, manifest_id TEXT NOT NULL,
        source_manifest_id TEXT NOT NULL, source_manifest_hash TEXT NOT NULL,
        input_case_version_id TEXT NOT NULL, bindings_json TEXT NOT NULL, binding_hash TEXT NOT NULL,
        body_hash TEXT NOT NULL, request_key TEXT NOT NULL, actor_id TEXT NOT NULL, created_at TEXT NOT NULL,
        PRIMARY KEY(project_id,manifest_id), UNIQUE(project_id,recording_id,request_key),
        FOREIGN KEY(project_id,recording_id) REFERENCES recordings(project_id,recording_id),
        FOREIGN KEY(project_id,manifest_id) REFERENCES recording_manifests(project_id,manifest_id),
        FOREIGN KEY(project_id,source_manifest_id) REFERENCES recording_manifests(project_id,manifest_id),
        FOREIGN KEY(project_id,input_case_version_id) REFERENCES case_versions(project_id,version_id)
    )""")
    connection.execute("""CREATE TRIGGER IF NOT EXISTS recording_check_binding_owner_insert
        BEFORE INSERT ON recording_check_bindings
        WHEN NOT EXISTS (
            SELECT 1 FROM recordings r
            JOIN recording_manifests m ON m.project_id=r.project_id AND m.recording_id=r.recording_id AND m.case_id=r.case_id
            JOIN recording_manifests s ON s.project_id=r.project_id AND s.recording_id=r.recording_id AND s.case_id=r.case_id
            JOIN case_versions v ON v.project_id=r.project_id AND v.version_id=r.input_case_version_id AND v.case_id=r.case_id
            WHERE r.project_id=NEW.project_id AND r.recording_id=NEW.recording_id
              AND m.manifest_id=NEW.manifest_id AND m.kind='package_rebuild'
              AND s.manifest_id=NEW.source_manifest_id AND m.prior_manifest_id=s.manifest_id
              AND s.body_hash=NEW.source_manifest_hash AND r.input_case_version_id=NEW.input_case_version_id
              AND m.action_mapping=s.action_mapping AND m.source_artifact_hashes=s.source_artifact_hashes
              AND m.input_version_hash=v.content_hash AND r.completion_status='completed'
              AND m.evidence_completeness='complete' AND s.evidence_completeness='complete'
        ) BEGIN SELECT RAISE(ABORT,'recording check binding source or owner differs'); END""")
    connection.execute("""CREATE TRIGGER IF NOT EXISTS recording_check_binding_no_update
        BEFORE UPDATE ON recording_check_bindings BEGIN SELECT RAISE(ABORT,'recording check binding is immutable'); END""")
    connection.execute("""CREATE TRIGGER IF NOT EXISTS recording_check_binding_no_delete
        BEFORE DELETE ON recording_check_bindings BEGIN SELECT RAISE(ABORT,'recording check binding is immutable'); END""")
