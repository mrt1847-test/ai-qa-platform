"""Replay packages, healing episodes, and repair proposals. Package body has no produced version hash."""


def apply(connection):
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS recording_manifests_case_key
        ON recording_manifests(project_id, case_id, manifest_id)
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS replay_packages (
            project_id TEXT NOT NULL,
            package_id TEXT NOT NULL,
            case_id TEXT NOT NULL,
            case_version_id TEXT NOT NULL,
            ready INTEGER NOT NULL CHECK (ready IN (0, 1)),
            schema_version TEXT NOT NULL,
            source_manifest_id TEXT NOT NULL,
            source_manifest_hash TEXT NOT NULL,
            raw_source_hash TEXT NOT NULL,
            approved_code_hash TEXT NOT NULL,
            runtime_ref TEXT NOT NULL,
            compiler_ref TEXT NOT NULL,
            lock_hash TEXT NOT NULL,
            step_mapping_hash TEXT NOT NULL,
            body_hash TEXT NOT NULL,
            PRIMARY KEY (project_id, package_id),
            UNIQUE (project_id, case_id, package_id),
            UNIQUE (project_id, case_id, case_version_id),
            FOREIGN KEY (project_id, case_id, case_version_id)
                REFERENCES case_versions(project_id, case_id, version_id),
            FOREIGN KEY (project_id, case_id, source_manifest_id)
                REFERENCES recording_manifests(project_id, case_id, manifest_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS package_version_links (
            project_id TEXT NOT NULL,
            case_id TEXT NOT NULL,
            version_id TEXT NOT NULL,
            package_id TEXT NOT NULL,
            PRIMARY KEY (project_id, case_id, version_id),
            UNIQUE (project_id, case_id, package_id),
            FOREIGN KEY (project_id, case_id, version_id)
                REFERENCES case_versions(project_id, case_id, version_id)
                DEFERRABLE INITIALLY DEFERRED,
            FOREIGN KEY (project_id, case_id, package_id)
                REFERENCES replay_packages(project_id, case_id, package_id)
                DEFERRABLE INITIALLY DEFERRED
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS package_steps (
            project_id TEXT NOT NULL,
            package_id TEXT NOT NULL,
            step_id TEXT NOT NULL,
            position INTEGER NOT NULL,
            step_hash TEXT NOT NULL,
            PRIMARY KEY (project_id, package_id, step_id),
            FOREIGN KEY (project_id, package_id) REFERENCES replay_packages(project_id, package_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS healing_episodes (
            project_id TEXT NOT NULL,
            episode_id TEXT NOT NULL,
            case_run_id TEXT NOT NULL,
            attempt_id TEXT NOT NULL,
            package_id TEXT NOT NULL,
            request_key TEXT NOT NULL,
            PRIMARY KEY (project_id, episode_id),
            UNIQUE (project_id, case_run_id),
            UNIQUE (project_id, case_run_id, request_key),
            FOREIGN KEY (project_id, case_run_id) REFERENCES case_runs(project_id, case_run_id),
            FOREIGN KEY (project_id, attempt_id) REFERENCES attempts(project_id, attempt_id),
            FOREIGN KEY (project_id, package_id) REFERENCES replay_packages(project_id, package_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS runtime_overrides (
            project_id TEXT NOT NULL,
            override_id TEXT NOT NULL,
            episode_id TEXT NOT NULL,
            case_run_id TEXT NOT NULL,
            attempt_id TEXT NOT NULL,
            package_id TEXT NOT NULL,
            request_key TEXT NOT NULL,
            body_hash TEXT NOT NULL,
            PRIMARY KEY (project_id, override_id),
            UNIQUE (project_id, episode_id),
            UNIQUE (project_id, episode_id, request_key),
            FOREIGN KEY (project_id, episode_id) REFERENCES healing_episodes(project_id, episode_id),
            FOREIGN KEY (project_id, case_run_id) REFERENCES case_runs(project_id, case_run_id),
            FOREIGN KEY (project_id, attempt_id) REFERENCES attempts(project_id, attempt_id),
            FOREIGN KEY (project_id, package_id) REFERENCES replay_packages(project_id, package_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS repair_proposals (
            project_id TEXT NOT NULL,
            proposal_id TEXT NOT NULL,
            episode_id TEXT NOT NULL,
            case_run_id TEXT NOT NULL,
            attempt_id TEXT NOT NULL,
            package_id TEXT NOT NULL,
            request_key TEXT NOT NULL,
            diff_hash TEXT NOT NULL,
            PRIMARY KEY (project_id, proposal_id),
            UNIQUE (project_id, episode_id),
            UNIQUE (project_id, episode_id, request_key),
            FOREIGN KEY (project_id, episode_id) REFERENCES healing_episodes(project_id, episode_id),
            FOREIGN KEY (project_id, case_run_id) REFERENCES case_runs(project_id, case_run_id),
            FOREIGN KEY (project_id, attempt_id) REFERENCES attempts(project_id, attempt_id),
            FOREIGN KEY (project_id, package_id) REFERENCES replay_packages(project_id, package_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS healing_episodes_same_case
        BEFORE INSERT ON healing_episodes
        WHEN NOT EXISTS (
            SELECT 1
            FROM case_runs
            JOIN attempts
              ON attempts.project_id = case_runs.project_id
             AND attempts.attempt_id = NEW.attempt_id
            JOIN jobs
              ON jobs.project_id = attempts.project_id
             AND jobs.job_id = attempts.job_id
             AND jobs.case_run_id = case_runs.case_run_id
            JOIN replay_packages
              ON replay_packages.project_id = NEW.project_id
             AND replay_packages.package_id = NEW.package_id
             AND replay_packages.case_id = case_runs.case_id
            WHERE case_runs.project_id = NEW.project_id
              AND case_runs.case_run_id = NEW.case_run_id
        )
        BEGIN
            SELECT RAISE(ABORT, 'episode is outside the item package');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS runtime_overrides_match_episode
        BEFORE INSERT ON runtime_overrides
        WHEN NOT EXISTS (
            SELECT 1 FROM healing_episodes
            WHERE project_id = NEW.project_id
              AND episode_id = NEW.episode_id
              AND case_run_id = NEW.case_run_id
              AND attempt_id = NEW.attempt_id
              AND package_id = NEW.package_id
        )
        BEGIN
            SELECT RAISE(ABORT, 'override is outside the episode');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS repair_proposals_match_episode
        BEFORE INSERT ON repair_proposals
        WHEN NOT EXISTS (
            SELECT 1 FROM healing_episodes
            WHERE project_id = NEW.project_id
              AND episode_id = NEW.episode_id
              AND case_run_id = NEW.case_run_id
              AND attempt_id = NEW.attempt_id
              AND package_id = NEW.package_id
        )
        BEGIN
            SELECT RAISE(ABORT, 'proposal is outside the episode');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS repair_proposals_immutable
        BEFORE UPDATE ON repair_proposals
        BEGIN
            SELECT RAISE(ABORT, 'repair proposal is immutable');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS artifact_refs_package_owner
        BEFORE INSERT ON artifact_refs
        WHEN NEW.package_id IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM replay_packages
            WHERE project_id = NEW.project_id AND package_id = NEW.package_id
          )
        BEGIN
            SELECT RAISE(ABORT, 'package owner is missing');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS artifact_refs_healing_owner
        BEFORE INSERT ON artifact_refs
        WHEN NEW.healing_id IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM healing_episodes
            WHERE project_id = NEW.project_id AND episode_id = NEW.healing_id
          )
        BEGIN
            SELECT RAISE(ABORT, 'healing owner is missing');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS artifact_refs_proposal_owner
        BEFORE INSERT ON artifact_refs
        WHEN NEW.proposal_id IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM repair_proposals
            WHERE project_id = NEW.project_id AND proposal_id = NEW.proposal_id
          )
        BEGIN
            SELECT RAISE(ABORT, 'proposal owner is missing');
        END
        """
    )
