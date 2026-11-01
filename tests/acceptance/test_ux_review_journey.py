import asyncio
import sqlite3
from uuid import uuid4
import httpx
from ux_support import ux_app, session
from acceptance.test_w18 import _graph


def test_review_setup_offers_exact_stored_source_and_trial_without_mutation(ux_app):
    app,p,db=ux_app
    graph=_graph(db,p,str(uuid4()))
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO item_finalizations(project_id,case_run_id,created_seq,finalized_seq,release_label,content_hash,core_result,denominator) VALUES(?,?,1,2,'synthetic','hash','INCONCLUSIVE',1)",(p,graph['trial']))
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1') as c:
            h=await session(c,p)
            page=await c.get(f'/ui/projects/{p}/cases/{graph["case"]}/review')
            assert page.status_code==200
            assert 'id="request-review"' in page.text
            assert graph['trial'] in page.text
            assert graph['healed'] not in page.text
            missing=await c.get(f'/ui/projects/{p}/cases/{graph["case"]}/review',params={'entry':str(uuid4())})
            assert missing.status_code==404
    asyncio.run(run())
    with sqlite3.connect(db) as c: assert c.execute('SELECT count(*) FROM reviews').fetchone()[0]==0
