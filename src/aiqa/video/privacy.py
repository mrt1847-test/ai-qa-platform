"""Read the exact active device job's project and secret-reference policy."""
import json

def contexts(connection,native,worker):
    return connection.execute("""SELECT DISTINCT l.project_id,j.purpose,v.definition_json,v.settings_json
        FROM leases l JOIN physical_resource_keys k USING(physical_key_id)
        JOIN jobs j ON j.project_id=l.project_id AND j.job_id=l.job_id
        LEFT JOIN recordings r ON r.project_id=j.project_id AND r.recording_id=j.recording_id
        LEFT JOIN case_runs c ON c.project_id=j.project_id AND c.case_run_id=j.case_run_id
        LEFT JOIN case_versions v ON v.project_id=j.project_id
            AND v.version_id=COALESCE(r.input_case_version_id,c.case_version_id)
        WHERE k.native_id=? AND k.worker_id=? AND j.status IN ('preparing','running','finalizing','cancel_requested')""",(native,worker)).fetchall()

def sensitive(context):
    if context[1] not in {'recording','trial','regression'}:return False
    try:
        definition,settings=(json.loads(v) for v in context[2:4])
        if type(definition) is not dict or type(settings) is not dict:return True
        return any(type(d.get('secret_refs',{})) is not dict or bool(d.get('secret_refs')) for d in (definition,settings))
    except (ValueError,TypeError):return True

def incompatible(connection,native,project,worker):
    return any(str(c[0])!=str(project) or sensitive(c) for c in contexts(connection,native,worker))
