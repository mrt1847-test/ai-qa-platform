(function () {
  function bindPanel(panel, statusId) {
    if (!panel || !window.aiqaRequest) return;
    panel.querySelectorAll("button[data-decision]").forEach(function (button) {
      button.addEventListener("click", function () {
        var proposal = button.closest("[data-proposal]").getAttribute("data-proposal");
        var accepted = button.getAttribute("data-decision") === "accept";
        var body = { proposal_id: proposal };
        if (accepted) body.expected_head = panel.getAttribute("data-head");
        var url =
          "/api/v1/projects/" +
          panel.getAttribute("data-project") +
          "/cases/" +
          panel.getAttribute("data-case") +
          (accepted ? "/proposal-acceptances" : "/proposal-rejections");
        button.disabled = true;
        window
          .aiqaRequest(url, { method: "POST", body: JSON.stringify(body) })
          .then(function (response) {
            if (response.ok) {
              window.location.reload();
              return;
            }
            return response.json().then(function (payload) {
              throw new Error(payload.error.message);
            });
          })
          .catch(function (error) {
            var status = document.getElementById(statusId);
            if (status) status.textContent = error.message;
            button.disabled = false;
          });
      });
    });
  }

  bindPanel(document.getElementById("tc-import"), "proposal-status");
  bindPanel(document.getElementById("structure-proposals"), "structure-proposal-status");

  var requestPanel = document.getElementById("structure-request");
  var requestButton = document.getElementById("request-structure");
  if (requestPanel && requestButton && window.aiqaRequest) {
    requestButton.addEventListener("click", function () {
      var head = requestPanel.getAttribute("data-head");
      if (!head) return;
      requestButton.disabled = true;
      var url =
        "/api/v1/projects/" +
        requestPanel.getAttribute("data-project") +
        "/cases/" +
        requestPanel.getAttribute("data-case") +
        "/versions/" +
        head +
        "/structure";
      window
        .aiqaRequest(url, { method: "POST", body: "{}" })
        .then(function (response) {
          if (response.ok) {
            window.location.reload();
            return;
          }
          return response.json().then(function (payload) {
            throw new Error(payload.error.message);
          });
        })
        .catch(function (error) {
          var status = document.getElementById("structure-status");
          if (status) status.textContent = error.message;
          requestButton.disabled = false;
        });
    });
  }
})();
