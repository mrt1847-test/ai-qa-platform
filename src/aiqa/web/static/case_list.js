(function () {
  var params = new URLSearchParams(window.location.search);
  ["filter", "sort", "page", "selected"].forEach(function (name) {
    var node = document.querySelector("[data-query='" + name + "']");
    if (!node || !params.has(name === "filter" ? "q" : name === "page" ? "cursor" : name)) {
      return;
    }
    var key = name === "filter" ? "q" : name === "page" ? "cursor" : name;
    node.value = params.get(key);
  });
  var columns = document.querySelector("[data-columns]");
  var saved = window.sessionStorage.getItem("aiqa.columns");
  if (columns && saved) {
    columns.setAttribute("data-columns", saved);
  }
  window.addEventListener("scroll", function () {
    window.sessionStorage.setItem("aiqa.scroll", String(window.scrollY));
  });
})();
