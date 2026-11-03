"""Track authenticated worker sessions separately from device observations."""


def apply(connection):
    connection.execute("""
        CREATE TABLE worker_presence (
            project_id TEXT NOT NULL REFERENCES projects(project_id),
            worker_id TEXT NOT NULL,
            token_id TEXT NOT NULL REFERENCES worker_tokens(token_id) ON DELETE CASCADE,
            boot_id TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            session_id TEXT NOT NULL,
            PRIMARY KEY (project_id, worker_id)
        )
    """)
    connection.execute("""
        CREATE TABLE worker_retired_boots (
            project_id TEXT NOT NULL REFERENCES projects(project_id),
            worker_id TEXT NOT NULL,
            boot_id TEXT NOT NULL,
            token_id TEXT NOT NULL REFERENCES worker_tokens(token_id) ON DELETE CASCADE,
            PRIMARY KEY (project_id, worker_id, boot_id)
        )
    """)
    connection.execute("""
        CREATE TABLE job_worker_sessions (
            project_id TEXT NOT NULL,
            job_id TEXT NOT NULL,
            worker_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            PRIMARY KEY (project_id, job_id, worker_id),
            FOREIGN KEY (project_id, job_id) REFERENCES jobs(project_id, job_id) ON DELETE CASCADE
        )
    """)
    connection.execute("""
        CREATE TRIGGER jobs_pin_worker_session AFTER INSERT ON jobs
        WHEN NEW.status = 'queued'
          AND NEW.purpose IN ('recording','trial','regression','resource_probe','app_install')
        BEGIN
            INSERT INTO job_worker_sessions (project_id, job_id, worker_id, session_id)
            SELECT DISTINCT NEW.project_id, NEW.job_id, presence.worker_id, presence.session_id
            FROM json_each(
                CASE
                    WHEN NEW.purpose IN ('trial', 'regression')
                        AND json_type(
                            CASE WHEN json_valid(NEW.limits) THEN NEW.limits ELSE '{}' END, '$.resource_id'
                        ) = 'text'
                    THEN json_array(json_extract(NEW.limits, '$.resource_id'))
                    WHEN json_valid(NEW.source_refs) THEN NEW.source_refs
                    ELSE '[]'
                END
            ) AS ref
            JOIN resource_aliases AS alias
              ON alias.project_id = NEW.project_id AND alias.physical_key_id = ref.value
            JOIN physical_resource_keys AS resource ON resource.physical_key_id = alias.physical_key_id
            JOIN worker_presence AS presence
              ON presence.project_id = NEW.project_id AND presence.worker_id = resource.worker_id;
        END
    """)
