(function(){
  window.aiqaCompareConflict=function(form,server,local,accept){
    var section=form.querySelector('[data-conflict-comparison]');if(!section)return;
    section.replaceChildren();section.hidden=false;var title=document.createElement('h2');title.textContent='동시 수정 비교';section.appendChild(title);
    var note=document.createElement('p');note.textContent='내 입력을 유지했습니다. 서버의 변경과 비교한 뒤 내 내용으로 새 저장을 준비하거나 계속 편집하세요. 이 선택만으로 저장하지 않습니다.';section.appendChild(note);
    var table=document.createElement('table'),head=document.createElement('thead'),tr=document.createElement('tr');['항목','현재 서버본','내 작성 내용'].forEach(function(label){var th=document.createElement('th');th.scope='col';th.textContent=label;tr.appendChild(th);});head.appendChild(tr);table.appendChild(head);var body=document.createElement('tbody');
    var labels={raw_text:'자연어',objective:'목적',preconditions:'사전조건',variables:'입력 변수',secret_refs:'비밀 참조',steps:'단계와 검증',final_expected:'최종 기대',path_policy:'필수·금지 경로',settings:'실행 설정',recorded_steps:'녹화 절차',lock_version:'설정 저장 버전',timeout_seconds:'제한 시간',bindings:'모델 연결'};
    Object.keys(Object.assign({},server,local)).filter(function(key){return !['expected_head','parent_version_id','roles'].includes(key);}).forEach(function(key){if(JSON.stringify(server[key])===JSON.stringify(local[key]))return;var row=document.createElement('tr');[labels[key]||key,server[key],local[key]].forEach(function(value){var td=document.createElement('td'),pre=document.createElement('pre');pre.textContent=typeof value==='string'?value:JSON.stringify(value,null,2)||'없음';td.appendChild(pre);row.appendChild(td);});body.appendChild(row);});table.appendChild(body);var scroll=document.createElement('div');scroll.className='table-scroll';scroll.appendChild(table);section.appendChild(scroll);
    var action=document.createElement('input');action.type='button';action.value='비교한 서버본을 기준으로 내 수정 저장 준비';action.className='secondary';action.addEventListener('click',function(){accept();action.disabled=true;note.textContent='새 기준을 확인했습니다. 편집 내용을 검토하고 저장 버튼을 직접 눌러 주세요.';});section.appendChild(action);section.tabIndex=-1;section.focus();
  };
})();
