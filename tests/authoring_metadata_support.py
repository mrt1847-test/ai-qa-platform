"""Explicit available metadata for old recording fixtures; no OS key or model call."""
def seed_authoring_key_metadata(connection,project_id):
    rows=connection.execute("SELECT key_ref_id,key_revision,actor_id,created_at FROM binding_revisions WHERE project_id=? AND role='authoring'",(str(project_id),)).fetchall()
    for ref,revision,actor,created in rows:
        connection.execute("INSERT OR IGNORE INTO secret_refs (project_id,ref_id,revision,name,availability,created_at,actor_id) VALUES (?,?,?,'fixture authoring key','available',?,?)",(str(project_id),ref,revision,created,actor))
