"""Restore checks and explicit activations. The live database is not the check path."""

import sqlite3


def apply(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS restore_validations (
            project_id TEXT NOT NULL,
            validation_id TEXT NOT NULL,
            receipt_id TEXT NOT NULL,
            separate_path TEXT NOT NULL,
            schema_ok INTEGER NOT NULL CHECK (schema_ok IN (0, 1)),
            foreign_keys_ok INTEGER NOT NULL CHECK (foreign_keys_ok IN (0, 1)),
            integrity_ok INTEGER NOT NULL CHECK (integrity_ok IN (0, 1)),
            manifest_ok INTEGER NOT NULL CHECK (manifest_ok IN (0, 1)),
            hash_ok INTEGER NOT NULL CHECK (hash_ok IN (0, 1)),
            missing_count INTEGER NOT NULL,
            secret_reset_required INTEGER NOT NULL CHECK (secret_reset_required = 1),
            accepted INTEGER NOT NULL CHECK (accepted IN (0, 1)),
            created_at TEXT NOT NULL,
            PRIMARY KEY (project_id, validation_id),
            FOREIGN KEY (project_id, receipt_id) REFERENCES backup_receipts(project_id, receipt_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS restore_activations (
            project_id TEXT NOT NULL,
            activation_id TEXT NOT NULL,
            validation_id TEXT NOT NULL,
            auto_replayed_jobs INTEGER NOT NULL CHECK (auto_replayed_jobs = 0),
            old_leases_reused INTEGER NOT NULL CHECK (old_leases_reused = 0),
            secret_reset_required INTEGER NOT NULL CHECK (secret_reset_required = 1),
            created_at TEXT NOT NULL,
            PRIMARY KEY (project_id, activation_id),
            FOREIGN KEY (project_id, validation_id)
                REFERENCES restore_validations(project_id, validation_id)
        )
        """
    )
