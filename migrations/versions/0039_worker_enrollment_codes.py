"""One-time worker enrollment codes and optional bearer expiry."""


def apply(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS worker_enrollment_codes (
            code_id TEXT PRIMARY KEY,
            code_hash TEXT NOT NULL UNIQUE,
            enrollment_id TEXT NOT NULL REFERENCES worker_enrollments(enrollment_id),
            purpose TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            consumed_at TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(worker_tokens)").fetchall()
    }
    if "expires_at" not in columns:
        connection.execute("ALTER TABLE worker_tokens ADD COLUMN expires_at TEXT")
