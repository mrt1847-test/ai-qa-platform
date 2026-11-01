(function () {
  var root = document.getElementById("evidence-viewer");
  if (!root) {
    return;
  }
  var params = new URLSearchParams(window.location.search);
  var actions = Array.prototype.slice.call(root.querySelectorAll("[data-action]"));
  var fullscreenActive=false;
  function fullscreenState(open){fullscreenActive=open;root.querySelectorAll('[data-view-mode="full"]').forEach(function(link){link.textContent=open?'전체보기 닫기':'전체보기';link.setAttribute('aria-expanded',String(open));});}

  function show(actionId) {
    actions.forEach(function (node) {
      node.hidden = node.getAttribute("data-action") !== actionId;
    });
    root.setAttribute("data-action-id", actionId);
    if(!params.has('entry')){params.set("action_id", actionId);window.history.replaceState(null, "", window.location.pathname + "?" + params.toString());}
  }

  root.addEventListener("keydown", function (event) {
    if(event.target.closest('input,textarea,select,[contenteditable="true"]'))return;
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") {
      return;
    }
    var current = root.getAttribute("data-action-id");
    var index = -1;
    actions.forEach(function (node, position) {
      if (node.getAttribute("data-action") === current) {
        index = position;
      }
    });
    var next = event.key === "ArrowRight" ? index + 1 : index - 1;
    if (next < 0 || next >= actions.length) {
      return;
    }
    event.preventDefault();
    show(actions[next].getAttribute("data-action"));
  });

  root.querySelectorAll("[data-view-mode]").forEach(function (link) {
    link.addEventListener("click", function (event) {
      event.preventDefault();
      root.setAttribute("data-view", link.getAttribute("data-view-mode"));
      var mode=link.getAttribute('data-view-mode');
      root.querySelectorAll('[data-view-mode]').forEach(function(item){if(item===link)item.setAttribute('aria-current','true');else item.removeAttribute('aria-current');});
      root.querySelectorAll('img').forEach(function(img){
        if(mode==='fit'){img.style.width='';img.style.maxWidth='100%';img.style.maxHeight='100%';}
        else{img.style.maxWidth='none';img.style.maxHeight='none';img.style.width=Math.round((img.naturalWidth||img.width)*(mode==='zoom'?1.5:1))+'px';}
      });
      var note=root.querySelector('[data-view-note]');if(note)note.textContent=mode==='pan'?'이미지 영역을 끌거나 스크롤해 이동하세요.':mode==='hundred'?'원본 크기 100%':mode==='zoom'?'원본 크기 150%':mode==='fit'?'영역에 맞춘 크기':'';
      if(mode==='full'){
        if((fullscreenActive||document.fullscreenElement===root)&&document.exitFullscreen){fullscreenState(false);Promise.resolve(document.exitFullscreen()).catch(function(){if(note)note.textContent='전체보기 상태를 다시 확인하세요.';});}
        else if(root.requestFullscreen){fullscreenState(true);Promise.resolve(root.requestFullscreen()).catch(function(){fullscreenState(false);if(note)note.textContent='전체 화면을 열지 못했습니다. 100% 이미지 영역에서 확인하세요.';});}
        else if(note)note.textContent='이 브라우저는 전체보기를 지원하지 않습니다. 100% 이미지 영역에서 확인하세요.';
      }
    });
  });
  root.addEventListener('fullscreenchange',function(){fullscreenState(document.fullscreenElement===root);});
  if(document.addEventListener)document.addEventListener('fullscreenchange',function(){fullscreenState(document.fullscreenElement===root);});
  var steps = { previous: -1, next: 1 };
  root.querySelectorAll("[data-step]").forEach(function (link) {
    link.addEventListener("click", function (event) {
      var name = link.getAttribute("data-step");
      if (name === "first-failure") {
        event.preventDefault();
        var failure = root.getAttribute("data-first-failure");
        if (failure) {
          show(failure);
        }
        return;
      }
      if (!(name in steps)) {
        return;
      }
      event.preventDefault();
      var current = root.getAttribute("data-action-id");
      var index = -1;
      actions.forEach(function (node, position) {
        if (node.getAttribute("data-action") === current) {
          index = position;
        }
      });
      var next = index + steps[name];
      if (next < 0 || next >= actions.length) {
        return;
      }
      show(actions[next].getAttribute("data-action"));
    });
  });
  root.querySelectorAll('.capture-viewport').forEach(function(viewport){
    var drag=null;
    viewport.addEventListener('pointerdown',function(event){if(root.dataset.view!=='pan')return;drag={x:event.clientX,y:event.clientY,left:viewport.scrollLeft,top:viewport.scrollTop};viewport.setPointerCapture(event.pointerId);event.preventDefault();});
    viewport.addEventListener('pointermove',function(event){if(!drag)return;viewport.scrollLeft=drag.left+drag.x-event.clientX;viewport.scrollTop=drag.top+drag.y-event.clientY;});
    ['pointerup','pointercancel','lostpointercapture'].forEach(function(name){viewport.addEventListener(name,function(){drag=null;});});
    var img=viewport.querySelector('img');if(img)img.addEventListener('error',function(){var reason=document.createElement('p');reason.textContent='이 캡처를 불러오지 못했습니다. 보관 상태와 연결을 확인하세요.';img.replaceWith(reason);});
  });
})();
