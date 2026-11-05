(function(){
  var form=document.getElementById('recording-form');if(!form)return;
  var snapshot=JSON.parse(document.getElementById('recording-snapshot').textContent)||{};
  var profiles=JSON.parse(document.getElementById('recording-profiles').textContent)||[];
  var base='/api/v1/projects/'+form.dataset.project,caseId=form.dataset.case||'',head=snapshot.expected_head||snapshot.version_id||null,versionHash=snapshot.input_version_hash||'';
  var rerecordBase=snapshot.rerecord_base_version_id||'';
  var expectedCheckIds=[];
  var currentStep=Math.max(1,Math.min(3,Number(form.dataset.step)||1)),expectedEdited=false,prepared=false;
  var startGate=window.aiqaCommand(function(body,key){return window.aiqaRequest(base+'/recordings',{method:'POST',headers:{'Idempotency-Key':key},body:JSON.stringify(body)});}),startPayload=null,locked=[];
  function lockStart(value){if(value){locked=Array.from(form.querySelectorAll('input,select,textarea')).filter(function(node){return node!==start&&!node.disabled;});locked.forEach(function(node){node.disabled=true;});}else{locked.forEach(function(node){node.disabled=false;});locked=[];}}
  var start=document.getElementById('start-recording'),note=document.getElementById('recording-ready-note');
  function value(name){return form.elements.namedItem(name).value;}
  function set(name,val){form.elements.namedItem(name).value=val;}
  function chosen(){return form.querySelector('input[name="resource_id"]:checked');}
  function step(n){
    currentStep=Math.max(1,Math.min(3,n));
    form.querySelectorAll('[data-wizard-step]').forEach(function(section){section.hidden=Number(section.dataset.wizardStep)!==currentStep;});
    document.querySelectorAll('[data-step-link]').forEach(function(link){if(Number(link.dataset.stepLink)===currentStep)link.setAttribute('aria-current','step');else link.removeAttribute('aria-current');});
    form.querySelector('[data-step-previous]').disabled=currentStep===1;form.querySelector('[data-step-next]').hidden=currentStep===3;
    document.getElementById('wizard-step-note').textContent='현재 단계 '+currentStep;
    document.getElementById('recording-preflight').hidden=currentStep!==3;
    var url=new URL(location.href);url.searchParams.set('step',currentStep);if(caseId)url.searchParams.set('case',caseId);history.replaceState(null,'',url);
  }
  function target(clear){
    var kind=value('target_kind');
    if(clear){if(kind==='web'){['android_package','build','account_ref'].forEach(function(name){set(name,'');});}else set('web_url','');}
    form.querySelectorAll('[data-target-fields]').forEach(function(group){group.hidden=group.dataset.targetFields!==kind;group.disabled=group.hidden;});
    Array.from(form.elements.namedItem('environment_revision_id').options).forEach(function(option){option.hidden=Boolean(option.dataset.kind&&option.dataset.kind!==kind);});
    var profile=profiles.find(function(item){return item.id===value('environment_revision_id');});if(profile&&profile.profile.target_kind!==kind)set('environment_revision_id','');
    var resource=chosen();if(resource&&resource.dataset.kind!==kind){resource.checked=false;step(1);note.textContent='대상 종류에 맞는 기기를 다시 선택해 주세요. 공통 검증 내용은 유지했습니다.';}
  }
  var previewRevision=0;
  async function preview(){
    var revision=++previewRevision;
    var resource=chosen(),label=document.getElementById('wizard-preview-name'),message=document.getElementById('wizard-preview-note'),image=document.getElementById('wizard-preview-image'),frame=document.getElementById('wizard-preview-frame'),time=document.getElementById('wizard-preview-time');
    image.hidden=true;image.removeAttribute('src');time.textContent='실시간 제어 화면이 아닙니다.';
    if(!resource){label.textContent='기기 선택 전';message.textContent='기기를 선택해 주세요.';return;}
    var id=resource.value;label.textContent=resource.getAttribute('aria-label');frame.dataset.kind=resource.dataset.kind;message.textContent='최근 관찰을 확인하는 중입니다.';
    try{
      var response=await window.aiqaRequest('/api/v1/resources/'+encodeURIComponent(id)+'/preview?project_id='+form.dataset.project,{method:'GET'});var body=await response.json();
      if(revision!==previewRevision)return;
      if(response.ok&&body.artifact_id&&body.reason!=='expired'&&body.reason!=='unobserved'){
        image.onerror=function(){image.hidden=true;message.textContent='관찰 화면을 불러오지 못했습니다. 새 관찰을 수집한 뒤 확인해 주세요.';};image.src='/api/v1/artifacts/'+encodeURIComponent(body.artifact_id);image.hidden=false;message.textContent='';
      }else message.textContent=body.reason==='expired'?'최근 캡처의 보관 기한이 지났습니다.':'저장된 관찰 화면이 없습니다. 연결 후 수집한 정제 캡처가 표시됩니다.';
      var resourceMeta=chosen();
      var observed=body.observed_at||(resourceMeta&&resourceMeta.dataset.observedAt)||'';
      var heartbeat=resourceMeta&&resourceMeta.dataset.lastSeen?resourceMeta.dataset.lastSeen:'';
      var geometry=resourceMeta&&resourceMeta.dataset.geometry?resourceMeta.dataset.geometry:'';
      var parts=[];
      if(observed)parts.push('관찰 '+new Date(observed).toLocaleString('ko-KR'));
      if(heartbeat)parts.push('heartbeat '+new Date(heartbeat).toLocaleString('ko-KR'));
      if(geometry)parts.push(geometry);
      parts.push('실시간 화면 아님');
      time.textContent=parts.join(' · ');
    }catch(_){if(revision===previewRevision)message.textContent='최근 관찰을 확인하지 못했습니다. 연결 상태를 확인해 주세요.';}
  }
  var packageSelect=document.getElementById('android-package-select');
  var appsNote=document.getElementById('installed-apps-observed');
  var refreshApps=document.getElementById('refresh-installed-apps');
  function renderInstalledApps(body){
    if(!packageSelect||!appsNote)return;
    var current=value('android_package');
    packageSelect.replaceChildren();
    var blank=document.createElement('option');blank.value='';blank.textContent=body&&body.apps&&body.apps.length?'앱을 선택':'조회 후 선택';packageSelect.appendChild(blank);
    (body&&body.apps||[]).forEach(function(app){
      var option=document.createElement('option');
      option.value=app.package;
      var meta=[app.version_name,app.api_level!=null?'API '+app.api_level:'',app.abi,app.content_hash==='unknown'?'hash unknown':''].filter(Boolean).join(' · ');
      option.textContent=meta?app.package+' ('+meta+')':app.package;
      if(app.package===current)option.selected=true;
      packageSelect.appendChild(option);
    });
    if(body&&body.observed_at){
      var when=new Date(body.observed_at);appsNote.textContent='관찰 '+((isNaN(when.getTime())?body.observed_at:when.toLocaleString('ko-KR')))+' · 상태 '+(body.state||'unknown')+' · 설치/초기화 '+(body.install_calls||0)+'/'+(body.reset_calls||0);
    }else appsNote.textContent='저장된 설치 앱 관찰이 없습니다. lease가 있는 Android에서 조회하세요.';
  }
  async function loadInstalledApps(){
    var resource=chosen();if(!resource||resource.dataset.kind!=='android'){renderInstalledApps(null);return;}
    try{
      var response=await window.aiqaRequest('/api/v1/resources/'+encodeURIComponent(resource.value)+'/installed-apps?project_id='+form.dataset.project,{method:'GET'});
      renderInstalledApps(await response.json());
    }catch(_){appsNote.textContent='설치 앱 관찰을 불러오지 못했습니다.';}
  }
  if(packageSelect)packageSelect.addEventListener('change',function(){if(packageSelect.value)set('android_package',packageSelect.value);invalidate();});
  if(refreshApps)refreshApps.addEventListener('click',async function(){
    var resource=chosen();
    if(!resource||resource.dataset.kind!=='android'){appsNote.textContent='Android 기기를 먼저 선택해 주세요.';return;}
    refreshApps.disabled=true;appsNote.textContent='설치 앱을 조회하는 중입니다.';
    try{
      var key=(crypto.randomUUID&&crypto.randomUUID())||('apps-'+Date.now());
      var probed=await window.aiqaRequest('/api/v1/resources/'+encodeURIComponent(resource.value)+'/probes?project_id='+form.dataset.project,{method:'POST',headers:{'Idempotency-Key':key},body:JSON.stringify({provider:'fixture',kind:'installed_apps',proof:null})});
      var body=await probed.json();
      if(!probed.ok){appsNote.textContent=(body.error&&body.error.message)||'설치 앱 조회가 거절되었습니다. lease와 연결을 확인해 주세요.';return;}
      if(body.observation)renderInstalledApps(body.observation);else await loadInstalledApps();
      invalidate();
    }catch(_){appsNote.textContent='설치 앱 조회 응답을 받지 못했습니다.';}
    finally{refreshApps.disabled=false;}
  });
  form.querySelectorAll('input[name="resource_id"]').forEach(function(radio){radio.addEventListener('change',function(){var previous=value('target_kind');set('target_kind',radio.dataset.kind);target(previous!==radio.dataset.kind);preview();loadInstalledApps();});});
  form.elements.namedItem('target_kind').addEventListener('change',function(){target(true);preview();loadInstalledApps();});
  form.elements.namedItem('expected_text').addEventListener('input',function(){expectedEdited=true;});
  form.elements.namedItem('environment_revision_id').addEventListener('change',function(){
    var item=profiles.find(function(p){return p.id===value('environment_revision_id');});if(!item)return;
    var p=item.profile;
    if(p.target_kind==='web')set('web_url',p.start_url||'');else set('android_package',p.package||'');
    if(p.reset_policy)set('reset_policy',p.reset_policy);
    ['timeout_seconds','max_actions','budget'].forEach(function(key){if(p.limits&&p.limits[key]!==undefined)set(key,p.limits[key]);});
    form.dispatchEvent(new Event('input',{bubbles:true}));
  });
  function read(){
    var definition=Object.assign({raw_text:'',objective:'',preconditions:[],variables:{},secret_refs:{},steps:[],final_expected:[],path_policy:{must_use:[],forbidden:[]}},JSON.parse(JSON.stringify(snapshot.definition||{})));
    definition.raw_text=value('raw_text');definition.objective=value('objective');
    if(expectedEdited)definition.final_expected=value('expected_text').split('\n').filter(function(text){return text.trim();}).map(function(text,i){var old=definition.final_expected[i];if(!expectedCheckIds[i])expectedCheckIds[i]=crypto.randomUUID();return old?Object.assign({},old,{expected:text}):{id:expectedCheckIds[i],kind:'text',expected:text};});
    var settings=JSON.parse(JSON.stringify(snapshot));
    ['definition','version_id','input_version_hash','version_revision','expected_head','case_name','raw_text','recorded_steps'].forEach(function(key){delete settings[key];});
    if(rerecordBase){settings.rerecord_base_version_id=rerecordBase;settings.rerecord_reason=value('rerecord_reason');settings.rerecord_confirmed=form.elements.namedItem('rerecord_confirmed').checked;}
    Object.assign(settings,{wizard:true,target_kind:value('target_kind'),execution_mode:'recorded_replay',resource_id:chosen()?chosen().value:'',environment_revision_id:value('environment_revision_id'),definition_buffer:definition.raw_text,web_url:value('target_kind')==='web'?value('web_url'):'',android_package:value('target_kind')==='android'?value('android_package'):'',build:value('target_kind')==='android'?value('build'):'',account_ref:value('target_kind')==='android'?value('account_ref'):'',data_revision_id:value('data_revision_id'),reset_policy:value('reset_policy'),limits:{timeout_seconds:Number(value('timeout_seconds')),max_actions:Number(value('max_actions')),budget:value('budget'),currency:'USD'}});
    return {name:value('case_name').trim(),definition:definition,settings:settings,recorded_steps:snapshot.recorded_steps||[]};
  }
  var handle=window.aiqaForms.register(form,{read:read,persist:async function(payload,key){
    var fields={};if(!payload.name)fields.case_name=['케이스 이름을 입력해 주세요.'];if(!payload.settings.resource_id)fields.resource_id=['기기를 먼저 선택해 주세요.'];if(rerecordBase&&!payload.settings.rerecord_reason.trim())fields.rerecord_reason=['재녹화 사유를 입력해 주세요.'];
    if(Object.keys(fields).length)return {ok:false,status:422,json:async function(){return {error:{fields:fields}};}};
    if(!caseId){
      form.elements.namedItem('case_name').readOnly=true;
      var created=await window.aiqaRequest(base+'/cases',{method:'POST',headers:{'Idempotency-Key':key+':case'},body:JSON.stringify({name:payload.name})});
      if(!created.ok){form.elements.namedItem('case_name').readOnly=false;return created;}
      caseId=(await created.json()).case_id;form.dataset.case=caseId;
      document.getElementById('recording-save-summary').textContent='케이스 생성됨 · 검증 내용 저장 필요';step(currentStep);
    }
    return window.aiqaRequest(base+'/cases/'+caseId+'/versions',{method:'POST',headers:{'Idempotency-Key':key+':version'},body:JSON.stringify({definition:payload.definition,settings:payload.settings,recorded_steps:payload.recorded_steps,parent_version_id:rerecordBase||head,base_version_id:rerecordBase||null,expected_head:head})});
  },onConflict:function(body){if(body.server_snapshot){var local=read();window.aiqaCompareConflict(form,{definition:body.server_snapshot.definition,settings:body.server_snapshot.settings},{definition:local.definition,settings:local.settings},function(){head=body.server_snapshot.expected_head;prepared=false;start.disabled=true;});}},onSaved:function(body,payload){
    head=body.id;versionHash=body.content_hash;form.elements.namedItem('case_name').readOnly=true;
    var savedUrl=new URL(location.href);savedUrl.searchParams.delete('base');history.replaceState(null,'',savedUrl);
    document.getElementById('recording-save-summary').textContent='초안 v'+body.revision+' 저장됨 · 승인 전';
    var visibleExpected=value('expected_text').split('\n').filter(function(text){return text.trim();}).join('\n');
    var submittedExpected=payload.definition.final_expected.map(function(check){return typeof check.expected==='string'?check.expected:'';}).join('\n');
    snapshot.definition=payload.definition;snapshot.recorded_steps=payload.recorded_steps;expectedEdited=visibleExpected!==submittedExpected;
    prepared=false;start.disabled=true;step(currentStep);
  },successMessage:function(body){return '초안 v'+body.revision+'을 저장했습니다. 녹화 시작 조건은 별도로 확인합니다.';}});
  function invalidate(){prepared=false;start.disabled=true;document.getElementById('recording-blockers').replaceChildren();note.textContent='입력이 바뀌면 저장 후 준비 상태를 다시 확인하세요.';}
  form.addEventListener('input',invalidate);form.addEventListener('change',invalidate);
  document.querySelectorAll('[data-step-link]').forEach(function(link){link.addEventListener('click',function(event){event.preventDefault();step(Number(link.dataset.stepLink));});});
  form.querySelector('[data-step-previous]').addEventListener('click',function(){step(currentStep-1);});
  form.querySelector('[data-step-next]').addEventListener('click',function(){if(currentStep===1&&!chosen()){note.textContent='기기를 먼저 선택해 주세요.';return;}step(currentStep+1);});
  function startBody(){return {case_id:caseId,input_case_version_id:head,input_version_hash:versionHash,resource_id:chosen()?chosen().value:''};}
  var sending=false;
  var availability=window.aiqaPcAvailability && window.aiqaPcAvailability.selection(form,
    function(){return chosen()?chosen().value:'';},function(){
      if(startGate.pending()){start.disabled=sending||!availability.connected();return;}
      if(!prepared)return;
      invalidate();
      note.textContent='기기 연결 상태가 바뀌었습니다. 준비 상태를 다시 확인하세요.';
    },document.querySelector('.wizard-preview [data-pc-availability]'));
  document.getElementById('check-recording').addEventListener('click',async function(){
    if(!head||handle.isDirty()){note.textContent='먼저 현재 초안을 저장해 주세요.';return;}
    if(startGate.pending())return;
    var check=this;check.disabled=true;prepared=false;start.disabled=true;
    try{
      if(availability)await availability.refresh();
      if(handle.isDirty())return;
      var payload=JSON.stringify(startBody()),revision=availability&&availability.revision();
      var response=await window.aiqaRequest(base+'/recording-previews',{method:'POST',body:payload});var result=await response.json();
      if(handle.isDirty()||payload!==JSON.stringify(startBody())||(availability&&revision!==availability.revision())){
        note.textContent='검사 중 조건이 바뀌었습니다. 준비 상태를 다시 확인하세요.';return;
      }
      var list=document.getElementById('recording-blockers');list.replaceChildren();
      if(!response.ok){note.textContent='준비 상태를 확인하지 못했습니다. 저장 버전과 연결을 다시 확인해 주세요.';return;}
      result.reasons.forEach(function(reason){var li=document.createElement('li');var a=document.createElement('a');a.textContent=reason.message;a.href=reason.href;li.appendChild(a);list.appendChild(li);});
      prepared=result.ready&&(!availability||availability.allowed());start.disabled=!prepared;note.textContent=prepared?'시작할 수 있습니다. 시작 시 다시 검사합니다.':'초안은 저장되어 있습니다. 위 항목을 준비하면 녹화를 시작할 수 있습니다.';
    }catch(_){note.textContent='준비 상태 응답을 받지 못했습니다. 잠시 후 다시 확인하세요.';}
    finally{check.disabled=false;}
  });
  start.addEventListener('click',async function(){
    var retry=startGate.pending();
    if(sending||(availability&&!(retry?availability.connected():availability.allowed()))||(!retry&&(!prepared||handle.isDirty())))return;
    sending=true;start.disabled=true;
    if(!startGate.pending()){startPayload=startBody();lockStart(true);}
    try{
      var response=await startGate.send(startPayload);var result=await response.json();
      if(response.ok){window.location.assign('/ui/projects/'+form.dataset.project+'/recordings/'+result.recording_id);}
      else{lockStart(false);prepared=false;start.value='AI 녹화 시작';if(availability)availability.refresh();note.textContent='현재 조건으로 시작하지 못했습니다. 초안은 유지됩니다. 준비 상태를 다시 확인하세요.';}
    }catch(_){note.textContent='응답을 받지 못했습니다. 연결된 상태에서 같은 요청으로 다시 접수할 수 있습니다.';start.value='같은 요청으로 다시 접수';start.disabled=!!(availability&&!availability.connected());}
    finally{sending=false;}
  });
  if(snapshot.version_revision)document.getElementById('recording-save-summary').textContent='초안 v'+snapshot.version_revision+' 저장됨 · 승인 전';
  target(false);step(currentStep);preview();loadInstalledApps();
})();
