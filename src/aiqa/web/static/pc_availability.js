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

  function setExecuteEnabled(card, allowed) {
    card.querySelectorAll('[data-pc-execute]').forEach(link => {
      if (allowed) {
        link.removeAttribute('aria-disabled');
        link.removeAttribute('tabindex');
        link.classList.remove('is-disabled');
      } else {
        link.setAttribute('aria-disabled', 'true');
        link.setAttribute('tabindex', '-1');
        link.classList.add('is-disabled');
      }
    });
  }

  function markWorkerRevoked(workerId) {
    document.querySelectorAll('[data-pc-worker="' + workerId + '"]').forEach(card => {
      card.dataset.state = 'unavailable';
      const state = card.querySelector('[data-pc-device-state]');
      if (state) state.textContent = '폐기됨';
      const reason = card.querySelector('[data-pc-reason]');
      if (reason) reason.textContent = '실행 PC가 폐기되었습니다. 새 등록 후 다시 연결하세요.';
      setExecuteEnabled(card, false);
    });
  }

  function bindRegistration(root) {
    if (!root || !window.aiqaRequest) return;
    const form = root.querySelector('#pc-registration-form');
    if (!form) return;
    const project = root.dataset.project;
    const status = form.querySelector('[data-pc-reg-status]');
    const codeBox = form.querySelector('[data-pc-code-box]');
    const codeInput = form.elements.namedItem('issued_code');
    const expiry = form.querySelector('[data-pc-code-expiry]');
    const copyBtn = form.querySelector('[data-pc-action="copy"]');
    const cancelBtn = form.querySelector('[data-pc-action="cancel"]');
    const saved = { worker_id: form.elements.namedItem('worker_id').value, purpose: form.elements.namedItem('purpose').value };

    function preserve() {
      form.elements.namedItem('worker_id').value = saved.worker_id;
      form.elements.namedItem('purpose').value = saved.purpose;
    }

    function remember() {
      saved.worker_id = form.elements.namedItem('worker_id').value;
      saved.purpose = form.elements.namedItem('purpose').value;
    }

    form.addEventListener('input', remember);
    form.addEventListener('change', remember);

    async function post(path, body, key) {
      remember();
      try {
        const response = await window.aiqaRequest(path, {
          method: 'POST',
          headers: { 'Idempotency-Key': key },
          body: JSON.stringify(body)
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
          preserve();
          const message = (payload.error && payload.error.message) || '요청이 거절되었습니다.';
          status.textContent = message;
          return null;
        }
        return payload;
      } catch (_) {
        preserve();
        status.textContent = '실행 PC 또는 서버에 연결할 수 없습니다. 입력은 그대로 둡니다.';
        return null;
      }
    }

    form.querySelector('[data-pc-action="issue"]').addEventListener('click', async () => {
      const workerId = form.elements.namedItem('worker_id').value.trim();
      const purpose = form.elements.namedItem('purpose').value;
      const body = await post(
        '/api/v1/projects/' + encodeURIComponent(project) + '/worker-enrollment-codes',
        { worker_id: workerId, purpose: purpose, expires_in_seconds: 900 },
        'pc-issue-' + Date.now()
      );
      if (!body) return;
      codeBox.hidden = false;
      codeInput.value = body.code || '';
      expiry.textContent = body.expires_at ? (' · 만료 ' + body.expires_at) : '';
      copyBtn.disabled = !body.code;
      cancelBtn.disabled = !body.code;
      status.textContent = '등록 코드를 발급했습니다. 등록된 실행 PC에서만 교환하세요.';
    });

    copyBtn.addEventListener('click', async () => {
      if (!codeInput.value) return;
      try {
        await navigator.clipboard.writeText(codeInput.value);
        status.textContent = '등록 코드를 복사했습니다.';
      } catch (_) {
        codeInput.select();
        status.textContent = '복사에 실패했습니다. 코드를 직접 선택해 복사하세요.';
        preserve();
      }
    });

    cancelBtn.addEventListener('click', async () => {
      const workerId = form.elements.namedItem('worker_id').value.trim();
      const body = await post(
        '/api/v1/projects/' + encodeURIComponent(project) + '/worker-enrollment-codes/cancel',
        { worker_id: workerId },
        'pc-cancel-' + Date.now()
      );
      if (!body) return;
      codeInput.value = '';
      expiry.textContent = '';
      codeBox.hidden = true;
      copyBtn.disabled = true;
      cancelBtn.disabled = true;
      status.textContent = '미교환 등록 코드를 취소했습니다.';
    });

    form.querySelector('[data-pc-action="revoke"]').addEventListener('click', async () => {
      const workerId = form.elements.namedItem('worker_id').value.trim();
      if (!workerId) {
        status.textContent = '폐기할 worker ID를 입력하세요.';
        return;
      }
      if (!window.confirm('worker ' + workerId + '를 폐기할까요? 직후 실행이 차단됩니다.')) {
        preserve();
        return;
      }
      const body = await post(
        '/api/v1/workers/' + encodeURIComponent(workerId) + '/revoke',
        { project_id: project },
        'pc-revoke-' + Date.now()
      );
      if (!body) return;
      markWorkerRevoked(workerId);
      codeInput.value = '';
      expiry.textContent = '';
      codeBox.hidden = true;
      copyBtn.disabled = true;
      cancelBtn.disabled = true;
      status.textContent = 'worker를 폐기했습니다. 실행 버튼이 비활성입니다.';
    });
  }

  window.aiqaPcAvailability = { selection, watch, markWorkerRevoked };
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
          setExecuteEnabled(card, !!(item && item.can_execute));
        });
      });
    });
    document.querySelectorAll('[data-pc-registration]').forEach(bindRegistration);
  });
})();
