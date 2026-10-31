"""Query indexes for case lists, queues, trends, checks, and long-term facts."""


def apply(connection):
    statements = (
        """
        CREATE INDEX IF NOT EXISTS automation_cases_archive
        ON automation_cases(project_id, archived_at, case_id)
        """,
        """
        CREATE INDEX IF NOT EXISTS jobs_queue
        ON jobs(project_id, status, job_id)
        """,
        """
        CREATE INDEX IF NOT EXISTS case_runs_requested
        ON case_runs(project_id, requested_at, case_run_id)
        """,
        """
        CREATE INDEX IF NOT EXISTS case_runs_case_requested
        ON case_runs(project_id, case_id, requested_at, case_run_id)
        """,
        """
        CREATE INDEX IF NOT EXISTS check_results_status
        ON check_results(project_id, check_id, status, attempt_id)
        """,
        """
        CREATE INDEX IF NOT EXISTS artifact_protections_artifact
        ON artifact_protections(project_id, artifact_id)
        """,
        """
        CREATE INDEX IF NOT EXISTS item_finalizations_seq
        ON item_finalizations(project_id, finalized_seq)
        """,
        """
        CREATE INDEX IF NOT EXISTS item_lifecycle_seq
        ON item_lifecycle_events(project_id, commit_seq)
        """,
        """
        CREATE INDEX IF NOT EXISTS usage_adjustments_seq
        ON usage_adjustments(project_id, commit_seq)
        """,
        """
        CREATE INDEX IF NOT EXISTS approval_events_case
        ON approval_events(project_id, case_id, case_version_id)
        """,
        """
        CREATE INDEX IF NOT EXISTS leases_resource
        ON leases(physical_key_id, generation)
        WHERE physical_key_id IS NOT NULL
        """,
    )
    for statement in statements:
        connection.execute(statement)
