import asyncio
from html.parser import HTMLParser
import httpx
from ux_support import ux_app,session

class Forms(HTMLParser):
    def __init__(self): super().__init__();self.actions=[]
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='form' and attrs.get('method','get').lower()=='get': self.actions.append(attrs.get('action'))

def test_catalog_page_links_preserve_supported_limit_and_archived_scope(ux_app):
    app,p,_=ux_app
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1') as c:
            h=await session(c,p)
            for i in range(2):await c.post(f'/api/v1/projects/{p}/cases',json={'name':f'회귀 {i}'},headers={**h,'Idempotency-Key':f'case{i}'})
            page=await c.get(f'/ui/projects/{p}/cases',params={'q':'회귀','limit':1,'archived':'false'})
            class Links(HTMLParser):
                def __init__(self):super().__init__();self.hrefs=[]
                def handle_starttag(self,tag,attrs):
                    if tag=='a':self.hrefs.append(dict(attrs).get('href',''))
            links=Links();links.feed(page.text)
            next_link=next(link for link in links.hrefs if 'cursor=' in link)
            assert 'limit=1' in next_link and 'archived=false' in next_link
            next_page=await c.get(next_link)
            assert next_page.status_code==200 and '전체 2개 중 2–2' in next_page.text
    asyncio.run(run())

def test_project_search_stays_in_actual_project_and_uses_actual_cases(ux_app):
    app,p,_=ux_app
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1') as c:
            h=await session(c,p)
            await c.post(f'/api/v1/projects/{p}/cases',json={'name':'로그인 확인'},headers=h)
            page=await c.get(f'/ui/projects/{p}/environments/editor')
            forms=Forms();forms.feed(page.text)
            assert f'/ui/projects/{p}/cases' in forms.actions
            assert '/ui/shell' not in forms.actions
            found=await c.get(f'/ui/projects/{p}/cases',params={'q':'로그인'})
            assert '로그인 확인' in found.text
            empty=await c.get(f'/ui/projects/{p}/cases',params={'q':'does-not-exist'})
            assert '로그인 확인' not in empty.text
    asyncio.run(run())
