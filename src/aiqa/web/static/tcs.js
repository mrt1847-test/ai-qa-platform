(function () {
  var node=document.getElementById('tc-data');
  if (!node) return;
  var data=JSON.parse(node.textContent);
  var prefix='/api/v1/projects/'+data.project_id;
  var status=document.getElementById('tc-status');
  function send(url,method,body) {
    return aiqaRequest(url,{method:method,body:JSON.stringify(body || {})}).then(function (response) {
      return response.json().then(function (body) {if (!response.ok) throw new Error(body.error.message);return body;});
    });
  }
  function importBody(item) {
    var body=JSON.parse(JSON.stringify(data.snapshot.definition));
    var source=item.body;
    body.raw_text=source.raw_text || body.raw_text;
    body.objective=source.objective || body.objective;
    ['preconditions','variables','secret_refs','final_expected','path_policy'].forEach(function (name) {if (Object.prototype.hasOwnProperty.call(source,name)) body[name]=source[name];});
    if (Array.isArray(source.steps)) body.steps=source.steps.map(function (step,index) {
      return {id:step.id || 'tc-step-'+(index+1),instruction:step.instruction || '',point:step.point || null,expected:Array.isArray(step.expected) ? step.expected : (step.expected ? [{id:'tc-check-'+(index+1),kind:'text',expected:String(step.expected)}] : [])};
    });
    return body;
  }
  document.querySelectorAll('#tc-list button[data-action]').forEach(function (button) {
    button.addEventListener('click',function () {
      var row=button.closest('[data-tc]');
      var item=data.items.find(function (item) {return item.tc_id===row.getAttribute('data-tc');});
      var action=button.getAttribute('data-action');
      var operation;
      button.disabled=true;
      if (action==='clone' || action==='archive') operation=send(prefix+'/tcs/'+item.tc_id+'/'+action,'POST',{expected_revision:item.revision});
      else if (action==='link') operation=send(prefix+'/cases/'+data.selected_case.case_id+'/tc-reference','PUT',{tc_version_id:item.version_id,expected_revision:data.selected_case.lock_version});
      else if (action==='preview') operation=send(prefix+'/cases/'+data.selected_case.case_id+'/tc-import-proposals','POST',{base_version_id:data.snapshot.expected_head,base_hash:data.selected_case.content_hash,body:importBody(item),source_job_id:null,tc_version_id:item.version_id});
      if (!operation) {button.disabled=false;return;}
      operation.then(function () {window.location.reload();}).catch(function (error) {status.textContent=error.message;button.disabled=false;});
    });
  });
  var unlink=document.getElementById('tc-unlink');
  if (unlink) unlink.addEventListener('click',function () {
    unlink.disabled=true;
    send(prefix+'/cases/'+data.selected_case.case_id+'/tc-reference','DELETE',{expected_revision:data.selected_case.lock_version})
      .then(function () {window.location.reload();}).catch(function (error) {status.textContent=error.message;unlink.disabled=false;});
  });
})();
