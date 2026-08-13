#!/usr/bin/env python3
"""Generate metrics/index.html with interactive Plotly charts and data table.

Parses all history HTML reports, extracts per-model time series (F1, Precision,
Recall), precipitation source data, and renders an interactive page with:
  - F1 Score over Time (line chart)
  - Precision over Time (line chart)
  - Recall over Time (line chart)
  - Latest Day Comparison (bar chart)
  - Precipitation Sources (bar chart)
  - Data table with all metrics

Also outputs metrics/data.json for programmatic access.
"""

from pathlib import Path
import re
import json
import sys
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent))
from report_parse import (  # noqa: E402
    extract_best_model,
    extract_date,
    extract_leaderboard,
    find_leaderboard_table,
    strip_tags,
)
from page_head import head_tags  # noqa: E402


# ─── Colour palette ───────────────────────────────────────────────────────────
MODEL_COLORS = {
    "ha_live_actual":      "#27ae60",  # green — production (actual)
    "ha_live_replica":    "#2ecc71",  # lighter green — replica backtest
    "ha_live":             "#27ae60",  # green — legacy
    "original":            "#3498db",  # blue
    "tuned":               "#e67e22",  # orange
    "trend_dominant":      "#c0392b",  # red — failed
    "pressure_aware":      "#8e44ad",  # purple
    "pressure_absolute":   "#2c3e50",  # dark
    "pressure_long_window":"#16a085",  # teal
    "pressure_lagged":     "#d35400",  # dark orange
    "pressure_combined":   "#7f8c8d",  # grey
}

FALLBACK_COLORS = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
]


def _color_for(model: str, fallback_index: int) -> str:
    return MODEL_COLORS.get(model, FALLBACK_COLORS[fallback_index % len(FALLBACK_COLORS)])


# ─── HTML parsers ─────────────────────────────────────────────────────────────

# Parsing lives in report_parse; these aliases keep the call sites below short
# and preserve the names the tests import.
_strip_tags = strip_tags
_extract_date = extract_date
_extract_model_rows = extract_leaderboard
_extract_best_model = extract_best_model


def _extract_source_rows(html_content: str) -> list[dict]:
    """Parse precipitation source table rows.
    
    Captures source code (e.g., 'OM', 'MS', 'YX') from cells that may contain
    additional text like 'OM (Open-Meteo)' or 'MS (Meteostat)'.
    """
    pat = re.compile(
        r'<tr>\s*<td>(\w+)(?:\s+\([^)]*\))?</td>\s*'
        r'<td>(\d+)</td>\s*'
        r'<td>(.*?)</td>\s*'
        r'</tr>',
        re.IGNORECASE,
    )
    rows = []
    for m in pat.finditer(html_content):
        # skip "Source" header row
        if m.group(1).lower() == "source":
            continue
        rows.append({
            "source": m.group(1),
            "rain_hours": int(m.group(2)),
            "agreement": m.group(3).strip(),
        })
    return rows


# ─── Main logic ───────────────────────────────────────────────────────────────

def main():
    history_dir = Path("history")
    if not history_dir.exists():
        # Non-zero, not "skipping": the workflow's unconditional `git add .` and
        # push made a skipped generator indistinguishable from a successful one.
        print("❌ history/ not found — nothing to build metrics from", file=sys.stderr)
        sys.exit(1)

    report_files = sorted(
        [f for f in history_dir.glob("*.html") if f.name != "index.html"]
    )
    if not report_files:
        print("❌ history/ contains no reports", file=sys.stderr)
        sys.exit(1)

    dates = []
    # model -> {metric -> [values]}
    model_series: dict[str, dict[str, list[float | None]]] = {}
    best_per_day: list[str] = []
    # date -> list of source rows
    source_data: dict[str, list[dict]] = {}
    
    # Files dropped entirely, and files kept but worth calling out
    skipped_files: list[tuple[str, str]] = []
    flagged_files: list[tuple[str, str]] = []

    for rf in report_files:
        html = rf.read_text()
        text = _strip_tags(html)
        date = _extract_date(text)
        if not date:
            skipped_files.append((rf.name, "date extraction failed"))
            continue

        rows = _extract_model_rows(html)
        if not rows:
            _, how = find_leaderboard_table(html)
            skipped_files.append((rf.name, "leaderboard table not found" if how == "missing"
                                  else "leaderboard contained no model rows"))
            continue

        if all(r["f1"] is None for r in rows):
            # Kept, not skipped: a gap in the chart is the truthful rendering. But
            # it is reported, because an all-N/A leaderboard means that day had no
            # ground truth — not that every model scored zero. Reading the numbers
            # from a later table instead is what used to publish fabricated data.
            flagged_files.append((rf.name, "leaderboard has no numeric metrics (all N/A)"))

        dates.append(date)

        best = _extract_best_model(text)
        best_per_day.append(best or "")

        # Collect model metrics
        for r in rows:
            name = r["model"]
            if name not in model_series:
                model_series[name] = {
                    "f1": [None] * len(dates),
                    "precision": [None] * len(dates),
                    "recall": [None] * len(dates),
                }
            # Ensure all series have same length (pad existing)
            for metric in ("f1", "precision", "recall"):
                series = model_series[name][metric]
                while len(series) < len(dates):
                    series.append(None)
                series[-1] = r.get(metric)

        # Pad models that weren't in this report
        for name, ms in model_series.items():
            for metric in ("f1", "precision", "recall"):
                while len(ms[metric]) < len(dates):
                    ms[metric].append(None)

        # Sources
        sources = _extract_source_rows(html)
        if sources:
            source_data[date] = sources

    if not dates:
        print("❌ No report data — every report failed to parse", file=sys.stderr)
        for fname, reason in skipped_files:
            print(f"   • {fname}: {reason}", file=sys.stderr)
        sys.exit(1)

    # Print summary of skipped files
    if skipped_files:
        print(f"\n⚠️  Parsed {len(dates)}/{len(report_files)} reports; {len(skipped_files)} skipped:")
        for fname, reason in skipped_files:
            print(f"   • {fname}: {reason}")

    if flagged_files:
        print(f"\n⚠️  {len(flagged_files)} report(s) kept but incomplete:")
        for fname, reason in flagged_files:
            print(f"   • {fname}: {reason}")

    # ── Build chart JSON ──────────────────────────────────────────────────

    # Only include models that have at least one non-None value
    active_models = {
        name: ms for name, ms in model_series.items()
        if any(v is not None for v in ms["f1"])
    }

    # Sort models: ha_live first, then by avg F1
    def _model_sort_key(item):
        name, ms = item
        vals = [v for v in ms["f1"] if v is not None]
        avg = sum(vals) / len(vals) if vals else 0.0
        is_prod = name == "ha_live_actual" or name == "ha_live"
        return (0 if is_prod else 1, -avg, name)

    sorted_models = sorted(active_models.items(), key=_model_sort_key)

    # Line chart traces for F1, Precision, Recall
    def _make_line_traces(models, dates, metric, metric_label):
        traces = []
        for idx, (name, ms) in enumerate(models):
            vals = ms[metric]
            # Filter to datapoints where value is not None
            x, y = [], []
            for d, v in zip(dates, vals):
                if v is not None:
                    x.append(d)
                    y.append(v)
            if not y:
                continue
            color = _color_for(name, idx)
            traces.append({
                "x": x, "y": y,
                "type": "scatter", "mode": "lines+markers",
                "name": name,
                "line": {"width": 3 if name == "ha_live_actual" or name == "ha_live" else 1.5,
                         "color": color},
                "marker": {"size": 6 if name == "ha_live_actual" or name == "ha_live" else 4,
                           "color": color},
                "hovertemplate": f"{name}<br>{metric_label}: %{{y:.3f}}<br>%{{x}}<extra></extra>",
            })
        return traces

    f1_traces = _make_line_traces(sorted_models, dates, "f1", "F1")
    prec_traces = _make_line_traces(sorted_models, dates, "precision", "Precision")
    rec_traces = _make_line_traces(sorted_models, dates, "recall", "Recall")

    # Latest day bar chart — only include models with ALL metrics present
    latest_idx = len(dates) - 1
    
    bar_data = []
    for name, ms in sorted_models:
        f1_val = ms["f1"][latest_idx]
        prec_val = ms["precision"][latest_idx]
        rec_val = ms["recall"][latest_idx]
        # Only include if all three metrics are present
        if f1_val is not None and prec_val is not None and rec_val is not None:
            bar_data.append({
                "name": name,
                "f1": f1_val,
                "precision": prec_val,
                "recall": rec_val,
            })
    
    bar_labels = [d["name"] for d in bar_data]
    bar_f1 = [d["f1"] for d in bar_data]
    bar_prec = [d["precision"] for d in bar_data]
    bar_rec = [d["recall"] for d in bar_data]
    bar_colors = [_color_for(d["name"], i) for i, d in enumerate(bar_data)]

    # Source data for precipitation chart
    source_dates = sorted(source_data.keys())
    source_series: dict[str, dict] = {}
    if source_dates and source_data.get(dates[-1]):
        for row in source_data[dates[-1]]:
            source_series[row["source"]] = {"rain_hours": [], "dates": []}
        for sd in source_dates:
            for row in source_data[sd]:
                if row["source"] in source_series:
                    source_series[row["source"]]["dates"].append(sd)
                    source_series[row["source"]]["rain_hours"].append(row["rain_hours"])

    source_traces = []
    source_colors = {"OM": "#3498db", "MS": "#e67e22", "YX": "#2ecc71"}
    for src, data in source_series.items():
        if data["rain_hours"]:
            source_traces.append({
                "x": data["dates"], "y": data["rain_hours"],
                "type": "bar", "name": src,
                "marker": {"color": source_colors.get(src, "#999")},
                "hovertemplate": f"{src}<br>Rain hours: %{{y}}<br>%{{x}}<extra></extra>",
            })

    # ── Build the HTML page ───────────────────────────────────────────────

    chart_data = {
        "dates": dates,
        "models": {name: ms for name, ms in model_series.items()},
        "best_per_day": best_per_day,
        "source_data": {d: rows for d, rows in source_data.items()},
    }

    # Also serialise pre-built trace data so JS doesn't re-process
    chart_config = {
        "f1_traces": f1_traces,
        "prec_traces": prec_traces,
        "rec_traces": rec_traces,
        "bar_labels": bar_labels,
        "bar_f1": bar_f1,
        "bar_prec": bar_prec,
        "bar_rec": bar_rec,
        "bar_colors": bar_colors,
        "source_traces": source_traces,
        "source_has_data": len(source_traces) > 0,
        "last_date": dates[-1],
    }

    # Static table rows
    table_rows = []
    for idx in reversed(range(len(dates))):
        d = dates[idx]
        bm = best_per_day[idx] or "—"
        # Get best model's metrics
        bf1, bpr, brc = "—", "—", "—"
        if bm in model_series:
            ms = model_series[bm]
            if ms["f1"][idx] is not None:
                bf1 = f'{ms["f1"][idx]:.3f}'
                bpr = f'{ms["precision"][idx]:.3f}'
                brc = f'{ms["recall"][idx]:.3f}'
        table_rows.append(
            f'                    <tr>\n'
            f'                        <td>{d}</td>\n'
            f'                        <td>{bm}</td>\n'
            f'                        <td class="metric">{bf1}</td>\n'
            f'                        <td class="metric">{bpr}</td>\n'
            f'                        <td class="metric">{brc}</td>\n'
            f'                    </tr>'
        )

    last_updated = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    chart_config_json = json.dumps(chart_config, separators=(',', ':'))

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Metrics Timeline — Rain Analysis</title>
    {head_tags("Model performance over time: F1, precision and recall for every rain prediction model.")}
    <link rel="stylesheet" href="../assets/style.css">
    <!-- Pinned by hash: without integrity, a changed or compromised CDN file
         executes unchallenged, and renderChart() calls Plotly.newPlot directly,
         so a failed load throws ReferenceError and every chart stays blank. The
         data table below the charts is the fallback either way. -->
    <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"
            integrity="sha384-cCVCZkAjYNxaYKbM8lsArLznDF/SvMFr1jcZrvOpSTCa0W40ZAdLzHCEulnUa5i7"
            crossorigin="anonymous"></script>
    <style>
        .chart-container {{
            background: #fff;
            border-radius: 8px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.12);
            margin: 1.5em 0;
            padding: 0.5em;
        }}
        .chart-row {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1em;
        }}
        @media (max-width: 900px) {{
            .chart-row {{ grid-template-columns: 1fr; }}
        }}
        .chart-full {{
            grid-column: 1 / -1;
        }}
        table {{
            font-size: 0.9em;
        }}
    </style>
</head>
<body>
    <header>
        <h1>🌧️ Rain Prediction Model Analysis</h1>
        <p>Automated performance tracking and reports</p>
        <p style="font-size:0.85em;opacity:0.85;max-width:70ch;margin:0.6em auto 0">
            ⚠️ Points before <strong>2026-08-13</strong> come from the pre-fix
            harness, which scored models on roughly 17 labelled rain hours.
            They are not comparable with later points — see the
            <a href="../docs/CHANGELOG.html">changelog</a>.
        </p>
    </header>

    <nav>
        <a href="../index.html">Home</a>
        <a href="../current/index.html">Latest Report</a>
        <a href="../history/index.html">History</a>
        <a href="../metrics/index.html" class="active">Metrics Timeline</a>
        <a href="../docs/GLOSSARY.html">Glossary</a>
    </nav>

    <main>
        <section>
            <h2>📈 Performance Metrics Over Time</h2>
            <p>Interactive charts tracking model performance evolution. Hover for details, click legend items to toggle, drag to zoom.</p>

            <h3>🏆 F1 Score Timeline</h3>
            <div class="chart-container" id="chart-f1" style="height:450px"></div>

            <h3>🎯 Model Comparison — {chart_config["last_date"]}</h3>
            <div class="chart-row">
                <div class="chart-container" id="chart-bar-f1" style="height:380px"></div>
                <div class="chart-container" id="chart-bar-prec-rec" style="height:380px"></div>
            </div>

            <h3>🎯 Precision Timeline</h3>
            <div class="chart-container" id="chart-precision" style="height:400px"></div>

            <h3>🔄 Recall Timeline</h3>
            <div class="chart-container" id="chart-recall" style="height:400px"></div>

            <h3>🌧️ Precipitation Sources</h3>
            <div class="chart-container" id="chart-sources" style="height:350px"></div>

            <h3>📋 Raw Data Table</h3>
            <table>
                <thead>
                    <tr>
                        <th>Date</th>
                        <th>Best Model</th>
                        <th>F1 Score</th>
                        <th>Precision</th>
                        <th>Recall</th>
                    </tr>
                </thead>
                <tbody>
{chr(10).join(table_rows)}
                </tbody>
            </table>

            <p><em>Last updated: {last_updated}</em></p>
        </section>
    </main>

    <footer>
        <p>Auto-generated from <a href="https://github.com/Kickoman/rain-analysis">rain-analysis</a> repository</p>
    </footer>

    <script>
        const cfg = {chart_config_json};

        // Common layout options
        const layoutBase = {{
            hovermode: "x unified",
            legend: {{ orientation: "h", y: -0.3, font: {{ size: 11 }} }},
            margin: {{ l: 50, r: 20, t: 20, b: 50 }},
            plot_bgcolor: "#fafafa",
            paper_bgcolor: "#fff",
            xaxis: {{ gridcolor: "#eee", tickangle: -30, automargin: true }},
            yaxis: {{ gridcolor: "#eee", rangemode: "tozero" }},
        }};

        function renderChart(id, traces, extraLayout) {{
            const layout = Object.assign({{}}, layoutBase, extraLayout);
            // A blocked or failed CDN leaves Plotly undefined; without this the
            // first newPlot throws and every chart stays an empty box with no
            // explanation. The data table below the charts still has the numbers.
            if (typeof Plotly === "undefined") {{
                document.getElementById(id).innerHTML =
                    '<p style="padding:2em;text-align:center;color:#666">' +
                    'Charts could not load. The full data is in the table below.</p>';
                return;
            }}
            if (traces && traces.length > 0) {{
                Plotly.newPlot(id, traces, layout, {{
                    responsive: true,
                    displayModeBar: true,
                    modeBarButtonsToRemove: ["lasso2d", "select2d"],
                    displaylogo: false,
                }});
            }} else {{
                document.getElementById(id).innerHTML =
                    '<p style="padding:2em;text-align:center;color:#666">No data available yet.</p>';
            }}
        }}

        // Defer all chart rendering until after CSS layout is computed.
        // Prevents Plotly responsive mode from getting 0-width containers
        // inside CSS grid layouts.
        window.addEventListener('load', function() {{
            // F1 timeline
            renderChart("chart-f1", cfg.f1_traces, {{
                yaxis: {{ title: "F1 Score", gridcolor: "#eee", rangemode: "tozero" }},
            }});

            // Precision timeline
            renderChart("chart-precision", cfg.prec_traces, {{
                yaxis: {{ title: "Precision", gridcolor: "#eee", rangemode: "tozero" }},
            }});

            // Recall timeline
            renderChart("chart-recall", cfg.rec_traces, {{
                yaxis: {{ title: "Recall", gridcolor: "#eee", rangemode: "tozero" }},
            }});

            // Bar: F1 comparison
            const f1BarTrace = {{
                x: cfg.bar_labels,
                y: cfg.bar_f1,
                type: "bar",
                name: "F1 Score",
                marker: {{ color: cfg.bar_colors }},
                hovertemplate: "%{{x}}<br>F1: %{{y:.3f}}<extra></extra>",
            }};
            renderChart("chart-bar-f1", [f1BarTrace], {{
                yaxis: {{ title: "F1 Score", gridcolor: "#eee", rangemode: "tozero" }},
            }});

            // Bar: Precision + Recall comparison
            const precBarTrace = {{
                x: cfg.bar_labels,
                y: cfg.bar_prec,
                type: "bar",
                name: "Precision",
                marker: {{ color: "#3498db" }},
                hovertemplate: "%{{x}}<br>Precision: %{{y:.3f}}<extra></extra>",
            }};
            const recBarTrace = {{
                x: cfg.bar_labels,
                y: cfg.bar_rec,
                type: "bar",
                name: "Recall",
                marker: {{ color: "#e67e22" }},
                hovertemplate: "%{{x}}<br>Recall: %{{y:.3f}}<extra></extra>",
            }};
            renderChart("chart-bar-prec-rec", [precBarTrace, recBarTrace], {{
                yaxis: {{ title: "Score", gridcolor: "#eee", rangemode: "tozero" }},
                barmode: "group",
            }});

            // Precipitation sources
            if (cfg.source_has_data) {{
                renderChart("chart-sources", cfg.source_traces, {{
                    yaxis: {{ title: "Rain Hours", gridcolor: "#eee" }},
                    barmode: "group",
                }});
            }} else {{
                document.getElementById("chart-sources").innerHTML =
                    '<p style="padding:2em;text-align:center;color:#666">Precipitation source data will appear as more reports accumulate.</p>';
            }}
        }});
    </script>
</body>
</html>'''

    # Ensure metrics/ directory exists
    Path("metrics").mkdir(exist_ok=True)

    # Write outputs
    Path("metrics/index.html").write_text(html)

    # Also write data.json for programmatic access
    Path("metrics/data.json").write_text(json.dumps(chart_data, indent=2))

    print(f"✅ Generated metrics/index.html — {len(dates)} reports ({dates[0]} to {dates[-1]})")
    print(f"✅ Generated metrics/data.json")


if __name__ == "__main__":
    main()
