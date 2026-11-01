(function(){
  var form=document.getElementById('environment-form');if(!form)return;
  var original=JSON.parse(document.getElementById('environment-snapshot').textContent)||{};
  function value(name){return form.elements.namedItem(name).value.trim();}
  function target(){form.querySelectorAll('[data-target]').forEach(function(box){box.hidden=box.dataset.target!==value('target_kind');box.disabled=box.hidden;});}
  form.elements.namedItem('target_kind').addEventListener('change',target);target();
  function read(){
    var web=value('target_kind')==='web';
    var body=Object.assign({},original.target_kind===value('target_kind')?original:{},{name:value('name'),target_kind:value('target_kind'),allowlist:(web?value('allowlist'):(value('android_allowlist')||value('package'))).split(/\n/).map(function(x){return x.trim();}).filter(Boolean),viewport:{width:Number(value('viewport.width')),height:Number(value('viewport.height'))},locale:value('locale'),reset_policy:value('reset_policy'),limits:Object.assign({},original.limits||{},{timeout_seconds:Number(value('limits.timeout_seconds')),max_actions:Number(value('limits.max_actions')),budget:value('limits.budget'),currency:value('limits.currency')})});
    if(web){body.start_url=value('start_url');body.dpr=1;body.timezone='Asia/Seoul';}
    else{body.package=value('package');body.orientation='portrait';body.setup=value('setup');body.reset=value('reset');body.cleanup=value('cleanup');body.account_ref=value('account_ref');}
    return body;
  }
  window.aiqaForms.register(form,{read:read,persist:function(body,key){
    var endpoint=form.action+(form.dataset.environmentId?'/'+encodeURIComponent(form.dataset.environmentId)+'/revisions':'');
    return window.aiqaRequest(endpoint,{method:'POST',headers:{'Idempotency-Key':key},body:JSON.stringify(body)});
  },onSaved:function(body,payload){
    original=payload;
    form.dataset.environmentId=body.environment_id;
    form.elements.namedItem('name').readOnly=true;
    document.querySelector('.page-heading h1').textContent=value('name');
    window.aiqaAssetSaved({id:body.environment_id,name:value('name'),href:'?environment='+encodeURIComponent(body.environment_id),detail:body.target_kind+' · v'+body.revision});
    document.getElementById('environment-version').textContent='저장본 v'+body.revision+' · 다른 케이스에서 선택할 수 있습니다.';
    history.replaceState(null,'',location.pathname+'?environment='+encodeURIComponent(body.environment_id));
  },successMessage:function(body){return '프로필 v'+body.revision+'을 저장했습니다.';}});
})();
