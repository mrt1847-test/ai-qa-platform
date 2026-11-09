"""Read release and admission facts from an immutable execution job snapshot."""
from __future__ import annotations

import json
import sqlite3


def normalized_release_label(value: object) -> str:
    return value.strip() if type(value) is str else ""


def _item_limits(connection: sqlite3.Connection, project_id: object, case_run_id: object) -> dict:
    row = connection.execute(
        "SELECT limits FROM jobs WHERE project_id=? AND case_run_id=? LIMIT 1",
        (str(project_id), str(case_run_id)),
    ).fetchone()
    if row is None:
        return {}
    try:
        limits = json.loads(str(row[0]))
    except (ValueError, TypeError):
        return {}
    return limits if type(limits) is dict else {}


def item_release_label(connection: sqlite3.Connection, project_id: object, case_run_id: object) -> str:
    """Keep old unlabeled runs empty; never infer or backfill a release."""
    return normalized_release_label(_item_limits(connection, project_id, case_run_id).get("release_label"))


def item_created_seq(
    connection: sqlite3.Connection, project_id: object, case_run_id: object, finalized_seq: int
) -> int:
    """New results keep admission time; legacy unknown creation keeps its old fallback."""
    created = _item_limits(connection, project_id, case_run_id).get("commit_seq")
    return created if type(created) is int and 0 < created <= finalized_seq else finalized_seq
