(function () {
  var form=document.getElementById('definition-form');
  if (!form) return;
  var snapshot=JSON.parse(document.getElementById('definition-snapshot').textContent);
  form.addEventListener('submit',function (event) {
    event.preventDefault();
    var body=JSON.parse(JSON.stringify(snapshot));
    var fields=form.elements;
    body.definition.raw_text=fields.raw_text.value;
    body.definition.objective=fields.objective.value;
    try {
      ['preconditions','variables','secret_refs','steps','final_expected','path_policy'].forEach(function (name) {
        body.definition[name]=JSON.parse(fields[name].value);
      });
    } catch (error) {document.getElementById('readiness').textContent='JSON 입력을 다시 확인해 주세요. 입력은 그대로입니다.';return;}
    body.expected_head=document.getElementById('expected-head').value || null;
    aiqaRequest(form.getAttribute('action'),{method:'POST',body:JSON.stringify(body)})
      .then(function (response) {return response.json().then(function (payload) {return {status:response.status,body:payload};});})
      .then(function (result) {
        if (result.status===201 || result.status===200) {
          snapshot=body;snapshot.parent_version_id=result.body.id;
          document.getElementById('expected-head').value=result.body.id;
          document.getElementById('readiness').textContent='저장됨 '+result.body.readiness.reasons.map(function (item) {return item.message;}).join(' ');
        } else {
          document.getElementById('readiness').textContent='입력은 그대로입니다. 저장 내용을 다시 확인해 주세요.';
          if (result.status===409 && result.body.server) document.getElementById('server-diff').textContent='서버 초안 '+result.body.server.raw_text;
        }
      });
  });
})();
