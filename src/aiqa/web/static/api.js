/* Shared same-origin request boundary. Credentials stay in cookies/page memory. */
(function () {
  var csrf = null;
  var scope = null;
  var session = null;
  var queue = Promise.resolve();
  function key() { return window.crypto.randomUUID(); }
  function sessionFor(project) {
    if (csrf && (!project || scope === project)) return Promise.resolve(csrf);
    if (session) return session.then(function () { return sessionFor(project); });
    session = fetch('/api/v1/session/csrf', {credentials:'same-origin', headers:{'Origin':window.location.origin}})
      .then(function (response) { return response.ok ? response.json() : {}; })
      .then(function (body) {
        if (body.csrf_token && (!project || body.project_id === project)) return body;
        if (!project) return {};
        return fetch('/api/v1/session/nonces', {method:'POST', credentials:'same-origin', headers:{'content-type':'application/json','Origin':window.location.origin,'Idempotency-Key':key()}, body:JSON.stringify({origin:window.location.origin,project_id:project})})
          .then(function (response) { if (!response.ok) throw new Error('Session unavailable'); return response.json(); })
          .then(function (nonce) { return fetch('/api/v1/session/bootstrap', {method:'POST',credentials:'same-origin',headers:{'content-type':'application/json','Origin':window.location.origin,'Idempotency-Key':key()},body:JSON.stringify({nonce:nonce.nonce})}); })
          .then(function (response) { if (!response.ok) throw new Error('Session unavailable'); return response.json(); })
          .then(function (created) { created.project_id=project; return created; });
      }).then(function (body) { csrf=body.csrf_token || null; scope=body.project_id || null; session=null; return csrf; }, function (error) {session=null; throw error;});
    return session;
  }
  window.aiqaRequest = function (url, options) {
    options=options || {};
    var mutation = /^(POST|PUT|PATCH|DELETE)$/i.test(options.method || 'GET');
    var project = /\/projects\/([0-9a-f-]{36})(?:\/|$)/i.exec(url);
    var requestKey = (options.headers || {})['Idempotency-Key'] || key();
    // Serialize token acquisition and dispatch in this page; other tabs can rotate
    // a token, so a rejected request may refresh once with the same durable key.
    function send(retry) {
      return sessionFor(project && project[1]).then(function (token) {
        var headers=Object.assign({}, options.headers, {'Origin':window.location.origin});
        if (token) headers['X-CSRF-Token']=token;
        if (mutation) {headers['Idempotency-Key']=requestKey;headers['content-type']='application/json';}
        return fetch(url,Object.assign({},options,{credentials:'same-origin',headers:headers}));
      }).then(function (response) {
        if (response.status===403 && !retry) {csrf=null;return send(true);}
        return response;
      });
    }
    var result=queue.then(function () { return send(false); });
    queue=result.catch(function () {});
    return result;
  };
  window.aiqaOpenProject=function (project,url) {return sessionFor(project).then(function () {window.location.assign(url);});};
  document.addEventListener('click',function (event) {
    var link=event.target.closest && event.target.closest('a[href]');
    if (!link || event.ctrlKey || event.metaKey || event.shiftKey || event.defaultPrevented) return;
    var url=new URL(link.href,window.location.href);
    var project=/^\/ui\/projects\/([0-9a-f-]{36})(?:\/|$)/i.exec(url.pathname);
    if (!project || url.origin!==window.location.origin) return;
    event.preventDefault();
    sessionFor(project[1]).then(function () {window.location.assign(link.href);});
  });
})();
