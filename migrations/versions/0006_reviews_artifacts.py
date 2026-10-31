"""Review membership, approval events, and typed artifact protection."""


def apply(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS app_builds (
            project_id TEXT NOT NULL REFERENCES projects(project_id),
            build_id TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            PRIMARY KEY (project_id, build_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS backup_receipts (
            project_id TEXT NOT NULL REFERENCES projects(project_id),
            receipt_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (project_id, receipt_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS manual_retention_requests (
            project_id TEXT NOT NULL REFERENCES projects(project_id),
            request_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (project_id, request_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS reviews (
            project_id TEXT NOT NULL,
            review_id TEXT NOT NULL,
            case_id TEXT NOT NULL,
            case_version_id TEXT NOT NULL,
            version_hash TEXT NOT NULL,
            source_manifest_id TEXT,
            trial_case_run_id TEXT,
            evidence_set_hash TEXT NOT NULL,
            expected_current_approval_id TEXT,
            created_commit_seq INTEGER NOT NULL,
            PRIMARY KEY (project_id, review_id),
            FOREIGN KEY (project_id, case_id, case_version_id)
                REFERENCES case_versions(project_id, case_id, version_id),
            FOREIGN KEY (project_id, source_manifest_id)
                REFERENCES recording_manifests(project_id, manifest_id),
            FOREIGN KEY (project_id, trial_case_run_id)
                REFERENCES case_runs(project_id, case_run_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS artifact_refs (
            project_id TEXT NOT NULL,
            artifact_id TEXT NOT NULL,
            attempt_id TEXT,
            action_id TEXT,
            check_id TEXT,
            recording_id TEXT,
            review_id TEXT,
            build_id TEXT,
            export_id TEXT,
            package_id TEXT,
            healing_id TEXT,
            proposal_id TEXT,
            resource_observation_id TEXT,
            PRIMARY KEY (project_id, artifact_id),
            FOREIGN KEY (project_id, attempt_id, action_id)
                REFERENCES actions(project_id, attempt_id, action_id),
            FOREIGN KEY (project_id, attempt_id, check_id)
                REFERENCES check_results(project_id, attempt_id, check_id),
            FOREIGN KEY (project_id, recording_id) REFERENCES recordings(project_id, recording_id),
            FOREIGN KEY (project_id, review_id) REFERENCES reviews(project_id, review_id),
            FOREIGN KEY (project_id, build_id) REFERENCES app_builds(project_id, build_id),
            CHECK (
                (
                    (action_id IS NOT NULL)
                    + (check_id IS NOT NULL)
                    + (recording_id IS NOT NULL)
                    + (review_id IS NOT NULL)
                    + (build_id IS NOT NULL)
                    + (export_id IS NOT NULL)
                    + (package_id IS NOT NULL)
                    + (healing_id IS NOT NULL)
                    + (proposal_id IS NOT NULL)
                    + (resource_observation_id IS NOT NULL)
                ) = 1
                AND ((action_id IS NULL AND check_id IS NULL) OR attempt_id IS NOT NULL)
            )
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS review_evidence_entries (
            project_id TEXT NOT NULL,
            review_id TEXT NOT NULL,
            entry_id TEXT NOT NULL,
            owner_kind TEXT NOT NULL CHECK (owner_kind IN ('REC', 'ITEM')),
            owner_id TEXT NOT NULL,
            attempt_id TEXT NOT NULL,
            action_id TEXT NOT NULL,
            artifact_ref_id TEXT NOT NULL,
            role TEXT NOT NULL,
            expected_hash TEXT NOT NULL,
            evidence_digest TEXT NOT NULL,
            PRIMARY KEY (project_id, entry_id),
            UNIQUE (
                project_id, review_id, owner_kind, owner_id, attempt_id, action_id, artifact_ref_id
            ),
            FOREIGN KEY (project_id, review_id) REFERENCES reviews(project_id, review_id),
            FOREIGN KEY (project_id, attempt_id, action_id)
                REFERENCES actions(project_id, attempt_id, action_id),
            FOREIGN KEY (project_id, artifact_ref_id) REFERENCES artifact_refs(project_id, artifact_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS review_decisions (
            project_id TEXT NOT NULL,
            review_id TEXT NOT NULL,
            decision_id TEXT NOT NULL,
            state TEXT NOT NULL CHECK (state IN ('approved', 'rejected')),
            actor_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            reason TEXT NOT NULL,
            version_hash TEXT NOT NULL,
            PRIMARY KEY (project_id, decision_id),
            UNIQUE (project_id, review_id),
            FOREIGN KEY (project_id, review_id) REFERENCES reviews(project_id, review_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS approval_events (
            project_id TEXT NOT NULL,
            approval_id TEXT NOT NULL,
            case_id TEXT NOT NULL,
            case_version_id TEXT NOT NULL,
            review_id TEXT NOT NULL,
            event_kind TEXT NOT NULL CHECK (event_kind IN ('approved', 'rejected', 'revoked')),
            prior_approval_id TEXT,
            version_hash TEXT NOT NULL,
            evidence_set_hash TEXT NOT NULL,
            reason TEXT NOT NULL,
            PRIMARY KEY (project_id, approval_id),
            FOREIGN KEY (project_id, case_id, case_version_id)
                REFERENCES case_versions(project_id, case_id, version_id),
            FOREIGN KEY (project_id, review_id) REFERENCES reviews(project_id, review_id),
            FOREIGN KEY (project_id, prior_approval_id)
                REFERENCES approval_events(project_id, approval_id),
            CHECK (
                (event_kind IN ('approved', 'rejected') AND prior_approval_id IS NULL)
                OR (event_kind = 'revoked' AND prior_approval_id IS NOT NULL)
            )
        )
        """
    )
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS approval_events_one_revoke
        ON approval_events(project_id, prior_approval_id)
        WHERE event_kind = 'revoked'
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS artifact_provenance (
            project_id TEXT NOT NULL,
            provenance_id TEXT NOT NULL,
            artifact_id TEXT NOT NULL,
            source_note TEXT NOT NULL,
            PRIMARY KEY (project_id, provenance_id),
            FOREIGN KEY (project_id, artifact_id) REFERENCES artifact_refs(project_id, artifact_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS artifact_protections (
            project_id TEXT NOT NULL,
            protection_id TEXT NOT NULL,
            artifact_id TEXT NOT NULL,
            kind TEXT NOT NULL CHECK (kind IN ('review', 'approval', 'backup', 'build', 'manual')),
            backup_receipt_id TEXT,
            build_id TEXT,
            manual_request_id TEXT,
            PRIMARY KEY (project_id, protection_id),
            FOREIGN KEY (project_id, artifact_id) REFERENCES artifact_refs(project_id, artifact_id),
            FOREIGN KEY (project_id, backup_receipt_id)
                REFERENCES backup_receipts(project_id, receipt_id),
            FOREIGN KEY (project_id, build_id) REFERENCES app_builds(project_id, build_id),
            FOREIGN KEY (project_id, manual_request_id)
                REFERENCES manual_retention_requests(project_id, request_id),
            CHECK (
                (kind = 'backup' AND backup_receipt_id IS NOT NULL
                    AND build_id IS NULL AND manual_request_id IS NULL)
                OR (kind = 'build' AND build_id IS NOT NULL
                    AND backup_receipt_id IS NULL AND manual_request_id IS NULL)
                OR (kind = 'manual' AND manual_request_id IS NOT NULL
                    AND backup_receipt_id IS NULL AND build_id IS NULL)
                OR (kind IN ('review', 'approval')
                    AND backup_receipt_id IS NULL AND build_id IS NULL AND manual_request_id IS NULL)
            )
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS protection_releases (
            project_id TEXT NOT NULL,
            release_id TEXT NOT NULL,
            protection_id TEXT NOT NULL,
            released_at TEXT NOT NULL,
            PRIMARY KEY (project_id, release_id),
            UNIQUE (project_id, protection_id),
            FOREIGN KEY (project_id, protection_id)
                REFERENCES artifact_protections(project_id, protection_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS reviews_trial_same_case
        BEFORE INSERT ON reviews
        WHEN NEW.trial_case_run_id IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM case_runs
            WHERE project_id = NEW.project_id
              AND case_run_id = NEW.trial_case_run_id
              AND case_id = NEW.case_id
          )
        BEGIN
            SELECT RAISE(ABORT, 'trial item is outside the review case');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS review_evidence_same_owner
        BEFORE INSERT ON review_evidence_entries
        WHEN NOT EXISTS (
            SELECT 1
            FROM reviews
            JOIN actions
              ON actions.project_id = NEW.project_id
             AND actions.attempt_id = NEW.attempt_id
             AND actions.action_id = NEW.action_id
            JOIN attempts
              ON attempts.project_id = actions.project_id
             AND attempts.attempt_id = actions.attempt_id
            JOIN jobs
              ON jobs.project_id = attempts.project_id
             AND jobs.job_id = attempts.job_id
            WHERE reviews.project_id = NEW.project_id
              AND reviews.review_id = NEW.review_id
              AND (
                (
                    NEW.owner_kind = 'ITEM'
                    AND jobs.case_run_id = NEW.owner_id
                    AND reviews.case_id = (
                        SELECT case_id FROM case_runs
                        WHERE project_id = NEW.project_id AND case_run_id = NEW.owner_id
                    )
                )
                OR (
                    NEW.owner_kind = 'REC'
                    AND jobs.recording_id = NEW.owner_id
                    AND EXISTS (
                        SELECT 1 FROM recordings
                        WHERE project_id = NEW.project_id
                          AND recording_id = NEW.owner_id
                          AND case_id = reviews.case_id
                    )
                )
              )
        )
        BEGIN
            SELECT RAISE(ABORT, 'evidence owner is outside the review');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS approval_events_match_review
        BEFORE INSERT ON approval_events
        WHEN NOT EXISTS (
            SELECT 1 FROM reviews
            WHERE project_id = NEW.project_id
              AND review_id = NEW.review_id
              AND case_id = NEW.case_id
        )
        BEGIN
            SELECT RAISE(ABORT, 'approval review is outside the case');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS approval_events_revoke_target
        BEFORE INSERT ON approval_events
        WHEN NEW.event_kind = 'revoked'
          AND NOT EXISTS (
            SELECT 1 FROM approval_events
            WHERE project_id = NEW.project_id
              AND approval_id = NEW.prior_approval_id
              AND event_kind = 'approved'
              AND case_id = NEW.case_id
          )
        BEGIN
            SELECT RAISE(ABORT, 'revoke requires the approved event');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS automation_cases_approval_pointer
        BEFORE UPDATE OF current_approval_id ON automation_cases
        WHEN NEW.current_approval_id IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM approval_events
            WHERE project_id = NEW.project_id
              AND approval_id = NEW.current_approval_id
              AND case_id = NEW.case_id
              AND event_kind = 'approved'
          )
        BEGIN
            SELECT RAISE(ABORT, 'approval pointer is outside the case');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS protection_releases_manual_only
        BEFORE INSERT ON protection_releases
        WHEN NOT EXISTS (
            SELECT 1 FROM artifact_protections
            WHERE project_id = NEW.project_id
              AND protection_id = NEW.protection_id
              AND kind = 'manual'
        )
        BEGIN
            SELECT RAISE(ABORT, 'only a manual protection is released here');
        END
        """
    )
