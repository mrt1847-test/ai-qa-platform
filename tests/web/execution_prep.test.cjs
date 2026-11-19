const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
function host(){
  class N{
    constructor(){this.hidden=false;this.disabled=false;this.textContent='';this.children=[];this.attrs={};this.events={};}
    getAttribute(name){return this.attrs[name];}
    setAttribute(name,value){this.attrs[name]=String(value);}
    removeAttribute(name){delete this.attrs[name];}
    hasAttribute(name){return name in this.attrs;}
    addEventListener(type,fn){this.events[type]=fn;}
    replaceChildren(){this.children=[];}
    appendChild(node){this.children.push(node);}
    querySelector(selector){return selector==='[data-prep-confirmation]'?confirmation:null;}
    querySelectorAll(selector){
      if(selector==='[data-prep-panel]')return panels;
      if(selector==='[data-prep-step]')return steps;
      if(selector==='[data-prep-confirmation]')return confirmation;
      return [];
    }
  }
  const root=new N();root.attrs={'data-prep':''};
  const panels=[1,2,3,4].map(n=>{const p=new N();p.attrs={'data-prep-panel':String(n)};return p;});
  const steps=[1,2,3,4].map(n=>{const b=new N();b.attrs={'data-prep-step':String(n)};return b;});
  const confirmation=new N();
  const context={document:{querySelector:()=>root,createElement:()=>new N()},window:{}};
  vm.runInNewContext(fs.readFileSync('src/aiqa/web/static/execution_prep.js','utf8'),context);
  return {root,panels,steps,confirmation,prep:context.window.aiqaPrep};
}
test('final confirmation stays closed until the server preview is ready',()=>{
  const h=host();
  assert.equal(h.panels[0].hidden,false);
  assert.equal(h.panels[3].hidden,true);
  h.root.events.click({target:{getAttribute:()=>null,hasAttribute:name=>name==='data-prep-next'}});
  assert.equal(h.panels[1].hidden,false);
  h.root.events.click({target:{getAttribute:()=>null,hasAttribute:name=>name==='data-prep-next'}});
  h.root.events.click({target:{getAttribute:()=>null,hasAttribute:name=>name==='data-prep-next'}});
  assert.equal(h.panels[3].hidden,true);
  h.prep.showFinal({confirmation:{failure_policy:'continue',release_label:'2026.11',actor_call_cap:0,items:[{entry_id:'case-1',case_version_id:'v1',approval_id:'ap1',environment_revision_id:'env',resource_id:'device',dataset_version_id:null,reset_policy:'none',verifier_method:'deterministic',execution_limits:{max_actions:50,max_model_calls:4,timeout_seconds:600,budget:'2.00',currency:'USD'},healing_enabled:false,healing_limits:{}}]}});
  assert.equal(h.panels[3].hidden,false);
  assert.match(h.confirmation.children[0].textContent,/실제 비용이 아닙니다/);
  const text=h.confirmation.children[1].children.map(row=>row.children.map(part=>part.textContent).join(' ')).join('\n');
  assert.match(text,/행동 AI 예상 호출 상한 0/);
  assert.match(text,/검증 호출 상한 4/);
  assert.match(text,/복구 꺼짐/);
});
test('arrow keys move between the open steps and edit returns to the target',()=>{
  const h=host();
  h.steps[0].closest=()=>true;
  h.root.events.keydown({key:'ArrowRight',preventDefault(){},target:h.steps[0]});
  assert.equal(h.panels[1].hidden,false);
  h.root.events.click({target:{getAttribute:()=>null,hasAttribute:name=>name==='data-prep-edit'}});
  assert.equal(h.panels[0].hidden,false);
});
