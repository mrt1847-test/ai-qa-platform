(function(){
  var form=document.getElementById('trial-setup');if(!form)return;
  var base='/api/v1/projects/'+form.dataset.project,check=document.getElementById('preview-trial'),enqueue=document.getElementById('enqueue-trial'),status=document.getElementById('trial-status'),blockers=document.getElementById('trial-blockers'),pins=document.getElementById('trial-pins'),prepared=null,preparing=false,frozen=null,locked=[];
  function value(name){return form.elements.namedItem(name).value;}
  function read(){return {purpose:'trial',source:'single',failure_policy:value('failure_policy'),self_healing_enabled:false,exclusions:[],selection:{items:[{entry_id:form.dataset.case,case_version_id:value('case_version_id'),environment_revision_id:value('environment_revision_id'),resource_id:value('resource_id'),dataset_version_id:value('dataset_version_id')||null}]}};}
  var handle=window.aiqaForms.register(form,{read:read,saveBeforeLeave:false,persist:async function(){throw Error('explicit admission required');}});
  var gate=window.aiqaCommand(function(body,key){return window.aiqaRequest(base+'/executions',{method:'POST',headers:{'Idempotency-Key':key},body:JSON.stringify(body)});});
  function invalidate(){prepared=null;enqueue.disabled=true;blockers.replaceChildren();pins.textContent='';status.textContent='선택 내용이 바뀌었습니다. 준비 상태를 다시 확인해 주세요.';}
  form.addEventListener('input',invalidate);form.addEventListener('change',invalidate);
  var sending=false;
  var availability=window.aiqaPcAvailability && window.aiqaPcAvailability.selection(form,
    function(){return value('resource_id');},function(){
      if(gate.pending()){enqueue.disabled=sending||!availability.connected();return;}
      if(!prepared)return;
      invalidate();
      status.textContent='기기 연결 상태가 바뀌었습니다. 준비 상태를 다시 확인하세요.';
    });
  check.addEventListener('click',async function(){
    if(preparing||gate.pending())return;
    var payload=read(),item=payload.selection.items[0],serialized=JSON.stringify(payload);
    if(!item.case_version_id||!item.environment_revision_id||!item.resource_id){status.textContent='버전·환경·기기를 모두 선택해 주세요.';return;}
    preparing=true;check.disabled=true;prepared=null;enqueue.disabled=true;
    try{
      if(availability)await availability.refresh();
      if(serialized!==JSON.stringify(read()))return;
      var revision=availability&&availability.revision();
      var response=await window.aiqaRequest(base+'/execution-previews',{method:'POST',headers:{'Idempotency-Key':crypto.randomUUID()},body:JSON.stringify(payload)}),body=await response.json();
      if(serialized!==JSON.stringify(read())){status.textContent='검사 중 입력이 바뀌었습니다. 다시 검사해 주세요.';return;}
      if(availability&&revision!==availability.revision()){status.textContent='검사 중 연결 상태가 바뀌었습니다. 다시 검사해 주세요.';return;}
      blockers.replaceChildren();if(!response.ok){status.textContent='준비 상태를 확인하지 못했습니다. 저장본과 권한을 확인하세요.';return;}
      var labels={PACKAGE_MISSING:'재생 패키지가 필요합니다. 녹화를 준비하세요.',RESOURCE_UNAVAILABLE:'기기·환경·데이터의 연결 및 저장본을 확인하세요.',DEFINITION_AMBIGUOUS:'필수 검증의 기대 결과를 보완하세요.',MODEL_BINDING_UNAVAILABLE:'검증 AI의 키·모델 연결이 필요합니다.',BUDGET_UNAVAILABLE:'저장된 케이스의 시간·비용 한도를 확인하세요.'};
      body.blockers.forEach(function(reason){var li=document.createElement('li');li.textContent=labels[reason.code]||reason.message;blockers.appendChild(li);});
      var ready=body.ready&&(!availability||availability.allowed());
      pins.textContent=JSON.stringify(body.resolved_items,null,2);status.textContent=ready?'준비되었습니다. 아래 버튼으로 명시 접수하세요.':'위 항목을 보완한 뒤 다시 검사하세요.';
      if(ready){prepared={preview:body,selection:payload.selection.items[0]};enqueue.disabled=false;}
    }catch(_){status.textContent='검사 응답을 받지 못했습니다. 다시 확인해 주세요.';}
    finally{preparing=false;check.disabled=false;}
  });
  enqueue.addEventListener('click',async function(){
    var retry=gate.pending();
    if(sending||(availability&&!(retry?availability.connected():availability.allowed()))||(!retry&&!prepared))return;
    sending=true;enqueue.disabled=true;
    if(!gate.pending()){
      frozen={name:'시범 · '+document.title,purpose:'trial',source:'single',failure_policy:value('failure_policy'),self_healing_enabled:false,exclusions:[],preview_hash:prepared.preview.preview_hash,items:prepared.preview.resolved_items.map(function(item){return Object.assign({},prepared.selection,item);})};
      locked=Array.from(form.querySelectorAll('input,select')).filter(function(node){return node!==enqueue&&!node.disabled;});locked.forEach(function(node){node.disabled=true;});
    }
    try{
      var response=await gate.send(frozen),body=await response.json();
      if(response.ok){handle.markSaved();status.textContent='시범을 접수했습니다. 실행 '+body.execution_id+' · ';var historyLink=document.createElement('a');historyLink.href='/ui/projects/'+form.dataset.project+'/cases/'+form.dataset.case+'/definition?tab=history';historyLink.textContent='케이스 실행 기록 확인';status.appendChild(historyLink);prepared=null;}
      else{if(availability)availability.refresh();status.textContent=response.status===409?'접수 조건이 달라졌습니다. 다시 검사하세요.':'접수하지 못했습니다. 기기·버전·권한을 확인한 뒤 다시 검사하세요.';prepared=null;}
      locked.forEach(function(node){node.disabled=false;});check.disabled=false;enqueue.value='이 저장본으로 시범 접수';
    }catch(_){status.textContent='응답을 받지 못했습니다. 연결된 상태에서 같은 요청으로 다시 접수할 수 있습니다.';enqueue.value='같은 요청으로 다시 접수';enqueue.disabled=!!(availability&&!availability.connected());}
    finally{sending=false;}
  });
})();
/* Four-step execution wizard. A start stays one request and keeps the typed values. */
(function () {
  function purposesOf(draft) {
    var found = {};
    if (draft && draft.purpose) found[draft.purpose] = true;
    var extras = (draft && draft.purposes) || [];
    extras.forEach(function (item) { if (item) found[item] = true; });
    var items = (draft && draft.items) || [];
    items.forEach(function (item) { if (item && item.purpose) found[item.purpose] = true; });
    return found;
  }

  function review(draft) {
    var items = (draft && draft.items) || [];
    var count = typeof (draft && draft.proposed_n) === "number" ? draft.proposed_n : items.length;
    var found = purposesOf(draft || {});
    var mixed = !!found.trial && (!!found.regression || !!found.reverification);
    return {
      steps: 4,
      count: count,
      mixed: mixed,
      start: count >= 1 && count <= 100 && !mixed
    };
  }

  window.aiqaExecutionWizard = { review: review, steps: 4 };

  var form = document.getElementById("execution-wizard");
  if (!form) return;
  var step = 1;
  var pending = false;
  var sections = Array.prototype.slice.call(form.querySelectorAll("[data-step]"));

  function show() {
    sections.forEach(function (section) {
      section.hidden = String(section.getAttribute("data-step")) !== String(step);
    });
  }

  function draftFromForm() {
    return {
      name: form.name.value,
      purpose: form.purpose.value,
      source: form.source.value,
      reason: form.reason.value,
      release_label: form.release_label.value,
      items: []
    };
  }

  form.addEventListener("click", function (event) {
    var target = event.target;
    if (!target || !target.getAttribute) return;
    if (target.getAttribute("data-move") === "back" && step > 1) {
      step -= 1;
      show();
    }
  });

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    if (pending) return;
    var draft = draftFromForm();
    var decision = review(draft);
    var counts = document.getElementById("wizard-counts");
    if (counts) counts.textContent = "항목 " + decision.count + " · 제외 0";
    if (!decision.start) return;
    pending = true;
    var project = window.location.pathname.split("/")[3];
    var body = JSON.stringify({
      name: draft.name,
      purpose: draft.purpose,
      source: draft.source,
      failure_policy: "stop_on_non_pass",
      self_healing_enabled: false,
      release_label: draft.release_label,
      preview_hash: form.getAttribute("data-preview-hash") || "",
      exclusions: [],
      items: draft.items
    });
    window.aiqaRequest("/api/v1/projects/" + project + "/executions", {
      method: "POST",
      body: body
    }).then(function (response) {
      pending = false;
      if (response.status === 422 || response.status === 409) return;
    }, function () {
      pending = false;
    });
  });

  show();
})();
