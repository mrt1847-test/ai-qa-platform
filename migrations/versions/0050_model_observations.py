"""Immutable visual observation identity, referencing existing durable REC evidence."""
def apply(connection):
    connection.execute("""CREATE TABLE IF NOT EXISTS model_observations (
        project_id TEXT NOT NULL, observation_id TEXT NOT NULL, attempt_id TEXT NOT NULL,
        call_id TEXT NOT NULL, request_key TEXT NOT NULL, worker_id TEXT NOT NULL,
        request_hash TEXT NOT NULL, model_fingerprint TEXT NOT NULL, policy_ref TEXT NOT NULL,
        artifact_id TEXT NOT NULL, image_hash TEXT NOT NULL, geometry_hash TEXT NOT NULL,
        geometry_json TEXT NOT NULL, source_observation_id TEXT NOT NULL,
        captured_at TEXT NOT NULL, created_at TEXT NOT NULL,
        PRIMARY KEY(project_id,observation_id), UNIQUE(project_id,attempt_id,request_key),
        UNIQUE(project_id,call_id),
        FOREIGN KEY(project_id,attempt_id) REFERENCES attempts(project_id,attempt_id),
        FOREIGN KEY(project_id,artifact_id) REFERENCES artifact_objects(project_id,artifact_id)
    )""")
    connection.execute("""CREATE TRIGGER IF NOT EXISTS model_observation_no_update
        BEFORE UPDATE ON model_observations BEGIN SELECT RAISE(ABORT,'model observation is immutable'); END""")
    connection.execute("""CREATE TRIGGER IF NOT EXISTS model_observation_no_delete
        BEFORE DELETE ON model_observations BEGIN SELECT RAISE(ABORT,'model observation is immutable'); END""")
