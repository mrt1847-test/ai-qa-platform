const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
function host(request, count=2, selection=false) {
  class N {
    constructor(value=''){this.value=value;this.disabled=false;this.textContent='';this.children=[];this.events={};}
    addEventListener(type,fn){this.events[type]=fn;}
    replaceChildren(){this.children=[];}
    appendChild(node){this.children.push(node);}
    async fire(type){if(this.events[type])await this.events[type]({preventDefault(){}});}
  }
  const fields={name:new N('월간 회귀'),failure_policy:new N('stop_on_non_pass'),release_label:new N('v1')};
  const form=new N();form.dataset={project:'p',version:'saved-v1',count:String(count)};
  form.elements={namedItem:n=>fields[n]};
  const rows=Array.from({length:count},(_,i)=>{const row=new N();row.dataset={entryId:'case-'+i,version:'approved-'+i,approval:'approval-'+i};const rowFields={environment_revision_id:new N('env-'+i),resource_id:new N('resource-'+i),dataset_version_id:new N('')};row.querySelector=s=>rowFields[s.match(/name="([^"]+)"/)[1]];return row;});
  form.querySelectorAll=s=>s==='[data-execution-item]'?rows:Object.values(fields);
  form.reportValidity=()=>true;
  const nodes={'suite-execution':form,'preview-suite':new N(),'enqueue-suite':new N(),'suite-status':new N(),'suite-blockers':new N(),'suite-items':new N()};
  if(selection){nodes['suite-execution']=null;nodes['selection-execution']=form;form.dataset.source='selection';['preview','enqueue','status','blockers','items'].forEach(n=>{const id=n==='preview'||n==='enqueue'?n+'-suite':'suite-'+n;const next=n==='preview'||n==='enqueue'?n+'-selection':'selection-'+n;nodes[next]=nodes[id];});}
  nodes['enqueue-suite'].disabled=true;
  const calls=[];let saved=0;
  const context={document:{getElementById:id=>nodes[id],createElement:()=>new N()},crypto:require('node:crypto').webcrypto,window:{
    aiqaForms:{register:()=>({markSaved(){saved++;}})},
    aiqaRequest:async(url,options)=>{calls.push({url,body:JSON.parse(options.body),key:options.headers['Idempotency-Key']});return request(calls.at(-1));}
  }};
  vm.runInNewContext(fs.readFileSync('src/aiqa/web/static/command.js','utf8'),context);
  vm.runInNewContext(fs.readFileSync('src/aiqa/web/static/suite_execution.js','utf8'),context);
  return {nodes,fields,calls,get saved(){return saved;},preview:()=>nodes['preview-suite'].fire('click'),admit:()=>nodes['enqueue-suite'].fire('click'),change:()=>form.fire('input')};
}
function response(body,ok=true,status=200){return {ok,status,json:async()=>body,clone:()=>({json:async()=>body})};}
const resolved=[{entry_id:'a',case_version_id:'a-v1',approval_id:'ap-a'},{entry_id:'b',case_version_id:'b-v1',approval_id:'ap-b'}];
function preview(extra={}){return response({ready:true,preview_hash:'pinned-hash',resolved_items:resolved,blockers:[],...extra});}

test('saved suite preview pins both approved items and requires an explicit admission',async()=>{
  const h=host(c=>c.url.endsWith('execution-previews')?preview():response({execution_id:'run-id'},true,201));
  await h.preview();
  assert.equal(h.calls.length,1);
  assert.equal(h.calls[0].body.selection.suite_version_id,'saved-v1');
  assert.equal(h.nodes['enqueue-suite'].disabled,false);
  await h.admit();
  const sent=h.calls[1].body;
  assert.equal(sent.source,'suite');assert.equal(sent.purpose,'regression');
  assert.equal(sent.suite_version_id,'saved-v1');assert.equal(sent.preview_hash,'pinned-hash');
  assert.deepEqual(sent.items,resolved);assert.equal(sent.self_healing_enabled,false);
  assert.equal(h.saved,1);
  assert.match(h.nodes['suite-status'].children[0].href,/executions\/run-id$/);
});

test('empty and oversized suites never send a preview or an admission',async()=>{
  for(const count of [0,101]){
    const h=host(()=>{throw Error('must not send');},count);
    await h.preview();await h.admit();assert.equal(h.calls.length,0);
    assert.equal(h.nodes['enqueue-suite'].disabled,true);
  }
});

test('blockers and changed input invalidate a prepared scope',async()=>{
  const blocked=host(()=>preview({ready:false,blockers:[{code:'RESOURCE_UNAVAILABLE',message:'offline'}]}));
  await blocked.preview();await blocked.admit();assert.equal(blocked.calls.length,1);
  assert.equal(blocked.nodes['suite-blockers'].children.length,1);
  const h=host(()=>preview());await h.preview();
  h.fields.failure_policy.value='continue';await h.change();await h.admit();
  assert.equal(h.calls.length,1);assert.equal(h.nodes['enqueue-suite'].disabled,true);
});

test('a response lost after admission retries the identical body and key without another preview',async()=>{
  let admissions=0;
  const h=host(c=>{if(c.url.endsWith('execution-previews'))return preview();if(++admissions===1)throw Error('lost response');return response({execution_id:'same-run'});});
  await h.preview();await h.admit();
  assert.equal(h.nodes['preview-suite'].disabled,true);assert.equal(h.fields.name.disabled,true);
  await h.preview();await h.admit();
  assert.equal(h.calls.length,3);assert.equal(h.calls[1].key,h.calls[2].key);
  assert.deepEqual(h.calls[1].body,h.calls[2].body);
  assert.equal(h.saved,1);
});

test('a late preview after an input change cannot enable admission',async()=>{
  let finish;
  const h=host(()=>new Promise(resolve=>{finish=resolve;}));
  const pending=h.preview();h.fields.name.value='changed';await h.change();finish(preview());
  await pending;assert.equal(h.nodes['enqueue-suite'].disabled,true);
});

test('server rejection requires a new preview while preserving typed values',async()=>{
  const h=host(c=>c.url.endsWith('execution-previews')?preview():response({message:'offline'},false,422));
  await h.preview();await h.admit();
  assert.equal(h.fields.name.value,'월간 회귀');assert.equal(h.fields.name.disabled,false);
  assert.equal(h.nodes['enqueue-suite'].disabled,true);assert.equal(h.nodes['preview-suite'].disabled,false);
  await h.admit();assert.equal(h.calls.length,2);
});


test('selected regression sends every explicit row with its pinned approval and chosen resource',async()=>{
  const h=host(c=>c.url.endsWith('execution-previews')?preview({resolved_items:[{entry_id:'case-0',case_version_id:'approved-0',approval_id:'approval-0'},{entry_id:'case-1',case_version_id:'approved-1',approval_id:'approval-1'}]}):response({execution_id:'selection-run'}),2,true);
  await h.preview();assert.equal(h.calls[0].body.source,'selection');
  assert.equal(h.calls[0].body.selection.items.length,2);
  assert.equal(h.calls[0].body.selection.items[1].resource_id,'resource-1');
  await h.admit();const sent=h.calls[1].body;
  assert.equal(sent.source,'selection');assert.equal(sent.suite_version_id,undefined);
  assert.equal(sent.items.length,2);assert.equal(sent.items[1].approval_id,'approval-1');
  assert.equal(sent.items[1].environment_revision_id,'env-1');assert.equal(sent.items[1].resource_id,'resource-1');
});
