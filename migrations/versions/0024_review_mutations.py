"""Forward-only durable browser mutation receipts. Business writes share their transaction."""
import sqlite3


def apply(connection: sqlite3.Connection) -> None:
    connection.execute('''CREATE TABLE browser_mutation_receipts (
        actor_id TEXT NOT NULL,
        project_id TEXT NOT NULL,
        operation TEXT NOT NULL,
        request_key TEXT NOT NULL,
        body_hash TEXT NOT NULL,
        status_code INTEGER NOT NULL,
        response_body BLOB NOT NULL,
        media_type TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        PRIMARY KEY(actor_id,project_id,operation,request_key)
    )''')
    connection.execute('CREATE INDEX browser_receipts_expiry ON browser_mutation_receipts(created_at)')
    connection.execute('''CREATE TABLE local_owner_identity (
        singleton INTEGER PRIMARY KEY CHECK(singleton=1), actor_id TEXT NOT NULL UNIQUE)''')
    connection.execute('''CREATE TABLE browser_receipt_key (
        singleton INTEGER PRIMARY KEY CHECK(singleton=1), protected_key BLOB NOT NULL)''')
