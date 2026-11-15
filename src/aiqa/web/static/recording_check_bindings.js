(function(){
  'use strict';
  function fail(message,field){var error=new Error(message);if(field)error.fields={[field]:[message]};throw error;}
  function payload(context,boundaries,targets){
    var selected=new Map(),actions=new Map(context.actions.map(function(a){return [a.id,a.ordinal];}));
    boundaries.forEach(function(row){if(row.after_action_id){if(selected.has(row.step_id)||!actions.has(row.after_action_id))fail('녹화 동작을 다시 선택해 주세요.');selected.set(row.step_id,row.after_action_id);}});
    var last=0,ordered=[];
    context.logical_steps.forEach(function(step,index){var id=selected.get(step.id);if(!id)return;var ordinal=actions.get(id);if(ordinal<last)fail('앞 단계보다 이전 동작을 선택할 수 없습니다.','boundary-'+index);last=ordinal;ordered.push({step_id:step.id,after_action_id:id});});
    if(ordered.length!==selected.size)fail('저장본에 없는 검증 단계입니다.');
    var prefix=context.android_package+':id/',seen=new Set(),prepared=[];
    targets.forEach(function(row,index){var value=row.resource_id.trim();if(!value)return;if(seen.has(row.check_id)||!value.startsWith(prefix)||!/^[A-Za-z_][A-Za-z0-9_]{0,127}$/.test(value.slice(prefix.length)))fail('이 앱의 리소스 ID를 입력하거나 비워 주세요.','target-'+index);seen.add(row.check_id);prepared.push({check_id:row.check_id,resource_id:value});});
    return {expected_manifest_id:context.source_manifest.id,expected_manifest_hash:context.source_manifest.hash,step_boundaries:ordered,check_targets:prepared};
  }
  function compatible(a,b){return !!(a&&b&&a.native_source_hash&&a.native_source_hash===b.native_source_hash&&a.input_case_version_id===b.input_case_version_id&&a.source_content_hash===b.source_content_hash);}
  window.aiqaCheckBindings={payload:payload,compatible:compatible};
  var form=document.getElementById('recording-check-bindings'),data=document.getElementById('recording-check-binding-source');
  if(!form||!data||!window.aiqaForms)return;
  var context=JSON.parse(data.textContent),handle;
  var steps=Array.from(form.querySelectorAll('[data-step-id]')),targets=Array.from(form.querySelectorAll('[data-check-id]'));
  var saveButton=form.querySelector('[data-save-button]');
  function rows(){return {boundaries:steps.map(function(n){return {step_id:n.dataset.stepId,after_action_id:n.value};}),targets:targets.map(function(n){return {check_id:n.dataset.checkId,resource_id:n.value};})};}
  function read(){var r=rows();return payload(context,r.boundaries,r.targets);}
  function update(){
    steps.forEach(function(node){var link=Array.from(form.querySelectorAll('[data-action-evidence]')).find(function(a){return a.dataset.actionEvidence===node.dataset.stepId;});if(link){link.hidden=!node.value;link.href=form.dataset.recordingUrl+'?action_id='+encodeURIComponent(node.value);}});
    if(handle&&form.dataset.saveState!=='saving')saveButton.disabled=!handle.isDirty();
  }
  function conflict(){
    var box=form.querySelector('[data-conflict-comparison]');box.replaceChildren();box.hidden=false;
    var note=document.createElement('p');note.textContent='다른 저장본이 생겼습니다. 현재 입력은 유지했습니다. 최신 값과 비교한 뒤 원본을 선택하세요.';box.appendChild(note);
    window.aiqaRequest(form.action,{method:'GET'}).then(function(response){if(!response.ok)throw Error('read');return response.json();}).then(function(server){
      var current=rows();
      context.logical_steps.forEach(function(step,index){var ours=current.boundaries.find(function(r){return r.step_id===step.id;}),theirs=(server.bindings.step_boundaries||[]).find(function(r){return r.step_id===step.id;});var line=document.createElement('p');line.textContent='단계 '+(index+1)+' · 현재 입력: '+(ours&&ours.after_action_id||'미지정')+' / 서버: '+(theirs&&theirs.after_action_id||'미지정');box.appendChild(line);});
      var link=document.createElement('a');link.textContent='최신 저장본을 새 탭으로 보기';link.href=form.dataset.recordingUrl;link.target='_blank';link.rel='noopener';box.appendChild(link);
      var button=document.createElement('button');button.type='button';button.className='secondary';button.textContent='현재 입력을 유지하고 최신 원본으로 전환';button.disabled=!compatible(context,server);box.appendChild(button);
      if(button.disabled){var hint=document.createElement('p');hint.textContent='녹화 구조나 검증 원본이 달라졌습니다. 새 탭에서 확인한 뒤 다시 연결해 주세요.';box.appendChild(hint);}
      button.addEventListener('click',function(){context=server;box.hidden=true;form.dispatchEvent(new Event('input',{bubbles:true}));update();});
    }).catch(function(){note.textContent='최신 저장본을 읽지 못했습니다. 현재 입력을 유지했습니다. 연결을 확인한 뒤 다시 저장해 주세요.';});
  }
  handle=window.aiqaForms.register(form,{read:read,persist:function(body,key){return window.aiqaRequest(form.action,{method:'POST',headers:{'Idempotency-Key':key},body:JSON.stringify(body)});},onConflict:conflict,onSaved:function(body,submitted){
    var unchanged=false;try{var current=read();unchanged=JSON.stringify(current.step_boundaries)===JSON.stringify(submitted.step_boundaries)&&JSON.stringify(current.check_targets)===JSON.stringify(submitted.check_targets);}catch(_){}
    context.source_manifest={id:body.manifest_id,hash:body.manifest_hash};context.bindings={step_boundaries:submitted.step_boundaries,check_targets:submitted.check_targets};
    var panel=form.querySelector('[data-saved-candidate]');panel.hidden=false;
    panel.querySelector('[data-candidate-note]').textContent='검증 연결 후보를 저장했습니다. 기존 승인본은 유지됩니다. 후보 버전: '+body.case_version_id;
    panel.querySelector('[data-candidate-review]').href=form.dataset.reviewUrl+'?version='+encodeURIComponent(body.case_version_id);
    if(unchanged)handle.markSaved();update();
  },successMessage:function(){return '새 검증 연결 후보를 저장했습니다. 실행·승인은 하지 않았습니다.';}});
  form.addEventListener('input',update);form.addEventListener('change',update);update();
})();
