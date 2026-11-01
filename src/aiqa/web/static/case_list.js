(function(){
  var all=document.getElementById('select-page');if(!all)return;
  var boxes=Array.from(document.querySelectorAll('input[name="selected"][type="checkbox"]'));
  var clear=document.getElementById('clear-selection'),count=document.getElementById('selection-count'),trial=document.getElementById('selected-trial');
  function update(){
    var chosen=boxes.filter(function(box){return box.checked;});
    count.textContent=chosen.length+'개 선택 · 현재 페이지';clear.disabled=chosen.length===0;all.checked=chosen.length>0&&chosen.length===boxes.length;all.indeterminate=chosen.length>0&&chosen.length<boxes.length;
    document.querySelectorAll('#bulk-clone input[type="submit"],#bulk-archive input[type="submit"]').forEach(function(button){button.disabled=chosen.length===0;});
    trial.setAttribute('aria-disabled',chosen.length!==1?'true':'false');
    if(chosen.length===1){var base=location.pathname;trial.href=base+'/'+encodeURIComponent(chosen[0].value)+'/execution-setup';}else trial.removeAttribute('href');
  }
  boxes.forEach(function(box){box.checked=false;box.addEventListener('change',update);});
  all.addEventListener('change',function(){boxes.forEach(function(box){box.checked=all.checked;});update();});
  clear.addEventListener('click',function(){boxes.forEach(function(box){box.checked=false;});update();});
  window.addEventListener('pageshow',function(){boxes.forEach(function(box){box.checked=false;});update();});
  document.querySelectorAll('[data-copy]').forEach(function(button){button.addEventListener('click',async function(){try{await navigator.clipboard.writeText(button.dataset.copy);count.textContent='전체 ID를 복사했습니다.';}catch(_){count.textContent='복사하지 못했습니다. 전체 ID: '+button.dataset.copy;}});});
  update();
})();
