const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function gate(send){const ctx={window:{},crypto:require('node:crypto').webcrypto};vm.runInNewContext(fs.readFileSync('src/aiqa/web/static/command.js','utf8'),ctx);return ctx.window.aiqaCommand(send);}
test('lost response retains immutable command and key until explicitly retried',async()=>{
 const sent=[];const g=gate(async(p,k)=>{sent.push([JSON.stringify(p),k]);if(sent.length===1)throw Error('lost');return {ok:true};});
 await assert.rejects(g.send({value:1}));assert.equal(g.pending(),true);
 await assert.rejects(g.send({value:2}),/pending/);assert.equal(sent.length,1);
 await g.send({value:1});assert.deepEqual(sent[0],sent[1]);assert.equal(g.pending(),false);
});
test('concurrent commands share one request and definitive rejection permits a new command',async()=>{
 let count=0,resolve;const g=gate(()=>{count++;return new Promise(r=>resolve=r);});
 const a=g.send({v:1}),b=g.send({v:1});assert.equal(count,1);resolve({ok:false,status:422});await Promise.all([a,b]);assert.equal(g.pending(),false);
});
