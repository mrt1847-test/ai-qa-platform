"""Persisted case proposals. A version is created only by an explicit accept."""


def apply(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS case_edit_proposals (
            project_id TEXT NOT NULL,
            proposal_id TEXT NOT NULL,
            case_id TEXT NOT NULL,
            base_version_id TEXT NOT NULL,
            base_hash TEXT NOT NULL,
            kind TEXT NOT NULL CHECK (kind IN ('structure', 'tc_import')),
            body TEXT NOT NULL,
            body_hash TEXT NOT NULL,
            source_job_id TEXT,
            tc_version_id TEXT,
            PRIMARY KEY (project_id, proposal_id),
            FOREIGN KEY (project_id, case_id, base_version_id)
                REFERENCES case_versions(project_id, case_id, version_id),
            FOREIGN KEY (project_id, source_job_id) REFERENCES jobs(project_id, job_id),
            FOREIGN KEY (project_id, tc_version_id) REFERENCES tc_versions(project_id, version_id),
            CHECK (
                (kind = 'structure' AND source_job_id IS NOT NULL AND tc_version_id IS NULL)
                OR (kind = 'tc_import' AND tc_version_id IS NOT NULL AND source_job_id IS NULL)
            )
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS case_proposal_decisions (
            project_id TEXT NOT NULL,
            decision_id TEXT NOT NULL,
            proposal_id TEXT NOT NULL,
            decision TEXT NOT NULL CHECK (decision IN ('accepted', 'rejected')),
            produced_version_id TEXT,
            actor_id TEXT NOT NULL,
            commit_seq INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (project_id, decision_id),
            FOREIGN KEY (project_id, proposal_id)
                REFERENCES case_edit_proposals(project_id, proposal_id),
            FOREIGN KEY (project_id, produced_version_id)
                REFERENCES case_versions(project_id, version_id),
            CHECK (
                (decision = 'accepted' AND produced_version_id IS NOT NULL)
                OR (decision = 'rejected' AND produced_version_id IS NULL)
            )
        )
        """
    )
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS case_proposal_one_accept
        ON case_proposal_decisions(project_id, proposal_id)
        WHERE decision = 'accepted'
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS case_edit_proposals_structure_case
        BEFORE INSERT ON case_edit_proposals
        WHEN NEW.kind = 'structure'
          AND NOT EXISTS (
            SELECT 1 FROM jobs
            JOIN json_each(jobs.source_refs) AS source_ref
              ON source_ref.value = NEW.case_id
            WHERE jobs.project_id = NEW.project_id
              AND jobs.job_id = NEW.source_job_id
              AND jobs.purpose = 'structure'
          )
        BEGIN
            SELECT RAISE(ABORT, 'structure job belongs to another case');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS case_edit_proposals_immutable
        BEFORE UPDATE ON case_edit_proposals
        BEGIN
            SELECT RAISE(ABORT, 'case proposal is immutable');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS case_proposal_decisions_immutable
        BEFORE UPDATE ON case_proposal_decisions
        BEGIN
            SELECT RAISE(ABORT, 'proposal decision is append-only');
        END
        """
    )
