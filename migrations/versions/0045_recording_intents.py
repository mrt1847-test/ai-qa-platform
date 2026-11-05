"""Freeze case verification goals onto each recording at enqueue time."""


def apply(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS recording_intents (
            project_id TEXT NOT NULL,
            recording_id TEXT NOT NULL,
            case_version_id TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            intent_hash TEXT NOT NULL,
            body_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (project_id, recording_id),
            FOREIGN KEY (project_id, recording_id)
                REFERENCES recordings(project_id, recording_id)
        )
        """
    )
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS recording_intents_hash
        ON recording_intents (project_id, recording_id, intent_hash)
        """
    )
