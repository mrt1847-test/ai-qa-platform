(function () {
  'use strict';
  var form = document.getElementById('suite-create');
  if (!form || !window.aiqaForms || !window.aiqaRequest) return;
  var project = form.getAttribute('data-project');
  var list = document.querySelector('[data-suite-list]');
  var dialog = document.getElementById('suite-confirm');
  var confirmForm = document.getElementById('suite-confirm-form');
  var pending = null;

  function readCreate() {
    return {
      name: form.name.value,
      description: form.description.value,
      target_kind: form.target_kind.value,
      owner_name: form.owner_name.value,
      classification: form.classification.value
    };
  }

  function appendSuite(view) {
    if (!list) return;
    var empty = list.querySelector('[data-empty-suites]');
    if (empty) empty.remove();
    var item = document.createElement('li');
    item.dataset.suiteId = view.suite_id;
    item.innerHTML =
      '<a href="/ui/projects/' + project + '/suites/' + view.suite_id + '"></a>' +
      '<span></span><span></span><span></span><span></span><span></span><span data-head-version=""></span>' +
      '<button type="button" class="secondary" data-suite-clone>복제</button>' +
      '<button type="button" class="secondary" data-suite-archive>보관</button>';
    var link = item.querySelector('a');
    link.textContent = view.name;
    var spans = item.querySelectorAll('span');
    spans[0].textContent = view.description || '';
    spans[1].textContent = view.target_kind || '';
    spans[2].textContent = '담당 ' + (view.owner_name || '');
    spans[3].textContent = '구성 ' + String(view.entry_count || 0);
    spans[4].textContent = '분류 ' + (view.classification || '');
    spans[5].textContent = '버전 ' + (view.version_id || '');
    spans[5].dataset.headVersion = view.version_id || '';
    var cloneBtn = item.querySelector('[data-suite-clone]');
    cloneBtn.dataset.suiteId = view.suite_id;
    cloneBtn.dataset.suiteName = view.name;
    var archiveBtn = item.querySelector('[data-suite-archive]');
    archiveBtn.dataset.suiteId = view.suite_id;
    archiveBtn.dataset.suiteName = view.name;
    list.prepend(item);
  }

  window.aiqaForms.register(form, {
    read: readCreate,
    persist: function (body, key) {
      return window.aiqaRequest('/api/v1/projects/' + project + '/suites', {
        method: 'POST',
        headers: { 'Idempotency-Key': key },
        body: JSON.stringify(body)
      });
    },
    onSaved: function (body) {
      appendSuite(body);
      form.reset();
    },
    successMessage: function (body) {
      return '묶음을 만들었습니다. ' + (body.suite_id || '');
    }
  });

  function openConfirm(action, suiteId, suiteName) {
    pending = { action: action, suiteId: suiteId, suiteName: suiteName };
    var title = confirmForm.querySelector('[data-confirm-title]');
    var message = confirmForm.querySelector('[data-confirm-message]');
    var wrap = confirmForm.querySelector('[data-confirm-name-wrap]');
    var status = confirmForm.querySelector('[data-confirm-status]');
    status.textContent = '';
    if (action === 'clone') {
      title.textContent = '묶음 복제';
      message.textContent = '"' + suiteName + '" 묶음을 복제합니다. 기존 수행과 버전은 그대로 둡니다.';
      wrap.hidden = false;
      confirmForm.clone_name.value = suiteName + ' 복사';
    } else {
      title.textContent = '묶음 보관';
      message.textContent = '"' + suiteName + '" 묶음을 보관합니다. 기존 수행과 버전은 그대로 둡니다.';
      wrap.hidden = true;
    }
    if (typeof dialog.showModal === 'function') dialog.showModal();
  }

  document.addEventListener('click', function (event) {
    var clone = event.target.closest('[data-suite-clone]');
    if (clone) {
      openConfirm('clone', clone.dataset.suiteId, clone.dataset.suiteName || '');
      return;
    }
    var archive = event.target.closest('[data-suite-archive]');
    if (archive) openConfirm('archive', archive.dataset.suiteId, archive.dataset.suiteName || '');
  });

  confirmForm.addEventListener('submit', function (event) {
    var value = event.submitter ? event.submitter.value : 'cancel';
    if (value !== 'confirm' || !pending) return;
    event.preventDefault();
    var status = confirmForm.querySelector('[data-confirm-status]');
    var action = pending.action;
    var suiteId = pending.suiteId;
    var body = { project_id: project };
    if (action === 'clone') body.name = confirmForm.clone_name.value;
    var gate = window.aiqaCommand(function (payload, key) {
      return window.aiqaRequest('/api/v1/suites/' + suiteId + '/' + (action === 'clone' ? 'clone' : 'archive'), {
        method: 'POST',
        headers: { 'Idempotency-Key': key },
        body: JSON.stringify(payload)
      });
    });
    status.textContent = '요청 중…';
    gate.send(body).then(function (response) {
      return response.json().then(function (payload) {
        if (!response.ok) {
          status.textContent = (payload.error && payload.error.message) || '요청이 거절되었습니다. 입력은 유지됩니다.';
          return;
        }
        if (action === 'clone') appendSuite(payload);
        else {
          var row = list && list.querySelector('[data-suite-id="' + suiteId + '"]');
          if (row) {
            row.dataset.archived = 'true';
            row.querySelectorAll('[data-suite-clone],[data-suite-archive]').forEach(function (node) { node.remove(); });
            var mark = document.createElement('span');
            mark.textContent = '보관됨';
            row.appendChild(mark);
          }
        }
        status.textContent = action === 'clone' ? '복제했습니다.' : '보관했습니다.';
        pending = null;
        dialog.close();
      });
    }).catch(function () {
      status.textContent = '응답을 확인하지 못했습니다. 입력은 유지됩니다.';
    });
  });
})();
