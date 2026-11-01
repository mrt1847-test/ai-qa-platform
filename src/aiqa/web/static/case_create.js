(function(){
  var form=document.getElementById('create-case');if(!form)return;
  window.aiqaForms.register(form,{read:function(){return {name:form.elements.namedItem('name').value,tc_reference:null};},persist:function(body,key){return window.aiqaRequest(form.action,{method:'POST',headers:{'Idempotency-Key':key},body:JSON.stringify(body)});},onSaved:function(body){window.location.assign(form.action.replace('/api/v1/','/ui/')+'/'+body.case_id+'/definition');}});
})();
