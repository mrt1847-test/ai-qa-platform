"""Observation queries. One item stays one observation, and the window is UTC."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from aiqa.contracts.reports import (
    CORE_RESULTS,
    AnalyticsQuery,
    AnalyticsReport,
    CaseRunFacts,
    Observation,
    ObservationPage,
)
from aiqa.domain.cohorts import compute_strict_cohort_key
from aiqa.domain.report_math import derive_display_result, summarize_execution
from aiqa.store.models import Actor, Transaction

_KST = timezone(timedelta(hours=9))


class AnalyticsRejected(Exception):
    """The observation window cannot be read."""


def latest_terminals(items: tuple[CaseRunFacts, ...], as_of: int) -> tuple[CaseRunFacts, ...]:
    """Keep one newest finished item in each strict cohort. A later open item stays out."""

    grouped: dict[str, list[CaseRunFacts]] = {}
    for item in items:
        grouped.setdefault(compute_strict_cohort_key(item, as_of).value, []).append(item)
    chosen: list[CaseRunFacts] = []
    for group in grouped.values():
        finished = [item for item in group if item.status in CORE_RESULTS]
        if finished == []:
            continue
        finished.sort(key=lambda item: (item.requested_at, item.execution_id, item.item_id))
        chosen.append(finished[-1])
    return tuple(chosen)


def read_analytics(tx: Transaction, actor: Actor, query: AnalyticsQuery) -> AnalyticsReport:
    """Summarize one filtered window. An empty sample has no rate, and a late cost stays out."""

    if actor.project_scope != query.project_id or type(query.as_of) is not int:
        raise AnalyticsRejected("analytics query is invalid")
    if query.criteria not in {"", "all_observations", "latest_terminal"}:
        raise AnalyticsRejected("analytics query is invalid")
    start, end = _utc_window(query.period_from, query.period_to)
    criteria = "latest_terminal" if query.criteria == "latest_terminal" else "all_observations"
    selected, eligible = _analytics_scope(tx, query, start, end)
    paired = [(row, _analytics_fact(row)) for row in eligible]
    durations = [_duration(row, fact) for row, fact in paired]
    measured = [value for value in durations if value is not None]
    cost = _cost(tx, query.project_id, tuple(fact.item_id for _, fact in paired), query.as_of)
    dates = tuple(sorted({_kst_date(str(row["requested"])) for row, _ in paired}))
    rates = None if paired == [] else _rate_triple(tuple(fact for _, fact in paired))
    return AnalyticsReport(
        sample_count=len(paired) if criteria == "latest_terminal" else len(selected),
        denominator=len(paired),
        unverified=0 if paired == [] else _unverified(tuple(fact for _, fact in paired)),
        as_of=query.as_of,
        criteria=criteria,
        rates=rates,
        p50=_percentile(measured, 50),
        p95=_percentile(measured, 95),
        not_run_duration=None,
        cost=cost,
        storage_count=_storage(tx, query.project_id, tuple(fact.item_id for _, fact in paired)),
        trend_dates=dates,
        repeated_checks=_repeated(tx, query.project_id, tuple(fact.item_id for _, fact in paired)),
        analysis_count=_analyses(tx, query.project_id, tuple(fact.item_id for _, fact in paired)),
        first_satisfied=_first_satisfied(tuple(fact for _, fact in paired)),
        recovery_count=_recovered(tuple(fact for _, fact in paired)),
        condition_count=len({str(row["environment"]) for row, _ in paired if str(row["environment"]) != ""}),
        period_from=query.period_from,
        period_to=query.period_to,
        purpose=query.purpose,
        case_id=query.case_filter,
    )


def query_observations(tx: Transaction, actor: Actor, query: AnalyticsQuery) -> ObservationPage:
    """Return each selected item once; pending admissions already belong to the denominator."""
    if actor.project_scope != query.project_id or type(query.as_of) is not int:
        raise AnalyticsRejected("observation query is invalid")
    start, end = _utc_window(query.period_from, query.period_to)
    items = []
    selected, eligible = _analytics_scope(tx, query, start, end)
    scope = eligible if query.criteria == "latest_terminal" else selected
    for row in scope:
        created, finalized = row["created"], row["finalized"]
        in_denominator = created is not None and int(created) <= query.as_of
        terminal = in_denominator and finalized is not None and int(finalized) <= query.as_of
        items.append(Observation(
            case_run_id=UUID(str(row["case_run_id"])), execution_id=UUID(str(row["execution_id"])),
            source=str(row["source"]), purpose=str(row["purpose"]),
            in_denominator=in_denominator, terminal=terminal,
            result=str(row["result"]) if terminal and row["result"] else None,
            attempt_count=int(row["attempts"]),
        ))
    return ObservationPage(tuple(items))


def _analytics_scope(
    tx: Transaction, query: AnalyticsQuery, start: str, end: str
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    if query.criteria not in {"", "all_observations", "latest_terminal"}:
        raise AnalyticsRejected("analytics query is invalid")
    selected = [row for row in _analytics_rows(tx, query.project_id)
                if _analytics_visible(row, query, start, end)]
    eligible = []
    for row in selected:
        if row["created"] is None or int(row["created"]) > query.as_of:
            continue
        projected = dict(row)
        if row["finalized"] is None or int(row["finalized"]) > query.as_of:
            projected["result"] = ""
            if row["finalized"] is not None:
                projected["duration"] = None
        eligible.append(projected)
    if query.criteria == "latest_terminal":
        kept = {item.item_id for item in latest_terminals(
            tuple(_analytics_fact(row) for row in eligible), query.as_of)}
        eligible = [row for row in eligible if row["case_run_id"] in kept]
    return selected, eligible


def _created_seq(limits: dict, finalized_creation: object) -> int | None:
    admitted = limits.get("commit_seq")
    if type(admitted) is int and admitted > 0:
        return admitted
    return None if finalized_creation is None else int(finalized_creation)


def _utc_window(period_from: str, period_to: str) -> tuple[str, str]:
    start = _utc(period_from)
    end = _utc(period_to)
    if start >= end:
        raise AnalyticsRejected("observation window is invalid")
    return start, end


def _utc(value: str) -> str:
    if type(value) is not str or value.strip() == "":
        raise AnalyticsRejected("observation window is invalid")
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text + "T00:00:00" if len(text) == 10 else text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=_KST)
        return parsed.astimezone(timezone.utc).isoformat()
    except (ValueError, OverflowError) as exc:
        raise AnalyticsRejected("observation window is invalid") from exc


def _analytics_rows(tx: Transaction, project_id: UUID) -> tuple[dict[str, object], ...]:
    rows = tx.connection.execute(
        """
        SELECT case_runs.case_run_id, case_runs.execution_id, case_runs.case_id, case_runs.case_version_id,
               case_runs.purpose, case_runs.requested_at, executions.source, executions.scope_requested_at,
               case_versions.verification_digest, jobs.limits, item_finalizations.core_result,
               item_finalizations.created_seq,
               (
                   SELECT COUNT(*)
                   FROM jobs AS owned
                   JOIN attempts
                     ON attempts.project_id = owned.project_id
                    AND attempts.job_id = owned.job_id
                   WHERE owned.project_id = case_runs.project_id
                     AND owned.case_run_id = case_runs.case_run_id
               ), item_finalizations.finalized_seq
        FROM case_runs
        JOIN executions
          ON executions.project_id = case_runs.project_id
         AND executions.execution_id = case_runs.execution_id
        JOIN case_versions
          ON case_versions.project_id = case_runs.project_id
         AND case_versions.version_id = case_runs.case_version_id
        LEFT JOIN jobs
          ON jobs.project_id = case_runs.project_id
         AND jobs.case_run_id = case_runs.case_run_id
        LEFT JOIN item_finalizations
          ON item_finalizations.project_id = case_runs.project_id
         AND item_finalizations.case_run_id = case_runs.case_run_id
        WHERE case_runs.project_id = ?
        ORDER BY case_runs.requested_at, case_runs.rowid
        """,
        (str(project_id),),
    ).fetchall()
    found: list[dict[str, object]] = []
    for row in rows:
        limits = _limits(row[9])
        found.append(
            {
                "case_run_id": str(row[0]),
                "execution_id": str(row[1]),
                "case_id": str(row[2]),
                "version_id": str(row[3]),
                "purpose": str(row[4]),
                "item_requested": str(row[5]),
                "source": str(row[6]),
                "requested": str(row[7]),
                "verification": str(row[8]),
                "result": "" if row[10] is None else str(row[10]),
                "created": _created_seq(limits, row[11]),
                "finalized": None if row[13] is None else int(row[13]),
                "attempts": int(row[12]),
                "environment": str(limits.get("environment_revision_id", "")),
                "data": str(limits.get("data_fingerprint", "")),
                "build": str(limits.get("build_id", "")),
                "model": str(limits.get("model_status", "")),
                "release_label": str(limits.get("release_label", "")),
                "duration": limits.get("duration_ms"),
                "healing": limits.get("healing_requested") == "on",
            }
        )
    return tuple(found)


def _analytics_visible(row: dict[str, object], query: AnalyticsQuery, start: str, end: str) -> bool:
    if row["source"] == "recording" or row["purpose"] == "recording":
        return False
    if row["purpose"] == "trial" and not query.include_trial:
        return False
    requested = str(row["requested"])
    if requested < start or requested >= end:
        return False
    if query.purpose != "" and row["purpose"] != query.purpose:
        return False
    pairs = (
        (query.case_filter, row["case_id"]),
        (query.version_filter, row["version_id"]),
        (query.verification_filter, row["verification"]),
        (query.data_filter, row["data"]),
        (query.env_filter, row["environment"]),
        (query.build_filter, row["build"]),
        (query.model_filter, row["model"]),
        (query.release_label, row["release_label"]),
    )
    return all(expected == "" or expected == actual for expected, actual in pairs)


def _analytics_fact(row: dict[str, object]) -> CaseRunFacts:
    status = str(row["result"]) if str(row["result"]) in CORE_RESULTS else "running"
    return CaseRunFacts(
        status,
        project_id="",
        case_id=str(row["case_id"]),
        verification_digest=str(row["verification"]),
        env_profile_revision=str(row["environment"]),
        data_fingerprint=str(row["data"]),
        actual_build=str(row["build"]),
        model_status=str(row["model"]) if str(row["model"]) != "" else "unknown",
        healing_requested="on" if row["healing"] is True else "off",
        requested_at=str(row["item_requested"]),
        execution_id=str(row["execution_id"]),
        item_id=str(row["case_run_id"]),
        healing_used=row["healing"] is True,
    )


def _duration(row: dict[str, object], fact: CaseRunFacts) -> int | None:
    if fact.status == "NOT_RUN" or (fact.status == "CANCELLED" and int(row["attempts"]) == 0):
        return None
    value = row["duration"]
    if type(value) is not int:
        return None
    return value


def _rate_triple(items: tuple[CaseRunFacts, ...]) -> tuple[float | None, float | None, float | None]:
    summary = summarize_execution(list(items))
    return (summary.completion_rate, summary.verified_pass_rate, summary.total_pass_rate)


def _unverified(items: tuple[CaseRunFacts, ...]) -> int:
    return summarize_execution(list(items)).unverified


def _first_satisfied(items: tuple[CaseRunFacts, ...]) -> int:
    count = 0
    for item in items:
        result = derive_display_result(item)
        if result is None or item.healing_used:
            continue
        if result.code not in {"FAIL", "BLOCKED", "INCONCLUSIVE", "SKIPPED", "CANCELLED", "NOT_RUN"}:
            count += 1
    return count


def _recovered(items: tuple[CaseRunFacts, ...]) -> int:
    count = 0
    for item in items:
        result = derive_display_result(item)
        if result is None or not item.healing_used:
            continue
        if result.code not in {"FAIL", "BLOCKED", "INCONCLUSIVE", "SKIPPED", "CANCELLED", "NOT_RUN"}:
            count += 1
    return count


def _cost(tx: Transaction, project_id: UUID, case_run_ids: tuple[str, ...], as_of: int) -> str | None:
    if case_run_ids == ():
        return None
    marks = ", ".join("?" for _ in case_run_ids)
    rows = tx.connection.execute(
        f"""
        SELECT amount, commit_seq FROM usage_adjustments
        WHERE project_id = ? AND case_run_id IN ({marks})
          AND measurement_status = 'measured' AND commit_seq <= ?
        """,
        (str(project_id), *case_run_ids, as_of),
    ).fetchall()
    if rows == []:
        return None
    total = sum((Decimal(str(row[0])) for row in rows), Decimal("0"))
    return f"{total.quantize(Decimal('0.01'))}"


def _storage(tx: Transaction, project_id: UUID, case_run_ids: tuple[str, ...]) -> int:
    if case_run_ids == ():
        return 0
    marks = ", ".join("?" for _ in case_run_ids)
    row = tx.connection.execute(
        f"""
        SELECT COUNT(*)
        FROM jobs
        JOIN attempts
          ON attempts.project_id = jobs.project_id
         AND attempts.job_id = jobs.job_id
        JOIN artifact_refs
          ON artifact_refs.project_id = attempts.project_id
         AND artifact_refs.attempt_id = attempts.attempt_id
        WHERE jobs.project_id = ? AND jobs.case_run_id IN ({marks})
        """,
        (str(project_id), *case_run_ids),
    ).fetchone()
    return 0 if row is None else int(row[0])


def _repeated(tx: Transaction, project_id: UUID, case_run_ids: tuple[str, ...]) -> int:
    if case_run_ids == ():
        return 0
    marks = ", ".join("?" for _ in case_run_ids)
    rows = tx.connection.execute(
        f"""
        SELECT check_results.check_id
        FROM jobs
        JOIN attempts
          ON attempts.project_id = jobs.project_id
         AND attempts.job_id = jobs.job_id
        JOIN check_results
          ON check_results.project_id = attempts.project_id
         AND check_results.attempt_id = attempts.attempt_id
        WHERE jobs.project_id = ? AND jobs.case_run_id IN ({marks})
        GROUP BY check_results.check_id
        HAVING COUNT(*) > 1
        """,
        (str(project_id), *case_run_ids),
    ).fetchall()
    return len(rows)


def _analyses(tx: Transaction, project_id: UUID, case_run_ids: tuple[str, ...]) -> int:
    if case_run_ids == ():
        return 0
    marks = ", ".join("?" for _ in case_run_ids)
    row = tx.connection.execute(
        f"""
        SELECT COUNT(*) FROM analysis_records
        WHERE project_id = ? AND case_run_id IN ({marks}) AND commit_seq <= ?
        """,
        (str(project_id), *case_run_ids, 10**12),
    ).fetchone()
    return 0 if row is None else int(row[0])


def _percentile(values: list[int], percent: int) -> float | None:
    if values == []:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(percent / 100 * len(ordered)) - 1)
    return float(ordered[index])


def _kst_date(stamp: str) -> str:
    return datetime.fromisoformat(stamp).astimezone(_KST).date().isoformat()


@dataclass(frozen=True, slots=True)
class ReportSnapshotQuery:
    project_id: UUID
    as_of: int
    criteria_version: str


@dataclass(frozen=True, slots=True)
class ReportSnapshot:
    project_id: str
    as_of: int
    criteria_version: str
    denominator: int
    in_progress: int
    finalized: int
    content_hashes: tuple[str, ...]
    cost: str | None
    fingerprints: tuple[str, ...]
    csv_rows: tuple[object, ...] = ()


_SNAPSHOTS: dict[tuple[str, int, str], ReportSnapshot] = {}


def clear_report_snapshot_cache() -> None:
    """Drop regenerated projections. The next read comes from facts again."""

    _SNAPSHOTS.clear()


def resolve_report_snapshot(tx: Transaction, actor: Actor, query: ReportSnapshotQuery) -> ReportSnapshot:
    """Rebuild one as-of report from facts, hashes, lifecycle, and the ledger."""

    if actor.project_scope != query.project_id or type(query.as_of) is not int or query.criteria_version == "":
        raise AnalyticsRejected("report snapshot is invalid")
    key = (str(query.project_id), query.as_of, query.criteria_version)
    cached = _SNAPSHOTS.get(key)
    if cached is not None:
        return cached
    snapshot = _snapshot_from_facts(tx, query)
    _SNAPSHOTS[key] = snapshot
    return snapshot


def _snapshot_from_facts(tx: Transaction, query: ReportSnapshotQuery) -> ReportSnapshot:
    from aiqa.store.usage import ledger_total_as_of

    rows = tx.connection.execute(
        """
        SELECT case_runs.case_run_id, item_finalizations.content_hash, item_finalizations.denominator,
               created.commit_seq, finalized.commit_seq
        FROM case_runs
        JOIN item_finalizations
          ON item_finalizations.project_id = case_runs.project_id
         AND item_finalizations.case_run_id = case_runs.case_run_id
        JOIN item_lifecycle_events AS created
          ON created.project_id = case_runs.project_id
         AND created.case_run_id = case_runs.case_run_id
         AND created.kind = 'created'
         AND created.commit_seq = item_finalizations.created_seq
        LEFT JOIN item_lifecycle_events AS finalized
          ON finalized.project_id = case_runs.project_id
         AND finalized.case_run_id = case_runs.case_run_id
         AND finalized.kind = 'finalized'
         AND finalized.commit_seq = item_finalizations.finalized_seq
        WHERE case_runs.project_id = ?
        ORDER BY case_runs.case_run_id
        """,
        (str(query.project_id),),
    ).fetchall()
    denominator = 0
    in_progress = 0
    finalized_count = 0
    hashes: list[str] = []
    for row in rows:
        created_seq = int(row[3])
        finalized_seq = None if row[4] is None else int(row[4])
        if int(row[2]) != 1 or created_seq > query.as_of:
            continue
        denominator += 1
        if finalized_seq is not None and finalized_seq <= query.as_of:
            finalized_count += 1
            hashes.append(str(row[1]))
        else:
            in_progress += 1
    amounts = tx.connection.execute(
        """
        SELECT commit_seq, amount FROM usage_adjustments
        WHERE project_id = ? AND measurement_status = 'measured'
        ORDER BY commit_seq
        """,
        (str(query.project_id),),
    ).fetchall()
    keys = tx.connection.execute(
        """
        SELECT verification_digest, target_kind, env_profile_revision, data_fingerprint, oracle_policy
        FROM fingerprint_observations
        WHERE project_id = ? AND commit_seq <= ?
        ORDER BY observation_id
        """,
        (str(query.project_id), query.as_of),
    ).fetchall()
    return ReportSnapshot(
        str(query.project_id),
        query.as_of,
        query.criteria_version,
        denominator,
        in_progress,
        finalized_count,
        tuple(hashes),
        ledger_total_as_of(tuple((int(row[0]), str(row[1])) for row in amounts), query.as_of),
        tuple("|".join(str(part) for part in row) for row in keys),
    )


def _limits(raw: object) -> dict[str, object]:
    if raw is None:
        return {}
    try:
        parsed = json.loads(str(raw))
    except json.JSONDecodeError:
        return {}
    return parsed if type(parsed) is dict else {}
