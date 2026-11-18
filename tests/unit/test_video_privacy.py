import sqlite3
from aiqa.video.privacy import contexts,sensitive,incompatible

def test_sensitive_references_and_unprovable_case_context_fail_closed():
    assert sensitive(('p','recording','{"secret_refs":{"account":{}}}','{}'))
    assert sensitive(('p','trial','{}','{"secret_refs":{"account":{}}}'))
    assert sensitive(('p','recording',None,None))
    assert not sensitive(('p','recording','{}','{}'))

def test_active_device_context_uses_exact_job_version_and_project():
    d=sqlite3.connect(':memory:')
    for sql in [
        'CREATE TABLE leases(project_id,job_id,physical_key_id)',
        'CREATE TABLE physical_resource_keys(physical_key_id,native_id,worker_id)',
        'CREATE TABLE jobs(project_id,job_id,purpose,recording_id,case_run_id,status)',
        'CREATE TABLE recordings(project_id,recording_id,input_case_version_id)',
        'CREATE TABLE case_runs(project_id,case_run_id,case_version_id)',
        'CREATE TABLE case_versions(project_id,version_id,definition_json,settings_json)',
    ]:d.execute(sql)
    d.execute("INSERT INTO physical_resource_keys VALUES('r','serial','pc')")
    d.execute("INSERT INTO recordings VALUES('p','rec','v1')")
    d.execute("INSERT INTO case_versions VALUES('p','v1','{}','{}')")
    d.execute("INSERT INTO case_versions VALUES('p','v2','{}','{\"secret_refs\":{\"account\":{}}}')")
    d.execute("INSERT INTO jobs VALUES('p','j','recording','rec',NULL,'preparing')")
    d.execute("INSERT INTO leases VALUES('p','j','r')")
    assert len(contexts(d,'serial','pc'))==1
    assert not incompatible(d,'serial','p','pc')
    assert incompatible(d,'serial','foreign','pc')
    assert not incompatible(d,'serial','foreign','other-pc')
    d.execute("UPDATE recordings SET input_case_version_id='v2'")
    assert incompatible(d,'serial','p','pc')
    d.execute("UPDATE jobs SET status='completed'")
    assert not incompatible(d,'serial','foreign','pc')
