// Actual SSR/static assets plus local saved API/artifact fixtures. Never a user browser profile.
const fs=require('fs'),path=require('path'),assert=require('assert').strict;
const {chromium}=require(process.env.AIQA_PLAYWRIGHT_MODULE||'playwright');
const root=process.cwd(),fixtures=path.join(root,'.review-work/mobile-agent-review-ui'),out=path.join(root,'.review-work/mobile-agent-timeline-ui/visual'),staticRoot=path.join(root,'src/aiqa/web/static');
fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({channel:'chrome',headless:true}),report=[];
 try{
  for(const scene of ['failed','completed','open','interrupted','attack','stale']){
   const name=scene==='attack'?'failed':scene==='stale'?'timeline-legacy':scene;
   const html=fs.readFileSync(path.join(fixtures,name+'.html'),'utf8'),timeline=JSON.parse(fs.readFileSync(path.join(fixtures,name+'-timeline.json'),'utf8'));
   const assets=JSON.parse(fs.readFileSync(path.join(fixtures,name+'-assets.json'),'utf8'));
   if(scene==='attack'){
    timeline.actions[timeline.actions.length-1].error_text='<img src="/timeline-xss" onerror="window.__timelineInjected=true">';
    timeline.actions[timeline.actions.length-1].step_id='<svg onload="window.__timelineInjected=true">';
   }
   const api=html.match(/data-timeline-url="([^\"]+)"/)[1],project=api.match(/projects\/([^/]+)/)[1],recordingPath='/ui/projects/'+project+'/recordings/'+timeline.recording_id;
   for(const width of [360,768,1440]){
    const context=await browser.newContext({viewport:{width,height:1000}}),page=await context.newPage(),errors=[],mutations=[];
    page.on('pageerror',e=>errors.push(String(e)));
    await page.route('**/*',async route=>{
     const request=route.request(),url=new URL(request.url());
     if(request.method()!=='GET'){mutations.push(request.method()+' '+url.pathname);return route.fulfill({status:405,body:''});}
     if(url.pathname.startsWith('/static/')){
      const file=path.resolve(staticRoot,decodeURIComponent(url.pathname.slice(8)));
      if(!file.startsWith(staticRoot+path.sep)||!fs.existsSync(file))return route.fulfill({status:404,body:''});
      return route.fulfill({status:200,contentType:file.endsWith('.css')?'text/css':'application/javascript',body:fs.readFileSync(file)});
     }
     if(url.pathname===recordingPath)return route.fulfill({status:200,contentType:'text/html',body:html});
     if(url.pathname===api)return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(timeline)});
     const artifact=assets[url.pathname.split('/').pop()];
     if(url.pathname.startsWith('/api/v1/artifacts/')&&artifact)return route.fulfill({status:200,contentType:artifact.media_type,body:Buffer.from(artifact.body_b64,'base64')});
     if(url.pathname==='/api/v1/session/csrf')return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({csrf_token:'synthetic-visual-only',project_id:project})});
     return route.fulfill({status:404,contentType:'application/json',body:'{}'});
    });
    const selection=scene==='stale'?'missing-selection':timeline.selected_action_id||'';
    await page.goto('http://127.0.0.1:18111'+recordingPath+'?action_id='+encodeURIComponent(selection));
    const labels=await page.locator('#recording-timeline [data-action-label]').allTextContents();
    const links=page.locator('#recording-timeline [data-timeline-action]');
    const focused=await links.count()?await links.last().getAttribute('data-timeline-action'):null;
    if(focused)await links.last().focus();
    await page.waitForTimeout(2200);
    const shape=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,
      injected:window.__timelineInjected===true,focused:document.activeElement.getAttribute('data-timeline-action'),
      selected:document.querySelector('#recording-timeline [aria-current="step"]')?.getAttribute('data-timeline-action')||'',
      labels:[...document.querySelectorAll('#recording-timeline [data-action-label]')].map(e=>e.textContent),
      stateLabels:[...document.querySelectorAll('#recording-timeline [data-dispatch]')].map(e=>e.textContent)}));
    assert.deepEqual(shape.labels,labels,'SSR and poll labels differ');
    assert.equal(shape.selected,timeline.selected_action_id||'','server canonical selection lost');
    if(focused)assert.equal(shape.focused,focused,'poll removed keyboard focus');
    assert.equal(shape.injected,false,'timeline HTML executed');
    if(await page.locator('#recording-rerecord-link').count()){
     await page.locator('#recording-case-link').focus();await page.keyboard.press('Tab');
     assert.equal(await page.evaluate(()=>document.activeElement.id),'recording-rerecord-link');
     if(await page.locator('#recording-review-link').count()){await page.keyboard.press('Tab');assert.equal(await page.evaluate(()=>document.activeElement.id),'recording-review-link');}
    }
    await page.screenshot({path:path.join(out,scene+'-'+width+'.png'),fullPage:true});
    report.push({scene,...shape,errors,mutations});await context.close();
   }
  }
 }finally{await browser.close();}
 fs.writeFileSync(path.join(out,'browser-report.json'),JSON.stringify(report,null,2));
 console.log(JSON.stringify(report.map(r=>({scene:r.scene,width:r.width,scroll:r.scroll,injected:r.injected,selected:r.selected,errors:r.errors.length,mutations:r.mutations.length}))));
 assert(report.every(r=>r.scroll<=r.width+1&&r.errors.length===0&&r.mutations.length===0),'visual/runtime check failed');
})().catch(e=>{console.error(String(e));process.exitCode=1;});
