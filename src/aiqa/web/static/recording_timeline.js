(function () {
  var root = document.getElementById("recording-timeline-root");
  if (!root) {
    return;
  }
  var url = root.getAttribute("data-timeline-url") || "";
  var seconds = Number(root.getAttribute("data-poll-seconds") || "2");
  var lastCount = Number(root.getAttribute("data-action-count") || "0");
  var countNode = root.querySelector("[data-ack-count]");
  var lastCompletion=root.getAttribute("data-completion-status")||"";
  var pendingReload=false;

  function selectedAction() {
    var params = new URLSearchParams(window.location.search);
    return root.getAttribute("data-action-id") || params.get("action_id") || "";
  }

  function reloadKeepingSelection(actions) {
    var params = new URLSearchParams(window.location.search);
    var current = selectedAction();
    var stillThere = actions.some(function (item) {
      return item.action_id === current;
    });
    if (stillThere) {
      params.set("action_id", current);
    } else if (actions.length) {
      params.set("action_id", actions[0].action_id);
    } else {
      params.delete("action_id");
    }
    var next = window.location.pathname + (params.toString() ? "?" + params.toString() : "");
    try {var focus=focusedAction(document.getElementById('recording-timeline'));if(focus)window.sessionStorage.setItem('aiqa.recording.timeline-focus:'+window.location.pathname,focus);} catch(ignore) {}
    window.location.replace(next);
  }

  var stateLabels={planned:'동작 준비',lookup_failed:'전달 전 중단',dispatch_started:'기기 전달 중',acknowledged:'기기 전달 확인',observed:'관찰 기록',unknown:'전달 결과 확인 불가'};
  var shotLabels={stored:'저장됨',missing:'미수신',corrupt:'손상됨',expired:'보관 만료',delayed:'늦게 수신'};
  var checkLabels={satisfied:'조건 충족',violated:'조건 불일치',unknown:'확인 필요',unavailable:'확인 불가',error:'검증 오류'};
  function focusedAction(nav) {
    return nav&&nav.contains(document.activeElement)?document.activeElement.getAttribute('data-timeline-action'):null;
  }
  function focusAction(nav,identity,preventScroll) {
    if(!nav||!identity)return;
    var links=nav.querySelectorAll('[data-timeline-action]');
    for(var i=0;i<links.length;i++)if(links[i].getAttribute('data-timeline-action')===identity){links[i].focus({preventScroll:preventScroll});return;}
  }
  function textNode(tag,text,attribute) {
    var node=document.createElement(tag);node.textContent=text;
    if(attribute)node.setAttribute(attribute,'');
    return node;
  }
  function paintNav(actions,selectedIdentity) {
    var nav=document.getElementById('recording-timeline');if(!nav)return;
    var focused=focusedAction(nav),current=selectedIdentity||selectedAction(),fragment=document.createDocumentFragment();
    if(!actions.some(function(entry){return entry.action_id===current;}))current=actions.length?actions[0].action_id:'';
    root.setAttribute('data-action-id',current);
    if(!actions.length){var empty=textNode('p','아직 수신된 동작이 없습니다.');empty.className='empty';fragment.appendChild(empty);}
    actions.forEach(function(entry){
      var link=document.createElement('a');link.className='review-step';
      link.href='?action_id='+encodeURIComponent(entry.action_id);
      link.setAttribute('data-timeline-action',entry.action_id);link.setAttribute('data-action-seq',entry.action_seq);
      link.title='원본 참조: '+(entry.step_id||entry.action_id);
      if(entry.action_id===current)link.setAttribute('aria-current','step');
      link.appendChild(textNode('span','순서 '+entry.action_seq+' · '+(entry.label||'동작 '+entry.action_seq),'data-action-label'));
      var fallbackState=entry.dispatch_state==='observed'&&entry.before==='stored'&&entry.after==='stored'&&entry.log==='stored'?'화면·로그 수신':stateLabels[entry.dispatch_state]||'상태 확인 필요';
      var state=textNode('small',entry.state_label||fallbackState,'data-dispatch');
      state.setAttribute('data-dispatch-state',entry.dispatch_state);link.appendChild(state);
      link.appendChild(textNode('small','이전 '+(entry.before_label||shotLabels[entry.before]||'확인 필요')+' · 이후 '+(entry.after_label||shotLabels[entry.after]||'확인 필요')+' · 로그 '+(entry.log_label||shotLabels[entry.log]||'확인 필요'),'data-shot-state'));
      if(entry.error_text)link.appendChild(textNode('small','오류 '+entry.error_text,'data-error'));
      else if(entry.check_status)link.appendChild(textNode('small','검증 '+(entry.check_label||checkLabels[entry.check_status]||'확인 필요'),'data-check'));
      fragment.appendChild(link);
    });
    nav.replaceChildren(fragment);focusAction(nav,focused,true);
  }

  function poll() {
    if (document.hidden || !url) {
      return;
    }
    var request = window.aiqaRequest || function (path, options) {
      return window.fetch(path, options);
    };
    var action = selectedAction();
    var target = url + (url.indexOf("?") >= 0 ? "&" : "?") + "action_id=" + encodeURIComponent(action);
    request(target, { method: "GET", credentials: "same-origin" })
      .then(function (response) {
        if (!response.ok) {
          throw new Error("poll");
        }
        return response.json();
      })
      .then(function (body) {
        var actions = body.actions || [];
        if (countNode) {
          countNode.textContent = "수신 기록 " + actions.length + "개";
        }
        var completion=body.completion_status||lastCompletion;
        if (pendingReload||actions.length!==lastCount||completion!==lastCompletion) {
          var dirty=window.aiqaForms&&window.aiqaForms.dirty&&window.aiqaForms.dirty().length>0;
          if(dirty){pendingReload=true;paintNav(actions,body.selected_action_id);return;}
          pendingReload=false;lastCount=actions.length;lastCompletion=completion;
          reloadKeepingSelection(actions);
          return;
        }
        paintNav(actions,body.selected_action_id);
      })
      .catch(function () {});
  }

  try {var focusKey='aiqa.recording.timeline-focus:'+window.location.pathname;var restored=window.sessionStorage.getItem(focusKey);window.sessionStorage.removeItem(focusKey);focusAction(document.getElementById('recording-timeline'),restored,false);} catch(ignore) {}

  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) {
      poll();
    }
  });
  window.setInterval(poll, seconds === 2 ? 2000 : seconds * 1000);
})();
