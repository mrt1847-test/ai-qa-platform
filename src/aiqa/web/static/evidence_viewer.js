(function () {
  var root = document.getElementById("evidence-viewer");
  if (!root) {
    return;
  }
  var params = new URLSearchParams(window.location.search);
  var fields = ["owner_kind", "owner_id", "attempt_id", "action_id"];
  fields.forEach(function (name) {
    var value = params.get(name);
    if (value) {
      root.setAttribute("data-" + name.replace(/_/g, "-"), value);
    }
  });
  var actions = Array.prototype.slice.call(root.querySelectorAll("[data-action]"));

  function show(actionId) {
    actions.forEach(function (node) {
      node.hidden = node.getAttribute("data-action") !== actionId;
    });
    root.setAttribute("data-action-id", actionId);
    params.set("action_id", actionId);
    window.history.replaceState(null, "", window.location.pathname + "?" + params.toString());
  }

  root.addEventListener("keydown", function (event) {
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") {
      return;
    }
    var current = root.getAttribute("data-action-id");
    var index = -1;
    actions.forEach(function (node, position) {
      if (node.getAttribute("data-action") === current) {
        index = position;
      }
    });
    var next = event.key === "ArrowRight" ? index + 1 : index - 1;
    if (next < 0 || next >= actions.length) {
      return;
    }
    event.preventDefault();
    show(actions[next].getAttribute("data-action"));
  });

  root.querySelectorAll("[data-view-mode]").forEach(function (link) {
    link.addEventListener("click", function (event) {
      event.preventDefault();
      root.setAttribute("data-view", link.getAttribute("data-view-mode"));
    });
  });
  var steps = { previous: -1, next: 1 };
  root.querySelectorAll("[data-step]").forEach(function (link) {
    link.addEventListener("click", function (event) {
      var name = link.getAttribute("data-step");
      if (name === "first-failure") {
        event.preventDefault();
        var failure = root.getAttribute("data-first-failure");
        if (failure) {
          show(failure);
        }
        return;
      }
      if (!(name in steps)) {
        return;
      }
      event.preventDefault();
      var current = root.getAttribute("data-action-id");
      var index = -1;
      actions.forEach(function (node, position) {
        if (node.getAttribute("data-action") === current) {
          index = position;
        }
      });
      var next = index + steps[name];
      if (next < 0 || next >= actions.length) {
        return;
      }
      show(actions[next].getAttribute("data-action"));
    });
  });
})();
