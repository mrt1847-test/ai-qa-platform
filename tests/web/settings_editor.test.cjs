const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
test('new and replaced binding IDs update immediately with the saved model',()=>{
 const nodes=new Map();function node(name){if(!nodes.has(name))nodes.set(name,{value:name.startsWith('mode-')?'keep':name==='timeout_seconds'?'600':'',hidden:false,disabled:true,textContent:'',type:'password',attrs:{},listeners:{},setAttribute(k,v){this.attrs[k]=String(v);},getAttribute(k){return this.attrs[k]||null;},removeAttribute(k){delete this.attrs[k];},addEventListener(k,f){this.listeners[k]=f;},dispatchEvent(e){if(this.listeners[e.type])this.listeners[e.type](e);}});return nodes.get(name);}
 const form={action:'/ui/projects/p/settings',elements:{namedItem:node},querySelector:node,dispatchEvent(){}};let opts;
 vm.runInNewContext(fs.readFileSync('src/aiqa/web/static/settings_editor.js','utf8'),{document:{getElementById:id=>id==='project-settings'?form:node(id)},window:{aiqaForms:{register:(_,o)=>{opts=o;return{markSaved(){}};}}},Event:class{constructor(type){this.type=type;}}});
 const reference=node('[data-binding-ref="healing"]');reference.hidden=true;
 const first={role:'healing',model:'m1',endpoint:'https://model.example',binding_id:'h1',revision_id:'rev1',revision:1};
 opts.onSaved({lock_version:1,bindings:[first]},opts.read());
 assert.equal(reference.hidden,false);assert.equal(node('[data-binding-ref-id="healing"]').textContent,'h1');assert.equal(node('[data-binding-ref-revision="healing"]').textContent,'rev1');
 assert.equal(node('[data-role="healing"]').getAttribute('data-binding-id'),'h1');assert.equal(node('[data-check-binding="healing"]').disabled,false);
 opts.onSaved({lock_version:2,bindings:[{...first,model:'m2',revision_id:'rev2',revision:2}]},opts.read());
 assert.equal(node('[data-binding-ref-revision="healing"]').textContent,'rev2');assert.match(node('[data-binding-status="healing"]').textContent,/m2/);
});

test('binding a deployed reference clears raw input and saves only reference metadata',async()=>{
 const nodes=new Map();function node(name){if(!nodes.has(name))nodes.set(name,{value:name.startsWith('mode-')?'keep':name==='timeout_seconds'?'600':'',hidden:false,disabled:true,textContent:'',type:'password',attrs:{},listeners:{},setAttribute(k,v){this.attrs[k]=String(v);},getAttribute(k){return this.attrs[k]||null;},removeAttribute(k){delete this.attrs[k];},addEventListener(k,f){this.listeners[k]=f;},dispatchEvent(e){if(this.listeners[e.type])this.listeners[e.type](e);}});return nodes.get(name);}
 const form={action:'/ui/projects/p/settings',elements:{namedItem:node},querySelector:node,dispatchEvent(){}};let opts,sent;
 vm.runInNewContext(fs.readFileSync('src/aiqa/web/static/settings_editor.js','utf8'),{document:{getElementById:id=>id==='project-settings'?form:node(id)},window:{aiqaRequest:async(url,request)=>{sent={url,...request};return{ok:true};},aiqaForms:{register:(_,o)=>{opts=o;return{markSaved(){}};}}},Event:class{constructor(type){this.type=type;}}});
 const mode=node('mode-authoring'),raw=node('key-authoring');
 mode.value='replace';mode.dispatchEvent({type:'change'});raw.value='synthetic-unsent-key';raw.type='text';
 mode.value='bind_ref';mode.dispatchEvent({type:'change'});
 assert.equal(raw.value,'');assert.equal(raw.type,'password');
 assert.equal(node('[data-secret-entry="authoring"]').hidden,true);
 assert.equal(node('[data-secret-reference="authoring"]').hidden,false);
 const reference={project_id:'11111111-1111-4111-8111-111111111111',ref_id:'22222222-2222-4222-8222-222222222222',revision:2};
 node('key-ref-authoring').value=JSON.stringify(reference);node('endpoint-authoring').value='https://api.openai.com';node('model-authoring').value='configured-model';
 const payload=opts.read();await opts.persist(payload,'bind-reference');
 const posted=JSON.parse(sent.body).roles.find(item=>item.role==='authoring');
 assert.deepEqual(posted,{role:'authoring',mode:'bind_ref',endpoint:'https://api.openai.com',model:'configured-model',key_ref:reference});
 assert.equal(sent.headers['Idempotency-Key'],'bind-reference');assert.equal(sent.body.includes('synthetic-unsent-key'),false);
 opts.onSaved({lock_version:1,bindings:[]},payload);
 assert.equal(mode.value,'keep');assert.equal(node('[data-replace="authoring"]').hidden,true);
});
