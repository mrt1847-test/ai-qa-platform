"""Read-only resource probe captures. They are not recording after images."""


def apply(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS resource_observations (
            project_id TEXT NOT NULL,
            resource_id TEXT NOT NULL,
            probe_job_id TEXT NOT NULL,
            attempt_id TEXT NOT NULL,
            captured_at TEXT NOT NULL,
            geometry TEXT NOT NULL,
            artifact_id TEXT NOT NULL,
            scope_hash TEXT NOT NULL,
            PRIMARY KEY (project_id, artifact_id),
            FOREIGN KEY (project_id, resource_id)
                REFERENCES resource_aliases(project_id, physical_key_id),
            FOREIGN KEY (project_id, probe_job_id) REFERENCES jobs(project_id, job_id),
            FOREIGN KEY (project_id, attempt_id) REFERENCES attempts(project_id, attempt_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS resource_observations_match_lease
        BEFORE INSERT ON resource_observations
        WHEN NOT EXISTS (
            SELECT 1
            FROM attempts
            JOIN jobs
              ON jobs.project_id = attempts.project_id
             AND jobs.job_id = attempts.job_id
            JOIN leases
              ON leases.project_id = attempts.project_id
             AND leases.job_id = attempts.job_id
             AND leases.generation = attempts.generation
            WHERE attempts.project_id = NEW.project_id
              AND attempts.attempt_id = NEW.attempt_id
              AND jobs.job_id = NEW.probe_job_id
              AND jobs.purpose = 'resource_probe'
              AND leases.physical_key_id = NEW.resource_id
              AND attempts.physical_key_id = NEW.resource_id
        )
        BEGIN
            SELECT RAISE(ABORT, 'observation does not match the probe lease');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS resource_observations_immutable
        BEFORE UPDATE ON resource_observations
        BEGIN
            SELECT RAISE(ABORT, 'resource observation is append-only');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS artifact_refs_observation_owner
        BEFORE INSERT ON artifact_refs
        WHEN NEW.resource_observation_id IS NOT NULL
          AND (
            NEW.artifact_id <> NEW.resource_observation_id
            OR NEW.attempt_id IS NULL
            OR NOT EXISTS (
                SELECT 1 FROM resource_observations
                WHERE project_id = NEW.project_id
                  AND artifact_id = NEW.resource_observation_id
                  AND attempt_id = NEW.attempt_id
            )
          )
        BEGIN
            SELECT RAISE(ABORT, 'observation owner does not match the capture');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS artifact_refs_probe_not_recording_after
        BEFORE INSERT ON artifact_refs
        WHEN NEW.recording_id IS NOT NULL
          AND EXISTS (
            SELECT 1 FROM resource_observations
            WHERE project_id = NEW.project_id AND artifact_id = NEW.artifact_id
          )
        BEGIN
            SELECT RAISE(ABORT, 'probe capture is not a recording after image');
        END
        """
    )
