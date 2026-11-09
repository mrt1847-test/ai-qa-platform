const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
test('conflict comparison shows the same local target and values that will actually be saved',()=>{
 const values={web_url:'https://shop.example',android_package:'',environment_revision_id:'',data_revision_id:'',install_policy:'none',reset_policy:'none',cleanup_policy:'none',timeout_seconds:'300',verifier_method:'deterministic',verifier_binding_id:'',healing_allowed:false,healing_scope:'',healing_max_episodes:'1',healing_max_calls:'2',healing_max_seconds:'30'};
 const nodes=Object.fromEntries(Object.entries(values).map(([name,value])=>[name,{value:String(value),checked:value===true,type:name==='healing_allowed'?'checkbox':name.includes('max_')||name==='timeout_seconds'?'number':'text'}]));
 const form={elements:{namedItem:name=>nodes[name]},action:'/ui/projects/p/cases/c/settings'};let opts,comparison;
 const context={window:{aiqaForms:{register:(_,o)=>opts=o},aiqaCompareConflict:(_,server,local)=>comparison={server,local}},document:{getElementById:id=>id==='settings-form'?form:id==='case-settings-snapshot'?{textContent:JSON.stringify({settings:{target_kind:'web'}})}:{value:'old-head'}}};
 vm.runInNewContext(fs.readFileSync('src/aiqa/web/static/case_settings.js','utf8'),context);
 opts.onConflict({server_snapshot:{expected_head:'new-head',settings:{target_kind:'android',limits:{timeout_seconds:600},healing_policy:{},verifier_bindings:[]}}});
 assert.equal(comparison.server.target_kind,'android');assert.equal(comparison.local.target_kind,'web');assert.equal(JSON.stringify(comparison.local),JSON.stringify(opts.read()));
});

test('healer reference edits and revision appear in submission and conflict comparison',async()=>{
 const values={web_url:'https://shop.example',android_package:'',environment_revision_id:'',data_revision_id:'',install_policy:'none',reset_policy:'none',cleanup_policy:'none',timeout_seconds:'300',verifier_method:'deterministic',verifier_binding_id:'',healing_allowed:true,healing_scope:'locator',healing_max_episodes:'1',healing_max_calls:'1',healing_max_seconds:'20',healing_binding_id:'healer-local',healing_binding_revision:'rev-8'};
 const nodes=Object.fromEntries(Object.entries(values).map(([name,value])=>[name,{value:String(value),checked:value===true}]));
 const form={elements:{namedItem:name=>nodes[name]},action:'/ui/projects/p/cases/c/settings'};let opts,comparison,request;
 const context={window:{aiqaForms:{register:(_,o)=>opts=o},aiqaCompareConflict:(_,server,local)=>comparison={server,local},aiqaRequest:async(url,options)=>request={url,body:JSON.parse(options.body)}},document:{getElementById:id=>id==='settings-form'?form:id==='case-settings-snapshot'?{textContent:JSON.stringify({settings:{target_kind:'web',healing_policy:{model_binding_ref:'old',binding_revision:'rev-7'}}})}:{value:'old-head'}}};
 vm.runInNewContext(fs.readFileSync('src/aiqa/web/static/case_settings.js','utf8'),context);
 await opts.persist(opts.read(),'save-key');
 assert.equal(request.body.healing_binding_id,'healer-local');assert.equal(request.body.healing_binding_revision,'rev-8');
 opts.onConflict({server_snapshot:{expected_head:'new-head',settings:{target_kind:'web',healing_policy:{model_binding_ref:'healer-server',binding_revision:'rev-9'}}}});
 assert.equal(comparison.server.healing_binding_id,'healer-server');assert.equal(comparison.server.healing_binding_revision,'rev-9');
 assert.equal(comparison.local.healing_binding_id,'healer-local');assert.equal(comparison.local.healing_binding_revision,'rev-8');
 nodes.healing_binding_id.value='';nodes.healing_binding_revision.value='';
 assert.equal(opts.read().healing_binding_id,'');assert.equal(opts.read().healing_binding_revision,'');
});
