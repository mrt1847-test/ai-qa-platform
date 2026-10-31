(function () {
  var form = document.getElementById("step-edit");
  if (!form) {
    return;
  }
  form.addEventListener("submit", function (event) {
    event.preventDefault();
    var submitter = event.submitter;
    if (!submitter) {
      return;
    }
    var body = {
      action: submitter.getAttribute("data-action"),
      step_id: submitter.getAttribute("data-step") || "",
      instruction: form.instruction.value,
      expected: form.expected.value,
      direction: submitter.getAttribute("data-direction") || "down",
      variable: form.variable.value,
      expected_head: document.getElementById("step-head").value || null
    };
    aiqaRequest(form.getAttribute("action"), {
      method: "POST",
      headers: {"content-type": "application/json", "Idempotency-Key": window.crypto.randomUUID()},
      body: JSON.stringify(body)
    }).then(function (response) {
      if (response.status === 201 || response.status === 200) {
        window.location.reload();
      }
    });
  });
})();
