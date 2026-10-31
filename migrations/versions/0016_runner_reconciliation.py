"""Runner boot identity, restart reconciliation, and resource quarantine."""


def apply(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS runner_hosts (
            project_id TEXT NOT NULL,
            attempt_id TEXT NOT NULL,
            boot_id TEXT NOT NULL,
            PRIMARY KEY (project_id, attempt_id),
            FOREIGN KEY (project_id, attempt_id) REFERENCES attempts(project_id, attempt_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS resource_quarantine (
            physical_key_id TEXT PRIMARY KEY
                REFERENCES physical_resource_keys(physical_key_id),
            reason TEXT NOT NULL CHECK (reason IN ('expired', 'restarted', 'dead_runner')),
            quarantined_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS job_reconciliations (
            project_id TEXT NOT NULL,
            job_id TEXT NOT NULL,
            generation INTEGER NOT NULL,
            outcome TEXT NOT NULL CHECK (outcome IN ('continued', 'lost')),
            reason TEXT NOT NULL CHECK (
                reason IN ('live', 'dead_runner', 'restarted', 'expired', 'watchdog')
            ),
            reconciled_at TEXT NOT NULL,
            PRIMARY KEY (project_id, job_id, generation),
            FOREIGN KEY (project_id, job_id) REFERENCES jobs(project_id, job_id)
        )
        """
    )
