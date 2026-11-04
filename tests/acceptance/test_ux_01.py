"""UX-01: restore suites / executions / reports navigation to existing GET pages."""

from __future__ import annotations

import asyncio
from html.parser import HTMLParser
from uuid import uuid4

import httpx

from aiqa.domain.projects import bind_store, create_project
from aiqa.store.database import migrate_store
from aiqa.store.models import Actor, ProjectCreate
from ux_support import session, ux_app


class _Nav(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []
        self.current: list[str] = []
        self.crumbs: list[str] = []
        self.skip = False
        self._in_project_nav = False
        self._in_crumb = False
        self._capture_current = False
        self._buf = ""

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "nav" and attrs.get("aria-label") == "프로젝트 메뉴":
            self._in_project_nav = True
        if tag == "nav" and attrs.get("aria-label") == "경로":
            self._in_crumb = True
        if tag == "a" and attrs.get("href") == "#content" and "skip" in attrs.get("class", ""):
            self.skip = True
        if tag == "a" and "href" in attrs:
            href = attrs["href"]
            if self._in_project_nav:
                self.hrefs.append(href)
            if self._in_crumb:
                self.crumbs.append(href)
            if attrs.get("aria-current") == "page":
                self.current.append(href)
                self._capture_current = True
                self._buf = ""

    def handle_endtag(self, tag):
        if tag == "nav":
            self._in_project_nav = False
            self._in_crumb = False
        if tag == "a" and self._capture_current:
            self._capture_current = False

    def handle_data(self, data):
        if self._capture_current:
            self._buf += data


def test_suites_runs_reports_nav_reaches_existing_pages(ux_app) -> None:
    app, project_id, _ = ux_app
    other = _other_project(app)
    before = _execution_count(app, project_id)
    asyncio.run(_exercise(app, project_id, other))
    assert _execution_count(app, project_id) == before


async def _exercise(app, project_id: str, other_id: str) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        await session(client, project_id)
        home = await client.get(f"/ui/projects/{project_id}/overview")
        assert home.status_code == 200
        nav = _Nav()
        nav.feed(home.text)
        assert f"/ui/projects/{project_id}/suites" in nav.hrefs
        assert f"/ui/projects/{project_id}/executions" in nav.hrefs
        assert f"/ui/projects/{project_id}/reports" in nav.hrefs
        assert "nav-unavailable" not in home.text

        paths = {
            "suites": (f"/ui/projects/{project_id}/suites", "테스트 묶음", "묶음이 없습니다."),
            "runs": (f"/ui/projects/{project_id}/executions", "테스트 수행", "수행이 없습니다."),
            "reports": (
                f"/ui/projects/{project_id}/reports",
                "리포트",
                "조건에 맞는 수행이 없습니다.",
            ),
        }
        for key, (url, crumb_label, empty) in paths.items():
            page = await client.get(url)
            assert page.status_code == 200, (key, page.text)
            parsed = _Nav()
            parsed.feed(page.text)
            assert parsed.skip is True, key
            assert any(href.endswith(url.split(project_id, 1)[-1]) for href in parsed.current) or any(
                url.endswith(href.split(project_id, 1)[-1]) for href in parsed.current
            ), (key, parsed.current)
            assert crumb_label in page.text
            assert empty in page.text
            assert 'aria-label="경로"' in page.text
            assert 'href="#content"' in page.text

        foreign = await client.get(f"/ui/projects/{other_id}/suites")
        assert foreign.status_code == 403


def _other_project(app) -> str:
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(
            Actor(uuid4(), None, True), ProjectCreate("Other", "other", "x", "web")
        )
    store.close()
    return str(project.project_id)


def _execution_count(app, project_id: str) -> int:
    store = app.state.open_store()
    try:
        row = store._connection.execute(
            "SELECT count(*) FROM executions WHERE project_id=?", (project_id,)
        ).fetchone()
        return int(row[0])
    finally:
        store.close()
