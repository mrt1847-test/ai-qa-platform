"""CSV export keeps original ids and leaves formula text inert."""

from __future__ import annotations

import csv
import io
import sqlite3
from pathlib import Path
from uuid import uuid4


def test_w25_02(tmp_path: Path) -> None:
    import asyncio

    from aiqa.api.app import create_app
    from aiqa.config import load_settings
    from aiqa.domain.analytics import ReportSnapshot
    from aiqa.domain.exports import CsvLine, render_report_csv
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.store.database import migrate_store
    from aiqa.store.models import Actor, ProjectCreate

    secret = "csv-secret-plain"
    hidden = "csv-secret-ref"
    reasoning = "내부 추론 원문"
    path = r"C:\hidden\evidence.png"
    execution_id, run_id, version_id = "run-1", "item-1", "version-1"
    line = CsvLine(
        execution_id,
        run_id,
        version_id,
        "=데이터",
        "+환경",
        "-빌드",
        "@실패",
        "1",
        "0.5",
        "0.5",
        "1",
        "한글 \"인용\"\n다음",
        "\t=치유",
        None,
        "권한 없음",
        secret,
        hidden,
        reasoning,
        path,
    )
    snapshot = ReportSnapshot("project", 15, "criteria-1", 1, 0, 1, (), None, (), (line,))
    artifact = render_report_csv(snapshot)
    text = artifact.body.decode("utf-8")
    parsed = list(csv.reader(io.StringIO(text)))
    cells = parsed[1]
    observed = {
        "formula_injection_safe": all(not _formula(cell) for cell in cells),
        "korean_roundtrip": cells[11] == "한글 \"인용\"\n다음",
        "secret_plaintext": secret in text or hidden in text or reasoning in text or path in text,
        "original_ids_present": execution_id in cells and run_id in cells and version_id in cells,
    }
    assert cells[13] == "" and cells[16] == "권한 없음" and cells[14] == "15" and cells[15] == "criteria-1"
    assert artifact.media_type == "text/csv; charset=utf-8"
    root = tmp_path / "runtime"
    app = create_app(load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}))
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("표", "w2502", "csv", "web"))
    store.close()
    project_id = str(project.project_id)
    execution = _empty_execution(root / "db" / "aiqa.sqlite", project_id)
    page = asyncio.run(_page(app, project_id, execution))
    assert "CSV로 내보냅니다" in page and "수식 시작 문자" in page and "한글과 줄바꿈은 유지합니다" in page
    assert "원본 수행" in page and "기준 시각" in page and "비밀 원문" in page
    assert observed == {
        "formula_injection_safe": True,
        "korean_roundtrip": True,
        "secret_plaintext": False,
        "original_ids_present": True,
    }


def _formula(cell: str) -> bool:
    if cell == "":
        return False
    probe = cell.lstrip(" \t\r\n")
    return cell[0] in "\t\r\n" or probe[:1] in "=+-@"


def _empty_execution(database: Path, project_id: str) -> str:
    execution_id = str(uuid4())
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO executions (project_id, execution_id, name, purpose, source, suite_version_id, scope_requested_at)
            VALUES (?, ?, '빈 보고', 'regression', 'selection', NULL, '2026-11-01T00:00:00+00:00')
            """,
            (project_id, execution_id),
        )
    return execution_id


async def _page(app: object, project_id: str, execution_id: str) -> str:
    import httpx

    origin = "http://127.0.0.1"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        await _session(client, origin, project_id, "w2502")
        page = await client.get(f"/ui/projects/{project_id}/executions/{execution_id}/report")
    assert page.status_code == 200, page.text
    return page.text


async def _session(client: object, origin: str, project_id: str, key: str) -> dict[str, str]:
    issued = await client.post(  # type: ignore[attr-defined]
        "/api/v1/session/nonces",
        json={"origin": origin, "project_id": project_id},
        headers={"Idempotency-Key": key + "-nonce", "Origin": origin},
    )
    booted = await client.post(  # type: ignore[attr-defined]
        "/api/v1/session/bootstrap",
        json={"nonce": issued.json()["nonce"]},
        headers={"Idempotency-Key": key + "-boot", "Origin": origin},
    )
    client.cookies.set("aiqa_session", booted.cookies["aiqa_session"])  # type: ignore[attr-defined]
    return {"Origin": origin, "X-CSRF-Token": booted.json()["csrf_token"], "Idempotency-Key": key}


def test_w25_03(tmp_path: Path) -> None:
    import asyncio

    from aiqa.api.app import create_app
    from aiqa.config import load_settings
    from aiqa.domain.analytics import ReportSnapshot
    from aiqa.domain.exports import CsvLine, render_report_html
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.store.database import migrate_store
    from aiqa.store.models import Actor, ProjectCreate

    long_text = "한글" * 80
    line = CsvLine(
        "run-1",
        "item-1",
        "version-1",
        "<script>alert(1)</script>" + long_text,
        "env",
        "build",
        "실패",
        None,
        None,
        None,
        "0",
        "원래",
        "없음",
        None,
        "권한 없음",
    )
    snapshot = ReportSnapshot("project", 15, "criteria-1", 1, 1, 0, (), None, ("a", "b"), (line,))
    artifact = render_report_html(snapshot)
    html = artifact.body.decode("utf-8")
    root = tmp_path / "runtime"
    app = create_app(load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}))
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("인쇄", "w2503", "html", "web"))
    store.close()
    project_id = str(project.project_id)
    execution = _empty_execution(root / "db" / "aiqa.sqlite", project_id)
    report, printed, exported = asyncio.run(_print_flow(app, project_id, execution))
    observed = {
        "html_escaped": "&lt;script&gt;" in html and "<script>" not in html and long_text in html,
        "print_core_fields_clipped": "overflow: hidden" in html
        or "text-overflow" in html
        or long_text not in html
        or any(label not in html for label in ("범위", "기준", "원본", "시각", "중간 보고", "만료")),
        "localhost_public_claim": "공개로 공유합니다" in html or "공개로 공유합니다" in printed,
        "automatic_pdf": artifact.media_type == "application/pdf" or artifact.body.startswith(b"%PDF"),
    }
    assert exported["phase"] == "만료" and exported["expired_reason"] == "파일이 만료되었습니다"
    assert "인쇄 HTML" in report and "다운로드" in report and "진행" in report and "완료" in report and "실패" in report
    assert "@media print" in printed and "min-width: 1024px" in printed and "min-width: 1440px" in printed
    assert observed == {
        "html_escaped": True,
        "print_core_fields_clipped": False,
        "localhost_public_claim": False,
        "automatic_pdf": False,
    }


async def _print_flow(app: object, project_id: str, execution_id: str):
    import httpx

    origin = "http://127.0.0.1"
    body = {
        "format": "printable_html",
        "as_of": 15,
        "criteria_version": "criteria-1",
        "filters": {"purpose": "regression"},
        "cohort": "strict",
        "expires_at": "2026-10-01T00:00:00+00:00",
    }
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        headers = await _session(client, origin, project_id, "w2503")
        created = await client.post(
            f"/api/v1/executions/{execution_id}/exports",
            params={"project_id": project_id},
            headers=headers,
            json=body,
        )
        assert created.status_code == 201, created.text
        job_id = created.json()["job_id"]
        exported = await client.get(
            f"/api/v1/exports/{job_id}",
            params={"project_id": project_id},
            headers=headers,
        )
        report = await client.get(f"/ui/projects/{project_id}/executions/{execution_id}/report")
        printed = await client.get(
            f"/ui/projects/{project_id}/executions/{execution_id}/report/print",
            params={"body": "<script>alert(1)</script>"},
        )
    assert exported.status_code == 200, exported.text
    assert report.status_code == 200, report.text
    assert printed.status_code == 200, printed.text
    assert "&lt;script&gt;" in printed.text and "<script>" not in printed.text
    return report.text, printed.text, exported.json()
