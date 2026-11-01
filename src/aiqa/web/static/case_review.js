(function(){
  var request=document.getElementById('review-request-form');
  if(request){
    var candidates=JSON.parse(document.getElementById('review-candidates').textContent);
    var requestHandle=window.aiqaForms.register(request,{saveBeforeLeave:false,read:function(){return {trial:request.elements.namedItem('trial').value};},persist:function(body,key){var candidate=candidates.find(function(item){return item.trial_case_run_id===body.trial;});if(!candidate)return Promise.resolve({ok:false,status:422,json:async function(){return {error:{fields:{trial:['검토할 시범 근거를 선택하세요.']}}};}});return window.aiqaRequest('/api/v1/case-versions/'+request.dataset.version+'/review-requests',{method:'POST',headers:{'Idempotency-Key':key},body:JSON.stringify({trial_case_run_id:candidate.trial_case_run_id,entries:candidate.entries})});},onSaved:function(){setTimeout(function(){if(!window.aiqaForms.dirty().length)location.reload();},0);},successMessage:function(){return '검토 근거를 저장했습니다. 다른 의견 입력을 마친 뒤 화면을 새로 열어 확인하세요.';}});
  }
  var opinion=document.getElementById('action-opinion');
  if(opinion){
    var handle=window.aiqaForms.register(opinion,{saveBeforeLeave:false,read:function(){return {review_id:opinion.dataset.review,entry_key:opinion.dataset.entry,evidence_digest:opinion.dataset.digest,state:opinion.elements.namedItem('state').value,comment:opinion.elements.namedItem('comment').value};},persist:function(payload,key){return window.aiqaRequest('/api/v1/case-versions/'+opinion.dataset.version+'/action-reviews',{method:'POST',headers:{'Idempotency-Key':key},body:JSON.stringify(payload)});},onSaved:function(){setTimeout(function(){if(!window.aiqaForms.dirty().length)location.reload();},0);},successMessage:function(body){return '의견 저장됨 · 출처 '+body.source_reviewed+'/'+body.source_total+' · 시범 '+body.trial_reviewed+'/'+body.trial_total;}});
  }
  var form=document.getElementById('case-decision');if(!form)return;
  var approve=document.getElementById('approve-case'),reject=document.getElementById('reject-case'),reason=document.getElementById('reject-reason'),result=document.getElementById('decision-result'),busy=false,frozen=null,lastAction=null;
  var dirty=window.aiqaForms.register(form,{saveBeforeLeave:false,read:function(){return {reason:reason.value};},persist:async function(){throw Error('explicit decision required');}});
  var gate=window.aiqaCommand(function(command,key){return window.aiqaRequest('/api/v1/case-versions/'+approve.dataset.version+'/'+command.action,{method:'POST',headers:{'Idempotency-Key':key},body:JSON.stringify(command.body)});});
  async function decide(action){
    if(busy)return;
    if(gate.pending()&&lastAction!==action){result.textContent='응답이 확인되지 않은 이전 결정을 먼저 확인하세요.';return;}
    if(!gate.pending()){
      if(action==='rejections'&&!reason.value.trim()){result.textContent='반려 사유를 입력해 주세요.';reason.setAttribute('aria-invalid','true');reason.focus();return;}
      var body={review_id:approve.dataset.review,version_hash:approve.dataset.hash,reason:action==='rejections'?reason.value:'이 버전을 기본 실행본으로 사용합니다.'};
      if(action==='approvals'){body.evidence_set_hash=approve.dataset.evidence;body.expected_current_approval_id=form.dataset.default||null;}
      frozen={action:action,body:body};lastAction=action;
    }
    busy=true;var wasApprove=approve.disabled,wasReject=reject.disabled;approve.disabled=reject.disabled=true;reason.disabled=true;form.setAttribute('aria-busy','true');
    try{
      var response=await gate.send(frozen),body=await response.json();
      if(response.ok){dirty.markSaved();result.textContent=action==='approvals'?'이 버전을 기본 실행본으로 승인했습니다.':'반려 기록은 남아 있습니다. 기존 기본본을 유지합니다.';if(body.approval_id){form.dataset.default=body.approval_id;document.getElementById('current-default').textContent='현재 기본본 '+body.approval_id;}approve.disabled=reject.disabled=true;}
      else if(response.status===409){document.getElementById('decision-conflict').hidden=false;document.getElementById('decision-compare').hidden=false;result.textContent='현재 입력은 유지했습니다. 새 기본본을 비교한 뒤 명시적으로 다시 결정하세요.';}
      else{result.textContent=response.status===401||response.status===403?'권한·연결 세션을 확인하세요. 입력은 유지했습니다.':'승인 조건이나 반려 사유를 확인하세요. 저장된 근거는 유지됩니다.';approve.disabled=wasApprove;reject.disabled=wasReject;}
    }catch(_){result.textContent='응답을 확인하지 못했습니다. 같은 결정을 다시 누르면 이전 요청을 확인합니다.';approve.disabled=lastAction!=='approvals';reject.disabled=lastAction!=='rejections';}
    finally{busy=false;reason.disabled=gate.pending();form.removeAttribute('aria-busy');}
  }
  approve.addEventListener('click',function(){decide('approvals');});reject.addEventListener('click',function(){decide('rejections');});
})();
