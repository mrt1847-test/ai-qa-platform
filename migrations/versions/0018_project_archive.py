"""Archive timestamp for a project. Active rows keep this null."""


def apply(connection):
    connection.execute("ALTER TABLE projects ADD COLUMN archived_at TEXT")
