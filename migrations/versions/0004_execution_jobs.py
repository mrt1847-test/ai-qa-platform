"""RUN, ITEM, job, lease, and attempt owners. Suite rows exist for the execution FK."""


def apply(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS suites (
            project_id TEXT NOT NULL REFERENCES projects(project_id),
            suite_id TEXT NOT NULL,
            name TEXT NOT NULL,
            PRIMARY KEY (project_id, suite_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS suite_versions (
            project_id TEXT NOT NULL,
            suite_id TEXT NOT NULL,
            suite_version_id TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            PRIMARY KEY (project_id, suite_version_id),
            UNIQUE (project_id, suite_id, suite_version_id),
            FOREIGN KEY (project_id, suite_id) REFERENCES suites(project_id, suite_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS suite_entries (
            project_id TEXT NOT NULL,
            suite_version_id TEXT NOT NULL,
            entry_id TEXT NOT NULL,
            position INTEGER NOT NULL,
            PRIMARY KEY (project_id, suite_version_id, entry_id),
            FOREIGN KEY (project_id, suite_version_id)
                REFERENCES suite_versions(project_id, suite_version_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS executions (
            project_id TEXT NOT NULL REFERENCES projects(project_id),
            execution_id TEXT NOT NULL,
            name TEXT NOT NULL,
            purpose TEXT NOT NULL CHECK (purpose IN ('trial', 'regression', 'reverification')),
            source TEXT NOT NULL CHECK (source IN ('single', 'selection', 'suite', 'rerun')),
            suite_version_id TEXT,
            scope_requested_at TEXT NOT NULL,
            PRIMARY KEY (project_id, execution_id),
            FOREIGN KEY (project_id, suite_version_id)
                REFERENCES suite_versions(project_id, suite_version_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS case_runs (
            project_id TEXT NOT NULL,
            execution_id TEXT NOT NULL,
            case_run_id TEXT NOT NULL,
            case_id TEXT NOT NULL,
            case_version_id TEXT NOT NULL,
            purpose TEXT NOT NULL CHECK (purpose IN ('trial', 'regression', 'reverification')),
            requested_at TEXT NOT NULL,
            PRIMARY KEY (project_id, case_run_id),
            UNIQUE (project_id, execution_id, case_run_id),
            FOREIGN KEY (project_id, execution_id) REFERENCES executions(project_id, execution_id),
            FOREIGN KEY (project_id, case_id, case_version_id)
                REFERENCES case_versions(project_id, case_id, version_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            project_id TEXT NOT NULL REFERENCES projects(project_id),
            job_id TEXT NOT NULL,
            purpose TEXT NOT NULL CHECK (purpose IN (
                'recording', 'trial', 'regression', 'structure', 'app_inspect', 'app_install',
                'resource_probe', 'model_check', 'export', 'evidence_sync', 'package_rebuild', 'backup'
            )),
            recording_id TEXT,
            case_run_id TEXT,
            payload_hash TEXT NOT NULL,
            source_refs TEXT NOT NULL,
            limits TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN (
                'queued', 'preparing', 'running', 'finalizing', 'completed',
                'cancel_requested', 'cancelled', 'error', 'lost'
            )),
            PRIMARY KEY (project_id, job_id),
            FOREIGN KEY (project_id, recording_id) REFERENCES recordings(project_id, recording_id),
            FOREIGN KEY (project_id, case_run_id) REFERENCES case_runs(project_id, case_run_id),
            CHECK (
                (
                    purpose = 'recording'
                    AND recording_id IS NOT NULL
                    AND case_run_id IS NULL
                )
                OR (
                    purpose IN ('trial', 'regression')
                    AND recording_id IS NULL
                    AND case_run_id IS NOT NULL
                )
                OR (
                    purpose IN (
                        'structure', 'app_inspect', 'app_install', 'resource_probe', 'model_check',
                        'export', 'evidence_sync', 'package_rebuild', 'backup'
                    )
                    AND recording_id IS NULL
                    AND case_run_id IS NULL
                    AND source_refs <> '[]'
                )
            )
        )
        """
    )
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS jobs_recording_owner
        ON jobs(project_id, recording_id)
        WHERE recording_id IS NOT NULL
        """
    )
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS jobs_case_run_owner
        ON jobs(project_id, case_run_id)
        WHERE case_run_id IS NOT NULL
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS leases (
            project_id TEXT NOT NULL,
            job_id TEXT NOT NULL,
            generation INTEGER NOT NULL,
            worker_id TEXT NOT NULL,
            physical_key_id TEXT,
            expires_at TEXT NOT NULL,
            PRIMARY KEY (project_id, job_id, generation),
            FOREIGN KEY (project_id, job_id) REFERENCES jobs(project_id, job_id),
            FOREIGN KEY (physical_key_id) REFERENCES physical_resource_keys(physical_key_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS attempts (
            project_id TEXT NOT NULL,
            attempt_id TEXT NOT NULL,
            job_id TEXT NOT NULL,
            generation INTEGER NOT NULL,
            physical_key_id TEXT,
            PRIMARY KEY (project_id, attempt_id),
            UNIQUE (project_id, job_id, generation),
            FOREIGN KEY (project_id, job_id) REFERENCES jobs(project_id, job_id),
            FOREIGN KEY (physical_key_id) REFERENCES physical_resource_keys(physical_key_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS executions_suite_ref
        BEFORE INSERT ON executions
        WHEN (NEW.source = 'suite' AND NEW.suite_version_id IS NULL)
          OR (NEW.source <> 'suite' AND NEW.suite_version_id IS NOT NULL)
        BEGIN
            SELECT RAISE(ABORT, 'suite version belongs only to a suite execution');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS case_runs_match_execution
        BEFORE INSERT ON case_runs
        WHEN NOT EXISTS (
            SELECT 1 FROM executions
            WHERE project_id = NEW.project_id
              AND execution_id = NEW.execution_id
              AND purpose = NEW.purpose
              AND scope_requested_at = NEW.requested_at
        )
        BEGIN
            SELECT RAISE(ABORT, 'item scope does not match the execution');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS jobs_match_execution_purpose
        BEFORE INSERT ON jobs
        WHEN NEW.purpose IN ('trial', 'regression')
          AND NOT EXISTS (
            SELECT 1
            FROM case_runs AS runs
            JOIN executions AS runs_exec
              ON runs_exec.project_id = runs.project_id
             AND runs_exec.execution_id = runs.execution_id
            WHERE runs.project_id = NEW.project_id
              AND runs.case_run_id = NEW.case_run_id
              AND runs.requested_at = runs_exec.scope_requested_at
              AND runs.purpose = runs_exec.purpose
              AND (
                (NEW.purpose = 'trial' AND runs_exec.purpose = 'trial')
                OR (
                    NEW.purpose = 'regression'
                    AND runs_exec.purpose IN ('regression', 'reverification')
                )
              )
          )
        BEGIN
            SELECT RAISE(ABORT, 'job purpose does not match the item execution');
        END
        """
    )
