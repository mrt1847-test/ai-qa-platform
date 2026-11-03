(function () {
  const button = document.getElementById('start-rerun');
  if (!button) return;
  const reason = document.getElementById('rerun-reason');
  const scope = document.getElementById('rerun-scope');
  const connection = document.getElementById('rerun-connection');
  const feedback = document.getElementById('rerun-feedback');
  const targets = JSON.parse(document.getElementById('rerun-targets').textContent);
  let resources = new Map();
  let available = false;
  let connected = false;
  let sending = false;
  let payload;
  const url = '/api/v1/executions/' + encodeURIComponent(button.dataset.execution) +
    '/reruns?project_id=' + encodeURIComponent(button.dataset.project);
  const command = window.aiqaCommand((body, key) => window.aiqaRequest(url, {
    method: 'POST', headers: {'Idempotency-Key': key}, body: JSON.stringify(body)
  }));

  function update() {
    const selected = targets.filter(item => scope.value === 'all' ||
      (scope.value === 'failed' && item.failed) ||
      (scope.value === 'items' && item.case_run_id === button.dataset.selected));
    const unavailable = selected.find(item => !resources.get(item.resource_id)?.can_execute);
    available = selected.length > 0 && !unavailable;
    connected = selected.length > 0 && selected.every(item => resources.get(item.resource_id)?.connection_state === 'online');
    let text = '선택한 범위의 기기를 사용할 수 있습니다.';
    if (!selected.length) text = '선택한 범위에 다시 실행할 항목이 없습니다.';
    else if (unavailable) {
      const item = resources.get(unavailable.resource_id);
      text = item ? item.display_name + ' · ' + item.block_reason : '저장된 기기의 실행 PC 연결을 확인해 주세요.';
    }
    if (connection.textContent !== text) connection.textContent = text;
    button.disabled = sending || !(command.pending() ? connected : available);
    button.textContent = command.pending() && !sending ? '같은 요청으로 다시 접수' : '다시 실행';
  }

  scope.addEventListener('change', update);
  const refresh = window.aiqaPcAvailability.watch(button.dataset.project, rows => {
    resources = rows;
    update();
  });
  update();

  button.addEventListener('click', async function () {
    if (sending || !(command.pending() ? connected : available)) return;
    if (!command.pending()) {
      if (!reason.value.trim()) {
        feedback.textContent = '재실행 사유를 입력하세요.';
        reason.focus();
        return;
      }
      payload = {reason: reason.value, scope: scope.value};
      if (scope.value === 'items') payload.case_run_ids = [button.dataset.selected];
    }
    sending = true;
    reason.disabled = scope.disabled = true;
    update();
    try {
      const response = await command.send(payload);
      const body = await response.json();
      const labels = { APPROVAL_REVOKED: '기존 승인이 철회되었습니다.', APPROVAL_REQUIRED: '유효한 승인이 필요합니다.' };
      const blockers = (body.blockers || []).map(item => labels[item.code] || item.message);
      feedback.textContent = response.ok && body.ready ? '재실행을 접수했습니다.' :
        blockers.join(' · ') || '재실행을 접수하지 못했습니다. 기기 연결과 저장된 실행 조건을 확인하세요.';
      await refresh();
    } catch (_) {
      feedback.textContent = '응답을 받지 못했습니다. 연결된 상태에서 같은 요청으로 다시 접수할 수 있습니다.';
    } finally {
      sending = false;
      reason.disabled = scope.disabled = command.pending();
      update();
    }
  });
})();
