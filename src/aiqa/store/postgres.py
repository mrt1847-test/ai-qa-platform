"""Postgres port for the bounded SQL surface of the existing domain store.

The management writer fence deliberately preserves SQLite's single-writer
ordering across API processes. Failed statements have their own savepoint so
existing domain conflict handlers can keep querying inside an outer transaction.
"""
from __future__ import annotations

import re
import hashlib
import json
import sqlite3
from urllib.parse import parse_qs, urlparse

from aiqa.store.database import StorageError

_TOKENS = re.compile(r"('(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|--[^\n]*(?:\n|$)|/\*[\s\S]*?\*/)")
_WRITER_LOCK = 668946210735
_SCHEMA = re.compile(r'aiqa(?:_[a-z0-9_]{1,54})?')


def translate_sql(sql: str, *, parameterized: bool = True) -> str:
    parts = _TOKENS.split(sql)
    ignore = False
    for index in range(0, len(parts), 2):
        part = parts[index]
        if re.search(r'\bINSERT\s+OR\s+IGNORE\b', part, re.I):
            ignore = True
            part = re.sub(r'\bINSERT\s+OR\s+IGNORE\b', 'INSERT', part, flags=re.I)
        part = re.sub(r'\bIFNULL\s*(?=\()', 'COALESCE', part, flags=re.I)
        part = re.sub(r'\bjson_extract\s*(?=\()', 'aiqa_json_extract', part, flags=re.I)
        part = re.sub(r'\bLIKE\b', 'ILIKE', part, flags=re.I)
        # PostgreSQL cannot infer an unknown parameter used only in IS NULL.
        # This cast affects presence checks only, not the typed comparison copy.
        part = re.sub(r'\?(\s+IS\s+(?:NOT\s+)?NULL\b)', r'CAST(? AS TEXT)\1', part, flags=re.I)
        if parameterized:
            part = part.replace('%', '%%').replace('?', '%s')
        parts[index] = part
    if parameterized:
        for index in range(1, len(parts), 2):
            # psycopg scans % placeholders even inside SQL literals.
            parts[index] = parts[index].replace('%', '%%')
    result = ''.join(parts)
    if ignore:
        result = result.rstrip().rstrip(';') + ' ON CONFLICT DO NOTHING'
    return result


def _validated_url(url):
    try:
        parsed = urlparse(url) if type(url) is str else None
        if parsed is None or parsed.scheme not in {'postgres', 'postgresql'} or not parsed.hostname or not parsed.path.strip('/'):
            return None
        query = parse_qs(parsed.query)
        mode = query.get('sslmode', ['require'])
        if len(mode) != 1:
            return None
        if mode[0] not in {'require', 'verify-ca', 'verify-full'}:
            if not (parsed.hostname in {'127.0.0.1', 'localhost'} and mode == ['disable']):
                return None
        return url
    except (ValueError, TypeError):
        return None


def connect_postgres(config):
    url = _validated_url(config.database_url)
    if url is None or not _SCHEMA.fullmatch(config.database_schema):
        raise StorageError('valid AIQA_DATABASE_URL and private database schema are required')
    try:
        import psycopg
    except ImportError:
        raise StorageError('install the hosted extra for Postgres support') from None
    raw = None
    try:
        kwargs = {'autocommit': True, 'connect_timeout': 10, 'prepare_threshold': None}
        if 'sslmode=' not in url:
            kwargs['sslmode'] = 'require'
        raw = psycopg.connect(url, **kwargs)
        raw.execute('SET search_path TO "' + config.database_schema + '", pg_catalog')
        raw.execute("SET lock_timeout='10s'")
        raw.execute("SET statement_timeout='60s'")
    except psycopg.Error:
        if raw is not None:
            raw.close()
    if raw is None or raw.closed:
        raise StorageError('Postgres connection is unavailable')
    return PostgresConnection(raw)


class PostgresConnection:
    dialect = 'postgres'

    def __init__(self, raw):
        self.raw = raw
        self._statement = 0

    @property
    def in_transaction(self):
        from psycopg.pq import TransactionStatus
        return self.raw.info.transaction_status in {TransactionStatus.INTRANS, TransactionStatus.INERROR}

    def execute(self, sql, params=()):
        import psycopg
        command = sql.strip().upper()
        if command == 'BEGIN IMMEDIATE':
            self.raw.execute('BEGIN')
            try:
                return self.raw.execute('SELECT pg_advisory_xact_lock(%s)', (_WRITER_LOCK,))
            except psycopg.Error:
                self.raw.execute('ROLLBACK')
                raise sqlite3.OperationalError('database writer is unavailable') from None
        control = bool(re.match(r'^(BEGIN|COMMIT|ROLLBACK|SAVEPOINT|RELEASE)\b', command))
        guarded = self.in_transaction and not control
        self._statement += 1
        savepoint = 'aiqa_stmt_' + str(self._statement)
        if guarded:
            self.raw.execute('SAVEPOINT ' + savepoint)
        error = None
        result = None
        try:
            result = self.raw.execute(translate_sql(sql, parameterized=bool(params)), params or None)
        except psycopg.IntegrityError:
            error = sqlite3.IntegrityError('database constraint rejected the mutation')
        except psycopg.Error:
            error = sqlite3.OperationalError('database operation is unavailable')
        if guarded:
            if error is not None:
                self.raw.execute('ROLLBACK TO SAVEPOINT ' + savepoint)
            self.raw.execute('RELEASE SAVEPOINT ' + savepoint)
        if error is not None:
            raise error
        return result

    def close(self):
        self.raw.close()

    def executemany(self, sql, rows):
        import psycopg
        self._statement += 1
        savepoint = 'aiqa_batch_' + str(self._statement)
        guarded = self.in_transaction
        if guarded:
            self.raw.execute('SAVEPOINT ' + savepoint)
        cursor = self.raw.cursor()
        error = None
        try:
            cursor.executemany(translate_sql(sql), rows)
        except psycopg.IntegrityError:
            error = sqlite3.IntegrityError('database constraint rejected the batch')
        except psycopg.Error:
            error = sqlite3.OperationalError('database batch is unavailable')
        if guarded:
            if error is not None:
                self.raw.execute('ROLLBACK TO SAVEPOINT ' + savepoint)
            self.raw.execute('RELEASE SAVEPOINT ' + savepoint)
        if error is not None:
            cursor.close()
            raise error
        return cursor


def _guard_digest(raw, schema, manifest):
    guards = raw.execute('''SELECT t.tgname,t.tgenabled,pg_get_triggerdef(t.oid,true)
        FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname=%s AND NOT t.tgisinternal ORDER BY t.tgname''', (schema,)).fetchall()
    if ([row[0] for row in guards] != sorted(manifest['triggers'])
            or any(row[1] not in {'O', 'A'} for row in guards)):
        raise StorageError('Postgres guards differ; an explicit migration is required')
    functions = raw.execute('''SELECT p.proname,pg_get_functiondef(p.oid)
        FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname=%s AND p.proname LIKE 'aiqa_%%' ORDER BY p.proname''', (schema,)).fetchall()
    return hashlib.sha256(json.dumps([guards, functions], ensure_ascii=True).encode()).hexdigest()


def migrate_postgres(store) -> str:
    from aiqa.store.postgres_schema import load_manifest, schema_statements

    manifest = load_manifest()
    schema = store.config.database_schema
    with store.transaction() as connection:
        raw = connection.raw
        raw.execute('CREATE SCHEMA IF NOT EXISTS "' + schema + '"')
        raw.execute('REVOKE ALL ON SCHEMA "' + schema + '" FROM PUBLIC')
        exists = raw.execute('SELECT to_regclass(%s)', (schema + '.aiqa_schema_version',)).fetchone()[0]
        if exists is not None:
            columns = {r[0] for r in raw.execute('''SELECT column_name FROM information_schema.columns
                WHERE table_schema=%s AND table_name='aiqa_schema_version' ''', (schema,)).fetchall()}
            if not {'source_hash', 'rendered_hash', 'guard_hash'} <= columns:
                raise StorageError('Postgres schema metadata requires an explicit migration')
            row = raw.execute('SELECT source_hash,rendered_hash,guard_hash FROM aiqa_schema_version WHERE version=1').fetchone()
            if (row is None or tuple(row[:2]) != (manifest['source_sha256'], manifest['rendered_sha256'])
                    or row[2] != _guard_digest(raw, schema, manifest)):
                raise StorageError('Postgres schema differs; an explicit migration is required')
            return manifest['migration_head']
        for sql in schema_statements():
            raw.execute(sql)
        raw.execute('CREATE TABLE aiqa_schema_version(version INTEGER PRIMARY KEY,source_hash TEXT NOT NULL,rendered_hash TEXT NOT NULL,guard_hash TEXT NOT NULL)')
        raw.execute('INSERT INTO aiqa_schema_version VALUES(1,%s,%s,%s)',
            (manifest['source_sha256'], manifest['rendered_sha256'], _guard_digest(raw, schema, manifest)))
        raw.execute('INSERT INTO schema_migrations(id,applied_at) VALUES(%s,clock_timestamp()::text)', (manifest['migration_head'],))
    return manifest['migration_head']
