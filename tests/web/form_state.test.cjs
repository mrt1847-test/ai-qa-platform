const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
function fixture(persist,disabled=false){
  let value={name:'before'};
  const form=new EventTarget();
  form.dataset={};
  form.querySelector=()=>null;
  const button={disabled};
  form.querySelectorAll=(selector)=>selector.includes('data-save-button')?[button]:[];
  form.setAttribute=()=>{};
  const context={window:{},document:{querySelectorAll:()=>[]},crypto:require('node:crypto').webcrypto,Event,console};
  vm.runInNewContext(fs.readFileSync(path.resolve('src/aiqa/web/static/form_state.js'),'utf8'),context);
  const handle=context.window.aiqaForms.register(form,{read:()=>value,persist});
  return {handle,form,button,set(v){value=v;form.dispatchEvent(new Event('input'));}};
}
test('server-disabled save remains disabled through initialization and validation states',async()=>{
 const f=fixture(async()=>({ok:false,status:422,json:async()=>({error:{fields:{}}})}),true);
 assert.equal(f.button.disabled,true);f.set({name:'changed'});assert.equal(f.button.disabled,true);
 await f.handle.save();assert.equal(f.button.disabled,true);
});
test('failed save preserves dirty input and a successful acknowledgement clears it',async()=>{
  let bad=true;
  const f=fixture(async()=>({ok:!bad,status:bad?422:201,json:async()=>bad?{error:{fields:{name:['required']}}}:{id:'v1'}}));
  f.set({name:'changed'});
  assert.equal(f.handle.isDirty(),true);
  assert.equal(await f.handle.save(),false);
  assert.equal(f.handle.isDirty(),true);
  assert.equal(f.form.dataset.saveState,'invalid');
  bad=false;
  assert.equal(await f.handle.save(),true);
  assert.equal(f.handle.isDirty(),false);
});
test('uncertain commit retries the same payload and request key without automatic dispatch',async()=>{
  const keys=[];let first=true;
  const f=fixture(async(body,key)=>{keys.push(key);if(first){first=false;throw new Error('response lost');}return {ok:true,status:201,json:async()=>({id:'v1'})};});
  f.set({name:'changed'});
  assert.equal(await f.handle.save(),false);
  assert.equal(f.form.dataset.saveState,'unknown');
  assert.equal(keys.length,1);
  assert.equal(await f.handle.save(),true);
  assert.equal(keys[0],keys[1]);
});
test('concurrent click does not duplicate dispatch and edits during save stay dirty',async()=>{
  let done;let calls=0;
  const f=fixture(()=>{calls++;return new Promise(resolve=>{done=()=>resolve({ok:true,status:201,json:async()=>({id:'v1'})});});});
  f.set({name:'one'});
  const saving=f.handle.save();f.handle.save();
  await Promise.resolve();
  assert.equal(calls,1);
  f.set({name:'two'});done();await saving;
  assert.equal(f.handle.isDirty(),true);
});
test('reverting an edit returns to clean without a server request',()=>{
  const f=fixture(()=>{throw new Error('must not send');});
  f.set({name:'changed'});f.set({name:'before'});
  assert.equal(f.handle.isDirty(),false);
});
test('confirming an old unacknowledged save preserves newer edits and next save uses a new key',async()=>{
 const sent=[];const f=fixture(async(payload,key)=>{sent.push([JSON.stringify(payload),key]);if(sent.length===1)throw Error('lost');return {ok:true,status:201,json:async()=>({id:'saved'})};});
 f.set({name:'old request'});await f.handle.save();f.set({name:'newer edit'});
 await f.handle.confirmPending();assert.deepEqual(sent[0],sent[1]);assert.equal(f.handle.isDirty(),true);
 await f.handle.save();assert.notEqual(sent[1][1],sent[2][1]);assert.equal(sent[2][0],'{"name":"newer edit"}');assert.equal(f.handle.isDirty(),false);
});
