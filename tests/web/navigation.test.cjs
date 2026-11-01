const {test}=require('node:test'), assert=require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm');
function fixture(handle){
 const dialog=new EventTarget();dialog.open=false;dialog.returnValue='';dialog.querySelectorAll=()=>[];dialog.querySelector=()=>null;
 dialog.showModal=()=>{dialog.open=true;};dialog.close=value=>{dialog.returnValue=value;dialog.open=false;dialog.dispatchEvent(new Event('close'));};
 const doc=new EventTarget();doc.body={dataset:{dirty:'false'},getAttribute:()=> 'false'};doc.getElementById=()=>dialog;doc.querySelectorAll=()=>[];doc.querySelector=()=>null;doc.activeElement=null;
 const navigated=[];const loc={href:'http://127.0.0.1/editor',origin:'http://127.0.0.1',pathname:'/editor',search:'',assign:url=>navigated.push(url)};
 const win=new EventTarget();Object.assign(win,{location:loc,sessionStorage:{getItem:()=>null,setItem:()=>{}},scrollTo:()=>{},aiqaForms:{dirty:()=>[handle]}});
 const ctx={window:win,document:doc,location:loc,sessionStorage:win.sessionStorage,URL,URLSearchParams,FormData,Event,console};
 vm.runInNewContext(fs.readFileSync('src/aiqa/web/static/navigation.js','utf8'),ctx);
 return {go:win.aiqaNavigate,dialog,navigated};
}
test('cancel preserves edits and original destination is used after discard',async()=>{
 const f=fixture({isDirty:()=>true,saveBeforeLeave:true,save:async()=>true});
 const first=f.go('/wanted?tab=steps');f.dialog.close('cancel');await first;assert.equal(f.navigated.length,0);
 const second=f.go('/wanted?tab=steps');f.dialog.close('discard');await second;assert.deepEqual(f.navigated,['http://127.0.0.1/wanted?tab=steps']);
});
test('failed save before leaving keeps user on the edited page',async()=>{
 const f=fixture({isDirty:()=>true,saveBeforeLeave:true,save:async()=>false});
 const leaving=f.go('/wanted');f.dialog.close('save');await leaving;assert.equal(f.navigated.length,0);
});
test('review decision must never be implicitly submitted by save-and-leave',async()=>{
 let submitted=false;const f=fixture({isDirty:()=>true,saveBeforeLeave:false,save:async()=>{submitted=true;return true;}});
 const leaving=f.go('/wanted');f.dialog.close('save');await leaving;
 assert.equal(submitted,false);assert.equal(f.navigated.length,0);
});
