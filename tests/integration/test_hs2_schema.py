"""Offline verification of the reviewed hosted schema snapshot."""

import hashlib
import importlib
from pathlib import Path
import runpy
import sqlite3

import pytest


ROOT = Path(__file__).resolve().parents[2]


def schema_module():
    spec = importlib.util.find_spec("aiqa.store.postgres_schema")
    assert spec is not None, "hosted schema compiler is not implemented"
    return importlib.import_module("aiqa.store.postgres_schema")


@pytest.fixture
def migrated():
    env = runpy.run_path(str(ROOT / "migrations/env.py"))
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys=ON")
    env["ensure_history"](connection)
    for _, apply in env["revisions"]():
        apply(connection)
    yield connection
    connection.close()


def test_full_snapshot_matches_current_domain_and_manifest(migrated):
    module = schema_module()
    statements = module.compile_sqlite_schema(migrated)
    rendered = module.render_schema(statements)
    manifest = module.build_manifest(migrated, statements, "0054_execution_exclusions")
    assert manifest["counts"] == {"tables": 132, "indexes": 35, "foreign_keys": 193, "triggers": 114}
    assert module.load_schema_sql() == rendered
    assert module.load_manifest() == manifest
    assert manifest["rendered_sha256"] == hashlib.sha256(rendered.encode()).hexdigest()
    assert tuple(statements) == module.schema_statements()
    assert len(manifest["tables"]) == len(set(manifest["tables"])) == 132


def test_snapshot_preserves_guards_and_circular_claim_constraints(migrated):
    module = schema_module()
    statements = module.compile_sqlite_schema(migrated)
    sql = "\n".join(statements)
    assert sql.count("GENERATED ALWAYS AS IDENTITY UNIQUE") == 132
    assert sql.count("DEFERRABLE INITIALLY DEFERRED") == 13
    assert sql.count("UPDATE OF") == 5
    assert "(action_id IS NOT NULL)::integer" in sql
    assert "ERRCODE = '23514'" in sql
    assert "aiqa_json_each(jobs.source_refs)" in sql
    assert "aiqa_json_valid(NEW.limits)" in sql
    assert "WHEN 1" not in sql
    first_fk = next(i for i, s in enumerate(statements) if s.startswith("ALTER TABLE"))
    last_index = max(i for i, s in enumerate(statements) if s.startswith(("CREATE INDEX", "CREATE UNIQUE INDEX")))
    assert first_fk > last_index


def test_unknown_trigger_body_is_rejected():
    module = schema_module()
    connection = sqlite3.connect(":memory:")
    connection.executescript("CREATE TABLE sample(id TEXT PRIMARY KEY); CREATE TRIGGER unknown AFTER INSERT ON sample BEGIN UPDATE sample SET id='changed'; END;")
    with pytest.raises(ValueError, match="unsupported trigger"):
        module.compile_sqlite_schema(connection)
    connection.close()


def test_unknown_sqlite_ddl_is_rejected():
    module = schema_module()
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE sample(id TEXT COLLATE NOCASE PRIMARY KEY)")
    with pytest.raises(ValueError, match="unsupported"):
        module.compile_sqlite_schema(connection)
    connection.close()


def test_multiple_trigger_statements_are_not_silently_accepted():
    module = schema_module()
    connection = sqlite3.connect(":memory:")
    connection.executescript("CREATE TABLE sample(id TEXT PRIMARY KEY); CREATE TRIGGER unknown AFTER INSERT ON sample BEGIN INSERT INTO sample VALUES('a'); INSERT INTO sample VALUES('b'); END;")
    with pytest.raises(ValueError, match="unsupported trigger"):
        module.compile_sqlite_schema(connection)
    connection.close()


def test_splitter_keeps_function_bodies_and_literal_punctuation():
    module = schema_module()
    source = "CREATE FUNCTION f() RETURNS text LANGUAGE sql AS $body$ SELECT ';,(x)'; $body$; SELECT 'a;''b';"
    assert len(module._split(source)) == 2
    assert module._split(source)[1] == "SELECT 'a;''b'"


def test_checksum_rejects_an_altered_packaged_snapshot(monkeypatch, tmp_path):
    module = schema_module()
    directory = tmp_path / "sql"
    directory.mkdir()
    (directory / "hosted_v1.sql").write_text(module.load_schema_sql() + "\n", encoding="utf-8")
    (directory / "hosted_v1.json").write_text(
        (ROOT / "src/aiqa/store/sql/hosted_v1.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    monkeypatch.setattr(module, "files", lambda _: tmp_path)
    with pytest.raises(ValueError, match="checksum"):
        module.load_schema_sql()


def test_windows_git_checkout_preserves_schema_hash_and_worker_shell(tmp_path):
    import json
    import shutil
    import subprocess
    git = shutil.which('git')
    if git is None:
        pytest.skip('Git required for fresh-checkout packaging contract')
    repository = tmp_path / 'source'
    checked_out = tmp_path / 'checkout'
    repository.mkdir()
    paths = ('.gitattributes', 'src/aiqa/store/sql/hosted_v1.sql',
             'src/aiqa/store/sql/hosted_v1.json', 'deploy/run-worker.sh')
    for relative in paths:
        destination = repository / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / relative).read_bytes())
    def run(*args):
        subprocess.run([git, '-C', str(repository), '-c', 'core.autocrlf=true', *args],
                       check=True, capture_output=True, timeout=20)
    run('init', '-q')
    run('add', '.')
    run('checkout-index', '--all', '--force', '--prefix=' + checked_out.as_posix() + '/')
    manifest = json.loads((checked_out / paths[2]).read_text(encoding='utf-8'))
    assert hashlib.sha256((checked_out / paths[1]).read_bytes()).hexdigest() == manifest['rendered_sha256']
    assert b'\r\n' not in (checked_out / paths[3]).read_bytes()
