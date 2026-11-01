"""Retain a case's exact immutable asset revision even after a newer one exists."""
import json


def fixed_revision_choices(connection, project, profiles, datasets, settings):
    profiles=list(profiles);datasets=list(datasets)
    environment=settings.get('environment_revision_id','')
    data=settings.get('data_revision_id','')
    if environment and not any(item['id']==environment for item in profiles):
        row=connection.execute('''SELECT r.environment_id,e.name,r.revision,r.body_json FROM environment_revisions r
            JOIN environments e ON e.project_id=r.project_id AND e.environment_id=r.environment_id
            WHERE r.project_id=? AND r.revision_id=?''',(str(project),environment)).fetchone()
        if row: profiles.append({'id':environment,'environment_id':str(row[0]),'name':str(row[1]),'revision':row[2],'profile':json.loads(row[3])})
    if data and not any(item['id']==data for item in datasets):
        row=connection.execute('''SELECT d.dataset_id,d.name,r.revision,r.body_json FROM dataset_versions r
            JOIN datasets d ON d.project_id=r.project_id AND d.dataset_id=r.dataset_id
            WHERE r.project_id=? AND r.version_id=?''',(str(project),data)).fetchone()
        if row:
            body=json.loads(row[3]);datasets.append({'id':data,'version_id':data,'dataset_id':str(row[0]),'name':str(row[1]),'revision':row[2],'rows':body.get('rows',[])})
    return profiles,datasets
