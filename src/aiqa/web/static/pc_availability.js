(function () {
  function watch(project, update) {
    let pending;
    function refresh() {
      if (pending) return pending;
      pending = (async function () {
        let resources = new Map();
        try {
          const response = await fetch('/api/v1/projects/' + encodeURIComponent(project) + '/resources', {
            credentials: 'same-origin', cache: 'no-store', signal: AbortSignal.timeout(5000)
          });
          if (!response.ok) throw Error('resource list unavailable');
          const body = await response.json();
          resources = new Map(body.resources.map(item => [item.resource_id, item]));
        } catch (_) {
          // Missing responses are treated as unverified until the next server check.
        }
        update(resources);
      }()).finally(() => { pending = null; });
      return pending;
    }
    refresh();
    window.setInterval(refresh, 10000);
    window.addEventListener('focus', refresh);
    return refresh;
  }

  function paint(root, item, selected) {
    if (!root) return;
    const status = root.querySelector('[data-pc-status]');
    const time = root.querySelector('[data-pc-last-seen]');
    const reason = root.querySelector('[data-pc-reason]');
    const stamp = item && item.last_seen;
    const label = item ? '실행 PC ' + item.connection_label + ' · ' + item.worker_id + ' · 기기 ' + item.state_label :
      selected ? '실행 PC 상태 확인 필요' : '기기를 선택하면 실행 PC 상태를 확인합니다.';
    const detail = item ? item.block_reason : selected ? '서버에서 기기 연결 상태를 확인해 주세요.' : '';
    // Avoid repeating live announcements on every poll.
    if (status.textContent !== label) status.textContent = label;
    if (reason.textContent !== detail) reason.textContent = detail;
    time.textContent = stamp ? new Date(stamp).toLocaleString('ko-KR') : selected ? '기록 없음' : '기기 선택 전';
    if (stamp) time.dateTime = stamp;
    else time.removeAttribute('datetime');
  }

  function selection(form, selectedId, changed, root = form.querySelector('[data-pc-availability]')) {
    let items = new Map();
    let allowed = false;
    let connected = false;
    let signature;
    let revision = 0;
    function update() {
      const id = selectedId();
      const item = items.get(id);
      const next = JSON.stringify([id, item && item.connection_state, item && item.state, item && item.can_execute]);
      allowed = !!(item && item.can_execute);
      connected = !!(item && item.connection_state === 'online');
      paint(root, item, !!id);
      if (signature !== next) {
        const initialized = signature !== undefined;
        signature = next;
        revision += 1;
        if (initialized) changed();
      }
    }
    form.addEventListener('change', update);
    update();
    const refresh = watch(form.dataset.project, rows => { items = rows; update(); });
    return { allowed: () => allowed, connected: () => connected, revision: () => revision, refresh };
  }

  window.aiqaPcAvailability = { selection, watch };
  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-pc-inventory]').forEach(grid => {
      watch(grid.dataset.pcInventory, resources => {
        grid.querySelectorAll('[data-pc-resource]').forEach(card => {
          const item = resources.get(card.dataset.pcResource);
          paint(card.querySelector('[data-pc-availability]'), item, true);
          card.dataset.state = item ? item.state : 'unavailable';
          card.querySelector('[data-pc-device-state]').textContent = item ? item.state_label : '확인 필요';
          card.querySelector('[data-pc-diagnostics]').textContent = item && item.can_diagnose ? '' :
            '기기 진단에는 실행 PC 연결이 필요합니다.';
        });
      });
    });
  });
})();
