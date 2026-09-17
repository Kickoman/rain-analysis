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
from glyphs import to_ascii  # noqa: E402
from page_shell import render_page  # noqa: E402

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
        print("[x] history/ not found — nothing to build metrics from", file=sys.stderr)
        return 1

    dates, series, latest_rows, skipped = collect(history_dir)
    if not dates:
        print("[x] no onset-format reports found in history/", file=sys.stderr)
        for name, why in skipped:
            print(f"   • {name}: {why}", file=sys.stderr)
        return 1

    if skipped:
        print(f"[i] {len(dates)} onset reports plotted; {len(skipped)} older reports skipped")

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
        # ASCII marks; report_parse._VERDICT_MARK reads both spellings, so the
        # pages already on gh-pages keep parsing.
        marks = {"works": "[ok]", "ranks_only": "[~]", "one_label_only": "[!]", "chance": "—"}
        cells = []
        for r in sorted(latest_rows, key=lambda row: -(row.get("roc_auc") or 0)):
            ci = r.get("roc_auc_ci") or [None, None]
            ci_txt = f"{ci[0]:.2f}–{ci[1]:.2f}" if ci[0] is not None else "—"
            mark = marks.get(r.get("verdict"), "—")
            caught = f"{r['caught']}/{r['onsets']}"
            cells.append(
                f"                    <tr><td><code>{r['model']}</code></td>"
                f"<td>{caught}</td>"
                f"<td>{fmt(r.get('lift'))}</td>"
                f"<td>{fmt(r.get('alert_hours_per_week'), 0)}</td>"
                f"<td>{fmt(r.get('roc_auc'))} ({ci_txt})</td>"
                f"<td>{mark}</td></tr>"
            )
        return "\n".join(cells)

    # The page carries data, not code: assets/metrics-charts.js reads this
    # block, picks its axis and legend colours out of the stylesheet and
    # redraws them when the theme switch flips. `</script>` cannot appear in
    # the payload — every model name matches [\w_]+ — but the escape is free.
    charts = [
        {"target": "auc-chart", "yTitle": "front AUC", "refLine": 0.5, "traces": auc_traces},
        {"target": "lift-chart", "yTitle": "lift over random", "refLine": 1.0, "traces": lift_traces},
        {"target": "cost-chart", "yTitle": "alert-hours / week", "refLine": None, "traces": cost_traces},
    ]
    chart_json = json.dumps({"charts": charts}).replace("<", "\\u003c")

    body = f"""        <section class="intro">
            <h1>onset prediction over time</h1>
            <p>Every point is one report, scored on the whole record up to that day:
            standing in a dry hour, did anything warn that rain would start within
            three hours? Rain already falling is excluded, so a model that merely
            recognises wet weather earns nothing here.</p>
        </section>

        <section>
            <h2>skill — front AUC</h2>
            <p>0.5 is a coin toss; the dashed line marks it. A series that hugs
            that line has no ability to anticipate rain, however well it scores
            on other targets.</p>
            <div id="auc-chart"></div>
        </section>

        <section>
            <h2>is it aiming, or just yelling? — lift over random</h2>
            <p>How many rain starts the model caught, divided by how many the
            same number of alert-hours would catch scattered at random. At or
            below 1.0 the alerts carry no information.</p>
            <div id="lift-chart"></div>
        </section>

        <section>
            <h2>what it costs — alert-hours per week</h2>
            <p>Hours a week the alert would be raised at the threshold each model
            is scored at. This is the number a person actually pays.</p>
            <div id="cost-chart"></div>
        </section>

        <section>
            <h2>latest report — {latest}</h2>
            <div class="table-wrap">
            <table>
                <thead><tr><th>candidate</th><th>catches</th><th>lift</th>
                <th>alert h/wk</th><th>front auc (95% ci)</th><th></th></tr></thead>
                <tbody>
{table_rows()}
                </tbody>
            </table>
            </div>
            <p><a href="data.json">data.json</a> holds every series in full ·
            generated {data['generated_at'][:19]}Z</p>
        </section>"""

    html = render_page(
        title="Rain Onset Metrics",
        description="How well anything predicts the start of rain, tracked day by day.",
        subtitle=headline,
        body=to_ascii(body),
        active="metrics",
        root="../",
        extra_head='    <script src="https://cdn.plot.ly/plotly-2.35.2.min.js" charset="utf-8"></script>\n'
                   '    <script src="../assets/metrics-charts.js" defer></script>',
        extra_body=f'    <script id="chart-data" type="application/json">{chart_json}</script>',
    )

    (out_dir / "index.html").write_text(html)
    print(f"[ok] metrics/index.html — {len(dates)} onset reports, {len(latest_rows)} candidates")
    return 0


if __name__ == "__main__":
    sys.exit(main())
