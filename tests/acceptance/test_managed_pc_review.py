"""Stored approval is a server operation, independent of live execution resources."""
import asyncio
import sqlite3
from uuid import uuid4

import httpx
import pytest

from acceptance.test_w19 import _graph
from ux_support import ux_app, session


@pytest.mark.parametrize('complete', [True, False])
def test_review_and_approval_without_execution_pc(ux_app, complete):
    app, project, database = ux_app
    case = str(uuid4())
    with sqlite3.connect(database) as connection:
        connection.execute("INSERT INTO automation_cases(project_id,case_id,name,next_revision,lock_version) VALUES(?,?,'Stored',2,0)", (project, case))
        graph = _graph()(connection, project, str(uuid4()), case, 1, 'stored-offline', script=complete)
        assert connection.execute('SELECT COUNT(*) FROM resource_inventory').fetchone()[0] == 0

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1') as client:
            headers = await session(client, project)
            page = await client.get(f'/ui/projects/{project}/cases/{case}/review')
            assert page.status_code == 200
            assert '실행 PC가 오프라인이어도' in page.text
            response = await client.post(f"/api/v1/case-versions/{graph['version']}/approvals", params={'project_id': project}, headers={**headers, 'Idempotency-Key': 'offline-approve'}, json={
                'review_id': graph['review'], 'version_hash': graph['version_hash'], 'evidence_set_hash': graph['evidence_hash'], 'expected_current_approval_id': None, 'reason': 'stored review',
            })
            assert response.status_code == (201 if complete else 422), response.text
    asyncio.run(exercise())
    with sqlite3.connect(database) as connection:
        assert connection.execute('SELECT COUNT(*) FROM approval_events').fetchone()[0] == (1 if complete else 0)
        assert connection.execute('SELECT COUNT(*) FROM jobs WHERE status="queued"').fetchone()[0] == 0
