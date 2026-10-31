(function () {
  var form=document.getElementById('create-case');
  if (!form) return;
  form.addEventListener('submit',function (event) {
    event.preventDefault();
    aiqaRequest(form.getAttribute('action'),{method:'POST',body:JSON.stringify({name:form.elements.name.value,tc_reference:null})})
      .then(function (response) {return response.json().then(function (body) {if (!response.ok) throw new Error(body.error.message);return body;});})
      .then(function (body) {window.location.assign(form.getAttribute('action').replace('/api/v1/','/ui/')+'/'+body.case_id+'/definition');})
      .catch(function (error) {document.getElementById('case-create-status').textContent=error.message;});
  });
})();
