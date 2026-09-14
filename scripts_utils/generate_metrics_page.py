#!/usr/bin/env python3
"""Generate metrics/index.html — how onset prediction has held up over time.

The page this replaces plotted F1, precision and recall per model per day for
fifteen models: forty-five lines answering a question the product never asks,
which is whether a model can tell that it is raining while it rains. What it
needs to show instead is narrow:

  - can anything warn before rain *starts*, and is that still true today;
  - how much of it is real, against a chance line that is drawn on the chart;
  - what an alert would cost in hours a week.

Three series carry that: the best proven candidate, the deployed sensor, and
the control. Everything else is in the per-day reports and the JSON.

Also writes metrics/data.json for programmatic access.
"""

from pathlib import Path
import json
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent))
from report_parse import (  # noqa: E402
    extract_onset_date,
    extract_onset_scoreboard,
    extract_onset_window,
    extract_recommended,
    is_onset_report,
    strip_tags,
)
from page_head import head_tags  # noqa: E402

# Validated categorical palette, light/dark pairs.
SERIES_COLOURS = {
    "pressure_primary": "#2a78d6",
    "onset_gate": "#eb6834",
    "ha_live_actual": "#1baf7a",
    "persistence": "#8a8f98",
}
# Plotted by default; any other candidate stays in the table.
TRACKED = list(SERIES_COLOURS)

FRIENDLY = {
    "ha_live_actual": "ha_live_actual (deployed)",
    "persistence": "persistence (control)",
}


def collect(history_dir: Path) -> tuple[list[str], dict, list[dict], list[tuple[str, str]]]:
    files = sorted(f for f in history_dir.glob("*.html") if f.name != "index.html")
    dates: list[str] = []
    series: dict[str, dict[str, list]] = {}
    latest_rows: list[dict] = []
    skipped: list[tuple[str, str]] = []

    for path in files:
        html = path.read_text()
        if not is_onset_report(html):
            # Reports predating the onset format are left out of the timeline
            # rather than spliced into it: they scored a different target.
            skipped.append((path.name, "pre-onset report format"))
            continue
        date = extract_onset_date(html)
        rows = extract_onset_scoreboard(html)
        if not date or not rows:
            skipped.append((path.name, "no date" if not date else "scoreboard not found"))
            continue

        dates.append(date)
        window = extract_onset_window(html)
        by_model = {r["model"]: r for r in rows}
        for name in TRACKED:
            entry = series.setdefault(name, {"auc": [], "ci_lo": [], "ci_hi": [],
                                             "lift": [], "recall": [], "alert_hours": []})
            row = by_model.get(name)
            ci = (row or {}).get("roc_auc_ci") or [None, None]
            entry["auc"].append((row or {}).get("roc_auc"))
            entry["ci_lo"].append(ci[0])
            entry["ci_hi"].append(ci[1])
            entry["lift"].append((row or {}).get("lift"))
            entry["recall"].append((row or {}).get("event_recall"))
            entry["alert_hours"].append((row or {}).get("alert_hours_per_week"))

        latest_rows = [dict(r, date=date, **window) for r in rows]

    return dates, series, latest_rows, skipped


def trace(name: str, dates: list[str], values: list, colour: str) -> dict:
    return {
        "x": dates, "y": values, "name": FRIENDLY.get(name, name),
        "type": "scatter", "mode": "lines+markers",
        "line": {"color": colour, "width": 2},
        "marker": {"size": 5},
        "connectgaps": False,
    }


def main() -> int:
    history_dir = Path("history")
    if not history_dir.exists():
        print("❌ history/ not found — nothing to build metrics from", file=sys.stderr)
        return 1

    dates, series, latest_rows, skipped = collect(history_dir)
    if not dates:
        print("❌ No onset-format reports found in history/", file=sys.stderr)
        for name, why in skipped:
            print(f"   • {name}: {why}", file=sys.stderr)
        return 1

    if skipped:
        print(f"ℹ️  {len(dates)} onset reports plotted; {len(skipped)} older reports skipped")

    auc_traces = [trace(n, dates, series[n]["auc"], SERIES_COLOURS[n])
                  for n in TRACKED if any(v is not None for v in series.get(n, {}).get("auc", []))]
    lift_traces = [trace(n, dates, series[n]["lift"], SERIES_COLOURS[n])
                   for n in TRACKED if any(v is not None for v in series.get(n, {}).get("lift", []))]
    cost_traces = [trace(n, dates, series[n]["alert_hours"], SERIES_COLOURS[n])
                   for n in TRACKED if any(v is not None for v in series.get(n, {}).get("alert_hours", []))]

    latest = latest_rows[0].get("date") if latest_rows else dates[-1]
    proven = [r for r in latest_rows if r.get("verdict") == "works"]
    headline = (f"{proven[0]['model']} warns before {proven[0]['caught']} of "
                f"{proven[0]['onsets']} rain starts"
                if proven else "nothing currently beats chance")

    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dates": dates,
        "series": series,
        "latest": latest_rows,
        "skipped": [{"file": f, "reason": r} for f, r in skipped],
    }
    out_dir = Path("metrics")
    out_dir.mkdir(exist_ok=True)
    (out_dir / "data.json").write_text(json.dumps(data, indent=2))

    def fmt(value, digits=2, dash="—"):
        return dash if value is None else f"{value:.{digits}f}"

    def table_rows() -> str:
        marks = {"works": "✅", "ranks_only": "◐", "one_label_only": "⚠️", "chance": "—"}
        cells = []
        for r in sorted(latest_rows, key=lambda row: -(row.get("roc_auc") or 0)):
            ci = r.get("roc_auc_ci") or [None, None]
            ci_txt = f"{ci[0]:.2f}–{ci[1]:.2f}" if ci[0] is not None else "—"
            mark = marks.get(r.get("verdict"), "—")
            caught = f"{r['caught']}/{r['onsets']}"
            cells.append(
                f"<tr><td><code>{r['model']}</code></td>"
                f"<td>{caught}</td>"
                f"<td>{fmt(r.get('lift'))}</td>"
                f"<td>{fmt(r.get('alert_hours_per_week'), 0)}</td>"
                f"<td>{fmt(r.get('roc_auc'))} ({ci_txt})</td>"
                f"<td>{mark}</td></tr>"
            )
        return "\n".join(cells)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Rain Onset Metrics — Over Time</title>
    {head_tags("How well anything predicts the start of rain, tracked day by day.")}
    <link rel="stylesheet" href="../assets/style.css">
    <script src="https://cdn.plot.ly/plotly-2.35.2.min.js" charset="utf-8"></script>
</head>
<body>
    <header>
        <h1>🌧️ Onset prediction over time</h1>
        <p>{headline}</p>
    </header>

    <nav>
        <a href="../index.html">Home</a>
        <a href="../current/index.html">Latest Report</a>
        <a href="../history/index.html">History</a>
        <a href="index.html" class="active">Metrics</a>
        <a href="../docs/GLOSSARY.html">Glossary</a>
    </nav>

    <main>
        <section class="intro">
            <h2>What these charts answer</h2>
            <p>Every point is one report, scored on the whole record up to that day:
            standing in a dry hour, did anything warn that rain would start within
            three hours? Rain already falling is excluded, so a model that merely
            recognises wet weather earns nothing here.</p>
        </section>

        <section>
            <h2>Skill — front AUC</h2>
            <p>0.5 is a coin toss; the dashed line marks it. A series that hugs
            that line has no ability to anticipate rain, however well it scores
            on other targets.</p>
            <div id="auc-chart"></div>
        </section>

        <section>
            <h2>Is it aiming, or just yelling? — lift over random</h2>
            <p>How many rain starts the model caught, divided by how many the
            same number of alert-hours would catch scattered at random. At or
            below 1.0 the alerts carry no information.</p>
            <div id="lift-chart"></div>
        </section>

        <section>
            <h2>What it costs — alert-hours per week</h2>
            <p>Hours a week the alert would be raised at the threshold each model
            is scored at. This is the number a person actually pays.</p>
            <div id="cost-chart"></div>
        </section>

        <section>
            <h2>Latest report — {latest}</h2>
            <table>
                <thead><tr><th>Candidate</th><th>Catches</th><th>Lift</th>
                <th>Alert h/wk</th><th>Front AUC (95% CI)</th><th></th></tr></thead>
                <tbody>
{table_rows()}
                </tbody>
            </table>
        </section>
    </main>

    <footer>
        <p>Auto-generated from <a href="https://github.com/Kickoman/rain-analysis">rain-analysis</a></p>
        <p>Data: <a href="data.json">data.json</a> · generated {data['generated_at'][:19]}Z</p>
    </footer>

    <script>
    const layout = (title, yTitle, refLine) => ({{
        margin: {{t: 10, r: 10, b: 40, l: 50}},
        height: 340,
        xaxis: {{title: '', type: 'date'}},
        yaxis: {{title: yTitle}},
        legend: {{orientation: 'h', y: -0.2}},
        shapes: refLine === null ? [] : [{{
            type: 'line', xref: 'paper', x0: 0, x1: 1,
            y0: refLine, y1: refLine,
            line: {{dash: 'dash', width: 1, color: '#8a8f98'}}
        }}],
        paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)'
    }});
    const config = {{responsive: true, displayModeBar: false}};
    Plotly.newPlot('auc-chart', {json.dumps(auc_traces)}, layout('', 'front AUC', 0.5), config);
    Plotly.newPlot('lift-chart', {json.dumps(lift_traces)}, layout('', 'lift over random', 1.0), config);
    Plotly.newPlot('cost-chart', {json.dumps(cost_traces)}, layout('', 'alert-hours / week', null), config);
    </script>
</body>
</html>
"""
    (out_dir / "index.html").write_text(html)
    print(f"✅ metrics/index.html — {len(dates)} onset reports, {len(latest_rows)} candidates")
    return 0


if __name__ == "__main__":
    sys.exit(main())
