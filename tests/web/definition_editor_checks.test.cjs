const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function makeNode(){
  return {children:[],listeners:{},value:'',textContent:'',hidden:false,disabled:false,rows:0,readOnly:false,
    setAttribute(){},appendChild(child){this.children.push(child);return child},
    addEventListener(type,fn){this.listeners[type]=fn},replaceChildren(){this.children=[]},
    dispatchEvent(event){if(this.listeners[event.type])this.listeners[event.type]()}};
}
test('definition editor saves a screen-meaning assertion instead of a text comparison',()=>{
  const ids={};
  function byId(id){if(!ids[id])ids[id]=makeNode();return ids[id];}
  const form=byId('definition-form');
  form.elements={raw_text:{value:'주문'},namedItem:()=>({value:''})};
  form.action='/ui/projects/p/cases/c/definition';
  const snapshot={definition:{raw_text:'주문',objective:'주문',preconditions:[],variables:{},secret_refs:{},steps:[],final_expected:[],path_policy:{must_use:[],forbidden:[]}},recorded_steps:[],settings:{verifier_method:'ai_visual'}};
  byId('definition-snapshot').textContent=JSON.stringify(snapshot);
  byId('expected-head').value='head';
  const context={Event:class Event{constructor(type){this.type=type}},window:{},document:{getElementById:byId,createElement:()=>makeNode()},crypto:{randomUUID:()=>'check-1'}};
  vm.runInNewContext(fs.readFileSync('src/aiqa/web/static/definition_model.js','utf8'),context);
  const real=context.window.aiqaDefinitionModel;let live;
  context.window.aiqaDefinitionModel=function(snapshot){live=real(snapshot);return live;};
  context.window.aiqaForms={register(){}};
  context.window.aiqaRequest=async()=>({ok:true,json:async()=>({refs:[]})});
  vm.runInNewContext(fs.readFileSync('src/aiqa/web/static/definition_editor.js','utf8'),context);
  byId('add-final-check').listeners.click();
  const line=byId('definition-final-checks').children[0];
  const select=line.children.find(child=>child.listeners.change);
  assert.equal(select.value,'text');
  select.value='visual';select.listeners.change();
  assert.equal(live.data.definition.final_expected[0].kind,'visual');
  const hint=byId('definition-final-checks').children[0].children.map(child=>child.textContent).join(' ');
  assert.match(hint,/성공으로 처리하지 않습니다/);
});
