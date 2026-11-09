"""Sequential item admission. One slot starts the next item after cleanup."""

from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID

from aiqa.contracts.reports import CORE_RESULTS, CaseRunFacts
from aiqa.domain.execution_metadata import item_created_seq, item_release_label
from aiqa.domain.projects import next_commit_seq
from aiqa.domain.report_math import summarize_execution
from aiqa.domain.verdicts import remaining_disposition
from aiqa.store.models import Transaction

_STOP_REASON = "앞 항목이 통과하지 않아 실행하지 않습니다"
_CANCEL_REASON = "사용자가 취소했습니다"


class SchedulingRejected(Exception):
    """The finished item cannot move the run."""


@dataclass(frozen=True, slots=True)
class CaseRunView:
    case_run_id: UUID
    result: str
    cleanup_state: str
    cancelled: bool = False


@dataclass(frozen=True, slots=True)
class SchedulingDecision:
    parallel_items_max: int
    parent_terminal: bool
    open_items: int
    next_case_run_id: UUID | None
    remaining: tuple[tuple[str, str, str], ...]
    completion_rate: float | None
    verified_pass_rate: float | None
    total_pass_rate: float | None
    unverified: int


def advance_execution(
    tx: Transaction, project_id: UUID, execution_id: UUID, completed_item: CaseRunView
) -> SchedulingDecision:
    """Record one finished item, then continue, stop, or cancel the rest."""

    if completed_item.result not in CORE_RESULTS or completed_item.cleanup_state not in {"unchanged", "quarantine"}:
        raise SchedulingRejected("item result is invalid")
    items = _items(tx, project_id, execution_id)
    if str(completed_item.case_run_id) not in {item[0] for item in items}:
        raise SchedulingRejected("item is not in the run")
    policy = _policy(tx, project_id, completed_item.case_run_id)
    _store_result(tx, project_id, completed_item)
    _finish_cleanup(tx, project_id, completed_item)
    later = remaining_disposition(policy, completed_item.result, completed_item.cancelled)
    reason = _CANCEL_REASON if later == "CANCELLED" else _STOP_REASON
    marked: list[tuple[str, str, str]] = []
    completed_order = _order(items, completed_item.case_run_id)
    if later is not None:
        for case_run_id, order in items:
            if order <= completed_order:
                continue
            if _stored_result(tx, project_id, case_run_id) is not None:
                continue
            _insert_result(tx, project_id, case_run_id, later)
            _close_queued(tx, project_id, case_run_id, "cancelled" if later == "CANCELLED" else "completed")
            marked.append((case_run_id, later, reason))
    stored = [(case_run_id, _stored_result(tx, project_id, case_run_id)) for case_run_id, _requested in items]
    open_items = sum(1 for _case_run_id, result in stored if result is None)
    parent_terminal = open_items == 0
    summary = None
    if parent_terminal:
        summary = summarize_execution([CaseRunFacts(status=str(result)) for _case_run_id, result in stored])
    nxt = None if completed_item.cleanup_state == "quarantine" or open_items == 0 else _next_open(tx, project_id, items)
    return SchedulingDecision(
        1,
        parent_terminal,
        open_items,
        None if nxt is None else UUID(nxt),
        tuple(marked),
        None if summary is None else summary.completion_rate,
        None if summary is None else summary.verified_pass_rate,
        None if summary is None else summary.total_pass_rate,
        0 if summary is None else summary.unverified,
    )


def _items(tx: Transaction, project_id: UUID, execution_id: UUID) -> list[tuple[str, int]]:
    rows = tx.connection.execute(
        """
        SELECT case_run_id, rowid FROM case_runs
        WHERE project_id = ? AND execution_id = ?
        ORDER BY rowid
        """,
        (str(project_id), str(execution_id)),
    ).fetchall()
    if rows == []:
        raise SchedulingRejected("run is missing")
    return [(str(row[0]), int(row[1])) for row in rows]


def _policy(tx: Transaction, project_id: UUID, case_run_id: UUID) -> str:
    row = tx.connection.execute(
        "SELECT limits FROM jobs WHERE project_id = ? AND case_run_id = ?",
        (str(project_id), str(case_run_id)),
    ).fetchone()
    if row is None:
        raise SchedulingRejected("item job is missing")
    try:
        limits = json.loads(str(row[0]))
    except json.JSONDecodeError as exc:
        raise SchedulingRejected("item job is missing") from exc
    policy = limits.get("failure_policy") if type(limits) is dict else None
    if policy not in {"continue", "stop_on_non_pass"}:
        raise SchedulingRejected("failure policy is required")
    return str(policy)


def _store_result(tx: Transaction, project_id: UUID, item: CaseRunView) -> None:
    if _stored_result(tx, project_id, str(item.case_run_id)) is not None:
        return
    _insert_result(tx, project_id, str(item.case_run_id), item.result)
    status = "cancelled" if item.cancelled and item.result == "CANCELLED" else "completed"
    _close_queued(tx, project_id, str(item.case_run_id), status)


def _insert_result(tx: Transaction, project_id: UUID, case_run_id: str, result: str) -> None:
    seq = next_commit_seq(tx, project_id)
    tx.connection.execute(
        """
        INSERT INTO item_finalizations (
            project_id, case_run_id, created_seq, finalized_seq, release_label, content_hash, core_result, denominator
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 1)
        """,
        (str(project_id), case_run_id, item_created_seq(tx.connection, project_id, case_run_id, seq), seq, item_release_label(tx.connection, project_id, case_run_id), f"{result}:{case_run_id}", result),
    )


def _finish_cleanup(tx: Transaction, project_id: UUID, item: CaseRunView) -> None:
    if item.cleanup_state != "quarantine":
        return
    row = tx.connection.execute(
        "SELECT job_id FROM jobs WHERE project_id = ? AND case_run_id = ?",
        (str(project_id), str(item.case_run_id)),
    ).fetchone()
    if row is None:
        raise SchedulingRejected("item job is missing")
    existing = tx.connection.execute(
        "SELECT 1 FROM job_finish_facts WHERE project_id = ? AND job_id = ?",
        (str(project_id), str(row[0])),
    ).fetchone()
    if existing is not None:
        return
    verdict = "FAIL" if item.result == "FAIL" else None
    tx.connection.execute(
        """
        INSERT INTO job_finish_facts (
            project_id, job_id, verdict, finish_reason, cleanup_failed, resource_state, created_at
        ) VALUES (?, ?, ?, 'crash', 1, 'quarantine', '2026-11-01T00:00:00+00:00')
        """,
        (str(project_id), str(row[0]), verdict),
    )


def _close_queued(tx: Transaction, project_id: UUID, case_run_id: str, status: str) -> None:
    tx.connection.execute(
        """
        UPDATE jobs SET status = ?
        WHERE project_id = ? AND case_run_id = ? AND status IN ('queued', 'preparing', 'running', 'finalizing')
        """,
        (status, str(project_id), case_run_id),
    )


def _stored_result(tx: Transaction, project_id: UUID, case_run_id: str) -> str | None:
    row = tx.connection.execute(
        "SELECT core_result FROM item_finalizations WHERE project_id = ? AND case_run_id = ?",
        (str(project_id), case_run_id),
    ).fetchone()
    return None if row is None else str(row[0])


def _order(items: list[tuple[str, int]], case_run_id: UUID) -> int:
    for item_id, order in items:
        if item_id == str(case_run_id):
            return order
    return 0


def _next_open(tx: Transaction, project_id: UUID, items: list[tuple[str, int]]) -> str | None:
    for case_run_id, _requested in items:
        if _stored_result(tx, project_id, case_run_id) is None:
            return case_run_id
    return None
