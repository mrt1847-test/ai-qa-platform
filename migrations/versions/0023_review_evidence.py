"""Typed ready evidence, durable staging, and immutable object metadata."""


def apply(connection):
    for name, definition in (
        ('owner_kind', 'TEXT'), ('attempt_id', 'TEXT'), ('action_id', 'TEXT'),
        ('check_id', 'TEXT'), ('role', 'TEXT'), ('job_id', 'TEXT'), ('generation', 'INTEGER'),
    ):
        connection.execute(f'ALTER TABLE artifact_objects ADD COLUMN {name} {definition}')
    connection.execute('DROP INDEX artifact_objects_ready_hash')
    connection.execute("""CREATE UNIQUE INDEX artifact_objects_ready_identity ON artifact_objects(
        project_id, owner_kind, owner_id, attempt_id, COALESCE(action_id,''),
        COALESCE(check_id,''), role, media_type, content_hash) WHERE status='ready'""")
    connection.execute("""CREATE TABLE artifact_staging (
        project_id TEXT NOT NULL, artifact_id TEXT NOT NULL, object_key TEXT NOT NULL,
        identity TEXT NOT NULL, content_hash TEXT NOT NULL, byte_length INTEGER NOT NULL,
        PRIMARY KEY(project_id,artifact_id), UNIQUE(project_id,identity,content_hash),
        FOREIGN KEY(project_id) REFERENCES projects(project_id))""")
    connection.execute("""CREATE TABLE artifact_upload_requests (
        project_id TEXT NOT NULL, job_id TEXT NOT NULL, generation INTEGER NOT NULL,
        worker_id TEXT NOT NULL, request_key TEXT NOT NULL, body_hash TEXT NOT NULL,
        response_body TEXT, created_at TEXT NOT NULL,
        PRIMARY KEY(project_id,job_id,generation,worker_id,request_key),
        FOREIGN KEY(project_id,job_id) REFERENCES jobs(project_id,job_id))""")
    owner_rule = """NEW.owner_kind IS NULL OR NEW.owner_kind NOT IN ('REC','ITEM') OR NEW.role IS NULL
        OR NOT EXISTS (
          SELECT 1 FROM jobs j JOIN attempts a USING(project_id,job_id)
          WHERE j.project_id=NEW.project_id AND j.job_id=NEW.job_id
            AND a.attempt_id=NEW.attempt_id AND a.generation=NEW.generation
            AND ((NEW.owner_kind='REC' AND j.recording_id=NEW.owner_id)
              OR (NEW.owner_kind='ITEM' AND j.case_run_id=NEW.owner_id)))
        OR NOT EXISTS (
          SELECT 1 FROM artifact_refs r WHERE r.project_id=NEW.project_id AND r.artifact_id=NEW.artifact_id
          AND ((NEW.action_id IS NOT NULL AND NEW.check_id IS NULL AND r.action_id=NEW.action_id AND r.attempt_id=NEW.attempt_id)
            OR (NEW.check_id IS NOT NULL AND NEW.action_id IS NULL AND r.check_id=NEW.check_id AND r.attempt_id=NEW.attempt_id)
            OR (NEW.action_id IS NULL AND NEW.check_id IS NULL AND NEW.owner_kind='REC' AND r.recording_id=NEW.owner_id)))
        OR NEW.role NOT IN ('before','after','log','check','source')
        OR (NEW.role IN ('before','after') AND NEW.action_id IS NULL)
        OR (NEW.role='check' AND NEW.check_id IS NULL)
        OR ((NEW.action_id IS NOT NULL OR NEW.check_id IS NOT NULL) AND NOT EXISTS (
          SELECT 1 FROM actions a
          LEFT JOIN check_results c ON c.project_id=a.project_id AND c.attempt_id=a.attempt_id AND c.action_id=a.action_id
          JOIN jobs j ON j.project_id=a.project_id AND j.job_id=NEW.job_id
          LEFT JOIN recordings r ON r.project_id=j.project_id AND r.recording_id=j.recording_id
          LEFT JOIN case_runs i ON i.project_id=j.project_id AND i.case_run_id=j.case_run_id
          WHERE a.project_id=NEW.project_id AND a.attempt_id=NEW.attempt_id
          AND ((NEW.action_id IS NOT NULL AND a.action_id=NEW.action_id)
            OR (NEW.check_id IS NOT NULL AND c.check_id=NEW.check_id))
          AND ((NEW.owner_kind='REC' AND a.case_id=r.case_id AND a.case_version_id=r.input_case_version_id)
            OR (NEW.owner_kind='ITEM' AND a.case_id=i.case_id AND a.case_version_id=i.case_version_id))))
    """
    connection.execute(f"""CREATE TRIGGER artifact_ready_requires_typed_owner
        BEFORE INSERT ON artifact_objects WHEN NEW.status='ready' AND ({owner_rule})
        BEGIN SELECT RAISE(ABORT,'ready evidence requires exact typed ownership'); END""")
    connection.execute("""CREATE TRIGGER artifact_objects_content_immutable
        BEFORE UPDATE OF project_id,artifact_id,object_key,content_hash,byte_length,media_type,owner_id,owner_kind,
                         attempt_id,action_id,check_id,role,job_id,generation,status,acked
        ON artifact_objects WHEN OLD.status='ready'
        BEGIN SELECT RAISE(ABORT,'ready evidence metadata is immutable'); END""")
    connection.execute("""CREATE TRIGGER artifact_objects_no_promotion
        BEFORE UPDATE ON artifact_objects WHEN OLD.status<>'ready' AND (NEW.status='ready' OR NEW.acked=1)
        BEGIN SELECT RAISE(ABORT,'ready evidence must be created atomically with provenance'); END""")
    connection.execute("""CREATE TRIGGER artifact_objects_no_delete
        BEFORE DELETE ON artifact_objects WHEN OLD.status='ready'
        BEGIN SELECT RAISE(ABORT,'ready evidence metadata is immutable'); END""")
    connection.execute("""CREATE TRIGGER artifact_refs_no_update
        BEFORE UPDATE ON artifact_refs BEGIN SELECT RAISE(ABORT,'evidence provenance is immutable'); END""")
    connection.execute("""CREATE TRIGGER artifact_refs_no_delete
        BEFORE DELETE ON artifact_refs BEGIN SELECT RAISE(ABORT,'evidence provenance is immutable'); END""")
    for operation in ('UPDATE', 'DELETE'):
        connection.execute(f"""CREATE TRIGGER review_manifest_no_{operation.lower()}
            BEFORE {operation} ON recording_manifests
            BEGIN SELECT RAISE(ABORT,'sealed source manifest is immutable'); END""")
