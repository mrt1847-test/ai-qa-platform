"""Remember outstanding producer stop fences; never persist video pixels."""
def apply(connection):
    connection.execute("""CREATE TABLE IF NOT EXISTS live_video_publishers (
        session_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, resource_id TEXT NOT NULL,
        actor_id TEXT NOT NULL, worker_id TEXT NOT NULL, native_id TEXT NOT NULL,
        producer_id TEXT NOT NULL, closed INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY(project_id) REFERENCES projects(project_id)
    )""")
