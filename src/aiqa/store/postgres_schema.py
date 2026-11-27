"""Reviewed PostgreSQL snapshot and its offline SQLite-schema compiler.

Production loads packaged SQL only. The exporter supplies an in-memory SQLite
connection to the compiler; this module never opens or migrates a database.
Unknown SQLite DDL and trigger body forms fail closed for manual review.
"""

from __future__ import annotations

import hashlib
from importlib.resources import files
import json
import re
from typing import Any

SNAPSHOT_VERSION = "hosted_v1"
_IDENT = r"[A-Za-z_][A-Za-z_0-9]*"
_LITERAL = r"'(?:''|[^'])*'"


def _split(source: str, delimiter: str = ";") -> list[str]:
    """Split outside SQL strings, parentheses, and PostgreSQL dollar quotes."""
    result: list[str] = []
    start = index = depth = 0
    quote: str | None = None
    dollar: str | None = None
    while index < len(source):
        if dollar:
            if source.startswith(dollar, index):
                index += len(dollar)
                dollar = None
            else:
                index += 1
            continue
        char = source[index]
        if quote:
            if char == quote:
                if index + 1 < len(source) and source[index + 1] == quote:
                    index += 2
                    continue
                quote = None
            index += 1
            continue
        if char in "'\"":
            quote = char
        elif char == "$":
            match = re.match(r"\$(?:[A-Za-z_][A-Za-z_0-9]*)?\$", source[index:])
            if match:
                dollar = match.group()
                index += len(dollar)
                continue
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth < 0:
                raise ValueError("unbalanced SQL parentheses")
        elif char == delimiter and depth == 0:
            if source[start:index].strip():
                result.append(source[start:index].strip())
            start = index + 1
        index += 1
    if quote or dollar or depth:
        raise ValueError("unterminated SQL expression")
    if source[start:].strip():
        result.append(source[start:].strip())
    return result


def _outside_literals(source: str, rewrite) -> str:
    pieces = re.split(f"({_LITERAL})", source)
    return "".join(piece if position % 2 else rewrite(piece) for position, piece in enumerate(pieces))


def _json_names(source: str) -> str:
    return _outside_literals(source, lambda part: re.sub(
        r"\b(json_valid|json_type|json_extract|json_array|json_each)\s*(?=\()",
        lambda match: "aiqa_" + match.group(1).lower(), part, flags=re.I,
    ))


_JSON_FUNCTIONS = (
    """CREATE FUNCTION aiqa_json_valid(body text) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE AS $aiqa$
BEGIN
    IF body IS NULL THEN RETURN false; END IF;
    PERFORM body::jsonb;
    RETURN true;
EXCEPTION WHEN invalid_text_representation THEN RETURN false;
END
$aiqa$""",
    """CREATE FUNCTION aiqa_json_type(body text, path text) RETURNS text
LANGUAGE plpgsql IMMUTABLE AS $aiqa$
DECLARE item jsonb; kind text;
BEGIN
    IF body IS NULL OR path IS NULL THEN RETURN NULL; END IF;
    IF path !~ '^\\$\\.[A-Za-z_][A-Za-z_0-9]*(\\.[A-Za-z_][A-Za-z_0-9]*)*$' THEN
        RAISE EXCEPTION 'unsupported JSON path' USING ERRCODE = '22023';
    END IF;
    item := body::jsonb #> string_to_array(substring(path FROM 3), '.');
    kind := jsonb_typeof(item);
    RETURN CASE kind WHEN 'string' THEN 'text'
        WHEN 'boolean' THEN item #>> '{}'
        WHEN 'number' THEN CASE WHEN item::text ~ '^-?[0-9]+$' THEN 'integer' ELSE 'real' END
        ELSE kind END;
END
$aiqa$""",
    """CREATE FUNCTION aiqa_json_extract(body text, path text) RETURNS text
LANGUAGE plpgsql IMMUTABLE AS $aiqa$
DECLARE item jsonb;
BEGIN
    IF body IS NULL OR path IS NULL THEN RETURN NULL; END IF;
    IF path !~ '^\\$\\.[A-Za-z_][A-Za-z_0-9]*(\\.[A-Za-z_][A-Za-z_0-9]*)*$' THEN
        RAISE EXCEPTION 'unsupported JSON path' USING ERRCODE = '22023';
    END IF;
    item := body::jsonb #> string_to_array(substring(path FROM 3), '.');
    RETURN CASE WHEN item = 'true'::jsonb THEN '1' WHEN item = 'false'::jsonb THEN '0'
        ELSE item #>> '{}' END;
END
$aiqa$""",
    """CREATE FUNCTION aiqa_json_array(item text) RETURNS text
LANGUAGE sql IMMUTABLE AS $aiqa$
    SELECT jsonb_build_array(item)::text
$aiqa$""",
    """CREATE FUNCTION aiqa_json_each(body text) RETURNS TABLE(value text)
LANGUAGE plpgsql IMMUTABLE AS $aiqa$
DECLARE parsed jsonb;
BEGIN
    IF body IS NULL THEN RETURN; END IF;
    parsed := body::jsonb;
    RETURN QUERY
    SELECT CASE WHEN items.item = 'true'::jsonb THEN '1'
        WHEN items.item = 'false'::jsonb THEN '0' ELSE items.item #>> '{}' END
    FROM (
        SELECT elements.value AS item FROM jsonb_array_elements(
            CASE WHEN jsonb_typeof(parsed) = 'array' THEN parsed ELSE '[]'::jsonb END) AS elements
        UNION ALL
        SELECT members.value AS item FROM jsonb_each(
            CASE WHEN jsonb_typeof(parsed) = 'object' THEN parsed ELSE '{}'::jsonb END) AS members
        UNION ALL
        SELECT parsed WHERE jsonb_typeof(parsed) NOT IN ('array', 'object')
    ) AS items;
END
$aiqa$""",
)


def _objects(connection: Any) -> list[tuple[str, str, str, str]]:
    return [tuple(row) for row in connection.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master "
        "WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY type,name"
    )]


def _table(name: str, sql: str) -> tuple[str, list[str]]:
    match = re.fullmatch(rf"CREATE TABLE\s+{_IDENT}\s*\((.*)\)", sql.strip(), re.I | re.S)
    if not match:
        raise ValueError(f"unsupported table grammar: {name}")
    raw = match.group(1)
    prohibited = r"\b(COLLATE|AUTOINCREMENT|GENERATED|CONFLICT|VIRTUAL)\b"
    if re.search(prohibited, re.sub(_LITERAL, "''", raw), re.I):
        raise ValueError(f"unsupported table feature: {name}")
    columns: list[str] = []
    foreign_keys: list[str] = []
    for part in _split(raw, ","):
        if re.match(r"FOREIGN\s+KEY\b", part, re.I):
            if not re.fullmatch(
                rf"FOREIGN\s+KEY\s*\([\w\s,]+\)\s+REFERENCES\s+{_IDENT}\s*\([\w\s,]+\)"
                r"(?:\s+ON\s+(?:UPDATE|DELETE)\s+(?:CASCADE|RESTRICT|NO ACTION|SET NULL|SET DEFAULT))*"
                r"(?:\s+DEFERRABLE\s+INITIALLY\s+DEFERRED)?", part, re.I | re.S,
            ):
                raise ValueError(f"unsupported foreign key: {name}")
            foreign_keys.append(part)
            continue
        inline = re.search(r"\s+REFERENCES\s+", part, re.I)
        if inline:
            column = re.match(_IDENT, part)
            assert column is not None
            tail = part[inline.end():]
            if not re.fullmatch(
                rf"{_IDENT}\s*\([\w\s,]+\)"
                r"(?:\s+ON\s+(?:UPDATE|DELETE)\s+(?:CASCADE|RESTRICT|NO ACTION|SET NULL|SET DEFAULT))*",
                tail, re.I | re.S,
            ):
                raise ValueError(f"unsupported inline reference: {name}")
            foreign_keys.append(f"FOREIGN KEY ({column.group()}) REFERENCES {tail}")
            part = part[:inline.start()]
        part = _outside_literals(part, lambda text: re.sub(r"\bINTEGER\b", "BIGINT", re.sub(r"\bBLOB\b", "BYTEA", text, flags=re.I), flags=re.I))
        part = part.replace(
            "strftime('%Y-%m-%dT%H:%M:%fZ','now')",
            "to_char(clock_timestamp() AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.MS\"Z\"')",
        )
        if name == "artifact_refs":
            part = re.sub(r"\(\s*([a-z_][a-z_0-9]*\s+IS\s+NOT\s+NULL)\s*\)", r"(\1)::integer", part, flags=re.I)
        columns.append(part)
    columns.append("rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE")
    table = f"CREATE TABLE {name} (\n    " + ",\n    ".join(columns) + "\n)"
    return table, [f"ALTER TABLE {name} ADD {foreign_key}" for foreign_key in foreign_keys]


def _trigger(name: str, table: str, sql: str) -> list[str]:
    match = re.fullmatch(
        rf"CREATE TRIGGER\s+{_IDENT}\s+(BEFORE|AFTER)\s+"
        rf"(INSERT|DELETE|UPDATE(?:\s+OF\s+{_IDENT}(?:\s*,\s*{_IDENT})*)?)\s+ON\s+{_IDENT}"
        r"(?:\s+WHEN\s+(.*?))?\s+BEGIN\s+(.*?)\s*END", sql.strip(), re.I | re.S,
    )
    if not match:
        raise ValueError(f"unsupported trigger grammar: {name}")
    timing, event, condition, body = match.groups()
    event = " ".join(event.split())
    guard = re.fullmatch(rf"SELECT\s+RAISE\s*\(\s*ABORT\s*,\s*({_LITERAL})\s*\)\s*;", body, re.I | re.S)
    if guard:
        if timing.upper() != "BEFORE":
            raise ValueError(f"unsupported trigger timing: {name}")
        action = f"RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = {guard.group(1)};"
    else:
        insert = re.fullmatch(
            rf"INSERT\s+(OR\s+IGNORE\s+)?INTO\s+{_IDENT}\s*(?:\([\w\s,]+\)\s*)?"
            r"(?:VALUES\s*\(.+\)|SELECT\s+.+)\s*;", body, re.I | re.S,
        )
        if timing.upper() != "AFTER" or not insert or len(_split(body)) != 1:
            raise ValueError(f"unsupported trigger body: {name}")
        action = body.rstrip().removesuffix(";").rstrip()
        if insert.group(1):
            action = re.sub(r"\bINSERT\s+OR\s+IGNORE\b", "INSERT", action, count=1, flags=re.I)
            action += " ON CONFLICT DO NOTHING"
        action = _json_names(action) + ";"
    if condition and condition.strip() != "1":
        action = f"IF {_json_names(condition.strip())} THEN\n        {action}\n    END IF;"
    returned = "OLD" if event.upper() == "DELETE" else "NEW"
    function = "aiqa_guard_" + name
    if len(function.encode()) > 63:
        function = function[:46] + "_" + hashlib.sha256(function.encode()).hexdigest()[:16]
    return [
        f"CREATE FUNCTION {function}() RETURNS trigger LANGUAGE plpgsql AS $aiqa$\nBEGIN\n    {action}\n    RETURN {returned};\nEND\n$aiqa$",
        f"CREATE TRIGGER {name} {timing} {event} ON {table} FOR EACH ROW EXECUTE FUNCTION {function}()",
    ]


def compile_sqlite_schema(connection: Any) -> list[str]:
    """Compile final synthetic SQLite DDL to deterministic PostgreSQL statements."""
    objects = _objects(connection)
    if any(kind not in {"table", "index", "trigger"} for kind, *_ in objects):
        raise ValueError("unsupported schema object")
    tables: list[str] = []
    foreign_keys: list[str] = []
    indexes: list[str] = []
    triggers: list[str] = []
    for kind, name, table, sql in objects:
        if kind == "table":
            rendered, references = _table(name, sql)
            tables.append(rendered)
            foreign_keys.extend(references)
        elif kind == "index":
            if not re.fullmatch(rf"CREATE\s+(?:UNIQUE\s+)?INDEX\s+{_IDENT}\s+ON\s+{_IDENT}\s*\(.+\)(?:\s+WHERE\s+.+)?\s*", sql, re.I | re.S):
                raise ValueError(f"unsupported index grammar: {name}")
            if re.search(r"\bCOLLATE\b", re.sub(_LITERAL, "''", sql), re.I):
                raise ValueError(f"unsupported index collation: {name}")
            indexes.append(sql.strip())
        else:
            triggers.extend(_trigger(name, table, sql))
    return [*_JSON_FUNCTIONS, *tables, *indexes, *foreign_keys, *triggers]


def render_schema(statements: list[str] | tuple[str, ...]) -> str:
    return ";\n\n".join(statement.rstrip().removesuffix(";") for statement in statements) + ";\n"


def build_manifest(connection: Any, statements: list[str], migration_head: str) -> dict[str, Any]:
    objects = _objects(connection)
    names = {kind: sorted(name for typ, name, _, _ in objects if typ == kind)
             for kind in ("table", "index", "trigger")}
    source = json.dumps(objects, ensure_ascii=False, separators=(",", ":"))
    return {
        "snapshot_version": SNAPSHOT_VERSION,
        "migration_head": migration_head,
        "counts": {"tables": len(names["table"]), "indexes": len(names["index"]),
                   "foreign_keys": sum(statement.startswith("ALTER TABLE") for statement in statements),
                   "triggers": len(names["trigger"])},
        "tables": names["table"], "indexes": names["index"], "triggers": names["trigger"],
        "statement_count": len(statements),
        "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "rendered_sha256": hashlib.sha256(render_schema(statements).encode()).hexdigest(),
    }


def load_schema_sql() -> str:
    content = files("aiqa.store").joinpath("sql", SNAPSHOT_VERSION + ".sql").read_bytes()
    manifest = load_manifest()
    if hashlib.sha256(content).hexdigest() != manifest["rendered_sha256"]:
        raise ValueError("hosted schema snapshot checksum differs from manifest")
    return content.decode("utf-8")


def load_manifest() -> dict[str, Any]:
    return json.loads(files("aiqa.store").joinpath("sql", SNAPSHOT_VERSION + ".json").read_text(encoding="utf-8"))


def schema_statements() -> tuple[str, ...]:
    return tuple(_split(load_schema_sql()))
