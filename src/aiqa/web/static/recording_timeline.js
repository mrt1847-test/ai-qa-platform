(function () {
  var root = document.getElementById("recording-timeline-root");
  if (!root) {
    return;
  }
  var url = root.getAttribute("data-timeline-url") || "";
  var seconds = Number(root.getAttribute("data-poll-seconds") || "2");
  var lastCount = Number(root.getAttribute("data-action-count") || "0");
  var countNode = root.querySelector("[data-ack-count]");

  function selectedAction() {
    var params = new URLSearchParams(window.location.search);
    return params.get("action_id") || root.getAttribute("data-action-id") || "";
  }

  function reloadKeepingSelection(actions) {
    var params = new URLSearchParams(window.location.search);
    var current = selectedAction();
    var stillThere = actions.some(function (item) {
      return item.action_id === current;
    });
    if (stillThere) {
      params.set("action_id", current);
    } else if (actions.length) {
      params.set("action_id", actions[0].action_id);
    } else {
      params.delete("action_id");
    }
    var next = window.location.pathname + (params.toString() ? "?" + params.toString() : "");
    window.location.replace(next);
  }

  function paintNav(actions) {
    var nav = document.getElementById("recording-timeline");
    if (!nav) {
      return;
    }
    var current = selectedAction();
    if (!actions.length) {
      nav.innerHTML = '<p class="empty">서버에 ACK된 행동이 아직 없습니다.</p>';
      return;
    }
    nav.innerHTML = actions
      .map(function (entry) {
        var currentAttr = entry.action_id === current ? ' aria-current="step"' : "";
        var error = entry.error_text
          ? '<small data-error>오류 ' + entry.error_text + "</small>"
          : entry.check_status
            ? '<small data-check>검증 ' + entry.check_status + "</small>"
            : "";
        return (
          '<a class="review-step" href="?action_id=' +
          encodeURIComponent(entry.action_id) +
          '" data-timeline-action="' +
          entry.action_id +
          '" data-action-seq="' +
          entry.action_seq +
          '"' +
          currentAttr +
          ">순서 " +
          entry.action_seq +
          " · 단계 " +
          entry.step_id +
          '<small data-dispatch>' +
          entry.dispatch_state +
          "</small>" +
          '<small data-shot-state>이전 ' +
          entry.before +
          " · 이후 " +
          entry.after +
          " · 로그 " +
          entry.log +
          "</small>" +
          error +
          "</a>"
        );
      })
      .join("");
  }

  function poll() {
    if (document.hidden || !url) {
      return;
    }
    var request = window.aiqaRequest || function (path, options) {
      return window.fetch(path, options);
    };
    var action = selectedAction();
    var target = url + (url.indexOf("?") >= 0 ? "&" : "?") + "action_id=" + encodeURIComponent(action);
    request(target, { method: "GET", credentials: "same-origin" })
      .then(function (response) {
        if (!response.ok) {
          throw new Error("poll");
        }
        return response.json();
      })
      .then(function (body) {
        var actions = body.actions || [];
        if (countNode) {
          countNode.textContent = "서버 ACK " + actions.length;
        }
        if (actions.length !== lastCount) {
          lastCount = actions.length;
          reloadKeepingSelection(actions);
          return;
        }
        paintNav(actions);
      })
      .catch(function () {});
  }

  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) {
      poll();
    }
  });
  window.setInterval(poll, seconds === 2 ? 2000 : seconds * 1000);
})();
