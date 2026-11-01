"""Export admission. The manifest stays fixed after the job is accepted."""

from __future__ import annotations

import csv
import html
import io
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from aiqa.contracts.jobs import IdempotencyKey
from aiqa.domain.analytics import ReportSnapshot
from aiqa.domain.hashing import canonical_hash, canonical_json
from aiqa.store.models import Actor, Transaction
from aiqa.store.queue import JobConflict, enqueue_export
from aiqa.store.usage import ledger_total_as_of


class ExportMissing(Exception):
    """The execution or export is not in this project."""


class ExportRejected(Exception):
    """The export request cannot be accepted."""


class ExportConflict(Exception):
    """The same key arrived with a different body."""


@dataclass(frozen=True, slots=True)
class ExportInput:
    execution_id: UUID
    export_format: str
    as_of: int
    criteria_version: str
    filters: tuple[tuple[str, str], ...]
    cohort: str
    expires_at: str


@dataclass(frozen=True, slots=True)
class ExportView:
    job_id: UUID
    replayed: bool
    verdict: None
    as_of: int
    criteria_version: str
    interim: bool
    expires_at: str
    expired_reason: str | None
    artifact_ready: bool
    source_ids: tuple[str, ...]
    created_at: str
    cost: str | None
    export_format: str


def request_export(
    tx: Transaction,
    actor: Actor,
    project_id: UUID,
    incoming: ExportInput,
    key: IdempotencyKey,
    artifacts_dir: Path,
    now: datetime,
) -> ExportView:
    """Accept one export and freeze its manifest. A repeated key returns that job."""

    if actor.project_scope != project_id or key.project_id != project_id or key.actor_id != actor.actor_id:
        raise ExportRejected("export is invalid")
    _validate(incoming)
    if not _execution_exists(tx, project_id, incoming.execution_id):
        raise ExportMissing("execution was not found")
    request_hash = _request_hash(incoming)
    try:
        job_id, replayed = enqueue_export(
            tx, key, incoming.execution_id, _manifest(tx, project_id, incoming, now), request_hash
        )
    except JobConflict as exc:
        raise ExportConflict("export body does not match") from exc
    except ValueError as exc:
        raise ExportRejected("export is invalid") from exc
    if not replayed:
        _write_artifact(artifacts_dir, project_id, job_id, tx)
    return _view(tx, project_id, incoming.execution_id, job_id, replayed, artifacts_dir, now)


def read_export(
    tx: Transaction,
    actor: Actor,
    project_id: UUID,
    execution_id: UUID,
    job_id: UUID,
    artifacts_dir: Path,
    now: datetime,
) -> ExportView:
    """Read the stored manifest. A later ledger row does not replace it."""

    if actor.project_scope != project_id:
        raise ExportRejected("export is invalid")
    if not _execution_exists(tx, project_id, execution_id):
        raise ExportMissing("execution was not found")
    return _view(tx, project_id, execution_id, job_id, False, artifacts_dir, now)


def read_export_by_id(
    tx: Transaction,
    actor: Actor,
    project_id: UUID,
    job_id: UUID,
    artifacts_dir: Path,
    now: datetime,
) -> ExportView:
    """Read one export by its job id. The stored manifest stays fixed."""

    if actor.project_scope != project_id:
        raise ExportRejected("export is invalid")
    row = tx.connection.execute(
        """
        SELECT execution_id FROM job_receipts
        WHERE project_id = ? AND job_id = ? AND purpose = 'export'
        """,
        (str(project_id), str(job_id)),
    ).fetchone()
    if row is None or row[0] is None:
        raise ExportMissing("export was not found")
    return read_export(tx, actor, project_id, UUID(str(row[0])), job_id, artifacts_dir, now)


def _validate(incoming: ExportInput) -> None:
    if incoming.export_format not in {"csv", "printable_html"} or incoming.criteria_version.strip() == "":
        raise ExportRejected("export is invalid")
    if type(incoming.as_of) is not int or incoming.cohort.strip() == "":
        raise ExportRejected("export is invalid")
    expires = _instant(incoming.expires_at)
    if expires is None:
        raise ExportRejected("export is invalid")


def _manifest(tx: Transaction, project_id: UUID, incoming: ExportInput, now: datetime) -> dict[str, object]:
    source_ids = _source_ids(tx, project_id, incoming.execution_id)
    hashes = _hashes(tx, project_id, incoming.execution_id, incoming.as_of)
    expires = _instant(incoming.expires_at)
    if expires is None:
        raise ExportRejected("export is invalid")
    return {
        "format": incoming.export_format,
        "as_of": incoming.as_of,
        "criteria_version": incoming.criteria_version,
        "filters": {key: value for key, value in incoming.filters},
        "cohort": incoming.cohort,
        "source_ids": list(source_ids),
        "created_at": now.astimezone(timezone.utc).isoformat(),
        "interim": _interim(tx, project_id, incoming.execution_id, incoming.as_of),
        "expires_at": expires.astimezone(timezone.utc).isoformat(),
        "content_hashes": list(hashes),
        "cost": _cost(tx, project_id, incoming.execution_id, incoming.as_of),
        "verdict": None,
    }


def _view(
    tx: Transaction,
    project_id: UUID,
    execution_id: UUID,
    job_id: UUID,
    replayed: bool,
    artifacts_dir: Path,
    now: datetime,
) -> ExportView:
    manifest = _stored_manifest(tx, project_id, job_id)
    if manifest is None or str(execution_id) not in _text_list(manifest.get("source_ids")):
        raise ExportMissing("export was not found")
    expires = _instant(str(manifest.get("expires_at", "")))
    if expires is None:
        raise ExportRejected("export is invalid")
    reason = "파일이 만료되었습니다" if now.astimezone(timezone.utc) >= expires else None
    path = _artifact_path(artifacts_dir, project_id, job_id)
    ready = path.is_file() and path.read_bytes() == canonical_json(manifest).encode("utf-8")
    cost = manifest.get("cost")
    return ExportView(
        job_id,
        replayed,
        None,
        int(manifest["as_of"]),
        str(manifest["criteria_version"]),
        manifest.get("interim") is True,
        str(manifest["expires_at"]),
        reason,
        ready,
        tuple(_text_list(manifest.get("source_ids"))),
        str(manifest["created_at"]),
        None if cost is None else str(cost),
        str(manifest["format"]),
    )


def _write_artifact(root: Path, project_id: UUID, job_id: UUID, tx: Transaction) -> None:
    manifest = _stored_manifest(tx, project_id, job_id)
    if manifest is None:
        raise ExportRejected("export is invalid")
    path = _artifact_path(root, project_id, job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json(manifest).encode("utf-8"))


def _stored_manifest(tx: Transaction, project_id: UUID, job_id: UUID) -> dict[str, object] | None:
    row = tx.connection.execute(
        """
        SELECT limits FROM jobs
        WHERE project_id = ? AND job_id = ? AND purpose = 'export'
        """,
        (str(project_id), str(job_id)),
    ).fetchone()
    if row is None:
        return None
    parsed = json.loads(str(row[0]))
    return parsed if type(parsed) is dict else None


def _artifact_path(root: Path, project_id: UUID, job_id: UUID) -> Path:
    return root / str(project_id) / "exports" / f"{job_id}.json"


def _execution_exists(tx: Transaction, project_id: UUID, execution_id: UUID) -> bool:
    row = tx.connection.execute(
        "SELECT 1 FROM executions WHERE project_id = ? AND execution_id = ?",
        (str(project_id), str(execution_id)),
    ).fetchone()
    return row is not None


def _source_ids(tx: Transaction, project_id: UUID, execution_id: UUID) -> tuple[str, ...]:
    rows = tx.connection.execute(
        """
        SELECT case_run_id FROM case_runs
        WHERE project_id = ? AND execution_id = ?
        ORDER BY case_run_id
        """,
        (str(project_id), str(execution_id)),
    ).fetchall()
    return (str(execution_id), *(str(row[0]) for row in rows))


def _hashes(tx: Transaction, project_id: UUID, execution_id: UUID, as_of: int) -> tuple[str, ...]:
    rows = tx.connection.execute(
        """
        SELECT item_finalizations.content_hash
        FROM case_runs
        JOIN item_finalizations
          ON item_finalizations.project_id = case_runs.project_id
         AND item_finalizations.case_run_id = case_runs.case_run_id
        WHERE case_runs.project_id = ? AND case_runs.execution_id = ?
          AND item_finalizations.finalized_seq <= ?
        ORDER BY case_runs.case_run_id
        """,
        (str(project_id), str(execution_id), as_of),
    ).fetchall()
    return tuple(str(row[0]) for row in rows)


def _interim(tx: Transaction, project_id: UUID, execution_id: UUID, as_of: int) -> bool:
    rows = tx.connection.execute(
        """
        SELECT item_finalizations.finalized_seq
        FROM case_runs
        LEFT JOIN item_finalizations
          ON item_finalizations.project_id = case_runs.project_id
         AND item_finalizations.case_run_id = case_runs.case_run_id
        WHERE case_runs.project_id = ? AND case_runs.execution_id = ?
        """,
        (str(project_id), str(execution_id)),
    ).fetchall()
    if rows == []:
        return True
    return any(row[0] is None or int(row[0]) > as_of for row in rows)


def _cost(tx: Transaction, project_id: UUID, execution_id: UUID, as_of: int) -> str | None:
    rows = tx.connection.execute(
        """
        SELECT usage_adjustments.commit_seq, usage_adjustments.amount
        FROM usage_adjustments
        JOIN case_runs
          ON case_runs.project_id = usage_adjustments.project_id
         AND case_runs.case_run_id = usage_adjustments.case_run_id
        WHERE usage_adjustments.project_id = ? AND case_runs.execution_id = ?
          AND usage_adjustments.measurement_status = 'measured'
        """,
        (str(project_id), str(execution_id)),
    ).fetchall()
    return ledger_total_as_of(tuple((int(row[0]), str(row[1])) for row in rows), as_of)


def _request_hash(incoming: ExportInput) -> str:
    return canonical_hash(
        {
            "as_of": incoming.as_of,
            "cohort": incoming.cohort,
            "criteria_version": incoming.criteria_version,
            "execution_id": str(incoming.execution_id),
            "expires_at": incoming.expires_at,
            "filters": {key: value for key, value in incoming.filters},
            "format": incoming.export_format,
        },
        "canon-json-v1",
    )


def _instant(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _text_list(value: object) -> list[str]:
    if type(value) is not list:
        return []
    return [str(item) for item in value]


def new_export_id() -> UUID:
    return uuid4()


@dataclass(frozen=True, slots=True)
class CsvLine:
    execution_id: str
    case_run_id: str
    case_version_id: str
    data_name: str
    environment: str
    build: str
    result_label: str
    completion_rate: str | None
    verified_rate: str | None
    total_rate: str | None
    unverified: str
    original_error: str
    healing: str
    role_usage: str | None
    evidence: str
    secret_plaintext: str = ""
    secret_ref: str = ""
    hidden_reasoning: str = ""
    artifact_path: str = ""


@dataclass(frozen=True, slots=True)
class SanitizedArtifact:
    media_type: str
    filename: str
    body: bytes


def render_report_csv(snapshot: ReportSnapshot) -> SanitizedArtifact:
    """Write one UTF-8 CSV. Formula text is quoted, and secret text stays out."""

    if type(snapshot) is not ReportSnapshot:
        raise ExportRejected("export is invalid")
    header = (
        "수행",
        "항목",
        "케이스버전",
        "데이터",
        "환경",
        "빌드",
        "결과",
        "완료율",
        "검증비율",
        "전체비율",
        "미검증",
        "원래오류",
        "치유",
        "역할사용량",
        "기준시각",
        "산식",
        "증거",
    )
    table = [header]
    for row in snapshot.csv_rows:
        if not isinstance(row, CsvLine):
            raise ExportRejected("export is invalid")
        table.append(
            (
                _safe(row.execution_id),
                _safe(row.case_run_id),
                _safe(row.case_version_id),
                _safe(row.data_name),
                _safe(row.environment),
                _safe(row.build),
                _safe(row.result_label),
                _blank(row.completion_rate),
                _blank(row.verified_rate),
                _blank(row.total_rate),
                _safe(row.unverified),
                _safe(row.original_error),
                _safe(row.healing),
                _blank(row.role_usage),
                _safe(str(snapshot.as_of)),
                _safe(snapshot.criteria_version),
                _safe(_evidence_label(row)),
            )
        )
    buffer = io.StringIO(newline="")
    csv.writer(buffer, lineterminator="\n").writerows(table)
    return SanitizedArtifact("text/csv; charset=utf-8", "report.csv", buffer.getvalue().encode("utf-8"))


def _evidence_label(row: CsvLine) -> str:
    if row.artifact_path != "" and row.evidence == "권한 없음":
        return "권한 없음"
    return row.evidence


def _blank(value: str | None) -> str:
    if value is None:
        return ""
    return _safe(value)


def _safe(value: str) -> str:
    if value == "":
        return ""
    probe = value.lstrip(" \t\r\n")
    if value[0] in "\t\r\n" or (probe != "" and probe[0] in "=+-@"):
        return "'" + value
    return value


def render_report_html(snapshot: ReportSnapshot) -> SanitizedArtifact:
    """Write printable HTML. Core fields stay visible, and script text is escaped."""

    if type(snapshot) is not ReportSnapshot:
        raise ExportRejected("export is invalid")
    rows: list[str] = []
    ids: list[str] = []
    for row in snapshot.csv_rows:
        if not isinstance(row, CsvLine):
            raise ExportRejected("export is invalid")
        ids.extend((row.execution_id, row.case_run_id, row.case_version_id))
        rows.append(
            "<tr><td>"
            + html.escape(row.result_label)
            + "</td><td>"
            + html.escape(row.data_name)
            + "</td></tr>"
        )
    interim = "중간 보고" if snapshot.in_progress > 0 else "확정된 보고"
    condition = "조건 차이가 있습니다." if len(snapshot.fingerprints) > 1 else "조건 차이는 따로 표시합니다."
    document = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>인쇄 보고</title>
<style>
  .sheet {{ overflow: visible; max-height: none; }}
  table {{ border-collapse: collapse; width: 100%; table-layout: auto; }}
  td, th {{ overflow: visible; white-space: normal; word-break: break-word; }}
  @media (min-width: 1024px) {{ .sheet {{ overflow: visible; max-height: none; }} }}
  @media (min-width: 1440px) {{ .sheet {{ overflow: visible; max-height: none; }} }}
  @media print {{ .sheet {{ overflow: visible; max-height: none; }} }}
</style>
</head>
<body>
<section class="sheet">
  <h1>인쇄 보고</h1>
  <p>범위 {html.escape(snapshot.project_id)}</p>
  <p>기준 {html.escape(snapshot.criteria_version)} · 기준 시각 {snapshot.as_of}</p>
  <p>원본 {html.escape(", ".join(ids))}</p>
  <p>시각 {snapshot.as_of}</p>
  <p>{interim}</p>
  <p>{condition}</p>
  <p>정제된 근거는 링크로만 남고 경로는 보이지 않습니다.</p>
  <p>만료 시각은 내보내기 작업에 고정되어 있습니다.</p>
  <p>localhost 주소는 공개 공유가 아닙니다.</p>
  <p>PDF를 만들지 않습니다. 예약 발송은 없습니다.</p>
  <table>
    <tr><th>결과</th><th>내용</th></tr>
    {"".join(rows)}
  </table>
</section>
</body>
</html>
"""
    return SanitizedArtifact("text/html; charset=utf-8", "report.html", document.encode("utf-8"))
