/* Rain Analysis — two things the stylesheet cannot do on its own.
 *
 * 1. LIGHT|DARK switch in the nav, remembered in localStorage.
 * 2. Right-aligns numeric table cells (adds class="num"), so the generators
 *    need no change. If you'd rather emit the class from Python, delete
 *    markNumericCells() and this file keeps working.
 *
 * Load it in <head> with the defer attribute; the theme is applied from an
 * inline snippet before paint (see scripts_utils/page_shell.py) to avoid a
 * flash of the light page for a dark reader.
 *
 * Nothing here knows about the charts: metrics/index.html watches the
 * data-theme attribute itself, so this file stays the design system's.
 */
(function () {
  "use strict";

  var KEY = "ra-theme";

  function stored() {
    try { return localStorage.getItem(KEY); } catch (e) { return null; }
  }

  function apply(theme) {
    if (theme === "dark") document.documentElement.setAttribute("data-theme", "dark");
    else document.documentElement.removeAttribute("data-theme");
  }

  function buildSwitch() {
    var nav = document.querySelector("nav");
    if (!nav || nav.querySelector(".theme-switch")) return;

    var current = stored() === "dark" ? "dark" : "light";
    var wrap = document.createElement("div");
    wrap.className = "theme-switch";

    var buttons = ["light", "dark"].map(function (theme) {
      var b = document.createElement("button");
      b.type = "button";
      b.textContent = theme.toUpperCase();
      b.setAttribute("aria-pressed", String(theme === current));
      b.addEventListener("click", function () {
        current = theme;
        try { localStorage.setItem(KEY, theme); } catch (e) {}
        apply(theme);
        buttons.forEach(function (other) {
          other.setAttribute("aria-pressed", String(other === b));
        });
      });
      return b;
    });

    var label = document.createElement("span");
    label.className = "theme-switch-label";
    label.textContent = "theme";

    wrap.appendChild(label);
    buttons.forEach(function (b) { wrap.appendChild(b); });
    nav.appendChild(wrap);
  }

  /* A cell is numeric if it is a number, a percentage, a ratio (10/15),
   * a signed value (+0.37) or the n/a placeholder. */
  var NUMERIC = /^(n\/a|—|-|\+?-?\d+(\.\d+)?%?|\d+\/\d+|[+-]\d+(\.\d+)?)$/i;

  function markNumericCells() {
    var tables = document.querySelectorAll("main table");
    Array.prototype.forEach.call(tables, function (table) {
      var rows = table.tBodies.length ? table.tBodies[0].rows : table.rows;
      if (!rows.length) return;

      var width = 0;
      Array.prototype.forEach.call(rows, function (r) { width = Math.max(width, r.cells.length); });

      for (var col = 0; col < width; col++) {
        var seen = 0, numeric = 0;
        Array.prototype.forEach.call(rows, function (r) {
          var cell = r.cells[col];
          if (!cell) return;
          seen++;
          if (NUMERIC.test(cell.textContent.trim())) numeric++;
        });
        if (!seen || numeric / seen < 0.7) continue;

        Array.prototype.forEach.call(rows, function (r) {
          if (r.cells[col]) r.cells[col].classList.add("num");
        });
        var head = table.tHead && table.tHead.rows[0];
        if (head && head.cells[col]) head.cells[col].classList.add("num");
      }
    });
  }

  apply(stored());
  document.addEventListener("DOMContentLoaded", function () {
    buildSwitch();
    markNumericCells();
  });
})();
