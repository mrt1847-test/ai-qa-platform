(function () {
  var params = new URLSearchParams(window.location.search);
  ["filter", "sort", "page", "selected"].forEach(function (name) {
    var node = document.querySelector("[data-query='" + name + "']");
    if (!node || !params.has(name)) {
      return;
    }
    node.value = params.get(name);
  });
  var savedScroll = window.sessionStorage.getItem("aiqa.scroll");
  if (savedScroll) {
    window.scrollTo(0, Number(savedScroll));
  }
  window.addEventListener("scroll", function () {
    window.sessionStorage.setItem("aiqa.scroll", String(window.scrollY));
  });
  var columns = document.querySelector("[data-columns]");
  if (columns) {
    var savedColumns = window.sessionStorage.getItem("aiqa.columns");
    if (savedColumns) {
      columns.setAttribute("data-columns", savedColumns);
    }
  }
  if (document.body.getAttribute("data-dirty") === "true") {
    window.addEventListener("beforeunload", function (event) {
      event.preventDefault();
      event.returnValue = "";
    });
    var dialog = document.getElementById("unsaved-dialog");
    document.querySelectorAll("a[href]").forEach(function (link) {
      link.addEventListener("click", function (event) {
        if (!dialog) {
          return;
        }
        event.preventDefault();
        dialog.hidden = false;
      });
    });
  }
})();
