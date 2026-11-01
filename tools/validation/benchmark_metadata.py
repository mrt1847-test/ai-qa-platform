"""Synthetic metadata timings. File and device delay stay outside these numbers."""

from __future__ import annotations

import json
import math
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

_OWNERS = re.compile(r"\[(W\d+-\d+)\]")
_SCENARIO = re.compile(r"^\| ((?:DATA|EXEC)-\d+) \|")


@dataclass(frozen=True, slots=True)
class MetadataWorkload:
    database_path: Path
    coverage_path: Path
    index_path: Path
    items: int = 10000
    actions: int = 100000
    trend_target_ms: int = 1000
    event_page_target_ms: int = 500
    event_page_size: int = 200
    trend_days: int = 30


@dataclass(frozen=True, slots=True)
class ScenarioTrack:
    scenario_id: str
    owners: tuple[str, ...]
    status: str


@dataclass(frozen=True, slots=True)
class MetadataBenchmarkReport:
    items: int
    actions: int
    trend_target_ms: int
    event_page_target_ms: int
    untracked_scenarios: int
    trend_p95_ms: float
    event_page_p95_ms: float
    trend_plan: str
    event_plan: str
    file_io_included: bool
    device_latency_included: bool
    scenarios: tuple[ScenarioTrack, ...]


def benchmark_metadata(workload: MetadataWorkload) -> MetadataBenchmarkReport:
    """Measure one synthetic database. The targets are proposals, not a live device result."""

    if workload.items < 1 or workload.actions < 1 or workload.event_page_size < 1:
        raise ValueError("metadata workload is invalid")
    connection = sqlite3.connect(workload.database_path)
    try:
        _schema(connection)
        _load(connection, workload)
        items = int(connection.execute("SELECT COUNT(*) FROM items").fetchone()[0])
        actions = int(connection.execute("SELECT COUNT(*) FROM actions").fetchone()[0])
        trend_plan = _plan(connection, _TREND_SQL, (_start(workload), _end()))
        event_plan = _plan(connection, _EVENT_SQL, (0, workload.event_page_size))
        trend_p95 = _time_query(connection, _TREND_SQL, (_start(workload), _end()))
        event_p95 = _time_query(connection, _EVENT_SQL, (0, workload.event_page_size))
        page = connection.execute(_EVENT_SQL, (0, workload.event_page_size)).fetchall()
    finally:
        connection.close()
    if len(page) != workload.event_page_size:
        raise ValueError("event page is short")
    scenarios = _scenarios(workload.coverage_path, workload.index_path)
    return MetadataBenchmarkReport(
        items=items,
        actions=actions,
        trend_target_ms=workload.trend_target_ms,
        event_page_target_ms=workload.event_page_target_ms,
        untracked_scenarios=sum(1 for row in scenarios if row.status == "missing"),
        trend_p95_ms=trend_p95,
        event_page_p95_ms=event_p95,
        trend_plan=trend_plan,
        event_plan=event_plan,
        file_io_included=False,
        device_latency_included=False,
        scenarios=scenarios,
    )


def render_metadata_load(report: MetadataBenchmarkReport) -> str:
    """Describe the synthetic measurement without treating a task status as a native result."""

    lines = [
        "# metadata 부하 측정",
        "",
        "합성 전용 SQLite에서 최근 30일 추세와 event 페이지를 측정했다. 파일 입출력과 기기 지연은 이 수치에 넣지 않았다. 목표 밀리초는 제안 규모이며 실기기 성능 입증이 아니다.",
        "",
        f"- 항목 {report.items}",
        f"- 행동 {report.actions}",
        f"- 추세 제안 목표 {report.trend_target_ms}ms, 측정 p95 {report.trend_p95_ms:.3f}ms",
        f"- event 페이지 제안 목표 {report.event_page_target_ms}ms, 측정 p95 {report.event_page_p95_ms:.3f}ms",
        f"- 담당이 없는 시나리오 {report.untracked_scenarios}",
        "",
        "추세 query plan:",
        "",
        "```text",
        report.trend_plan,
        "```",
        "",
        "event query plan:",
        "",
        "```text",
        report.event_plan,
        "```",
        "",
        "| 시나리오 | 상태 | 담당 |",
        "|---|---|---|",
    ]
    for row in report.scenarios:
        owners = ", ".join(row.owners) if row.owners else "없음"
        lines.append(f"| {row.scenario_id} | {row.status} | {owners} |")
    lines.append("")
    lines.append("상태는 색인의 담당 작업 상태다. 미실행과 차단을 구현 완료로 바꾸지 않는다.")
    lines.append("")
    return "\n".join(lines)


_TREND_SQL = """
SELECT substr(requested_at, 1, 10) AS day, COUNT(*)
FROM items
WHERE requested_at >= ? AND requested_at < ?
GROUP BY day
"""
_EVENT_SQL = """
SELECT event_id, seq
FROM events
WHERE seq > ?
ORDER BY seq
LIMIT ?
"""


def _schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE items (
            item_id INTEGER PRIMARY KEY,
            requested_at TEXT NOT NULL
        );
        CREATE TABLE actions (
            action_id INTEGER PRIMARY KEY,
            item_id INTEGER NOT NULL,
            occurred_at TEXT NOT NULL
        );
        CREATE TABLE events (
            event_id INTEGER PRIMARY KEY,
            seq INTEGER NOT NULL
        );
        """
    )


def _load(connection: sqlite3.Connection, workload: MetadataWorkload) -> None:
    origin = datetime(2026, 10, 2, tzinfo=timezone.utc)
    items = [
        (index + 1, (origin + timedelta(days=index % workload.trend_days)).isoformat())
        for index in range(workload.items)
    ]
    actions = [
        (index + 1, (index % workload.items) + 1, items[index % workload.items][1])
        for index in range(workload.actions)
    ]
    events = [(index + 1, index + 1) for index in range(max(workload.event_page_size * 2, 400))]
    with connection:
        connection.executemany("INSERT INTO items (item_id, requested_at) VALUES (?, ?)", items)
        connection.executemany(
            "INSERT INTO actions (action_id, item_id, occurred_at) VALUES (?, ?, ?)",
            actions,
        )
        connection.executemany("INSERT INTO events (event_id, seq) VALUES (?, ?)", events)
        connection.execute("CREATE INDEX items_requested ON items(requested_at)")
        connection.execute("CREATE INDEX events_seq ON events(seq)")


def _start(workload: MetadataWorkload) -> str:
    origin = datetime(2026, 10, 2, tzinfo=timezone.utc)
    return origin.isoformat()


def _end() -> str:
    return datetime(2026, 11, 2, tzinfo=timezone.utc).isoformat()


def _plan(connection: sqlite3.Connection, sql: str, parameters: tuple[object, ...]) -> str:
    rows = connection.execute("EXPLAIN QUERY PLAN " + sql, parameters).fetchall()
    return "\n".join(" ".join(str(column) for column in row) for row in rows)


def _time_query(connection: sqlite3.Connection, sql: str, parameters: tuple[object, ...]) -> float:
    samples: list[float] = []
    for _ in range(21):
        started = time.perf_counter()
        connection.execute(sql, parameters).fetchall()
        samples.append((time.perf_counter() - started) * 1000)
    ordered = sorted(samples[1:])
    index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return ordered[index]


def _scenarios(coverage_path: Path, index_path: Path) -> tuple[ScenarioTrack, ...]:
    text = coverage_path.read_text(encoding="utf-8")
    statuses = _statuses(index_path)
    rows: list[ScenarioTrack] = []
    for heading in ("DATA", "EXEC"):
        body = _section(text, heading)
        for line in body.splitlines():
            matched = _SCENARIO.match(line.strip())
            if matched is None:
                continue
            owners = tuple(_OWNERS.findall(line))
            if owners == () or any(owner not in statuses for owner in owners):
                status = "missing"
            elif any(statuses[owner] == "blocked" for owner in owners):
                status = "blocked"
            elif all(statuses[owner] == "complete" for owner in owners):
                status = "complete"
            else:
                status = "not_started"
            rows.append(ScenarioTrack(matched.group(1), owners, status))
    return tuple(rows)


def _section(text: str, heading: str) -> str:
    marker = f"### {heading}"
    start = text.find(marker)
    if start < 0:
        return ""
    rest = text[start + len(marker):]
    finish = rest.find("\n## ")
    next_heading = rest.find("\n### ")
    cut = len(rest)
    for candidate in (finish, next_heading):
        if candidate >= 0:
            cut = min(cut, candidate)
    return rest[:cut]


def _statuses(index_path: Path) -> dict[str, str]:
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    tasks = payload["tasks"] if isinstance(payload, dict) else payload
    return {str(task["id"]): str(task["status"]) for task in tasks}
