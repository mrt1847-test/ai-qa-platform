"""Item finalization, lifecycle, fingerprint, and append-only usage ledger."""


def apply(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS item_finalizations (
            project_id TEXT NOT NULL,
            case_run_id TEXT NOT NULL,
            created_seq INTEGER NOT NULL,
            finalized_seq INTEGER NOT NULL,
            release_label TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            core_result TEXT NOT NULL CHECK (core_result IN (
                'PASS', 'FAIL', 'BLOCKED', 'INCONCLUSIVE', 'SKIPPED', 'CANCELLED', 'NOT_RUN'
            )),
            denominator INTEGER NOT NULL CHECK (denominator IN (0, 1)),
            PRIMARY KEY (project_id, case_run_id),
            FOREIGN KEY (project_id, case_run_id) REFERENCES case_runs(project_id, case_run_id),
            CHECK (created_seq <= finalized_seq)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS item_lifecycle_events (
            project_id TEXT NOT NULL,
            event_id TEXT NOT NULL,
            case_run_id TEXT NOT NULL,
            commit_seq INTEGER NOT NULL,
            kind TEXT NOT NULL CHECK (kind IN ('created', 'finalized')),
            PRIMARY KEY (project_id, event_id),
            UNIQUE (project_id, case_run_id, kind),
            UNIQUE (project_id, case_run_id, commit_seq),
            FOREIGN KEY (project_id, case_run_id) REFERENCES case_runs(project_id, case_run_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS item_usage_facts (
            project_id TEXT NOT NULL,
            usage_id TEXT NOT NULL,
            case_run_id TEXT NOT NULL,
            commit_seq INTEGER NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('authoring', 'verification', 'healing', 'maintenance')),
            measurement_status TEXT NOT NULL CHECK (measurement_status IN (
                'measured', 'estimated', 'unreported', 'not_used', 'unknown'
            )),
            amount TEXT,
            currency TEXT,
            PRIMARY KEY (project_id, usage_id),
            FOREIGN KEY (project_id, case_run_id) REFERENCES case_runs(project_id, case_run_id),
            CHECK (
                (
                    measurement_status IN ('not_used', 'unknown', 'unreported')
                    AND amount IS NULL
                    AND currency IS NULL
                )
                OR (
                    measurement_status IN ('measured', 'estimated')
                    AND amount IS NOT NULL
                    AND currency IS NOT NULL
                )
            )
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS usage_adjustments (
            project_id TEXT NOT NULL,
            adjustment_id TEXT NOT NULL,
            case_run_id TEXT NOT NULL,
            commit_seq INTEGER NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('authoring', 'verification', 'healing', 'maintenance')),
            measurement_status TEXT NOT NULL CHECK (measurement_status IN (
                'measured', 'estimated', 'unreported', 'not_used', 'unknown'
            )),
            amount TEXT,
            currency TEXT,
            PRIMARY KEY (project_id, adjustment_id),
            UNIQUE (project_id, case_run_id, commit_seq, role),
            FOREIGN KEY (project_id, case_run_id) REFERENCES case_runs(project_id, case_run_id),
            CHECK (
                (
                    measurement_status IN ('not_used', 'unknown', 'unreported')
                    AND amount IS NULL
                    AND currency IS NULL
                )
                OR (
                    measurement_status IN ('measured', 'estimated')
                    AND amount IS NOT NULL
                    AND currency IS NOT NULL
                )
            )
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS fingerprint_observations (
            project_id TEXT NOT NULL,
            observation_id TEXT NOT NULL,
            case_run_id TEXT NOT NULL,
            case_id TEXT NOT NULL,
            commit_seq INTEGER NOT NULL,
            verification_digest TEXT NOT NULL,
            target_kind TEXT NOT NULL,
            env_profile_revision TEXT NOT NULL,
            data_fingerprint TEXT NOT NULL,
            oracle_policy TEXT NOT NULL,
            schema_version TEXT NOT NULL,
            PRIMARY KEY (project_id, observation_id),
            FOREIGN KEY (project_id, case_run_id) REFERENCES case_runs(project_id, case_run_id),
            FOREIGN KEY (project_id, case_id) REFERENCES automation_cases(project_id, case_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS analysis_records (
            project_id TEXT NOT NULL,
            record_id TEXT NOT NULL,
            case_run_id TEXT NOT NULL,
            commit_seq INTEGER NOT NULL,
            body TEXT NOT NULL,
            PRIMARY KEY (project_id, record_id),
            FOREIGN KEY (project_id, case_run_id) REFERENCES case_runs(project_id, case_run_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS item_finalizations_immutable
        BEFORE UPDATE ON item_finalizations
        BEGIN
            SELECT RAISE(ABORT, 'item finalization is immutable');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS item_lifecycle_events_immutable
        BEFORE UPDATE ON item_lifecycle_events
        BEGIN
            SELECT RAISE(ABORT, 'lifecycle event is append-only');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS item_usage_facts_immutable
        BEFORE UPDATE ON item_usage_facts
        BEGIN
            SELECT RAISE(ABORT, 'usage fact is immutable');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS usage_adjustments_immutable
        BEFORE UPDATE ON usage_adjustments
        BEGIN
            SELECT RAISE(ABORT, 'usage adjustment is append-only');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS analysis_records_immutable
        BEFORE UPDATE ON analysis_records
        BEGIN
            SELECT RAISE(ABORT, 'analysis record is append-only');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS fingerprint_observations_same_case
        BEFORE INSERT ON fingerprint_observations
        WHEN NOT EXISTS (
            SELECT 1 FROM case_runs
            WHERE project_id = NEW.project_id
              AND case_run_id = NEW.case_run_id
              AND case_id = NEW.case_id
        )
        BEGIN
            SELECT RAISE(ABORT, 'fingerprint case does not match the item');
        END
        """
    )
