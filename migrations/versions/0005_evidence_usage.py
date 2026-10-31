"""Action, check, event, dispatch journal, and nullable model usage facts."""


def apply(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS actions (
            project_id TEXT NOT NULL,
            attempt_id TEXT NOT NULL,
            action_seq INTEGER NOT NULL,
            step_id TEXT NOT NULL,
            action_id TEXT NOT NULL,
            package_step_id TEXT,
            proposal_hash TEXT NOT NULL,
            dispatch_state TEXT NOT NULL CHECK (dispatch_state IN (
                'planned', 'lookup_failed', 'dispatch_started', 'acknowledged', 'observed', 'unknown'
            )),
            case_id TEXT NOT NULL,
            case_version_id TEXT NOT NULL,
            outcome_known INTEGER NOT NULL CHECK (outcome_known IN (0, 1)),
            PRIMARY KEY (project_id, attempt_id, action_seq),
            UNIQUE (project_id, attempt_id, action_id),
            FOREIGN KEY (project_id, attempt_id) REFERENCES attempts(project_id, attempt_id),
            FOREIGN KEY (project_id, case_id, case_version_id)
                REFERENCES case_versions(project_id, case_id, version_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS check_results (
            project_id TEXT NOT NULL,
            attempt_id TEXT NOT NULL,
            action_id TEXT NOT NULL,
            check_id TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('satisfied', 'violated', 'unknown', 'not_run')),
            method TEXT NOT NULL CHECK (method IN (
                'deterministic', 'ai_visual', 'deterministic_then_ai_unknown'
            )),
            expected_snapshot TEXT NOT NULL,
            sanitized_observed TEXT NOT NULL,
            reason TEXT NOT NULL,
            artifact_refs TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            PRIMARY KEY (project_id, attempt_id, check_id),
            FOREIGN KEY (project_id, attempt_id, action_id)
                REFERENCES actions(project_id, attempt_id, action_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS dispatch_journal (
            project_id TEXT NOT NULL,
            attempt_id TEXT NOT NULL,
            action_seq INTEGER NOT NULL,
            entry_seq INTEGER NOT NULL,
            dispatch_state TEXT NOT NULL CHECK (dispatch_state IN (
                'planned', 'lookup_failed', 'dispatch_started', 'acknowledged', 'observed', 'unknown'
            )),
            recorded_at TEXT NOT NULL,
            PRIMARY KEY (project_id, attempt_id, action_seq, entry_seq),
            FOREIGN KEY (project_id, attempt_id, action_seq)
                REFERENCES actions(project_id, attempt_id, action_seq)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS attempt_events (
            project_id TEXT NOT NULL,
            event_id TEXT NOT NULL,
            attempt_id TEXT NOT NULL,
            local_seq INTEGER NOT NULL,
            captured_at TEXT NOT NULL,
            event_type TEXT NOT NULL,
            minimum_facts TEXT NOT NULL,
            payload_hash TEXT NOT NULL,
            body_hash TEXT NOT NULL,
            detail_payload TEXT,
            sealed INTEGER NOT NULL DEFAULT 0 CHECK (sealed IN (0, 1)),
            PRIMARY KEY (project_id, event_id),
            UNIQUE (project_id, attempt_id, local_seq),
            FOREIGN KEY (project_id, attempt_id) REFERENCES attempts(project_id, attempt_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS model_call_facts (
            project_id TEXT NOT NULL,
            call_id TEXT NOT NULL,
            attempt_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('authoring', 'verification', 'healing', 'maintenance')),
            action_id TEXT,
            check_id TEXT,
            measurement_status TEXT NOT NULL CHECK (measurement_status IN (
                'measured', 'estimated', 'unreported', 'not_used', 'unknown'
            )),
            input_tokens INTEGER,
            output_tokens INTEGER,
            cache_tokens INTEGER,
            image_tokens INTEGER,
            PRIMARY KEY (project_id, call_id),
            FOREIGN KEY (project_id, attempt_id) REFERENCES attempts(project_id, attempt_id),
            FOREIGN KEY (project_id, attempt_id, action_id)
                REFERENCES actions(project_id, attempt_id, action_id),
            FOREIGN KEY (project_id, attempt_id, check_id)
                REFERENCES check_results(project_id, attempt_id, check_id),
            CHECK (
                (action_id IS NOT NULL AND check_id IS NULL)
                OR (action_id IS NULL AND check_id IS NOT NULL)
            )
        )
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS dispatch_journal_no_lookup_after_start
        BEFORE INSERT ON dispatch_journal
        WHEN NEW.dispatch_state = 'lookup_failed'
          AND EXISTS (
            SELECT 1 FROM dispatch_journal
            WHERE project_id = NEW.project_id
              AND attempt_id = NEW.attempt_id
              AND action_seq = NEW.action_seq
              AND dispatch_state = 'dispatch_started'
          )
        BEGIN
            SELECT RAISE(ABORT, 'lookup_failed cannot follow dispatch_started');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS attempt_events_hash_conflict
        BEFORE INSERT ON attempt_events
        WHEN EXISTS (
            SELECT 1 FROM attempt_events
            WHERE project_id = NEW.project_id
              AND attempt_id = NEW.attempt_id
              AND local_seq = NEW.local_seq
              AND (payload_hash <> NEW.payload_hash OR body_hash <> NEW.body_hash)
        )
        BEGIN
            SELECT RAISE(ABORT, 'event hash conflict');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS attempt_events_protect_facts
        BEFORE UPDATE ON attempt_events
        WHEN OLD.sealed = 1
          OR NEW.attempt_id <> OLD.attempt_id
          OR NEW.local_seq <> OLD.local_seq
          OR NEW.payload_hash <> OLD.payload_hash
          OR NEW.body_hash <> OLD.body_hash
          OR NEW.minimum_facts <> OLD.minimum_facts
          OR NEW.event_id <> OLD.event_id
        BEGIN
            SELECT RAISE(ABORT, 'event fact is sealed');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS model_call_facts_unknown_usage
        BEFORE INSERT ON model_call_facts
        WHEN NEW.measurement_status IN ('unknown', 'unreported', 'not_used')
          AND (
            NEW.input_tokens IS NOT NULL
            OR NEW.output_tokens IS NOT NULL
            OR NEW.cache_tokens IS NOT NULL
            OR NEW.image_tokens IS NOT NULL
          )
        BEGIN
            SELECT RAISE(ABORT, 'unknown usage has no token count');
        END
        """
    )
