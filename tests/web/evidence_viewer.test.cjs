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

function viewer({rejectFullscreen=false}={}) {
 const listeners={},note={textContent:''},image={naturalWidth:1080,width:1080,style:{}};
 const buttons=['fit','hundred','zoom','pan','full'].map(mode=>({
  textContent:mode,attrs:{'data-view-mode':mode,...(mode==='fit'?{'aria-current':'true'}:{})},
  getAttribute(name){return this.attrs[name];},setAttribute(name,value){this.attrs[name]=value;},
  removeAttribute(name){delete this.attrs[name];},addEventListener(name,fn){this[name]=fn;}
 }));
 const root={dataset:{view:'fit'},getAttribute(name){return name==='data-view'?this.dataset.view:'';},
  setAttribute(name,value){if(name==='data-view')this.dataset.view=value;},querySelector:()=>note,
  querySelectorAll:selector=>selector==='[data-view-mode]'?buttons:selector==='[data-view-mode="full"]'?[buttons[4]]:selector==='img'?[image]:[],
  addEventListener(name,fn){listeners[name]=fn;},requestFullscreen(){
   if(rejectFullscreen)return Promise.reject(new Error('unavailable'));
   doc.fullscreenElement=root;return Promise.resolve();
  }};
 const doc={fullscreenElement:null,getElementById:()=>root,exitFullscreen(){doc.fullscreenElement=null;return Promise.resolve();}};
 vm.runInNewContext(fs.readFileSync('src/aiqa/web/static/evidence_viewer.js','utf8'),
  {document:doc,window:{location:{search:'',pathname:'/evidence'},history:{replaceState(){}}},URLSearchParams});
 return {root,doc,image,buttons,note,listeners,async click(mode){buttons.find(b=>b.attrs['data-view-mode']===mode).click({preventDefault(){}});await new Promise(setImmediate);}};
}
test('fullscreen keeps fitted portrait images and the selected image mode',async()=>{
 const v=viewer();await v.click('full');
 assert.equal(v.root.dataset.view,'fit');assert.equal(v.image.style.width,undefined);
 assert.equal(v.buttons[0].attrs['aria-current'],'true');assert.equal(v.buttons[4].attrs['aria-current'],undefined);
 assert.equal(v.buttons[4].attrs['aria-expanded'],'true');
 v.doc.fullscreenElement=null;v.listeners.fullscreenchange();
 assert.equal(v.buttons[4].attrs['aria-expanded'],'false');assert.equal(v.root.dataset.view,'fit');
 await v.click('zoom');assert.equal(v.image.style.width,'1620px');
 await v.click('full');assert.equal(v.root.dataset.view,'zoom');assert.equal(v.image.style.width,'1620px');
 await v.click('fit');assert.equal(v.image.style.maxHeight,'100%');assert.equal(v.image.style.width,'');
});
test('unsupported native fullscreen falls back to an in-page view and can close',async()=>{
 const v=viewer({rejectFullscreen:true});await v.click('full');
 assert.equal(v.root.dataset.view,'fit');assert.equal(v.buttons[4].attrs['aria-expanded'],'true');
 assert.match(v.note.textContent,/브라우저 안에서 전체보기/);
 await v.click('full');assert.equal(v.buttons[4].attrs['aria-expanded'],'false');
});
