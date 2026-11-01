(function(){
  var form=document.getElementById('trial-setup');if(!form)return;
  var base='/api/v1/projects/'+form.dataset.project,check=document.getElementById('preview-trial'),enqueue=document.getElementById('enqueue-trial'),status=document.getElementById('trial-status'),blockers=document.getElementById('trial-blockers'),pins=document.getElementById('trial-pins'),prepared=null,preparing=false,frozen=null,locked=[];
  function value(name){return form.elements.namedItem(name).value;}
  function read(){return {purpose:'trial',source:'single',failure_policy:value('failure_policy'),self_healing_enabled:false,exclusions:[],selection:{items:[{entry_id:form.dataset.case,case_version_id:value('case_version_id'),environment_revision_id:value('environment_revision_id'),resource_id:value('resource_id'),dataset_version_id:value('dataset_version_id')||null}]}};}
  var handle=window.aiqaForms.register(form,{read:read,saveBeforeLeave:false,persist:async function(){throw Error('explicit admission required');}});
  var gate=window.aiqaCommand(function(body,key){return window.aiqaRequest(base+'/executions',{method:'POST',headers:{'Idempotency-Key':key},body:JSON.stringify(body)});});
  function invalidate(){prepared=null;enqueue.disabled=true;blockers.replaceChildren();pins.textContent='';status.textContent='선택 내용이 바뀌었습니다. 준비 상태를 다시 확인해 주세요.';}
  form.addEventListener('input',invalidate);form.addEventListener('change',invalidate);
  check.addEventListener('click',async function(){
    if(preparing||gate.pending())return;
    var payload=read(),item=payload.selection.items[0],serialized=JSON.stringify(payload);
    if(!item.case_version_id||!item.environment_revision_id||!item.resource_id){status.textContent='버전·환경·기기를 모두 선택해 주세요.';return;}
    preparing=true;check.disabled=true;prepared=null;enqueue.disabled=true;
    try{
      var response=await window.aiqaRequest(base+'/execution-previews',{method:'POST',headers:{'Idempotency-Key':crypto.randomUUID()},body:JSON.stringify(payload)}),body=await response.json();
      if(serialized!==JSON.stringify(read())){status.textContent='검사 중 입력이 바뀌었습니다. 다시 검사해 주세요.';return;}
      blockers.replaceChildren();if(!response.ok){status.textContent='준비 상태를 확인하지 못했습니다. 저장본과 권한을 확인하세요.';return;}
      var labels={PACKAGE_MISSING:'재생 패키지가 필요합니다. 녹화를 준비하세요.',RESOURCE_UNAVAILABLE:'기기·환경·데이터의 연결 및 저장본을 확인하세요.',DEFINITION_AMBIGUOUS:'필수 검증의 기대 결과를 보완하세요.',MODEL_BINDING_UNAVAILABLE:'검증 AI의 키·모델 연결이 필요합니다.',BUDGET_UNAVAILABLE:'저장된 케이스의 시간·비용 한도를 확인하세요.'};
      body.blockers.forEach(function(reason){var li=document.createElement('li');li.textContent=labels[reason.code]||reason.message;blockers.appendChild(li);});
      pins.textContent=JSON.stringify(body.resolved_items,null,2);status.textContent=body.ready?'준비되었습니다. 아래 버튼으로 명시 접수하세요.':'위 항목을 보완한 뒤 다시 검사하세요.';
      if(body.ready){prepared={preview:body,selection:payload.selection.items[0]};enqueue.disabled=false;}
    }catch(_){status.textContent='검사 응답을 받지 못했습니다. 다시 확인해 주세요.';}
    finally{preparing=false;check.disabled=false;}
  });
  enqueue.addEventListener('click',async function(){
    if(!prepared&&!gate.pending())return;enqueue.disabled=true;
    if(!gate.pending()){
      frozen={name:'시범 · '+document.title,purpose:'trial',source:'single',failure_policy:value('failure_policy'),self_healing_enabled:false,exclusions:[],preview_hash:prepared.preview.preview_hash,items:prepared.preview.resolved_items.map(function(item){return Object.assign({},prepared.selection,item);})};
      locked=Array.from(form.querySelectorAll('input,select')).filter(function(node){return node!==enqueue&&!node.disabled;});locked.forEach(function(node){node.disabled=true;});
    }
    try{
      var response=await gate.send(frozen),body=await response.json();
      if(response.ok){handle.markSaved();status.textContent='시범을 접수했습니다. 실행 '+body.execution_id+' · ';var historyLink=document.createElement('a');historyLink.href='/ui/projects/'+form.dataset.project+'/cases/'+form.dataset.case+'/definition?tab=history';historyLink.textContent='케이스 실행 기록 확인';status.appendChild(historyLink);prepared=null;}
      else{status.textContent=response.status===409?'접수 조건이 달라졌습니다. 다시 검사하세요.':'접수하지 못했습니다. 기기·버전·권한을 확인한 뒤 다시 검사하세요.';prepared=null;}
      locked.forEach(function(node){node.disabled=false;});check.disabled=false;
    }catch(_){status.textContent='응답을 확인하지 못했습니다. 접수 버튼을 다시 누르면 같은 요청을 확인합니다.';enqueue.disabled=false;}
  });
})();
