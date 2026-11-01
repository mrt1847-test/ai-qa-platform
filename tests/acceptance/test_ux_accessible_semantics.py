import asyncio
from html.parser import HTMLParser
from uuid import UUID,uuid4
import httpx
from ux_support import ux_app,session
from aiqa.domain.versions import bind_case_store,create_case
from aiqa.store.models import Actor

class Controls(HTMLParser):
    def __init__(self):super().__init__();self.labels=[];self.depth=0;self.controls=[];self.ids=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if a.get('id'):self.ids.append(a['id'])
        if tag=='label':self.depth+=1;self.labels.append(a.get('for'))
        if tag in {'input','textarea','select'} and a.get('type') not in {'hidden','submit','button'}:
            self.controls.append((a,self.depth>0))
    def handle_endtag(self,tag):
        if tag=='label':self.depth-=1

def test_authoring_pages_expose_labels_and_unique_ids(ux_app):
    app,p,_=ux_app
    store=app.state.open_store()
    with bind_case_store(store):case=create_case(Actor(uuid4(),UUID(p),True),'키보드 케이스',None)
    store.close()
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1') as c:
            await session(c,p)
            for suffix in ['cases','settings','environments/editor','datasets','recordings/wizard',f'cases/{case.case_id}/definition',f'cases/{case.case_id}/execution-setup',f'cases/{case.case_id}/settings',f'cases/{case.case_id}/review']:
                page=await c.get(f'/ui/projects/{p}/{suffix}');assert page.status_code==200,(suffix,page.text)
                parser=Controls();parser.feed(page.text)
                assert len(parser.ids)==len(set(parser.ids)),suffix
                for attrs,wrapped in parser.controls:
                    assert wrapped or attrs.get('aria-label') or attrs.get('aria-labelledby') or attrs.get('id') in parser.labels,(suffix,attrs)
    asyncio.run(run())
