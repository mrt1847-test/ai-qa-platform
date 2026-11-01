import asyncio
import sqlite3
from uuid import uuid4
import httpx
from ux_support import ux_app,session
from acceptance.test_w18 import _graph


def test_settings_distinguishes_stored_cost_records_from_unknown_totals(ux_app):
    app,p,db=ux_app
    graph=_graph(db,p,str(uuid4()))
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO item_usage_facts(project_id,usage_id,case_run_id,commit_seq,role,measurement_status,amount,currency) VALUES(?,?,?,1,'verification','measured','3.15','USD')",(p,str(uuid4()),graph['trial']))
        c.execute("INSERT INTO usage_adjustments(project_id,adjustment_id,case_run_id,commit_seq,role,measurement_status,amount,currency) VALUES(?,?,?,2,'verification','unreported',NULL,NULL)",(p,str(uuid4()),graph['trial']))
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1') as c:
            await session(c,p)
            page=await c.get(f'/ui/projects/{p}/settings')
            assert page.status_code==200
            assert '누적 원본 비용 기록 1건 · 보정 기록 1건' in page.text
            assert '3.15 USD' in page.text and '금액 확인 전' in page.text
            assert '최종 누적 금액: 집계 연결 전' in page.text
            assert '3,000' in page.text and '시범 healing OFF' in page.text
    asyncio.run(run())
