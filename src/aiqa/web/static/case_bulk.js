(function () {
  var clone = document.getElementById("bulk-clone");
  var archive = document.getElementById("bulk-archive");
  if (!clone || !archive) {
    return;
  }
  function send(form, action) {
    var gate=window.aiqaCommand(function(body,key){return aiqaRequest(form.getAttribute('action'),{method:'POST',headers:{'content-type':'application/json','Idempotency-Key':key},body:JSON.stringify(body)});});
    var busy=false, pendingItems=null;
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      if(busy)return;
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
      if(items.length>100){list.textContent='한 번에 100개까지 처리할 수 있습니다.';return;}
      if(gate.pending())items=pendingItems;
      if(!window.confirm((action==='archive'?'보관':'복제')+'할 '+items.length+'개 케이스를 확인하세요.\n'+items.map(function(item){var box=Array.from(boxes).find(function(b){return b.value===item.case_id;});return box?box.getAttribute('aria-label'):item.case_id;}).join('\n')))return;
      busy=true;pendingItems=items;form.setAttribute('aria-busy','true');
      gate.send({items: items}).then(function (response) {
        if(!response.ok)throw Error('rejected');
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
      }).catch(function(){list.textContent=gate.pending()?'응답을 확인하지 못했습니다. 같은 버튼을 누르면 이전 요청을 확인합니다.':'처리하지 못했습니다. 입력과 권한을 확인하세요.';})
      .finally(function(){busy=false;form.removeAttribute('aria-busy');});
    });
  }
  send(clone, "clone");
  send(archive, "archive");
})();
