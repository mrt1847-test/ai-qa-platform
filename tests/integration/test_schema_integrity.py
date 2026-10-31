"""Two ways of building the schema must agree on integrity, indexes, and FK probes."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from aiqa.config import load_settings
from aiqa.store.database import StorageConfig, migrate_store, open_store
from aiqa.store.schema import SchemaIntegrityReport, validate_schema


def observed_reports(tmp_path: Path) -> list[dict[str, object]]:
    fresh = _restarted(tmp_path / "fresh")
    upgraded = _upgraded(tmp_path / "upgrade")
    return [_projection(validate_schema(fresh)), _projection(validate_schema(upgraded))]


def _projection(report: SchemaIntegrityReport) -> dict[str, object]:
    return {
        "integrity": report.integrity,
        "foreign_key_violations": report.foreign_key_violations,
        "required_indexes_present": report.required_indexes_present,
        "mutable_sealed_content": report.mutable_sealed_content,
        "all_fk_target_tables_exist": report.all_fk_target_tables_exist,
        "nullable_fk_inserts_work": report.nullable_fk_inserts_work,
    }


def _restarted(root: Path):
    store = _open(root)
    migrate_store(store)
    store.close()
    restarted = _open(root)
    migrate_store(restarted)
    return restarted


def _upgraded(root: Path):
    from migrations.env import ensure_history, revisions

    store = _open(root)
    connection = store._connection
    connection.execute("BEGIN")
    ensure_history(connection)
    for revision_id, apply in revisions():
        if revision_id == "0009_indexes":
            break
        apply(connection)
        connection.execute(
            "INSERT INTO schema_migrations (id, applied_at) VALUES (?, ?)",
            (revision_id, datetime.now(timezone.utc).isoformat()),
        )
    connection.execute("COMMIT")
    store.close()
    upgraded = _open(root)
    migrate_store(upgraded)
    return upgraded


def _open(root: Path):
    settings = load_settings(
        {"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}
    )
    return open_store(StorageConfig.from_settings(settings))
