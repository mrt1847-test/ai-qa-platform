(function(){
  var form=document.getElementById('project-settings');if(!form)return;
  var roles=['authoring','verification','healing','maintenance'],lock=Number(document.getElementById('settings-lock').value);
  function node(name){return form.elements.namedItem(name);}
  roles.forEach(function(role){
    var mode=node('mode-'+role),group=form.querySelector('[data-replace="'+role+'"]'),key=node('key-'+role),show=form.querySelector('[data-show-key="'+role+'"]');
    var check=form.querySelector('[data-check-binding="'+role+'"]'),checkStatus=form.querySelector('[data-check-status="'+role+'"]'),field=form.querySelector('[data-role="'+role+'"]');
    function update(){group.hidden=mode.value!=='replace';if(group.hidden){key.value='';key.type='password';show.setAttribute('aria-pressed','false');show.value='입력한 키 보기';}}
    mode.addEventListener('change',update);update();
    show.addEventListener('click',function(){var visible=key.type==='password';key.type=visible?'text':'password';show.value=visible?'키 숨기기':'입력한 키 보기';show.setAttribute('aria-pressed',String(visible));});
    form.querySelector('[data-cancel-key="'+role+'"]').addEventListener('click',function(){mode.value='keep';update();form.dispatchEvent(new Event('input',{bubbles:true}));});
    if(check)check.addEventListener('click',async function(){
      var bindingId=field&&field.getAttribute('data-binding-id');
      if(!bindingId){if(checkStatus)checkStatus.textContent='저장된 연결이 없어 검사할 수 없습니다.';return;}
      check.disabled=true;if(checkStatus)checkStatus.textContent='연결을 검사하는 중입니다.';
      try{
        var keyId=(crypto.randomUUID&&crypto.randomUUID())||('check-'+Date.now());
        var response=await window.aiqaRequest('/api/v1/model-bindings/'+encodeURIComponent(bindingId)+'/checks?project_id='+encodeURIComponent(form.action.split('/projects/')[1].split('/')[0]),{method:'POST',headers:{'Idempotency-Key':keyId},body:JSON.stringify({provider:'fixture',mode:'ok'})});
        var body=await response.json();
        if(!response.ok){if(checkStatus)checkStatus.textContent=(body.error&&body.error.message)||'연결 검사가 거절되었습니다.';return;}
        if(checkStatus)checkStatus.textContent='상태 '+body.status+' · 사유 '+body.reason+(body.checked_at?' · 검사 '+new Date(body.checked_at).toLocaleString('ko-KR'):'')+' · 계측 호출 '+body.metered_calls+(body.replay_requires_model_check?'':' · 결정적 재생은 키 검사 없이 가능');
      }catch(_){if(checkStatus)checkStatus.textContent='연결 검사 응답을 받지 못했습니다.';}
      finally{check.disabled=false;}
    });
  });
  function read(){
    return {expected_lock:lock,failure_policy:node('failure_policy').value,retention:node('retention').value,timeout_seconds:Number(node('timeout_seconds').value),healing_scope:node('healing_scope').value,roles:roles.map(function(role){return node('mode-'+role).value==='keep'?{role:role,mode:'keep'}:{role:role,mode:'replace',endpoint:node('endpoint-'+role).value,model:node('model-'+role).value,key:node('key-'+role).value};})};
  }
  var handle=window.aiqaForms.register(form,{read:read,persist:function(payload,key){return window.aiqaRequest(form.action,{method:'POST',headers:{'Idempotency-Key':key},body:JSON.stringify(payload)});},onConflict:function(){window.aiqaRequest(form.action.replace('/ui/','/api/v1/'),{method:'GET'}).then(function(response){if(!response.ok)throw Error('scope');return response.json();}).then(function(server){var local=read();delete local.roles;window.aiqaCompareConflict(form,server,local,function(){lock=server.lock_version;document.getElementById('settings-lock').value=lock;});}).catch(function(){document.getElementById('settings-note').textContent='서버 값을 비교하지 못했습니다. 입력을 유지한 상태로 연결을 확인해 주세요.';});},onSaved:function(body,payload){
    var unchanged=JSON.stringify(read())===JSON.stringify(payload);
    lock=body.lock_version;document.getElementById('settings-lock').value=lock;
    document.getElementById('settings-note').textContent='설정 버전 '+lock+' 저장됨 · 키 입력을 비웠습니다.';
    roles.forEach(function(role){
      var binding=(body.bindings||[]).filter(function(item){return item.role===role;}).pop();
      form.querySelector('[data-binding-status="'+role+'"]').textContent=binding?'연결 저장됨 · '+binding.model+' · '+binding.endpoint+' · 키 참조 연결됨':'저장된 연결 없음';
      var submitted=payload.roles.find(function(item){return item.role===role;});
      if(submitted&&submitted.mode==='replace'&&node('key-'+role).value===submitted.key){node('key-'+role).value='';node('key-'+role).type='password';}
      if(unchanged){node('mode-'+role).value='keep';node('mode-'+role).dispatchEvent(new Event('change'));}
    });
    if(unchanged)handle.markSaved();
  },successMessage:function(){return '설정을 저장했습니다. 모델 호출은 수행하지 않았습니다.';}});
})();
