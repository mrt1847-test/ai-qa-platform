(function(){
  document.querySelectorAll('[data-secret-picker]').forEach(function(select){
    var current=select.dataset.current?JSON.parse(select.dataset.current):null;
    function key(ref){return ref?JSON.stringify({project_id:ref.project_id,ref_id:ref.ref_id,revision:ref.revision}):'';}
    var original=key(current);if(current){var option=document.createElement('option');option.value=original;option.textContent='현재 고정한 비밀 참조 · '+current.ref_id.slice(0,8)+' · v'+current.revision;select.appendChild(option);select.value=original;}
    window.aiqaRequest('/api/v1/projects/'+select.dataset.project+'/secret-refs',{method:'GET'}).then(function(response){return response.ok?response.json():{refs:[]};}).then(function(body){
      var previous=select.value;(body.refs||[]).forEach(function(item){var value=key(item);if(Array.from(select.options).some(function(option){return option.value===value;}))return;var option=document.createElement('option');option.value=value;option.textContent=item.name+' · v'+item.revision;select.appendChild(option);});select.value=previous;
    }).catch(function(){var note=document.querySelector('[data-secret-note]');if(note)note.textContent='참조 목록을 가져오지 못했습니다. 기존 참조는 유지됩니다.';});
  });
})();
