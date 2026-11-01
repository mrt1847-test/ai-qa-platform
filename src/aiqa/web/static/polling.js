(function () {
  var root = document.getElementById("live-connection");
  if (!root) {
    return;
  }
  var seconds = Number(root.getAttribute("data-poll-seconds") || "2");
  var projectUrl = root.getAttribute("data-project-events") || "";
  var attemptUrl = root.getAttribute("data-attempt-events") || "";
  var params = new URLSearchParams(window.location.search);
  function show(id, value) {
    var node = document.getElementById(id);
    if (node) {
      node.textContent = value || "";
    }
  }
  show("selected-rec", params.get("rec") || root.getAttribute("data-selected-rec"));
  show("selected-item", params.get("item") || root.getAttribute("data-selected-item"));
  show("selected-action", params.get("action") || root.getAttribute("data-selected-action"));
  var commitCursor = "0";
  var localCursor = "0";
  function address(url, name, cursor) {
    return url + (url.indexOf("?") >= 0 ? "&" : "?") + name + "=" + cursor;
  }
  function mark(ok, when) {
    var last = document.getElementById("last-received");
    var stale = document.getElementById("stale");
    if (last && ok) {
      last.textContent = when;
    }
    if (stale) {
      stale.hidden = ok;
    }
  }
  function read(url) {
    var request = window.aiqaRequest || function (path, options) {
      return window.fetch(path, options);
    };
    return request(url, {method: "GET", credentials: "same-origin"}).then(function (response) {
      if (!response.ok) {
        throw new Error("poll");
      }
      return response.json();
    });
  }
  function poll() {
    if (document.hidden || !projectUrl) {
      return;
    }
    read(address(projectUrl, "after_commit_seq", commitCursor)).then(function (body) {
      commitCursor = String(body.next_commit_seq);
      if (!attemptUrl) {
        return body;
      }
      return read(address(attemptUrl, "after_local_seq", localCursor));
    }).then(function (body) {
      if (body && body.next_local_seq !== undefined) {
        localCursor = String(body.next_local_seq);
      }
      mark(!body.stale, new Date().toISOString());
    }).catch(function () {
      mark(false, "");
    });
  }
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) {
      poll();
    }
  });
  window.setInterval(poll, seconds === 2 ? 2000 : seconds * 1000);
  poll();
})();
