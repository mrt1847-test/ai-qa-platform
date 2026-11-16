const fs=require('fs'),path=require('path'),assert=require('assert').strict;
const {chromium}=require(process.env.AIQA_PLAYWRIGHT_MODULE||'playwright');
const root=process.cwd(),out=path.join(root,'.review-work/mobile-agent-review-ui'),staticRoot=path.join(root,'src/aiqa/web/static');
(async()=>{
 const browser=await chromium.launch({channel:'chrome',headless:true});const report=[];
 try{
  for(const name of ['failed','completed','open','interrupted']){
   const html=fs.readFileSync(path.join(out,name+'.html'),'utf8'),timeline=JSON.parse(fs.readFileSync(path.join(out,name+'-timeline.json'),'utf8'));
   const assets=JSON.parse(fs.readFileSync(path.join(out,name+'-assets.json'),'utf8'));
   const match=html.match(/data-timeline-url="([^\"]+)"/);assert(match);
   const project=match[1].match(/projects\/([^/]+)/)[1],recordingPath='/ui/projects/'+project+'/recordings/'+timeline.recording_id;
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
     if(url.pathname===match[1])return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(timeline)});
     const artifact=assets[url.pathname.split('/').pop()];
     if(url.pathname.startsWith('/api/v1/artifacts/')&&artifact)return route.fulfill({status:200,contentType:artifact.media_type,body:Buffer.from(artifact.body_b64,'base64')});
     if(url.pathname==='/api/v1/session/csrf')return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({csrf_token:'synthetic-visual-only',project_id:project})});
     return route.fulfill({status:404,contentType:'application/json',body:'{}'});
    });
    await page.goto('http://127.0.0.1:18111'+recordingPath+'?action_id='+encodeURIComponent(timeline.selected_action_id||''));
    await page.waitForTimeout(2200);
    await page.locator('#recording-case-link').focus();
    if(['failed','completed','interrupted'].includes(name)){
     await page.keyboard.press('Tab');assert.equal(await page.evaluate(()=>document.activeElement.id),'recording-rerecord-link');
     if(name==='completed'){await page.keyboard.press('Tab');assert.equal(await page.evaluate(()=>document.activeElement.id),'recording-review-link');}
    }
    const shape=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,
      review:!!document.getElementById('recording-review-link'),selected:document.querySelector('[aria-current="step"]')?.getAttribute('data-timeline-action'),
      overflow:[...document.querySelectorAll('main *')].filter(e=>e.getBoundingClientRect().right>innerWidth+2).slice(0,6).map(e=>({tag:e.tagName,id:e.id,class:e.className,right:e.getBoundingClientRect().right}))}));
    await page.screenshot({path:path.join(out,name+'-'+width+'.png'),fullPage:true});
    report.push({name,...shape,errors,mutations});await context.close();
   }
  }
 }finally{await browser.close();}
 fs.writeFileSync(path.join(out,'browser-report.json'),JSON.stringify(report,null,2));
 console.log(JSON.stringify(report.map(r=>({name:r.name,width:r.width,scroll:r.scroll,review:r.review,errors:r.errors.length,mutations:r.mutations.length,overflow:r.scroll>r.width+1?r.overflow:[]}))));
 assert(report.every(r=>r.scroll<=r.width+1&&r.errors.length===0&&r.mutations.length===0),'visual/keyboard/overflow check failed');
})().catch(e=>{console.error(String(e));process.exitCode=1;});
