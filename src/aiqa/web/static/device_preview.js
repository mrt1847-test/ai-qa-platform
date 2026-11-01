(function(){
  document.querySelectorAll('[data-resource-preview]').forEach(function(root){
    var id=root.dataset.resourcePreview,project=root.dataset.project,message=root.querySelector('[data-preview-note]'),image=root.querySelector('img'),time=root.querySelector('time');
    var observed=root.dataset.observed;
    function showTime(raw){var date=new Date(raw);if(!raw||!Number.isFinite(date.getTime())){time.textContent='관찰 시각 확인 전';return;}time.dateTime=raw;time.textContent=date.toLocaleString('ko-KR')+' · 실시간 아님'+(Date.now()-date.getTime()>300000?' · 오래된 관찰':'');}
    showTime(observed);
    window.aiqaRequest('/api/v1/resources/'+encodeURIComponent(id)+'/preview?project_id='+encodeURIComponent(project),{method:'GET'}).then(async function(response){
      var body=await response.json();image.hidden=true;
      if(!response.ok){message.textContent=response.status===403?'이 기기의 관찰 화면을 볼 권한이 없습니다.':'관찰 화면을 확인하지 못했습니다. 연결 진단을 확인하세요.';return;}
      showTime(body.observed_at);root.dataset.preview=body.reason;
      var messages={expired:'최근 관찰의 보관 기한이 지났습니다. 새 관찰 수집 후 확인하세요.',unobserved:'아직 저장된 관찰이 없습니다. 기기와 작업자 연결을 확인하세요.',unauthorized:'기기에서 USB 디버깅 권한을 허용한 뒤 확인하세요.'};
      if(body.reason==='observed'&&body.artifact_id&&body.raw_control===false){image.src='/api/v1/artifacts/'+encodeURIComponent(body.artifact_id);image.hidden=false;message.textContent='저장된 정제 관찰입니다. 기기 제어 화면이 아닙니다.';}
      else message.textContent=messages[body.reason]||'저장된 관찰을 아직 표시할 수 없습니다. 연결 상태를 확인하세요.';
    }).catch(function(){message.textContent='관찰 조회 응답을 받지 못했습니다. 연결을 확인하고 페이지를 다시 여세요.';});
    image.addEventListener('error',function(){image.hidden=true;message.textContent='캡처 파일을 불러오지 못했습니다. 증거 보관 상태와 새 관찰을 확인하세요.';});
  });
})();
