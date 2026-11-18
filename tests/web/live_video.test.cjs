const {test}=require('node:test'),assert=require('node:assert/strict');
const {LiveConnection,VideoPlayer}=require('../../src/aiqa/web/static/live_video.js');
function setup(request){
 const values=new Map(),states=[],received=[];
 const storage={getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)};
 const player={hasFrame:true,append:(...x)=>received.push(x),close(){this.closed=true;}};
 const connection=new LiveConnection({project:'p',request,storage,player,onState:(...x)=>states.push(x)});
 return {connection,values,states,received,storage,player};
}
test('live connection uses a bounded playback stream and only start/stop mutations',async()=>{
 const calls=[];const s=setup(async(url,options)=>{
  calls.push([url,options]);
  if(url.endsWith('/video'))return {session_id:'session'};
  if(url.includes('?after='))return {status:'live',codec:'avc1.42c01e',segments:['AQI='],next_sequence:2,reset:true};
  return {status:'live'};
 });
 await s.connection.connect('resource');await s.connection.poll();
 assert.equal(s.received.length,1);assert.deepEqual([...s.received[0][1][0]],[1,2]);
 assert.equal(s.connection.cursor,2);assert(s.values.size===1);
 await s.connection.stop();assert(s.player.closed);assert.equal(s.values.size,0);
 assert(calls.some(([u])=>u.endsWith('/stop')));
 assert(!calls.some(([u])=>/download|save|record/.test(u)));
});
test('page resume reuses the same scoped session instead of starting another capture',async()=>{
 const calls=[];const s=setup(async(u)=>{calls.push(u);return {status:'pending',segments:[],next_sequence:0};});
 s.storage.setItem('aiqa-live-video:p',JSON.stringify({session_id:'old',resource:'device'}));
 assert(await s.connection.resume('device'));assert.equal(s.connection.id,'old');
 assert(!calls.some(u=>u.endsWith('/resources/device/video')));
});
test('switching device cannot append an old in-flight response',async()=>{
 let release;const s=setup(async(u)=>{
  if(u.endsWith('/video'))return {session_id:'first'};
  if(u.includes('?after='))return new Promise(r=>release=r);
  return {};
 });
 await s.connection.connect('one');const pending=s.connection.poll();
 await s.connection.changeResource('two');
 release({status:'live',codec:'avc1.42c01e',segments:['AQI='],next_sequence:1,reset:true});
 await pending;assert.equal(s.received.length,0);assert.equal(s.connection.resource,'two');assert.equal(s.connection.id,null);
});
test('publisher disconnect clears the old frame and never labels it live',async()=>{
 const s=setup(async(u)=>u.endsWith('/video')?{session_id:'s'}:{status:'error',reason:'publisher_disconnected',segments:[]});
 await s.connection.connect('device');await s.connection.poll();
 assert(s.player.closed);assert.equal(s.connection.id,null);assert.equal(s.states.at(-1)[0],'error');
});
test('a slow stop response cannot replace the latest device selection',async()=>{
 let release;const s=setup(async(u)=>{
  if(u.endsWith('/video'))return {session_id:'s'};
  if(u.endsWith('/stop'))return new Promise(r=>release=r);
  return {};
 });
 await s.connection.connect('one');const changing=s.connection.changeResource('two');
 await s.connection.changeResource('three');release({});await changing;
 assert.equal(s.connection.resource,'three');
});
test('a cancelled connect closes the late-created capture session',async()=>{
 let release;const calls=[];const s=setup(async(u)=>{
  calls.push(u);if(u.endsWith('/video'))return new Promise(r=>release=r);return {};
 });
 const connecting=s.connection.connect('one');await s.connection.changeResource('two');
 release({session_id:'late'});await connecting;
 assert.equal(s.connection.id,null);assert(calls.some(u=>u.endsWith('/late/stop')));
});
test('resyncing the rolling live buffer gets a fresh decoder startup deadline',async()=>{
 const s=setup(async(u)=>u.endsWith('/video')?{session_id:'s'}:{status:'live',codec:'avc1.42c01e',segments:['AQI='],next_sequence:9,reset:true});
 let now=1000;s.connection.now=()=>now;
 s.player.append=()=>{s.player.hasFrame=false;};
 await s.connection.connect('device');now=40000;await s.connection.poll();
 assert.equal(s.connection.id,'s');assert.equal(s.states.at(-1)[0],'connecting');
});
function fakeMedia(){
 const buffers=[],sources=[],revoked=[];
 class Source {
  static isTypeSupported(){return true;}
  constructor(){this.readyState='closed';this.events={};sources.push(this);}
  addEventListener(n,fn){this.events[n]=fn;}
  addSourceBuffer(){const b={updating:false,buffered:{length:0},events:{},data:[],addEventListener(n,f){this.events[n]=f;},appendBuffer(v){this.data.push(v);this.updating=true;},remove(){}};buffers.push(b);return b;}
 }
 const video={src:'',paused:true,currentTime:0,readyState:0,addEventListener(){},removeAttribute(){this.src='';},load(){},play(){this.paused=false;return Promise.resolve();}};
 return {Source,video,buffers,sources,url:{createObjectURL:()=> 'blob:video',revokeObjectURL:x=>revoked.push(x)},revoked};
}
test('MediaSource appends continuous bytes in order and ignores callbacks after close',()=>{
 const m=fakeMedia(),player=new VideoPlayer(m.video,{MediaSource:m.Source,URL:m.url,onState(){}});
 player.append('avc1.42c01e',[new Uint8Array([1]),new Uint8Array([2])],true);
 m.sources[0].readyState='open';m.sources[0].events.sourceopen();
 assert.deepEqual([...m.buffers[0].data[0]],[1]);assert.equal(m.buffers[0].data.length,1);
 m.buffers[0].updating=false;m.buffers[0].events.updateend();assert.deepEqual([...m.buffers[0].data[1]],[2]);
 player.close();m.buffers[0].events.updateend();assert.equal(m.buffers[0].data.length,2);assert.equal(m.video.src,'');assert.equal(m.revoked.length,1);
});
test('unsupported codec reports an explicit error instead of showing a still image',()=>{
 const m=fakeMedia();m.Source.isTypeSupported=()=>false;const states=[];
 const p=new VideoPlayer(m.video,{MediaSource:m.Source,URL:m.url,onState:s=>states.push(s)});
 assert.throws(()=>p.append('avc1.42c01e',[new Uint8Array([1])],true),/지원/);
 assert.equal(m.video.src,'');
});
