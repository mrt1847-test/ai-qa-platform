"""Execution reports. Trial runs stay out of the default list, and recordings are omitted."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from aiqa.contracts.reports import CORE_RESULTS, CaseRunFacts
from aiqa.domain.report_math import derive_display_result, summarize_execution
from aiqa.store.models import Actor, ModelCallFact, Transaction

_DEFAULT_PURPOSES = ("regression", "reverification")
_TRIAL = "trial"
_NEUTRAL = {
    "PASS": "satisfied",
    "FAIL": "failed",
    "BLOCKED": "blocked",
    "INCONCLUSIVE": "inconclusive",
    "SKIPPED": "skipped",
    "CANCELLED": "cancelled",
    "NOT_RUN": "not_run",
}


class ReportMissing(Exception):
    """The execution is not in this project."""


class ReportRejected(Exception):
    """The report filter cannot be read."""


@dataclass(frozen=True, slots=True)
class ReportListItem:
    execution_id: UUID
    name: str
    source: str
    purpose: str
    interim: bool
    n: int


@dataclass(frozen=True, slots=True)
class ReportPage:
    items: tuple[ReportListItem, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class ExecutionReport:
    execution_id: UUID
    name: str
    source: str
    purpose: str
    settings_text: str
    interim: bool
    n: int
    rates: tuple[float, float | None, float | None] | None
    unverified: int
    counts: dict[str, int]
    analysis_count: int
    issue_url: str
    first_attempt_id: str
    latest_attempt_id: str
    evidence_status: str
    period_label: str
    exclusion_outside: int
    pass_bucket: int
    healed_pass: int
    unassisted_pass: int
    action_retry: int
    verifier_used: int
    terminal_bucket_count: int
    missing_usage_display: str
    usage_cost: str
    episode_result: str


@dataclass(frozen=True, slots=True)
class AssistanceSummary:
    pass_bucket: int
    healed_pass: int
    unassisted_pass: int
    action_retry: int
    verifier_used: int
    healing_success: int
    healing_rejected: int
    healing_failed: int
    terminal_bucket_count: int


@dataclass(frozen=True, slots=True)
class RoleUsageSummary:
    calls_by_role: dict[str, int]
    missing_usage_display: str
    cost_text: str


def list_reports(
    tx: Transaction, actor: Actor, project_id: UUID, query: dict[str, str]
) -> ReportPage:
    """List confirmed runs. Trial stays hidden until the filter asks for it."""

    _scope(actor, project_id)
    purposes = _purposes(query)
    source = query.get("source", "")
    start, end = query.get("from", ""), query.get("to", "")
    rows = tx.connection.execute(
        """
        SELECT execution_id, name, source, purpose, scope_requested_at
        FROM executions
        WHERE project_id = ?
        ORDER BY scope_requested_at, execution_id
        """,
        (str(project_id),),
    ).fetchall()
    items: list[ReportListItem] = []
    for row in rows:
        if str(row[3]) not in purposes or str(row[2]) == "recording":
            continue
        if source != "" and str(row[2]) != source:
            continue
        if start != "" and str(row[4]) < start:
            continue
        if end != "" and str(row[4]) >= end:
            continue
        execution_id = UUID(str(row[0]))
        report = read_report(tx, actor, project_id, execution_id, None)
        items.append(ReportListItem(execution_id, str(row[1]), str(row[2]), str(row[3]), report.interim, report.n))
    return ReportPage(tuple(items), None)


def read_report(
    tx: Transaction, actor: Actor, project_id: UUID, execution_id: UUID, as_of: int | None
) -> ExecutionReport:
    """Read one run. An open item keeps the report marked as interim."""

    _scope(actor, project_id)
    row = tx.connection.execute(
        """
        SELECT name, source, purpose, scope_requested_at
        FROM executions
        WHERE project_id = ? AND execution_id = ?
        """,
        (str(project_id), str(execution_id)),
    ).fetchone()
    if row is None or str(row[1]) == "recording":
        raise ReportMissing("execution is missing")
    runs = tx.connection.execute(
        """
        SELECT case_run_id FROM case_runs
        WHERE project_id = ? AND execution_id = ?
        ORDER BY rowid
        """,
        (str(project_id), str(execution_id)),
    ).fetchall()
    run_ids = [str(item[0]) for item in runs]
    facts = [_fact(tx, project_id, case_run_id, as_of) for case_run_id in run_ids]
    codes = [None if item.status == "" else item.status for item in facts]
    summary = summarize_execution(facts)
    assistance = summarize_assistance(facts)
    usage = summarize_role_usage(_calls(tx, project_id, run_ids))
    counts = {name: 0 for name in (*_NEUTRAL.values(), "in_progress")}
    for code in codes:
        counts["in_progress" if code is None else _NEUTRAL[code]] += 1
    rates = None
    if summary.n != 0:
        rates = (
            _round(summary.completion_rate),
            _round(summary.verified_pass_rate),
            _round(summary.total_pass_rate),
        )
    analysis_count, issue_url = _analysis(tx, project_id, [str(item[0]) for item in runs])
    first_attempt, latest_attempt = _attempts(tx, project_id, [str(item[0]) for item in runs])
    return ExecutionReport(
        execution_id,
        str(row[0]),
        str(row[1]),
        str(row[2]),
        _settings(tx, project_id, [str(item[0]) for item in runs]),
        counts["in_progress"] > 0,
        summary.n,
        rates,
        summary.unverified,
        counts,
        analysis_count,
        issue_url,
        first_attempt,
        latest_attempt,
        _evidence(tx, project_id, [str(item[0]) for item in runs]),
        _period(str(row[3])),
        0,
        assistance.pass_bucket,
        assistance.healed_pass,
        assistance.unassisted_pass,
        assistance.action_retry,
        assistance.verifier_used,
        assistance.terminal_bucket_count,
        usage.missing_usage_display,
        usage.cost_text,
        _episode_result(assistance),
    )


def describe_item(tx: Transaction, project_id: UUID, case_run_id: str) -> dict[str, str]:
    """Describe one item without adding an eighth result."""

    fact = _fact(tx, project_id, case_run_id, None)
    usage = summarize_role_usage(_calls(tx, project_id, [case_run_id]))
    assistance = summarize_assistance([fact])
    if fact.healing_used and fact.healing_outcome == "success":
        label = "치유를 사용한 만족입니다."
    elif fact.status == "PASS" and _unassisted(fact):
        label = "도움 없이 만족했습니다."
    elif fact.action_retry:
        label = "동작 재시도가 있습니다."
    else:
        label = "이 항목의 결과입니다."
    roles = ", ".join(f"{name} {count}" for name, count in usage.calls_by_role.items() if count)
    return {
        "assistance_label": label,
        "usage_display": usage.missing_usage_display,
        "usage_cost": usage.cost_text,
        "episode_result": _episode_result(assistance) if fact.healing_used else "없음",
        "role_calls": roles or "없음",
    }


def summarize_assistance(items: list[CaseRunFacts]) -> AssistanceSummary:
    """Count assistance inside the satisfied bucket. Healing stays inside the seven results."""

    passed = [item for item in items if _shown(item) == "PASS"]
    return AssistanceSummary(
        len(passed),
        sum(1 for item in passed if item.healing_used),
        sum(1 for item in passed if _unassisted(item)),
        sum(1 for item in passed if item.action_retry and not item.healing_used),
        sum(1 for item in items if item.verifier_used),
        sum(1 for item in items if item.healing_outcome == "success"),
        sum(1 for item in items if item.healing_outcome == "rejected"),
        sum(1 for item in items if item.healing_outcome == "failed"),
        len(CORE_RESULTS),
    )


def summarize_role_usage(calls: list[ModelCallFact]) -> RoleUsageSummary:
    """Keep missing measurements apart from an unused role."""

    counts = {role: 0 for role in ("authoring", "verification", "healing", "maintenance")}
    for call in calls:
        if call.role in counts:
            counts[call.role] += 1
    return RoleUsageSummary(counts, _usage_label(calls), _cost_text(calls))


def _shown(item: CaseRunFacts) -> str:
    result = derive_display_result(item)
    return "" if result is None else result.code


def _unassisted(item: CaseRunFacts) -> bool:
    return not item.healing_used and not item.action_error and not item.action_retry and not item.recovery_used


def _usage_label(calls: list[ModelCallFact]) -> str:
    if calls == []:
        return "not_used"
    labels = {_call_label(call) for call in calls}
    if labels == {"not_used"}:
        return "not_used"
    if labels == {"unknown"}:
        return "unknown"
    if labels == {"null"}:
        return "null"
    if labels <= {"measured"}:
        return "complete"
    return "partial"


def _call_label(call: ModelCallFact) -> str:
    if call.measurement_status == "not_used":
        return "not_used"
    if call.measurement_status == "unknown":
        return "unknown"
    if call.measurement_status in {"unreported", "estimated"} or call.input_tokens is None:
        return "null"
    return "measured"


def _cost_text(calls: list[ModelCallFact]) -> str:
    if calls == []:
        return "없음"
    if any(_call_label(call) == "null" for call in calls) and any(_call_label(call) == "measured" for call in calls):
        return "일부 없음"
    known = [call.input_tokens for call in calls if call.input_tokens is not None]
    return "없음" if known == [] else str(sum(known))


def _episode_result(summary: AssistanceSummary) -> str:
    return f"치유 성공 {summary.healing_success}, 치유 거부 {summary.healing_rejected}, 치유 실패 {summary.healing_failed}"


def _fact(tx: Transaction, project_id: UUID, case_run_id: str, as_of: int | None) -> CaseRunFacts:
    code = _code(tx, project_id, case_run_id, as_of)
    marks = _marks(tx, project_id, case_run_id)
    healing = "healing" in marks or "episode" in marks
    outcome = ""
    if healing and code == "PASS":
        outcome = "success"
    elif healing and "rejected" in marks:
        outcome = "rejected"
    elif healing and code == "FAIL":
        outcome = "failed"
    return CaseRunFacts(
        status="" if code is None else code,
        healing_used=healing,
        healing_outcome=outcome,
        action_error="action_error" in marks,
        action_retry="action_retry" in marks,
        recovery_used="recovery" in marks,
        verifier_used="verification" in marks,
    )


def _marks(tx: Transaction, project_id: UUID, case_run_id: str) -> set[str]:
    rows = tx.connection.execute(
        """
        SELECT model_call_facts.role, attempt_events.event_type, healing_episodes.episode_id
        FROM jobs
        LEFT JOIN attempts
          ON attempts.project_id = jobs.project_id
         AND attempts.job_id = jobs.job_id
        LEFT JOIN model_call_facts
          ON model_call_facts.project_id = attempts.project_id
         AND model_call_facts.attempt_id = attempts.attempt_id
        LEFT JOIN attempt_events
          ON attempt_events.project_id = attempts.project_id
         AND attempt_events.attempt_id = attempts.attempt_id
        LEFT JOIN healing_episodes
          ON healing_episodes.project_id = jobs.project_id
         AND healing_episodes.case_run_id = jobs.case_run_id
        WHERE jobs.project_id = ? AND jobs.case_run_id = ?
        """,
        (str(project_id), case_run_id),
    ).fetchall()
    marks: set[str] = set()
    for role, event_type, episode_id in rows:
        if role is not None:
            marks.add(str(role))
        if event_type is not None:
            marks.add(str(event_type))
        if episode_id is not None:
            marks.add("episode")
    return marks


def _calls(tx: Transaction, project_id: UUID, case_run_ids: list[str]) -> list[ModelCallFact]:
    if case_run_ids == []:
        return []
    marks = ", ".join("?" for _ in case_run_ids)
    rows = tx.connection.execute(
        f"""
        SELECT model_call_facts.call_id, model_call_facts.attempt_id, model_call_facts.role,
               model_call_facts.action_id, model_call_facts.check_id, model_call_facts.measurement_status,
               model_call_facts.input_tokens, model_call_facts.output_tokens,
               model_call_facts.cache_tokens, model_call_facts.image_tokens
        FROM jobs
        JOIN attempts
          ON attempts.project_id = jobs.project_id
         AND attempts.job_id = jobs.job_id
        JOIN model_call_facts
          ON model_call_facts.project_id = attempts.project_id
         AND model_call_facts.attempt_id = attempts.attempt_id
        WHERE jobs.project_id = ? AND jobs.case_run_id IN ({marks})
        ORDER BY model_call_facts.call_id
        """,
        (str(project_id), *case_run_ids),
    ).fetchall()
    return [
        ModelCallFact(
            project_id,
            UUID(str(row[0])),
            UUID(str(row[1])),
            str(row[2]),
            None if row[3] is None else UUID(str(row[3])),
            None if row[4] is None else str(row[4]),
            str(row[5]),
            None if row[6] is None else int(row[6]),
            None if row[7] is None else int(row[7]),
            None if row[8] is None else int(row[8]),
            None if row[9] is None else int(row[9]),
        )
        for row in rows
    ]


def _purposes(query: dict[str, str]) -> tuple[str, ...]:
    include_trial = query.get("include_trial", "") == "1"
    requested = query.get("purpose", "")
    allowed = (*_DEFAULT_PURPOSES, _TRIAL) if include_trial else _DEFAULT_PURPOSES
    if requested == "":
        return allowed
    if requested not in allowed:
        return ()
    return (requested,)


def _code(tx: Transaction, project_id: UUID, case_run_id: str, as_of: int | None) -> str | None:
    row = tx.connection.execute(
        """
        SELECT core_result, finalized_seq FROM item_finalizations
        WHERE project_id = ? AND case_run_id = ?
        """,
        (str(project_id), case_run_id),
    ).fetchone()
    if row is None:
        return None
    if as_of is not None and int(row[1]) > as_of:
        return None
    return str(row[0])


def _analysis(tx: Transaction, project_id: UUID, case_run_ids: list[str]) -> tuple[int, str]:
    if case_run_ids == []:
        return 0, ""
    marks = ", ".join("?" for _ in case_run_ids)
    rows = tx.connection.execute(
        f"""
        SELECT body FROM analysis_records
        WHERE project_id = ? AND case_run_id IN ({marks})
        ORDER BY commit_seq, record_id
        """,
        (str(project_id), *case_run_ids),
    ).fetchall()
    issue_url = ""
    for (body,) in rows:
        try:
            parsed = json.loads(str(body))
        except json.JSONDecodeError:
            continue
        if type(parsed) is dict and type(parsed.get("issue_url")) is str and parsed["issue_url"] != "":
            issue_url = str(parsed["issue_url"])
    return len(rows), issue_url


def _attempts(tx: Transaction, project_id: UUID, case_run_ids: list[str]) -> tuple[str, str]:
    if case_run_ids == []:
        return "", ""
    marks = ", ".join("?" for _ in case_run_ids)
    rows = tx.connection.execute(
        f"""
        SELECT attempts.attempt_id
        FROM attempts
        JOIN jobs ON jobs.project_id = attempts.project_id AND jobs.job_id = attempts.job_id
        WHERE jobs.project_id = ? AND jobs.case_run_id IN ({marks})
        ORDER BY attempts.generation, attempts.attempt_id
        """,
        (str(project_id), *case_run_ids),
    ).fetchall()
    if rows == []:
        return "", ""
    return str(rows[0][0]), str(rows[-1][0])


def _settings(tx: Transaction, project_id: UUID, case_run_ids: list[str]) -> str:
    if case_run_ids == []:
        return ""
    row = tx.connection.execute(
        "SELECT limits FROM jobs WHERE project_id = ? AND case_run_id = ? ORDER BY rowid LIMIT 1",
        (str(project_id), case_run_ids[0]),
    ).fetchone()
    return "" if row is None else str(row[0])


def _evidence(tx: Transaction, project_id: UUID, case_run_ids: list[str]) -> str:
    if case_run_ids == []:
        return "없음"
    marks = ", ".join("?" for _ in case_run_ids)
    row = tx.connection.execute(
        f"""
        SELECT review_retention_events.reason
        FROM review_retention_events
        JOIN artifact_refs
          ON artifact_refs.project_id = review_retention_events.project_id
         AND artifact_refs.artifact_id = review_retention_events.artifact_id
        JOIN actions
          ON actions.project_id = artifact_refs.project_id
         AND actions.attempt_id = artifact_refs.attempt_id
         AND actions.action_id = artifact_refs.action_id
        JOIN attempts
          ON attempts.project_id = actions.project_id
         AND attempts.attempt_id = actions.attempt_id
        JOIN jobs
          ON jobs.project_id = attempts.project_id
         AND jobs.job_id = attempts.job_id
        WHERE review_retention_events.project_id = ? AND jobs.case_run_id IN ({marks})
        LIMIT 1
        """,
        (str(project_id), *case_run_ids),
    ).fetchone()
    return "없음" if row is None else str(row[0])


def _period(requested_at: str) -> str:
    try:
        parsed = datetime.fromisoformat(requested_at)
    except ValueError:
        return requested_at
    local = parsed.astimezone(timezone(timedelta(hours=9)))
    return local.strftime("%Y-%m-%d %H:%M KST")


def _round(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 2)


def _scope(actor: Actor, project_id: UUID) -> None:
    if actor.project_scope != project_id:
        raise ReportRejected("project scope does not match")
