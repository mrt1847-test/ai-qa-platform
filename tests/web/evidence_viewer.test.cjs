const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
for(const promised of [true,false])test('fullscreen provides explicit exit with promise='+promised,async()=>{
 let click,requests=0,exits=0;const listeners={};
 const full={textContent:'전체보기',getAttribute:()=> 'full',setAttribute(){},removeAttribute(){},addEventListener:(name,fn)=>{click=fn;}};
 const doc={fullscreenElement:null,getElementById:()=>root,exitFullscreen:()=>{exits++;doc.fullscreenElement=null;return promised?Promise.resolve():undefined;}};
 const root={dataset:{},setAttribute(){},getAttribute:()=>'',querySelector:()=>({textContent:''}),querySelectorAll:selector=>selector==='[data-view-mode]'||selector==='[data-view-mode="full"]'?[full]:[],addEventListener:(name,fn)=>listeners[name]=fn,requestFullscreen:()=>{requests++;doc.fullscreenElement=root;return promised?Promise.resolve():undefined;}};
 const ctx={document:doc,window:{location:{search:'',pathname:'/evidence'},history:{replaceState(){}}},URLSearchParams};
 vm.runInNewContext(fs.readFileSync('src/aiqa/web/static/evidence_viewer.js','utf8'),ctx);
 click({preventDefault(){}});await Promise.resolve();if(listeners.fullscreenchange)listeners.fullscreenchange();
 assert.equal(requests,1);assert.equal(full.textContent,'전체보기 닫기');click({preventDefault(){}});await Promise.resolve();assert.equal(exits,1);
});
