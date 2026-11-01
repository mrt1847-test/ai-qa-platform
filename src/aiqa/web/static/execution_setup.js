/* Four-step execution wizard. A start stays one request and keeps the typed values. */
(function () {
  function purposesOf(draft) {
    var found = {};
    if (draft && draft.purpose) found[draft.purpose] = true;
    var extras = (draft && draft.purposes) || [];
    extras.forEach(function (item) { if (item) found[item] = true; });
    var items = (draft && draft.items) || [];
    items.forEach(function (item) { if (item && item.purpose) found[item.purpose] = true; });
    return found;
  }

  function review(draft) {
    var items = (draft && draft.items) || [];
    var count = typeof (draft && draft.proposed_n) === "number" ? draft.proposed_n : items.length;
    var found = purposesOf(draft || {});
    var mixed = !!found.trial && (!!found.regression || !!found.reverification);
    return {
      steps: 4,
      count: count,
      mixed: mixed,
      start: count >= 1 && count <= 100 && !mixed
    };
  }

  window.aiqaExecutionWizard = { review: review, steps: 4 };

  var form = document.getElementById("execution-wizard");
  if (!form) return;
  var step = 1;
  var pending = false;
  var sections = Array.prototype.slice.call(form.querySelectorAll("[data-step]"));

  function show() {
    sections.forEach(function (section) {
      section.hidden = String(section.getAttribute("data-step")) !== String(step);
    });
  }

  function draftFromForm() {
    return {
      name: form.name.value,
      purpose: form.purpose.value,
      source: form.source.value,
      reason: form.reason.value,
      release_label: form.release_label.value,
      items: []
    };
  }

  form.addEventListener("click", function (event) {
    var target = event.target;
    if (!target || !target.getAttribute) return;
    if (target.getAttribute("data-move") === "back" && step > 1) {
      step -= 1;
      show();
    }
  });

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    if (pending) return;
    var draft = draftFromForm();
    var decision = review(draft);
    var counts = document.getElementById("wizard-counts");
    if (counts) counts.textContent = "항목 " + decision.count + " · 제외 0";
    if (!decision.start) return;
    pending = true;
    var project = window.location.pathname.split("/")[3];
    var body = JSON.stringify({
      name: draft.name,
      purpose: draft.purpose,
      source: draft.source,
      failure_policy: "stop_on_non_pass",
      self_healing_enabled: false,
      release_label: draft.release_label,
      preview_hash: form.getAttribute("data-preview-hash") || "",
      exclusions: [],
      items: draft.items
    });
    window.aiqaRequest("/api/v1/projects/" + project + "/executions", {
      method: "POST",
      body: body
    }).then(function (response) {
      pending = false;
      if (response.status === 422 || response.status === 409) return;
    }, function () {
      pending = false;
    });
  });

  show();
})();
