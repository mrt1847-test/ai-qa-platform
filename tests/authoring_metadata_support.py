"""Explicit available metadata for old recording fixtures; no OS key or model call."""
def seed_authoring_key_metadata(connection,project_id):
    rows=connection.execute("SELECT key_ref_id,key_revision,actor_id,created_at FROM binding_revisions WHERE project_id=? AND role='authoring'",(str(project_id),)).fetchall()
    for ref,revision,actor,created in rows:
        connection.execute("INSERT OR IGNORE INTO secret_refs (project_id,ref_id,revision,name,availability,created_at,actor_id) VALUES (?,?,?,'fixture authoring key','available',?,?)",(str(project_id),ref,revision,created,actor))


def seed_recording_capability(connection,project_id,physical_key_id,*,mode='fixture'):
    """Explicit authenticated fixture report for component fixtures, no model/device I/O."""
    import json
    from uuid import UUID,uuid4
    from datetime import datetime,timezone
    from aiqa.store.models import WorkerScope
    from aiqa.worker.presence import get_presence
    from aiqa.recording.mobile_agent_admission import authenticated_authoring_permissions
    worker=connection.execute('SELECT worker_id FROM physical_resource_keys WHERE physical_key_id=?',(str(physical_key_id),)).fetchone()[0]
    token=connection.execute("""SELECT t.token_id FROM worker_tokens t JOIN worker_enrollments e USING(enrollment_id)
        WHERE e.project_id=? AND e.worker_id=? AND t.purpose='recording' AND t.expires_at IS NULL LIMIT 1""",(str(project_id),worker)).fetchone()
    if token is None:
        enrollment=connection.execute('SELECT enrollment_id FROM worker_enrollments WHERE project_id=? AND worker_id=? LIMIT 1',(str(project_id),worker)).fetchone()[0]
        token=(str(uuid4()),)
        connection.execute("INSERT INTO worker_tokens(token_id,enrollment_id,token_hash,purpose,created_at) VALUES(?,?,?,'recording',?)",(token[0],enrollment,str(uuid4()),datetime.now(timezone.utc).isoformat()))
    presence=get_presence(connection,worker,datetime.now(timezone.utc),project_id=project_id)
    permissions={'authoring_mode':mode,'authoring_engine_boot_id':presence.boot_id,'authoring_engine_session_id':presence.session_id}
    if mode=='original':
        from aiqa.contracts.mobile_agent_engine import mobile_agent_engine_ref
        permissions['authoring_engine']=mobile_agent_engine_ref()
    raw=authenticated_authoring_permissions(connection,WorkerScope(worker,(UUID(str(project_id)),),('recording',),token[0]),json.dumps(permissions),target_kind='android')
    connection.execute('UPDATE resource_inventory SET permissions=? WHERE physical_key_id=?',(raw,str(physical_key_id)))
