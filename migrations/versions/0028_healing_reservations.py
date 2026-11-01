"""One durable healing reservation per item. Calls and seconds cannot be widened later."""

import sqlite3


def apply(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS healing_reservations (
            project_id TEXT NOT NULL,
            reservation_id TEXT NOT NULL,
            episode_id TEXT NOT NULL,
            case_run_id TEXT NOT NULL,
            request_key TEXT NOT NULL,
            reason TEXT NOT NULL CHECK (reason IN ('target_not_found', 'ambiguous', 'layout_shift')),
            reserved_calls INTEGER NOT NULL CHECK (reserved_calls BETWEEN 1 AND 2),
            reserved_seconds INTEGER NOT NULL CHECK (reserved_seconds BETWEEN 1 AND 30),
            created_at TEXT NOT NULL,
            PRIMARY KEY (project_id, reservation_id),
            UNIQUE (project_id, episode_id),
            UNIQUE (project_id, case_run_id),
            FOREIGN KEY (project_id, episode_id) REFERENCES healing_episodes(project_id, episode_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS healing_reservations_no_update
        BEFORE UPDATE ON healing_reservations
        BEGIN
            SELECT RAISE(ABORT, 'healing reservation is permanent');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS healing_reservations_no_delete
        BEFORE DELETE ON healing_reservations
        BEGIN
            SELECT RAISE(ABORT, 'healing reservation is permanent');
        END
        """
    )
