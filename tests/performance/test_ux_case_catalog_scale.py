import json
import platform
import time
from uuid import UUID, uuid4
from ux_support import ux_app
from aiqa.domain.catalog import bind_catalog_actor, bind_catalog_store, list_cases
from aiqa.domain.versions import bind_case_store, create_case
from aiqa.store.models import Actor, CaseListQuery


def test_catalog_3000_keeps_bounded_pages_and_constant_query_count(ux_app, tmp_path):
    app,p,_=ux_app
    actor=Actor(uuid4(),UUID(p),True);store=app.state.open_store()
    with bind_case_store(store):
        for i in range(3000): create_case(actor,f'회귀 주문 {i:04}',None)
    times=[];counts=[]
    with bind_catalog_store(store), bind_catalog_actor(actor):
        for _ in range(21):
            statements=[];store._connection.set_trace_callback(statements.append)
            start=time.perf_counter();page=list_cases(CaseListQuery(UUID(p),text='주문'))
            times.append(time.perf_counter()-start);counts.append(len([s for s in statements if s.lstrip().upper().startswith(('SELECT','WITH'))]))
            store._connection.set_trace_callback(None)
            assert page.total==3000 and len(page.items)==25
        seen=set();cursor=None
        while True:
            page=list_cases(CaseListQuery(UUID(p),text='주문',cursor=cursor))
            assert not (seen & {row.case_id for row in page.items})
            seen.update(row.case_id for row in page.items)
            if page.next_cursor is None: break
            cursor=page.next_cursor
        assert len(seen)==3000 and page.end==3000
    p95=sorted(times[1:])[18]
    result={'platform':platform.platform(),'python':platform.python_version(),'rows':3000,'page_size':25,'warm_samples':20,'p95_seconds':p95,'max_page_queries':max(counts),'missing_or_duplicate':0}
    (tmp_path/'catalog-metrics.json').write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))
    assert p95<1 and max(counts)<=7
    store.close()
