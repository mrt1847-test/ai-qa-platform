/* Form state is page-memory only. No input values are persisted in browser storage. */
(function () {
  'use strict';
  var handles = [];
  var messages = {idle:'',dirty:'저장하지 않은 변경이 있습니다.',saving:'저장 중…',saved:'저장했습니다.',invalid:'입력을 확인해 주세요.',conflict:'다른 곳에서 변경되었습니다. 입력을 유지했습니다. 최신 내용을 확인해 주세요.',forbidden:'저장할 권한 또는 연결 세션을 확인해 주세요. 입력을 유지했습니다.',unknown:'저장 응답을 확인하지 못했습니다. 입력을 유지했습니다. 같은 요청 재시도로 저장 여부를 확인하세요.'};
  function copy(value) { return JSON.parse(JSON.stringify(value)); }
  function register(form, options) {
    var original = JSON.stringify(options.read()), pending = null, inFlight = null;
    var acknowledged = false;
    var savingButtons = null;
    var feedback = form.querySelector('[data-form-feedback]');
    var handle = {form:form,saveBeforeLeave:options.saveBeforeLeave !== false};
    function isDirty() {try {return JSON.stringify(options.read()) !== original;} catch (_) {return true;}}
    function state(name, detail, fields) {
      form.dataset.saveState = name;
      form.setAttribute('aria-busy',name === 'saving' ? 'true' : 'false');
      if(name==='saving'&&!savingButtons){savingButtons=Array.from(form.querySelectorAll('[data-save-button],button[type="submit"],input[type="submit"]')).map(function(button){return {node:button,disabled:button.disabled};});savingButtons.forEach(function(item){item.node.disabled=true;});}
      else if(name!=='saving'&&savingButtons){savingButtons.forEach(function(item){item.node.disabled=item.disabled;});savingButtons=null;}
      if (!feedback) return;
      var confirm = feedback.querySelector('[data-confirm-pending]');if(confirm)confirm.hidden=name!=='unknown'||!pending;
      var note = feedback.querySelector('[data-save-message]');
      if (note) note.textContent = detail || messages[name];
      var list = feedback.querySelector('[data-field-errors]');
      if (list) list.replaceChildren();
      form.querySelectorAll('[aria-invalid="true"]').forEach(function (node) {node.removeAttribute('aria-invalid');var prior=node.getAttribute('aria-describedby')||'';node.setAttribute('aria-describedby',prior.split(' ').filter(function(id){return id!==node.id+'-error';}).join(' '));});
      Object.keys(fields || {}).forEach(function (field, index) {
        var node = Array.from(form.querySelectorAll('[name]')).find(function (n) {return n.name === field;});
        var errors = Array.isArray(fields[field]) ? fields[field] : [fields[field]];
        if (!list) return;
        var item = document.createElement('li');
        var label=node && ((node.labels && node.labels[0] && node.labels[0].textContent.trim()) || node.getAttribute('aria-label'));
        var text = (label || ({columns:'열 정의',rows:'입력 행'}[field]) || field) + ': ' + errors.join(' ');
        if (node) {
          if (!node.id) node.id = 'field-' + handles.length + '-' + index;
          node.setAttribute('aria-invalid','true');
          var link = document.createElement('a');
          link.href = '#' + node.id;link.textContent = text;
          link.addEventListener('click',function (event) {event.preventDefault();node.focus();});
          item.appendChild(link);
          item.id = node.id + '-error';
          node.setAttribute('aria-describedby',item.id);
        } else item.textContent = text;
        list.appendChild(item);
      });
      var first = form.querySelector('[aria-invalid="true"]');
      if (first) first.focus();
    }
    function edited() {
      if (!inFlight && form.dataset.saveState !== 'unknown') state(isDirty() ? 'dirty' : (acknowledged ? 'saved' : 'idle'));
      if (typeof document.dispatchEvent === 'function') document.dispatchEvent(new Event('aiqa:dirty'));
    }
    handle.isDirty = isDirty;
    handle.markSaved = function () {original=JSON.stringify(options.read());acknowledged=true;state('saved');};
    function dispatch(payload,serialized,request) {
      state('saving');
      inFlight = Promise.resolve().then(function () {return options.persist(payload,request.key);})
        .then(function (response) {
          return response.json().then(function (body) {
            if (!response.ok) {
              var names = {409:'conflict',401:'forbidden',403:'forbidden',422:'invalid'};
              var error=body.error || {};
              state(names[response.status] || 'invalid',null,error.fields);
              pending=null;
              if(response.status===409&&options.onConflict)options.onConflict(body,payload);
              return false;
            }
            original=serialized;acknowledged=true;pending=null;
            if (options.onSaved) options.onSaved(body,payload);
            state(isDirty() ? 'dirty' : 'saved',options.successMessage ? options.successMessage(body) : null);
            return true;
          });
        }).catch(function () {state('unknown');return false;})
        .finally(function () {inFlight=null;});
      return inFlight;
    }
    handle.save = function () {
      if (inFlight) return inFlight;
      var payload, serialized;
      try {payload=copy(options.read());serialized=JSON.stringify(payload);}
      catch (error) {state('invalid',error.message,error.fields);return Promise.resolve(false);}
      if (acknowledged && serialized === original && !pending) return Promise.resolve(true);
      if (pending && pending.body !== serialized && form.dataset.saveState === 'unknown') {
        state('unknown','확인되지 않은 이전 요청이 있습니다. 아래에서 저장 여부를 확인하세요. 지금 수정한 값은 유지됩니다.');
        return Promise.resolve(false);
      }
      if (!pending || pending.body !== serialized) pending={body:serialized,key:crypto.randomUUID()};
      return dispatch(payload,serialized,pending);
    };
    handle.confirmPending=function(){if(inFlight)return inFlight;if(!pending)return Promise.resolve(false);return dispatch(JSON.parse(pending.body),pending.body,pending);};
    if(feedback){var retry=feedback.querySelector('[data-confirm-pending]');if(retry)retry.addEventListener('click',handle.confirmPending);}
    handle.dispose = function () {form.removeEventListener('input',edited);form.removeEventListener('change',edited);handles=handles.filter(function(h){return h!==handle;});};
    form.addEventListener('input',edited);form.addEventListener('change',edited);
    form.addEventListener('submit',function(event){event.preventDefault();handle.save();});
    handles.push(handle);state('idle');
    return handle;
  }
  window.aiqaForms={register:register,dirty:function(){return handles.filter(function(h){return h.isDirty();});}};
})();
