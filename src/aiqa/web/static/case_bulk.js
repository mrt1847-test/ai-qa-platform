(function () {
  var clone = document.getElementById("bulk-clone");
  var archive = document.getElementById("bulk-archive");
  if (!clone || !archive) {
    return;
  }
  function send(form, action) {
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var boxes = document.querySelectorAll('input[name="selected"]:checked');
      var items = [];
      for (var index = 0; index < boxes.length; index += 1) {
        var box = boxes[index];
        var row = box.closest("tr");
        items.push({
          case_id: box.value,
          action: action,
          name: row ? row.getAttribute("data-name") + " 복사" : "",
          expected_revision: row ? Number(row.getAttribute("data-lock")) : 0
        });
      }
      var list = document.getElementById("bulk-result");
      if (items.length === 0) {
        list.textContent = "";
        var empty = document.createElement("li");
        empty.textContent = "선택한 항목이 없습니다.";
        list.appendChild(empty);
        return;
      }
      aiqaRequest(form.getAttribute("action"), {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "Idempotency-Key": window.crypto.randomUUID()
        },
        body: JSON.stringify({items: items})
      }).then(function (response) {
        return response.json();
      }).then(function (body) {
        list.textContent = "";
        var rows = body.items || [];
        for (var index = 0; index < rows.length; index += 1) {
          var item = rows[index];
          var line = document.createElement("li");
          var label = item.outcome;
          if (item.outcome === "cloned") {
            label = "복제됨";
          } else if (item.outcome === "archived") {
            label = "보관됨";
          } else if (item.outcome === "blocked") {
            label = "차단";
          }
          line.textContent = item.case_id + " " + label + (item.reason ? " " + item.reason : "");
          list.appendChild(line);
        }
      });
    });
  }
  send(clone, "clone");
  send(archive, "archive");
})();
