"""Postgres dialect and real temporary-server contracts; no cloud credentials."""
import os
import sqlite3
from dataclasses import replace
from uuid import uuid4

import pytest

from aiqa.config import SettingsError, load_settings
from aiqa.store.database import StorageConfig, migrate_store, open_store


def test_hosted_defaults_to_postgres_and_no_sqlite_fallback(tmp_path):
    settings = load_settings({'AIQA_PROFILE': 'hosted', 'AIQA_PUBLIC_ORIGIN': 'https://qa.example',
        'AIQA_TRUSTED_PROXIES': '127.0.0.1', 'AIQA_RUNTIME_ROOT': str(tmp_path)})
    assert settings.database_backend == 'postgres'
    config = StorageConfig.from_settings(settings)
    with pytest.raises(ValueError):
        open_store(config)
    assert not config.database_path.exists()


def test_database_url_is_server_only_and_validated_without_echo(tmp_path):
    raw = 'postgresql://user:synthetic-password@db.example/qa?sslmode=require'
    settings = load_settings({'AIQA_PROFILE': 'hosted', 'AIQA_PUBLIC_ORIGIN': 'https://qa.example',
        'AIQA_TRUSTED_PROXIES': '127.0.0.1', 'AIQA_RUNTIME_ROOT': str(tmp_path), 'AIQA_DATABASE_URL': raw})
    assert 'synthetic-password' not in repr(settings)
    assert 'synthetic-password' not in repr(StorageConfig.from_settings(settings))
    with pytest.raises(SettingsError) as exc:
        load_settings({'AIQA_RUNTIME_ROOT': str(tmp_path), 'AIQA_DATABASE_BACKEND': 'unknown-secret-marker'})
    assert 'unknown-secret-marker' not in str(exc.value)


@pytest.mark.parametrize('source,expected', [
    ("SELECT '?' AS literal, ? AS value", "SELECT '?' AS literal, %s AS value"),
    ("SELECT '100%' WHERE name LIKE '%' || ? || '%'", "SELECT '100%%' WHERE name ILIKE '%%' || %s || '%%'"),
    ("INSERT OR IGNORE INTO jobs(a) VALUES(?)", "INSERT INTO jobs(a) VALUES(%s) ON CONFLICT DO NOTHING"),
    ("SELECT IFNULL(name,'?'), json_extract(body,'$.name') FROM x WHERE id=?", "SELECT COALESCE(name,'?'), aiqa_json_extract(body,'$.name') FROM x WHERE id=%s"),
    ("SELECT ? -- literal ?\n", "SELECT %s -- literal ?\n"),
    ("SELECT id FROM x WHERE (? IS NULL OR id=?)", "SELECT id FROM x WHERE (CAST(%s AS TEXT) IS NULL OR id=%s)"),
])
def test_sql_translation_preserves_literals_and_binding(source, expected):
    from aiqa.store.postgres import translate_sql
    assert translate_sql(source) == expected


@pytest.fixture
def pg_store(tmp_path):
    url = os.environ.get('AIQA_TEST_POSTGRES_URL')
    if not url:
        pytest.skip('set AIQA_TEST_POSTGRES_URL to the isolated loopback test server')
    from urllib.parse import urlparse
    assert urlparse(url).hostname in {'127.0.0.1', 'localhost'}, 'only isolated loopback server allowed'
    settings = load_settings({'AIQA_RUNTIME_ROOT': str(tmp_path), 'AIQA_DATABASE_BACKEND': 'postgres',
        'AIQA_DATABASE_URL': url})
    config = replace(StorageConfig.from_settings(settings), database_schema='aiqa_test_' + uuid4().hex)
    store = open_store(config)
    migrate_store(store)
    yield store
    raw = store._connection.raw
    # Only this fixture's generated schema is removed; never reset the database.
    assert config.database_schema.startswith('aiqa_test_')
    raw.execute('DROP SCHEMA "' + config.database_schema + '" CASCADE')
    store.close()


def test_real_postgres_project_case_constraints_and_statement_recovery(pg_store):
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.domain.versions import bind_case_store, create_case
    from aiqa.store.models import Actor, ProjectCreate
    store = pg_store
    actor = Actor(uuid4(), None, True)
    with bind_store(store):
        project = create_project(actor, ProjectCreate('Postgres', 'pg', 'fixture', 'android'))
    with bind_case_store(store):
        case = create_case(Actor(actor.actor_id, project.project_id, True), 'Recording', None)
    with store.transaction() as con:
        assert con.execute('SELECT name FROM automation_cases WHERE case_id=?', (str(case.case_id),)).fetchone()[0] == 'Recording'
        with pytest.raises(sqlite3.IntegrityError):
            con.execute('INSERT INTO projects(project_id,key,name,description,target,created_at,actor_id,actor_is_local_owner) VALUES(?,?,?,?,?,?,?,?)',
                        (str(uuid4()), 'pg', 'duplicate', '', 'web', 'now', str(actor.actor_id), 1))
        assert con.execute('SELECT count(*) FROM projects').fetchone()[0] == 1
    assert migrate_store(store).id == '0054_execution_exclusions'


def test_real_postgres_rollback_and_writer_serialization(pg_store):
    from concurrent.futures import ThreadPoolExecutor
    store = pg_store
    with store.transaction() as con:
        con.execute('INSERT INTO project_rows VALUES(?,?)', ('p', '0'))
    def increment(_):
        other = open_store(store.config)
        try:
            with other.transaction() as con:
                value = int(con.execute('SELECT name FROM project_rows WHERE project_id=?', ('p',)).fetchone()[0])
                con.execute('UPDATE project_rows SET name=? WHERE project_id=?', (str(value+1), 'p'))
        finally:
            other.close()
    with ThreadPoolExecutor(max_workers=4) as workers:
        list(workers.map(increment, range(8)))
    assert store._connection.execute('SELECT name FROM project_rows').fetchone()[0] == '8'
    with pytest.raises(RuntimeError):
        with store.transaction() as con:
            con.execute('UPDATE project_rows SET name=?', ('discard',))
            raise RuntimeError('rollback')
    assert store._connection.execute('SELECT name FROM project_rows').fetchone()[0] == '8'


def test_read_transaction_does_not_hold_writer_fence_and_has_stable_snapshot(pg_store):
    from concurrent.futures import ThreadPoolExecutor
    store = pg_store
    with store.transaction() as con:
        con.execute('INSERT INTO project_rows VALUES(?,?)', ('p', 'before'))
    def write():
        other = open_store(store.config)
        try:
            with other.transaction() as con:
                con.execute('UPDATE project_rows SET name=?', ('after',))
        finally:
            other.close()
    with store.read_transaction() as con:
        assert con.execute('SELECT name FROM project_rows').fetchone()[0] == 'before'
        with ThreadPoolExecutor(max_workers=1) as worker:
            worker.submit(write).result(timeout=5)
        assert con.execute('SELECT name FROM project_rows').fetchone()[0] == 'before'
        with pytest.raises(sqlite3.OperationalError):
            con.execute('UPDATE project_rows SET name=?', ('forbidden',))
    assert store._connection.execute('SELECT name FROM project_rows').fetchone()[0] == 'after'
