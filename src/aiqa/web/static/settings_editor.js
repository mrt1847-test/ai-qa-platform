(function(){
  var form=document.getElementById('project-settings');if(!form)return;
  var roles=['authoring','verification','healing','maintenance'],lock=Number(document.getElementById('settings-lock').value);
  function node(name){return form.elements.namedItem(name);}
  roles.forEach(function(role){
    var mode=node('mode-'+role),group=form.querySelector('[data-replace="'+role+'"]'),key=node('key-'+role),show=form.querySelector('[data-show-key="'+role+'"]');
    function update(){group.hidden=mode.value!=='replace';if(group.hidden){key.value='';key.type='password';show.setAttribute('aria-pressed','false');show.value='입력한 키 보기';}}
    mode.addEventListener('change',update);update();
    show.addEventListener('click',function(){var visible=key.type==='password';key.type=visible?'text':'password';show.value=visible?'키 숨기기':'입력한 키 보기';show.setAttribute('aria-pressed',String(visible));});
    form.querySelector('[data-cancel-key="'+role+'"]').addEventListener('click',function(){mode.value='keep';update();form.dispatchEvent(new Event('input',{bubbles:true}));});
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
