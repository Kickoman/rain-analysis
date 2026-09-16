/* Rain Analysis — the three Plotly charts on metrics/index.html.
 *
 * The generator emits the data as JSON in a <script type="application/json">
 * block and nothing else: no layout, no palette, no inline script. That split
 * is the point. Plotly draws onto a transparent canvas but paints its own axis
 * labels, tick text, legend and reference line, and those were hard-coded to
 * dark grey — legible on the light page, nearly invisible on the dark one.
 *
 * So the chrome colours are read from the stylesheet at draw time via
 * getComputedStyle, and a MutationObserver on <html data-theme> redraws them
 * when the reader flips the switch. The series colours are NOT read from CSS:
 * they identify four specific candidates and have to stay recognisable across
 * both themes and across the day-by-day charts.
 */
(function () {
  "use strict";

  var ROOT = document.documentElement;
  var charts = [];

  function token(name, fallback) {
    var value = getComputedStyle(ROOT).getPropertyValue(name).trim();
    return value || fallback;
  }

  /* Plotly needs concrete colours, not var() references. */
  function palette() {
    return {
      text: token("--text-body", "#696969"),
      muted: token("--text-muted", "#808080"),
      grid: token("--border-soft", "#a9a9a9"),
      rule: token("--border-rule", "#808080"),
      font: token("--font-mono", "Courier New, monospace")
    };
  }

  function layout(spec, colours) {
    var axis = {
      color: colours.text,
      gridcolor: colours.grid,
      linecolor: colours.rule,
      zerolinecolor: colours.grid,
      tickfont: { color: colours.muted, size: 12 }
    };
    return {
      margin: { t: 10, r: 10, b: 40, l: 50 },
      height: 340,
      font: { family: colours.font, color: colours.text, size: 12 },
      xaxis: Object.assign({ title: "", type: "date" }, axis),
      yaxis: Object.assign({ title: { text: spec.yTitle, font: { color: colours.text } } }, axis),
      legend: { orientation: "h", y: -0.2, font: { color: colours.text } },
      shapes: spec.refLine === null ? [] : [{
        type: "line", xref: "paper", x0: 0, x1: 1,
        y0: spec.refLine, y1: spec.refLine,
        line: { dash: "dash", width: 1, color: colours.rule }
      }],
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)"
    };
  }

  function draw() {
    var node = document.getElementById("chart-data");
    if (!node || typeof Plotly === "undefined") return;

    var spec;
    try { spec = JSON.parse(node.textContent); } catch (e) { return; }
    if (!spec || !spec.charts) return;

    var colours = palette();
    var config = { responsive: true, displayModeBar: false };

    spec.charts.forEach(function (chart) {
      if (!document.getElementById(chart.target)) return;
      Plotly.newPlot(chart.target, chart.traces, layout(chart, colours), config);
      charts.push(chart);
    });
  }

  /* Relayout rather than redraw: the traces have not changed, only the chrome,
   * and relayout keeps whatever the reader has zoomed or hidden in the legend. */
  function retheme() {
    if (typeof Plotly === "undefined") return;
    var colours = palette();
    charts.forEach(function (chart) {
      var node = document.getElementById(chart.target);
      if (node) Plotly.relayout(node, layout(chart, colours));
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    draw();
    new MutationObserver(retheme).observe(ROOT, {
      attributes: true,
      attributeFilter: ["data-theme"]
    });
  });
})();
