(function () {
  var panel=document.getElementById('tc-import');
  if (!panel) return;
  panel.querySelectorAll('button[data-decision]').forEach(function (button) {
    button.addEventListener('click',function () {
      var proposal=button.closest('[data-proposal]').getAttribute('data-proposal');
      var accepted=button.getAttribute('data-decision')==='accept';
      var body={proposal_id:proposal};
      if (accepted) body.expected_head=panel.getAttribute('data-head');
      var url='/api/v1/projects/'+panel.getAttribute('data-project')+'/cases/'+panel.getAttribute('data-case')+(accepted ? '/proposal-acceptances' : '/proposal-rejections');
      button.disabled=true;
      aiqaRequest(url,{method:'POST',body:JSON.stringify(body)}).then(function (response) {
        if (response.ok) {window.location.reload();return;}
        return response.json().then(function (payload) {throw new Error(payload.error.message);});
      }).catch(function (error) {document.getElementById('proposal-status').textContent=error.message;button.disabled=false;});
    });
  });
})();
