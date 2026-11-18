/* Live viewing only: no recording, download, still-image loop or device input. */
(function(global){
  'use strict';
  class VideoPlayer {
    constructor(video,options={}){
      this.video=video;this.MS=options.MediaSource||global.MediaSource;this.URL=options.URL||global.URL;
      this.onState=options.onState||function(){};this.epoch=0;this.queue=[];this.queued=0;this.hasFrame=false;
      video.addEventListener('loadeddata',()=>{if(this.source){this.hasFrame=true;this.onState('live');}});
      video.addEventListener('error',()=>{if(this.source)this.onState('error','영상 재생 연결을 다시 확인해 주세요.');});
    }
    append(codec,segments,reset){
      const mime='video/mp4; codecs="'+codec+'"';
      if(!this.MS||!this.MS.isTypeSupported(mime))throw new Error('이 브라우저는 Android 실시간 영상을 지원하지 않습니다.');
      if(reset||!this.source||this.codec!==codec){
        this.close();this.codec=codec;const epoch=this.epoch;
        this.source=new this.MS();this.url=this.URL.createObjectURL(this.source);this.video.src=this.url;
        this.source.addEventListener('sourceopen',()=>{
          if(epoch!==this.epoch)return;
          try{
            this.buffer=this.source.addSourceBuffer(mime);
            this.buffer.addEventListener('updateend',()=>{if(epoch===this.epoch){this.catchup();this.pump();}});
            this.buffer.addEventListener('error',()=>{if(epoch===this.epoch)this.onState('error','영상 연결이 끊겼습니다. 다시 연결해 주세요.');});
            this.pump();
          }catch(error){this.onState('error',error.message);}
        });
      }
      for(const segment of segments){
        if(this.queued+segment.byteLength>4*1024*1024)throw new Error('영상 연결이 지연되고 있습니다. 다시 연결해 주세요.');
        this.queue.push(segment);this.queued+=segment.byteLength;
      }
      this.pump();
    }
    pump(){
      if(!this.buffer||this.buffer.updating||!this.queue.length)return;
      const ranges=this.buffer.buffered;
      if(ranges.length&&ranges.end(ranges.length-1)-ranges.start(0)>25){
        this.buffer.remove(ranges.start(0),ranges.end(ranges.length-1)-15);return;
      }
      const next=this.queue.shift();this.queued-=next.byteLength;
      try{this.buffer.appendBuffer(next);}catch(error){this.onState('error','영상 연결이 지연되고 있습니다. 다시 연결해 주세요.');}
    }
    catchup(){
      if(!this.buffer||!this.buffer.buffered.length)return;
      const ranges=this.buffer.buffered,end=ranges.end(ranges.length-1),start=ranges.start(ranges.length-1);
      if(end-this.video.currentTime>.75||this.video.currentTime<start)this.video.currentTime=Math.max(start,end-.12);
      if(this.video.paused)Promise.resolve(this.video.play()).catch(function(){});
    }
    close(){
      this.epoch++;this.queue=[];this.queued=0;this.hasFrame=false;this.buffer=null;this.source=null;this.codec='';
      if(this.video.pause)this.video.pause();this.video.removeAttribute('src');this.video.load();
      if(this.url){this.URL.revokeObjectURL(this.url);this.url=null;}
    }
  }

  class LiveConnection {
    constructor({project,request,storage,player,onState,now=Date.now}){
      this.project=project;this.request=request;this.storage=storage;this.player=player;this.onState=onState;
      this.now=now;this.key='aiqa-live-video:'+project;this.id=null;this.resource='';this.cursor=0;this.epoch=0;this.lastAlive=0;
    }
    url(suffix=''){return '/api/v1/projects/'+encodeURIComponent(this.project)+'/video-sessions/'+encodeURIComponent(this.id)+suffix;}
    remember(){this.storage.setItem(this.key,JSON.stringify({session_id:this.id,resource:this.resource}));}
    async connect(resource){
      if(!resource)throw new Error('Android 기기를 먼저 선택해 주세요.');
      if(this.id){const stopping=this.stop(),epoch=this.epoch;await stopping;if(epoch!==this.epoch)return;}
      this.resource=resource;this.player.close();const epoch=++this.epoch;this.onState('connecting');
      const body=await this.request('/api/v1/projects/'+encodeURIComponent(this.project)+'/resources/'+encodeURIComponent(resource)+'/video',{method:'POST',body:'{}'});
      if(epoch!==this.epoch){
        try{await this.request('/api/v1/projects/'+encodeURIComponent(this.project)+'/video-sessions/'+encodeURIComponent(body.session_id)+'/stop',{method:'POST',body:'{}'});}catch(error){}
        return;
      }
      this.id=body.session_id;this.cursor=0;this.lastAlive=this.now();this.started=this.now();this.remember();
    }
    async resume(resource){
      let saved;
      try{saved=JSON.parse(this.storage.getItem(this.key)||'null');}catch(error){this.storage.removeItem(this.key);return false;}
      if(!saved||saved.resource!==resource||!saved.session_id)return false;
      this.id=saved.session_id;this.resource=resource;this.cursor=0;this.started=this.now();this.onState('connecting');
      const epoch=this.epoch;
      try{
        const body=await this.request(this.url('/keepalive'),{method:'POST',body:'{}'});
        if(epoch!==this.epoch)return false;
        if(!['pending','live'].includes(body.status)){this.forget();this.onState('stopped');return false;}
        this.lastAlive=this.now();return true;
      }catch(error){if(epoch!==this.epoch)return false;this.forget();this.onState('error','이전 영상 연결이 종료됐습니다. 다시 연결해 주세요.');return false;}
    }
    forget(){this.epoch++;this.id=null;this.cursor=0;this.storage.removeItem(this.key);this.player.close();}
    async poll(){
      if(!this.id)return;const epoch=this.epoch;
      try{
        if(this.now()-this.lastAlive>5000){
          await this.request(this.url('/keepalive'),{method:'POST',body:'{}'});
          if(epoch!==this.epoch)return;this.lastAlive=this.now();
        }
        const body=await this.request(this.url('?after='+this.cursor));
        if(epoch!==this.epoch)return;
        if(!['pending','live'].includes(body.status)){
          this.forget();this.onState(body.status==='stopped'?'stopped':'error',body.reason==='sensitive_or_foreign_job'?'현재 작업의 화면은 표시할 수 없습니다.':'영상 연결이 종료됐습니다.');return;
        }
        const segments=(body.segments||[]).map(encoded=>Uint8Array.from(global.atob(encoded),c=>c.charCodeAt(0)));
        if(body.reset)this.started=this.now();
        if(segments.length)this.player.append(body.codec,segments,body.reset);
        this.cursor=body.next_sequence;
        this.onState(this.player.hasFrame?'live':'connecting');
        if(!this.player.hasFrame&&this.now()-this.started>30000){await this.stop();this.onState('error','기기 영상 연결을 확인한 뒤 다시 시도해 주세요.');}
      }catch(error){
        if(epoch!==this.epoch)return;
        await this.stop();this.onState('error',error.message||'영상 연결이 끊겼습니다.');
      }
    }
    async stop(){
      const url=this.id&&this.url('/stop');this.forget();this.onState('stopped');
      if(url)try{await this.request(url,{method:'POST',body:'{}'});}catch(error){} // Viewer lease also expires without a response.
    }
    async changeResource(resource){if(resource!==this.resource){this.resource=resource;await this.stop();}}
    dispose(){this.epoch++;this.player.close();} // Page navigation resumes the same short-lived stream.
  }

  function bind(){
    const root=document.getElementById('android-live-video');if(!root)return;
    const project=root.dataset.project,video=root.querySelector('video'),start=root.querySelector('[data-video-connect]'),stop=root.querySelector('[data-video-stop]'),note=root.querySelector('[data-video-status]');
    let connection,busy=false,disposed=false;
    function state(status,message){
      const active=!!(connection&&connection.id)||status==='connecting';
      root.dataset.open=String(active);root.dataset.state=status;
      note.textContent=message||({idle:'연결 안 됨',connecting:'연결 중…',live:'실시간',stopped:'연결 종료'}[status]||'영상 연결을 확인해 주세요.');
      start.disabled=busy||active||!connection.resource;start.hidden=active;stop.hidden=!active;video.hidden=!active;
      if(status==='error'&&connection&&connection.id){connection.stop().then(()=>state('error',message));}
    }
    const player=new VideoPlayer(video,{onState:state});
    async function request(url,options){
      const response=options?await global.aiqaRequest(url,options):await fetch(url,{credentials:'same-origin',cache:'no-store'});
      const body=await response.json();
      if(!response.ok)throw new Error(response.status===409?'현재 기기 작업이나 영상 연결 상태를 확인해 주세요.':body.error&&body.error.message||'영상 연결을 확인해 주세요.');
      return body;
    }
    connection=new LiveConnection({project,request,storage:global.sessionStorage,player,onState:state});
    function selected(){
      const form=document.querySelector('#recording-form'),trial=document.querySelector('#trial-setup');
      if(form){const radio=form.querySelector('[name="resource_id"]:checked');return radio&&radio.dataset.kind==='android'?radio.value:'';}
      if(trial){const choice=trial.querySelector('[name="resource_id"] option:checked');return choice&&choice.dataset.kind==='android'?choice.value:'';}
      return root.dataset.resource||'';
    }
    async function sync(initial){
      let resource=selected(),saved=null;
      try{saved=JSON.parse(global.sessionStorage.getItem(connection.key)||'null');}catch(error){}
      const trialSelect=document.querySelector('#trial-setup [name="resource_id"]');
      if(initial&&!resource&&saved&&trialSelect&&!trialSelect.value){
        const previous=Array.from(trialSelect.options).find(option=>option.value===saved.resource&&option.dataset.kind==='android');
        if(previous){trialSelect.value=previous.value;resource=previous.value;}
      }
      if(!resource&&!document.querySelector('#recording-form,#trial-setup')&&saved)resource=saved.resource;
      root.hidden=!resource;
      if(initial&&saved&&saved.resource===resource){connection.resource=resource;await connection.resume(resource);return;}
      else{
        if(initial&&saved){connection.id=saved.session_id;await connection.stop();}
        await connection.changeResource(resource);
      }
      if(!connection.id)state('idle');
    }
    start.addEventListener('click',async()=>{
      busy=true;let failure;
      try{await connection.connect(connection.resource);}catch(error){failure=error.message;}
      finally{busy=false;state(failure?'error':connection.id?'connecting':'idle',failure);}
    });
    stop.addEventListener('click',()=>connection.stop());
    document.addEventListener('change',event=>{if(event.target.name==='resource_id')sync(false);});
    let timer;
    async function tick(){
      if(disposed)return;
      await connection.poll();if(!disposed)timer=setTimeout(tick,250);
    }
    sync(true).then(tick);
    global.addEventListener('pagehide',()=>{disposed=true;clearTimeout(timer);connection.dispose();});
  }
  if(typeof module!=='undefined'&&module.exports)module.exports={LiveConnection,VideoPlayer};
  else{global.AiqaLiveVideo={LiveConnection,VideoPlayer};bind();}
})(typeof window!=='undefined'?window:globalThis);
