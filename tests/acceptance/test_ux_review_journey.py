import asyncio
import sqlite3
from uuid import UUID, uuid4
import httpx
from ux_support import ux_app, session
from acceptance.test_w18 import _graph


def test_review_setup_offers_exact_stored_source_and_trial_without_mutation(ux_app, monkeypatch):
    app,p,db=ux_app
    sequence = 0
    def deterministic_id():
        nonlocal sequence
        sequence += 1
        # Equal timestamps must not let a lower UUID select the healed trial.
        return UUID(int=1 if sequence == 9 else 900000 if sequence == 7 else 1000 + sequence)
    monkeypatch.setattr('acceptance.test_w18.uuid4', deterministic_id)
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


def test_readiness_keeps_the_trial_pinned_by_review(ux_app):
    from aiqa.api.cases import load_review_readiness

    _, project_id, database = ux_app
    graph = _graph(database, project_id, str(uuid4()))
    with sqlite3.connect(database) as connection:
        # Another completed candidate must not replace an existing snapshot.
        connection.execute("INSERT INTO item_finalizations(project_id,case_run_id,created_seq,finalized_seq,release_label,content_hash,core_result,denominator) VALUES(?,?,1,2,'synthetic','hash','INCONCLUSIVE',1)", (project_id, graph['foreign']))
        connection.execute('''INSERT INTO reviews(project_id,review_id,case_id,case_version_id,
            version_hash,source_manifest_id,trial_case_run_id,evidence_set_hash,created_commit_seq)
            VALUES(?,?,?,?,?,?,?,?,1)''', (project_id, str(uuid4()), graph['case'], graph['version'],
            'version-hash', graph['manifest'], graph['trial'], 'evidence'))
        readiness = load_review_readiness(connection, UUID(project_id), UUID(graph['version']))
    assert readiness['trial_owner_id'] == graph['trial']
    assert readiness['trial_off'] is True
