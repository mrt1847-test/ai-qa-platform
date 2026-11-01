const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
test('editing Android timeout preserves reset account reference and full allowlist',()=>{
 const p={target_kind:'android',allowlist:['com.example.app','com.example.helper'],package:'com.example.app',setup:'login',reset:'clear app data',cleanup:'logout',account_ref:'saved-ref-v2',orientation:'portrait'};
 const values={name:'Android',target_kind:'android',package:p.package,setup:p.setup,reset:p.reset,cleanup:p.cleanup,account_ref:p.account_ref,allowlist:'',android_allowlist:p.allowlist.join('\n'),'viewport.width':'1280','viewport.height':'720',locale:'ko-KR',reset_policy:'none','limits.timeout_seconds':'300','limits.max_actions':'50','limits.budget':'1','limits.currency':'USD'};
 const nodes=Object.fromEntries(Object.entries(values).map(([k,v])=>[k,{value:v,addEventListener(){}}]));
 const form={elements:{namedItem:n=>nodes[n]},querySelectorAll:()=>[],dataset:{environmentId:'env'},addEventListener(){}};let registered;
 const ctx={window:{aiqaForms:{register:(_,opts)=>registered=opts}},document:{getElementById:id=>id==='environment-form'?form:id==='environment-snapshot'?{textContent:JSON.stringify(p)}:null}};
 vm.runInNewContext(fs.readFileSync('src/aiqa/web/static/environment_editor.js','utf8'),ctx);
 const body=registered.read();assert.equal(body.reset,p.reset);assert.equal(body.account_ref,p.account_ref);assert.equal(JSON.stringify(body.allowlist),JSON.stringify(p.allowlist));assert.equal(body.limits.timeout_seconds,300);
});
