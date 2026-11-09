/* A saved suite revision becomes one explicitly admitted, preview-pinned run. */
(function () {
  var form = document.getElementById('suite-execution') || document.getElementById('selection-execution');
  if (!form) return;
  var source = form.dataset.source || 'suite';
  var check = document.getElementById('preview-' + source);
  var enqueue = document.getElementById('enqueue-' + source);
  var status = document.getElementById(source + '-status');
  var blockers = document.getElementById(source + '-blockers');
  var items = document.getElementById(source + '-items');
  var rows = source === 'selection' ? Array.from(form.querySelectorAll('[data-execution-item]')) : [];
  var base = '/api/v1/projects/' + form.dataset.project;
  var count = Number(form.dataset.count);
  var validCount = Number.isInteger(count) && count >= 1 && count <= 100 && form.dataset.blocked !== 'true';
  var prepared = null, frozen = null, preparing = false, sending = false, generation = 0;
  var locked = [];

  function value(name) { return form.elements.namedItem(name).value.trim(); }
  function read() {
    var selection = {suite_version_id: form.dataset.version};
    if (source === 'selection') selection = {items: rows.map(function (row) {
      function field(name) { return row.querySelector('[name="' + name + '"]').value; }
      return {entry_id: row.dataset.entryId, case_version_id: row.dataset.version,
        approval_id: row.dataset.approval, environment_revision_id: field('environment_revision_id'),
        resource_id: field('resource_id'), dataset_version_id: field('dataset_version_id') || null,
        install_policy: 'none'};
    })};
    return {
      name: value('name'), purpose: 'regression', source: source,
      failure_policy: value('failure_policy'), release_label: value('release_label'),
      self_healing_enabled: false, exclusions: [],
      selection: selection
    };
  }
  var handle = window.aiqaForms.register(form, {
    read: read, saveBeforeLeave: false,
    persist: async function () { throw Error('explicit admission required'); }
  });
  var gate = window.aiqaCommand(function (body, key) {
    return window.aiqaRequest(base + '/executions', {
      method: 'POST', headers: {'Idempotency-Key': key}, body: JSON.stringify(body)
    });
  });
  function invalidate() {
    if (gate.pending()) return;
    generation += 1;
    prepared = null;
    enqueue.disabled = true;
    blockers.replaceChildren();
    items.replaceChildren();
    status.textContent = '설정이 바뀌었습니다. 준비 상태를 다시 확인하세요.';
  }
  form.addEventListener('input', invalidate);
  form.addEventListener('change', invalidate);
  form.addEventListener('submit', function (event) { event.preventDefault(); });

  check.addEventListener('click', async function () {
    if (preparing || sending || gate.pending()) return;
    if (!validCount) { status.textContent = '저장된 구성이 1~100개인 묶음을 선택하세요.'; return; }
    if (!form.reportValidity()) return;
    var payload = read(), serialized = JSON.stringify(payload), stamp = generation;
    if (!payload.name) { status.textContent = '실행 이름을 입력하세요.'; return; }
    preparing = true; check.disabled = true; prepared = null; enqueue.disabled = true;
    blockers.replaceChildren(); items.replaceChildren();
    status.textContent = '기기 연결과 저장된 승인본을 확인하고 있습니다.';
    try {
      var response = await window.aiqaRequest(base + '/execution-previews', {
        method: 'POST', headers: {'Idempotency-Key': crypto.randomUUID()}, body: serialized
      });
      var body = await response.json();
      if (stamp !== generation || serialized !== JSON.stringify(read())) {
        status.textContent = '검사 중 설정이 바뀌었습니다. 다시 확인하세요.';
        return;
      }
      if (!response.ok) { status.textContent = '준비 상태를 확인하지 못했습니다. 저장된 구성과 접근 권한을 확인하세요.'; return; }
      var labels = {
        RESOURCE_UNAVAILABLE: '기기 연결·환경·데이터를 확인하세요. 실행 PC가 꺼져 있으면 실행할 수 없습니다.',
        PACKAGE_MISSING: '승인된 재생 패키지가 필요합니다.',
        MODEL_BINDING_UNAVAILABLE: '검증에 사용할 AI 모델과 키 연결을 확인하세요.',
        BUDGET_UNAVAILABLE: '시간·행동·비용 한도를 확인하세요.'
      };
      (body.blockers || []).forEach(function (reason) {
        var li = document.createElement('li');
        li.textContent = labels[reason.code] || reason.message || reason.code;
        blockers.appendChild(li);
      });
      var resolved = body.resolved_items || [];
      resolved.forEach(function (item) {
        var li = document.createElement('li');
        li.textContent = item.entry_id + ' · 승인본 ' + item.case_version_id + ' · 기기 ' + item.resource_id;
        items.appendChild(li);
      });
      if (!body.ready || resolved.length !== count || !body.preview_hash ||
          (body.exclusions || []).length || body.silent_exclusions) {
        status.textContent = '전체 구성이 준비되지 않았습니다. 위 항목을 보완한 뒤 다시 확인하세요.';
        return;
      }
      prepared = {payload: payload, preview: body};
      enqueue.disabled = false;
      status.textContent = '전체 ' + resolved.length + '개가 준비되었습니다. 실행 버튼을 누르면 접수합니다.';
    } catch (_) {
      status.textContent = '검사 응답을 받지 못했습니다. 입력을 유지했으니 다시 확인하세요.';
    } finally {
      preparing = false; check.disabled = !validCount;
    }
  });

  enqueue.addEventListener('click', async function () {
    if (sending || (!gate.pending() && !prepared)) return;
    sending = true; enqueue.disabled = true; check.disabled = true;
    if (!gate.pending()) {
      frozen = Object.assign({}, prepared.payload, {
        preview_hash: prepared.preview.preview_hash,
        items: prepared.preview.resolved_items.map(function (item) {
          if (source !== 'selection') return item;
          var choice = prepared.payload.selection.items.find(function (candidate) { return candidate.entry_id === item.entry_id; });
          return Object.assign({}, choice, item);
        })
      });
      if (source === 'suite') frozen.suite_version_id = form.dataset.version;
      delete frozen.selection;
      locked = Array.from(form.querySelectorAll('input,select')).filter(function (node) { return !node.disabled; });
      locked.forEach(function (node) { node.disabled = true; });
    }
    try {
      var response = await gate.send(frozen), body = await response.json();
      prepared = null;
      if (response.ok) {
        handle.markSaved();
        status.textContent = '회귀 실행을 접수했습니다. ';
        var link = document.createElement('a');
        link.href = '/ui/projects/' + form.dataset.project + '/executions/' + body.execution_id;
        link.textContent = '진행 상황과 결과 확인';
        status.appendChild(link);
      } else {
        status.textContent = response.status === 409
          ? '접수 조건이 달라졌습니다. 준비 상태를 다시 확인하세요.'
          : '접수하지 못했습니다. 기기 연결·구성·권한을 확인한 뒤 다시 검사하세요.';
      }
      locked.forEach(function (node) { node.disabled = false; });
      check.disabled = !validCount;
      enqueue.textContent = '이 구성으로 회귀 실행 접수';
    } catch (_) {
      status.textContent = '접수 응답을 받지 못했습니다. 아래 버튼으로 같은 요청의 결과를 다시 확인하세요. 새 실행을 자동으로 만들지 않습니다.';
      enqueue.textContent = '같은 요청으로 접수 결과 확인';
      enqueue.disabled = false;
    } finally {
      sending = false;
    }
  });
})();
