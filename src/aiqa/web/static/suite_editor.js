(function () {
  'use strict';
  var form = document.getElementById('suite-entries');
  if (!form || !window.aiqaForms || !window.aiqaRequest) return;
  var project = form.getAttribute('data-project');
  var suiteId = form.getAttribute('data-suite-id');
  var list = form.querySelector('[data-entry-list]');
  var expected = form.querySelector('[name="expected_version_id"]');
  var upgradeStatus = document.querySelector('[data-upgrade-status]');

  function rows() {
    return Array.prototype.slice.call(list.querySelectorAll('[data-entry-row]'));
  }

  function clearEmpty() {
    var empty = list.querySelector('[data-empty-entries]');
    if (empty) empty.remove();
  }

  function readEntries() {
    return rows().map(function (row) {
      return {
        entry_id: row.querySelector('[name="entry_id"]').value,
        case_id: row.querySelector('[name="case_id"]').value,
        case_version_id: row.querySelector('[name="case_version_id"]').value,
        approval_id: row.querySelector('[name="approval_id"]').value,
        data_name: row.querySelector('[name="data_name"]').value,
        environment_revision_id: row.querySelector('[name="environment_revision_id"]').value,
        reset_policy: row.querySelector('[name="reset_policy"]').value,
        failure_policy: row.querySelector('[name="failure_policy"]').value,
        resource_id: row.querySelector('[name="resource_id"]').value,
        target_kind: row.querySelector('[name="target_kind"]').value
      };
    });
  }

  function buildRow(entry) {
    var li = document.createElement('li');
    li.dataset.entryRow = '';
    li.dataset.entryId = entry.entry_id;
    li.innerHTML =
      '<label>항목 <input name="entry_id" required></label>' +
      '<input type="hidden" name="case_id">' +
      '<input type="hidden" name="case_version_id">' +
      '<input type="hidden" name="approval_id">' +
      '<span></span>' +
      '<label>데이터 행 <input name="data_name" required></label>' +
      '<label>환경 <input name="environment_revision_id"></label>' +
      '<label>초기화 <select name="reset_policy"><option value="keep">keep</option><option value="reset">reset</option></select></label>' +
      '<label>실패 <select name="failure_policy"><option value="continue">continue</option><option value="stop">stop</option></select></label>' +
      '<label>자원 <input name="resource_id"></label>' +
      '<label>대상 <select name="target_kind"><option value="web">web</option><option value="android">android</option></select></label>' +
      '<button type="button" class="secondary" data-entry-up>위로</button>' +
      '<button type="button" class="secondary" data-entry-down>아래로</button>' +
      '<button type="button" class="secondary" data-entry-remove>삭제</button>';
    li.querySelector('[name="entry_id"]').value = entry.entry_id;
    li.querySelector('[name="case_id"]').value = entry.case_id;
    li.querySelector('[name="case_version_id"]').value = entry.case_version_id;
    li.querySelector('[name="approval_id"]').value = entry.approval_id;
    li.querySelector('[name="data_name"]').value = entry.data_name;
    li.querySelector('[name="environment_revision_id"]').value = entry.environment_revision_id || '';
    li.querySelector('[name="reset_policy"]').value = entry.reset_policy || 'keep';
    li.querySelector('[name="failure_policy"]').value = entry.failure_policy || 'stop';
    li.querySelector('[name="resource_id"]').value = entry.resource_id || '';
    li.querySelector('[name="target_kind"]').value = entry.target_kind || 'web';
    li.querySelector('span').textContent =
      entry.entry_id +
      ' ' +
      entry.data_name +
      ' ' +
      entry.target_kind +
      ' ' +
      entry.case_version_id +
      ' ' +
      entry.approval_id +
      ' ' +
      (entry.reset_policy || 'keep') +
      ' ' +
      (entry.failure_policy || 'stop') +
      ' ' +
      (entry.resource_id || '');
    return li;
  }

  function nextEntryId() {
    return 'entry-' + String(rows().length + 1) + '-' + String(Date.now()).slice(-6);
  }

  document.addEventListener('click', function (event) {
    var add = event.target.closest('[data-add-case]');
    if (add) {
      clearEmpty();
      list.appendChild(
        buildRow({
          entry_id: nextEntryId(),
          case_id: add.getAttribute('data-case-id'),
          case_version_id: add.getAttribute('data-case-version-id'),
          approval_id: add.getAttribute('data-approval-id'),
          data_name: add.getAttribute('data-case-name') || '행',
          environment_revision_id: '',
          reset_policy: 'keep',
          failure_policy: 'stop',
          resource_id: '',
          target_kind: add.getAttribute('data-target-kind') || 'web'
        })
      );
      form.dispatchEvent(new Event('input', { bubbles: true }));
      return;
    }
    var remove = event.target.closest('[data-entry-remove]');
    if (remove) {
      var row = remove.closest('[data-entry-row]');
      if (row) row.remove();
      if (!rows().length) {
        var empty = document.createElement('li');
        empty.dataset.emptyEntries = '';
        empty.textContent = '구성이 비어 있습니다.';
        list.appendChild(empty);
      }
      form.dispatchEvent(new Event('input', { bubbles: true }));
      return;
    }
    var up = event.target.closest('[data-entry-up]');
    if (up) {
      var current = up.closest('[data-entry-row]');
      if (current && current.previousElementSibling && current.previousElementSibling.matches('[data-entry-row]')) {
        list.insertBefore(current, current.previousElementSibling);
        form.dispatchEvent(new Event('input', { bubbles: true }));
      }
      return;
    }
    var down = event.target.closest('[data-entry-down]');
    if (down) {
      var moving = down.closest('[data-entry-row]');
      if (moving && moving.nextElementSibling && moving.nextElementSibling.matches('[data-entry-row]')) {
        list.insertBefore(moving.nextElementSibling, moving);
        form.dispatchEvent(new Event('input', { bubbles: true }));
      }
      return;
    }
    if (event.target.closest('[data-upgrade-accept]')) {
      decideUpgrade('accept');
      return;
    }
    if (event.target.closest('[data-upgrade-reject]')) {
      decideUpgrade('reject');
    }
  });

  function decideUpgrade(decision) {
    if (!upgradeStatus) return;
    var selected = Array.prototype.slice
      .call(document.querySelectorAll('[data-upgrade-entry]:checked'))
      .map(function (box) {
        return box.value;
      });
    if (decision === 'accept' && !selected.length) {
      upgradeStatus.textContent = '수락할 항목을 선택하세요.';
      return;
    }
    var key = 'ux03-upgrade-' + decision + '-' + String(Date.now());
    window
      .aiqaRequest('/api/v1/suites/' + suiteId + '/versions', {
        method: 'POST',
        headers: { 'Idempotency-Key': key },
        body: JSON.stringify({
          project_id: project,
          decision: decision,
          expected_version_id: expected.value,
          entry_ids: selected
        })
      })
      .then(function (response) {
        return response.json().then(function (body) {
          return { ok: response.ok, status: response.status, body: body };
        });
      })
      .then(function (result) {
        if (!result.ok) {
          upgradeStatus.textContent =
            result.status === 409 ? '구성이 바뀌었습니다. 화면을 다시 연 뒤 저장하세요.' : '제안을 처리하지 못했습니다.';
          return;
        }
        if (result.body.suite_version_id) {
          expected.value = result.body.suite_version_id;
          form.setAttribute('data-expected-version', result.body.suite_version_id);
        }
        upgradeStatus.textContent = decision === 'reject' ? '제안을 거부했습니다.' : '선택한 항목을 새 구성으로 옮겼습니다.';
        if (decision === 'accept') {
          setTimeout(function () {
            window.location.reload();
          }, 0);
        }
      })
      .catch(function () {
        upgradeStatus.textContent = '연결을 확인한 뒤 다시 시도하세요. 입력은 유지됩니다.';
      });
  }

  window.aiqaForms.register(form, {
    read: function () {
      return {
        project_id: project,
        expected_version_id: expected.value,
        entries: readEntries()
      };
    },
    persist: function (body, key) {
      return window.aiqaRequest('/api/v1/suites/' + suiteId + '/versions', {
        method: 'POST',
        headers: { 'Idempotency-Key': key },
        body: JSON.stringify(body)
      });
    },
    onConflict: function () {
      var note = form.querySelector('[data-save-message]');
      if (note) note.textContent = '구성이 바뀌었습니다. 화면을 다시 연 뒤 저장하세요. 입력은 유지됩니다.';
    },
    onSaved: function (body) {
      if (body.suite_version_id) {
        expected.value = body.suite_version_id;
        form.setAttribute('data-expected-version', body.suite_version_id);
      }
    },
    successMessage: function (body) {
      return '새 구성을 저장했습니다. ' + (body.suite_version_id || '');
    }
  });
})();
