"""Bind a healing reservation to the unsent action it owns."""


def apply(connection):
    columns = {row[1] for row in connection.execute("PRAGMA table_info(healing_reservations)")}
    if "action_id" not in columns:
        connection.execute("ALTER TABLE healing_reservations ADD COLUMN action_id TEXT")
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS healing_reservations_unsent_action
        BEFORE INSERT ON healing_reservations
        WHEN NEW.action_id IS NOT NULL AND NOT EXISTS (
            SELECT 1
            FROM healing_episodes AS episode
            JOIN actions AS action
              ON action.project_id = episode.project_id
             AND action.attempt_id = episode.attempt_id
             AND action.action_id = NEW.action_id
            WHERE episode.project_id = NEW.project_id
              AND episode.episode_id = NEW.episode_id
              AND action.dispatch_state IN ('planned', 'lookup_failed')
              AND NOT EXISTS (
                  SELECT 1 FROM dispatch_journal AS journal
                  WHERE journal.project_id = action.project_id
                    AND journal.attempt_id = action.attempt_id
                    AND journal.action_seq = action.action_seq
                    AND journal.dispatch_state IN ('dispatch_started', 'acknowledged', 'observed', 'unknown')
              )
        )
        BEGIN
            SELECT RAISE(ABORT, 'healing action was sent');
        END
        """
    )
