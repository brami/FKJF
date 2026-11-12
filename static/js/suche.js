// Filter für die Adresstabelle der Mail-Übersicht
(function () {
  var feld = document.getElementById("suche");
  var tabelle = document.getElementById("adresstabelle");
  if (!feld || !tabelle) return;
  feld.addEventListener("input", function () {
    var q = feld.value.trim().toLowerCase();
    tabelle.querySelectorAll("tbody tr").forEach(function (tr) {
      tr.hidden = q && tr.textContent.toLowerCase().indexOf(q) < 0;
    });
  });
})();
