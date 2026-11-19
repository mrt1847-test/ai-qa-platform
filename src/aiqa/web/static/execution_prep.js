/* Shared 1대상 → 2환경·데이터 → 3사전 점검 → 4최종 확인 for trial, selection, suite, and rerun. */
(function () {
  var root = document.querySelector('[data-prep]');
  if (!root) return;
  var step = 1;
  var panels = Array.prototype.slice.call(root.querySelectorAll('[data-prep-panel]'));

  function show(next) {
    if (next < 1 || next > 4) return;
    if (next === 4 && root.getAttribute('data-prep-ready') !== 'true') return;
    step = next;
    panels.forEach(function (panel) {
      panel.hidden = panel.getAttribute('data-prep-panel') !== String(step);
    });
    root.querySelectorAll('[data-prep-step]').forEach(function (button) {
      var current = button.getAttribute('data-prep-step') === String(step);
      if (current) button.setAttribute('aria-current', 'step');
      else button.removeAttribute('aria-current');
      button.disabled = button.getAttribute('data-prep-step') === '4' && root.getAttribute('data-prep-ready') !== 'true';
    });
  }

  function line(list, label, value) {
    var row = document.createElement('div');
    var term = document.createElement('dt');
    var detail = document.createElement('dd');
    term.textContent = label;
    detail.textContent = value === undefined || value === null || value === '' ? '저장된 값 없음' : String(value);
    row.appendChild(term);
    row.appendChild(detail);
    list.appendChild(row);
  }

  function fill(node, body) {
    if (!node) return;
    var confirmation = (body && body.confirmation) || {};
    var items = confirmation.items || [];
    node.replaceChildren();
    var note = document.createElement('p');
    note.textContent = '아래 호출·시간·예산은 예상 상한입니다. 실제 비용이 아닙니다.';
    node.appendChild(note);
    var list = document.createElement('dl');
    line(list, '배포', confirmation.release_label || '없음');
    line(list, '실패 정책', confirmation.failure_policy || '저장된 정책');
    line(list, '행동 AI 예상 호출 상한', confirmation.actor_call_cap);
    items.forEach(function (item) {
      line(list, item.entry_id + ' 버전', item.case_version_id);
      line(list, item.entry_id + ' 승인', item.approval_id || '시범 · 승인 전');
      line(list, item.entry_id + ' 환경', item.environment_revision_id);
      line(list, item.entry_id + ' 기기', item.resource_id);
      line(list, item.entry_id + ' 데이터', item.dataset_version_id || '없음');
      line(list, item.entry_id + ' 초기화', item.reset_policy || '저장된 원본');
      line(list, item.entry_id + ' 검증', item.verifier_method || '저장된 검증');
      var limits = item.execution_limits || {};
      line(list, item.entry_id + ' 행동 상한', limits.max_actions);
      line(list, item.entry_id + ' 검증 호출 상한', limits.max_model_calls);
      line(list, item.entry_id + ' 시간 상한', limits.timeout_seconds);
      line(list, item.entry_id + ' 예산 상한', limits.budget ? limits.budget + ' ' + (limits.currency || '') : '');
      var healing = item.healing_limits || {};
      function shown(value) { return value === undefined || value === null || value === '' ? '확인 필요' : String(value); }
      line(list, item.entry_id + ' 복구', item.healing_enabled === true
        ? '켜짐 · episode ' + shown(healing.max_episodes_per_item) + ' · 호출 ' + shown(healing.max_model_calls_per_item) + ' · ' + shown(healing.max_seconds) + '초 · 예산 ' + shown(healing.budget)
        : '꺼짐');
    });
    node.appendChild(list);
  }

  window.aiqaPrep = {
    allowFinal: function () {
      root.setAttribute('data-prep-ready', 'true');
      show(step);
    },
    showFinal: function (body) {
      root.setAttribute('data-prep-ready', 'true');
      fill(root.querySelector('[data-prep-confirmation]'), body);
      show(4);
    },
    reset: function () {
      root.removeAttribute('data-prep-ready');
      var node = root.querySelector('[data-prep-confirmation]');
      if (node) node.replaceChildren();
      if (step === 4) step = 3;
      show(step);
    },
    fill: fill
  };

  root.addEventListener('click', function (event) {
    var target = event.target;
    if (!target || !target.getAttribute) return;
    if (target.hasAttribute('data-prep-back')) show(step - 1);
    if (target.hasAttribute('data-prep-edit')) show(1);
    if (target.hasAttribute('data-prep-next')) show(step < 3 ? step + 1 : 4);
    var chosen = target.getAttribute('data-prep-step');
    if (chosen) show(Number(chosen));
  });
  root.addEventListener('keydown', function (event) {
    if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return;
    if (!event.target || !event.target.closest || !event.target.closest('.prep-steps')) return;
    event.preventDefault();
    show(step + (event.key === 'ArrowRight' ? 1 : -1));
  });
  show(1);
})();
