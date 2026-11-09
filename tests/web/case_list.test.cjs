const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
function selectionPage(size=3){
  class N{constructor(){this.checked=false;this.disabled=false;this.events={};this.attributes={};}addEventListener(e,fn){this.events[e]=fn;}setAttribute(k,v){this.attributes[k]=v;}removeAttribute(k){delete this.attributes[k];delete this[k];}fire(e){this.events[e]();}}
  const nodes={'select-page':new N(),'clear-selection':new N(),'selection-count':new N(),'selected-trial':new N(),'selected-regression':new N()};
  const boxes=Array.from({length:size},(_,i)=>Object.assign(new N(),{value:'case-'+i}));
  const ctx={document:{getElementById:id=>nodes[id],querySelectorAll:s=>s.includes('input[name="selected"]')?boxes:[]},window:{addEventListener(){}},location:{pathname:'/ui/projects/project/cases'},URLSearchParams};
  vm.runInNewContext(fs.readFileSync('src/aiqa/web/static/case_list.js','utf8'),ctx);
  return {nodes,boxes,select(ids){boxes.forEach((box,i)=>box.checked=ids.includes(i));boxes[0].fire('change');}};
}
test('selected regression link contains only current page selections and clearing removes it',()=>{
  const h=selectionPage();h.select([0,2]);
  const link=new URL(h.nodes['selected-regression'].href,'http://localhost');
  assert.equal(link.pathname,'/ui/projects/project/execution-setup');
  assert.deepEqual(link.searchParams.getAll('case_id'),['case-0','case-2']);
  assert.equal(h.nodes['selected-trial'].attributes['aria-disabled'],'true');
  h.nodes['clear-selection'].fire('click');
  assert.equal(h.nodes['selected-regression'].href,undefined);
});
test('more than 100 selected cases cannot generate a formal run link',()=>{
  const h=selectionPage(101);h.nodes['select-page'].checked=true;h.nodes['select-page'].fire('change');
  assert.equal(h.nodes['selected-regression'].attributes['aria-disabled'],'true');
  assert.equal(h.nodes['selected-regression'].href,undefined);
});
