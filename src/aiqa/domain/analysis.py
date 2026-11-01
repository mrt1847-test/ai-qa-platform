"""Append-only analysis notes. This does not change a stored verdict or open a device."""

from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID, uuid4

from aiqa.domain.projects import next_commit_seq
from aiqa.store.models import Actor, Transaction

_STATUSES = {"unclassified", "in_progress", "resolved"}
_CLASSES = {"product", "automation", "environment", "data", "unclassified"}
_KINDS = {"analysis", "dissent"}


class AnalysisRejected(Exception):
    """The analysis note cannot be stored."""


class AnalysisConflict(Exception):
    """The same key arrived with a different body."""


class AnalysisMissing(Exception):
    """The case run is not in this project."""


@dataclass(frozen=True, slots=True)
class AnalysisRecord:
    record_id: UUID
    case_run_id: UUID
    status: str
    classification: str
    assignee: str
    comment: str
    issue_url: str
    record_kind: str
    prior_record_id: str
    commit_seq: int
    issue_created: bool


@dataclass(frozen=True, slots=True)
class AnalysisPage:
    items: tuple[AnalysisRecord, ...]
    next_cursor: str | None


def list_analysis_records(tx: Transaction, actor: Actor, project_id: UUID, case_run_id: UUID) -> AnalysisPage:
    """Return the appended notes for one item."""

    _scope(actor, project_id)
    _require_run(tx, project_id, case_run_id)
    rows = tx.connection.execute(
        """
        SELECT record_id, body, commit_seq
        FROM analysis_records
        WHERE project_id = ? AND case_run_id = ?
        ORDER BY commit_seq, record_id
        """,
        (str(project_id), str(case_run_id)),
    ).fetchall()
    return AnalysisPage(tuple(_record(case_run_id, row) for row in rows), None)


def append_analysis_record(
    tx: Transaction, actor: Actor, project_id: UUID, case_run_id: UUID, payload: dict[str, object], request_key: str
) -> tuple[AnalysisRecord, bool]:
    """Append one note. The same key and body return the stored note."""

    _scope(actor, project_id)
    if request_key.strip() == "":
        raise AnalysisRejected("idempotency key is required")
    _require_run(tx, project_id, case_run_id)
    fields = _fields(payload)
    body_hash = _hash(fields)
    stored = _stored_key(tx, project_id, case_run_id, request_key)
    if stored is not None:
        if stored[1] != body_hash:
            raise AnalysisConflict("idempotency body does not match")
        return stored[0], True
    if fields["record_kind"] == "dissent":
        prior = fields["prior_record_id"]
        found = tx.connection.execute(
            """
            SELECT 1 FROM analysis_records
            WHERE project_id = ? AND case_run_id = ? AND record_id = ?
            """,
            (str(project_id), str(case_run_id), prior),
        ).fetchone()
        if found is None:
            raise AnalysisRejected("prior analysis is missing")
    record_id = uuid4()
    commit_seq = next_commit_seq(tx, project_id)
    body = json.dumps({**fields, "idempotency_key": request_key, "body_hash": body_hash}, ensure_ascii=False)
    tx.connection.execute(
        """
        INSERT INTO analysis_records (project_id, record_id, case_run_id, commit_seq, body)
        VALUES (?, ?, ?, ?, ?)
        """,
        (str(project_id), str(record_id), str(case_run_id), commit_seq, body),
    )
    return _from_fields(record_id, case_run_id, fields, commit_seq), False


def read_original_verdict(tx: Transaction, project_id: UUID, case_run_id: UUID) -> str:
    """Read the stored QA result. Analysis does not rewrite it."""

    row = tx.connection.execute(
        """
        SELECT core_result, content_hash FROM item_finalizations
        WHERE project_id = ? AND case_run_id = ?
        """,
        (str(project_id), str(case_run_id)),
    ).fetchone()
    return "" if row is None else str(row[0])


def _fields(payload: dict[str, object]) -> dict[str, str]:
    status = payload.get("status")
    classification = payload.get("classification")
    assignee = payload.get("assignee")
    comment = payload.get("comment")
    issue_url = payload.get("issue_url", "")
    record_kind = payload.get("record_kind", "analysis")
    prior = payload.get("prior_record_id", "")
    if status not in _STATUSES or classification not in _CLASSES or record_kind not in _KINDS:
        raise AnalysisRejected("analysis value is invalid")
    if type(assignee) is not str or assignee.strip() == "":
        raise AnalysisRejected("assignee is required")
    if type(comment) is not str or comment.strip() == "":
        raise AnalysisRejected("comment is required")
    if type(issue_url) is not str or type(prior) is not str:
        raise AnalysisRejected("analysis value is invalid")
    if issue_url.strip() != "" and not (issue_url.startswith("http://") or issue_url.startswith("https://")):
        raise AnalysisRejected("issue url is invalid")
    if record_kind == "dissent" and prior.strip() == "":
        raise AnalysisRejected("prior analysis is missing")
    return {
        "status": str(status),
        "classification": str(classification),
        "assignee": assignee.strip(),
        "comment": comment,
        "issue_url": issue_url.strip(),
        "record_kind": str(record_kind),
        "prior_record_id": prior.strip(),
    }


def _stored_key(
    tx: Transaction, project_id: UUID, case_run_id: UUID, request_key: str
) -> tuple[AnalysisRecord, str] | None:
    rows = tx.connection.execute(
        """
        SELECT record_id, body, commit_seq FROM analysis_records
        WHERE project_id = ? AND case_run_id = ?
        """,
        (str(project_id), str(case_run_id)),
    ).fetchall()
    for row in rows:
        parsed = _body(str(row[1]))
        if parsed.get("idempotency_key") == request_key:
            return _record(case_run_id, row), str(parsed.get("body_hash", ""))
    return None


def _record(case_run_id: UUID, row: tuple[object, ...]) -> AnalysisRecord:
    parsed = _body(str(row[1]))
    return _from_fields(UUID(str(row[0])), case_run_id, parsed, int(row[2]))


def _from_fields(record_id: UUID, case_run_id: UUID, fields: dict[str, str], commit_seq: int) -> AnalysisRecord:
    return AnalysisRecord(
        record_id,
        case_run_id,
        fields.get("status", ""),
        fields.get("classification", ""),
        fields.get("assignee", ""),
        fields.get("comment", ""),
        fields.get("issue_url", ""),
        fields.get("record_kind", "analysis"),
        fields.get("prior_record_id", ""),
        commit_seq,
        False,
    )


def _body(raw: str) -> dict[str, str]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AnalysisRejected("analysis record is invalid") from exc
    if type(parsed) is not dict:
        raise AnalysisRejected("analysis record is invalid")
    return {str(key): value for key, value in parsed.items() if type(value) is str}


def _hash(fields: dict[str, str]) -> str:
    return json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _require_run(tx: Transaction, project_id: UUID, case_run_id: UUID) -> None:
    row = tx.connection.execute(
        "SELECT 1 FROM case_runs WHERE project_id = ? AND case_run_id = ?",
        (str(project_id), str(case_run_id)),
    ).fetchone()
    if row is None:
        raise AnalysisMissing("case run is missing")


def _scope(actor: Actor, project_id: UUID) -> None:
    if actor.project_scope != project_id:
        raise AnalysisRejected("project scope does not match")
