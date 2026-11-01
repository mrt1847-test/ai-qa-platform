from uuid import UUID, uuid4
import pytest
from ux_support import ux_app
from aiqa.domain.catalog import bind_catalog_actor, bind_catalog_store, list_cases
from aiqa.domain.versions import bind_case_store, create_case
from aiqa.store.models import Actor, CaseListQuery


def test_catalog_exact_total_and_previous_cursor_stay_in_filter(ux_app):
    app, project, _ = ux_app
    store = app.state.open_store()
    actor = Actor(uuid4(), UUID(project), True)
    with bind_case_store(store):
        for i in range(32):
            create_case(actor, f'주문 {i:03}', None)
        other = create_case(actor, '다른 조건', None)
    with bind_catalog_store(store), bind_catalog_actor(actor):
        query = dict(project_id=UUID(project), text='주문', limit=10)
        first = list_cases(CaseListQuery(**query))
        second = list_cases(CaseListQuery(**query, cursor=first.next_cursor))
        third = list_cases(CaseListQuery(**query, cursor=second.next_cursor))
        previous = list_cases(CaseListQuery(**query, cursor=third.previous_cursor))
        assert first.total == second.total == third.total == 32
        assert (second.start, second.end) == (11, 20)
        assert previous.items == second.items
        assert all(row.target_kind is None and row.latest_result is None for row in first.items)
        with pytest.raises(ValueError):
            list_cases(CaseListQuery(**query, cursor=str(other.case_id)))
    store.close()
