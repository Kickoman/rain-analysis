#!/usr/bin/env python3
"""Generate root index.html (landing page) from the latest daily report.

Reads current/index.html, extracts the best model + date, and produces
a landing page with up-to-date model descriptions and latest results.
"""

import sys
from pathlib import Path
import re
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent))
from report_parse import (  # noqa: E402
    extract_best_model,
    extract_date,
    extract_leaderboard,
    extract_onset_date,
    extract_onset_scoreboard,
    extract_onset_window,
    extract_recommended,
    is_onset_report,
    strip_tags,
)
from page_head import head_tags  # noqa: E402


# Single source of truth for model descriptions.
#
# Deliberately carries no F1 values: these are static constants, and the numbers
# that used to live here were pre-2026-08-13 figures the changelog has since
# declared superseded — the homepage showed `tuned` at 0.441 here and 0.273 in
# the live table three sections below. The ✅/❌ prefixes stay; _is_failed_experiment
# depends on them.
MODEL_DESCRIPTIONS = {
    "original":           "Baseline v0.1 — dew-point spread + trend",
    "tuned":              "Grid-search optimized parameters",
    "trend_dominant":     "❌ Failed experiment — trend-primary",
    "ha_live_actual":     "✅ Production — actual HA sensor",
    "ha_live_replica":   "🔄 Replica backtest of production formula",
    "ha_live":            "✅ Production — deployed in Home Assistant — legacy",
    "pressure_aware":     "Pressure-corrected baseline",
    "pressure_absolute":  "Absolute pressure + trend",
    "pressure_long_window": "12h pressure window",
    "pressure_lagged":    "Pressure lagged by 6h",
    "pressure_combined":  "Combined pressure signals",
    "combined":           "✅ Fully combined — temp + humidity + pressure signals",
}


_strip_tags = strip_tags


def _is_failed_experiment(model_name: str) -> bool:
    """Check if a model is marked as a failed experiment in MODEL_DESCRIPTIONS.
    
    Returns True if the model's description starts with ❌, indicating
    it's a known failed experiment that should not be considered a valid "best model".
    """
    desc = MODEL_DESCRIPTIONS.get(model_name, "")
    return desc.startswith("❌")


def _extract_onset_meta(html: str) -> dict:
    """Headline facts from an onset-format report.

    The landing page used to lead with "best model by F1", a nowcast score:
    the model best at noticing rain that is already falling. That is the one
    thing the alert cannot use, so the hero now carries the onset verdict —
    what warns before rain starts, how often, and at what cost — or says
    plainly that nothing does.
    """
    text = _strip_tags(html)
    window = extract_onset_window(html)
    rows = extract_onset_scoreboard(html)
    recommended = extract_recommended(text)
    proven = [r for r in rows if r.get("verdict") == "works"]
    deployed = next((r for r in rows if r["model"] == "ha_live_actual"), None)
    return {
        "date": extract_onset_date(html),
        "onset_format": True,
        "rows": rows,
        "recommended": recommended,
        "proven": proven,
        "deployed": deployed,
        "window_days": window.get("window_days"),
        "onsets": window.get("onsets"),
    }


def _extract_report_meta(html: str) -> dict[str, str | None]:
    """Parse current/index.html for date and best model info."""
    text = _strip_tags(html)

    meta: dict[str, str | None] = {"date": None, "best_model": None, "best_f1": None, "om_coverage": None}
    meta["date"] = extract_date(text)

    model = extract_best_model(text)
    if model:
        meta["best_model"] = model
        # Read the metric from the located leaderboard, matching the model name
        # as a whole cell. The previous unanchored search matched "combined"
        # inside "pressure_combined</td>" and, on an N/A row, walked forward into
        # the Temporal Metrics table and reported its score instead.
        for row in extract_leaderboard(html):
            if row["model"] == model:
                meta["best_f1"] = None if row["f1"] is None else f"{row['f1']:.3f}"
                break

    # Extract Open-Meteo coverage (issue #342)
    cov_m = re.search(r'Open-Meteo precipitation:\s*([0-9.]+)%', text)
    if cov_m:
        meta["om_coverage"] = float(cov_m.group(1))

    return meta


def _detect_models(html: str) -> list[dict]:
    """Models named in the leaderboard, each with its F1 (``None`` when N/A).

    Models whose metrics are all ``N/A`` are kept rather than dropped: the
    production model `ha_live_actual` reports N/A whenever the analysis window
    reaches past the Home Assistant recorder's retention, and silently removing
    it from the homepage hides that instead of explaining it.
    """
    return [{"model": r["model"], "f1": r["f1"]} for r in extract_leaderboard(html)]


def build_onset_landing(html_content: str) -> None:
    """Landing page for the onset-first report format.

    One hero fact, one table, and the honest caveat. The old page listed
    fifteen models with nowcast F1 next to each; that list answered "which
    model notices rain best" for a product whose entire job is to speak before
    the rain, so it is gone.
    """
    meta = _extract_onset_meta(html_content)
    date = meta["date"] or datetime.utcnow().strftime("%Y-%m-%d")
    proven, deployed = meta["proven"], meta["deployed"]
    rec = meta["recommended"]

    if proven:
        best = max(proven, key=lambda r: r.get("lift") or 0)
        thr = f" at {rec['threshold']:.0f}%" if rec and rec["model"] == best["model"] else ""
        headline = (
            f"<strong><code>{best['model']}</code>{thr}</strong> warns before "
            f"{best['caught']} of {best['onsets']} rain starts "
            f"({best['caught'] / best['onsets'] * 100:.0f}%), costing "
            f"{best['alert_hours_per_week']:.0f} alert-hours a week — "
            f"{best['lift']:.2f}× better than alerting at random."
        )
    else:
        headline = ("<strong>Nothing currently beats a coin toss.</strong> No candidate's "
                    "confidence interval clears chance on both yardsticks.")

    if deployed and deployed.get("verdict") != "works":
        deployed_line = (
            f"The sensor actually deployed in Home Assistant, <code>ha_live_actual</code>, "
            f"scores {deployed['roc_auc']:.2f} — chance is 0.50. It reaches "
            f"{deployed['caught']} of {deployed['onsets']} starts, which is what "
            f"{deployed['alert_hours_per_week']:.0f} alert-hours a week reach by luck."
        )
    elif deployed:
        deployed_line = (f"The deployed sensor <code>ha_live_actual</code> clears chance "
                         f"({deployed['roc_auc']:.2f}).")
    else:
        deployed_line = "The deployed sensor had no data in this window."

    marks = {"works": "✅", "ranks_only": "◐", "one_label_only": "⚠️", "chance": "—"}

    def row_html(r: dict) -> str:
        lift = "—" if r.get("lift") is None else f"{r['lift']:.2f}"
        hours = "—" if r.get("alert_hours_per_week") is None else f"{r['alert_hours_per_week']:.0f}"
        auc = "—" if r.get("roc_auc") is None else f"{r['roc_auc']:.2f}"
        ci = r.get("roc_auc_ci") or [None, None]
        ci_txt = f" ({ci[0]:.2f}–{ci[1]:.2f})" if ci[0] is not None else ""
        return (f"<tr><td><code>{r['model']}</code></td>"
                f"<td>{r['caught']}/{r['onsets']}</td><td>{lift}</td>"
                f"<td>{hours}</td><td>{auc}{ci_txt}</td>"
                f"<td>{marks.get(r.get('verdict'), '—')}</td></tr>")

    top = sorted(meta["rows"], key=lambda r: -(r.get("roc_auc") or 0))[:6]
    table_rows = "\n".join(row_html(r) for r in top)

    landing = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Rain Analysis — Does anything warn before rain?</title>
    {head_tags("Which rain-prediction model warns before rain starts, how often it is right, and what the alerts cost.")}
    <link rel="stylesheet" href="assets/style.css">
</head>
<body>
    <header>
        <h1>🌧️ Will it start raining?</h1>
        <p>One question, measured honestly: does anything warn before the first drop?</p>
        <div id="live-rain-widget"></div>
    </header>

    <nav>
        <a href="index.html" class="active">Home</a>
        <a href="current/index.html">Latest Report</a>
        <a href="history/index.html">History</a>
        <a href="metrics/index.html">Metrics Timeline</a>
        <a href="docs/GLOSSARY.html">Glossary</a>
    </nav>

    <main>
        <section class="latest">
            <h2>Where it stands — {date}</h2>
            <div class="report-card">
                <p>{headline}</p>
                <p>{deployed_line}</p>
                <a href="current/index.html" class="btn">Read the full report →</a>
            </div>
        </section>

        <section class="intro">
            <h2>Top candidates</h2>
            <p>Scored over {meta["window_days"] or "?"} days holding {meta["onsets"] or "?"} rain starts.
            <strong>Catches</strong> counts starts with an alert in the three hours before them;
            <strong>lift</strong> divides that by what the same alert time would catch at random,
            so 1.0 means the alerts carry no information. ✅ marks a candidate that clears chance
            on two independent yardsticks <em>and</em> beats random at its own threshold.</p>
            <table>
                <thead><tr><th>Candidate</th><th>Catches</th><th>Lift</th>
                <th>Alert h/wk</th><th>Front AUC (95% CI)</th><th></th></tr></thead>
                <tbody>
{table_rows}
                </tbody>
            </table>
        </section>

        <section class="quick-links">
            <h2>More</h2>
            <div class="cards">
                <div class="card">
                    <h3>📈 Over time</h3>
                    <p>Has the skill held up, day by day?</p>
                    <a href="metrics/index.html">View →</a>
                </div>
                <div class="card">
                    <h3>📅 Past reports</h3>
                    <p>Every daily report, newest first</p>
                    <a href="history/index.html">Browse →</a>
                </div>
                <div class="card">
                    <h3>📖 Glossary</h3>
                    <p>What onset, lift and lead mean here</p>
                    <a href="docs/GLOSSARY.html">Read →</a>
                </div>
                <div class="card">
                    <h3>💾 Data sources</h3>
                    <p>Where ground truth comes from, and how it fails</p>
                    <a href="docs/DATA_SOURCES.html">Read →</a>
                </div>
            </div>
        </section>
    </main>

    <footer>
        <p>Auto-generated from <a href="https://github.com/Kickoman/rain-analysis">rain-analysis</a> repository</p>
        <p>Last updated: <span id="last-update">{date}</span></p>
    </footer>
    <script src="assets/live-widget.js" defer></script>
</body>
</html>'''

    Path("index.html").write_text(landing)
    print(f"✅ Generated landing page (onset format) — {date}")


def main():
    current_html = Path("current/index.html")
    if not current_html.exists():
        # Exit non-zero. Returning 0 here let the workflow carry on to
        # `git add . && git push`, publishing whatever happened to be on disk
        # while the only sign of trouble was this line in the Actions log.
        print("❌ current/index.html not found — cannot build landing page", file=sys.stderr)
        sys.exit(1)

    html_content = current_html.read_text()

    if is_onset_report(html_content):
        return build_onset_landing(html_content)

    meta = _extract_report_meta(html_content)

    date = meta["date"] or datetime.utcnow().strftime("%Y-%m-%d")
    best_model = meta["best_model"] or "N/A"
    best_f1 = meta["best_f1"]
    om_coverage = meta.get("om_coverage")
    
    # Issue #342: Don't show "best model" if coverage is too low
    LOW_COVERAGE_THRESHOLD = 20.0
    low_coverage = om_coverage is not None and om_coverage < LOW_COVERAGE_THRESHOLD
    
    # Issue #336: Warn if "best model" is a known failed experiment
    failed_experiment = best_model != "N/A" and _is_failed_experiment(best_model)

    # Model list (only models that exist in the report)
    models_in_report = _detect_models(html_content)
    if not models_in_report:
        # Fallback: use known models but mark as stale
        models_in_report = [{"model": m, "f1": None} for m in MODEL_DESCRIPTIONS]
        fallback_note = ' <em>(using fallback model list — table parsing failed)</em>'
    else:
        fallback_note = ''

    def _model_item(entry: dict) -> str:
        name = entry["model"]
        desc = MODEL_DESCRIPTIONS.get(name, "New model — no description yet")
        metric = "⚪ no data this run" if entry["f1"] is None else f"F1={entry['f1']:.3f}"
        return f'                <li><strong>{name}</strong> — {desc} <em>({metric})</em></li>'

    model_items = "\n".join(_model_item(e) for e in models_in_report)

    # Build best model string with warnings
    if low_coverage:
        best_str = f"⚠️ Insufficient data (coverage: {om_coverage:.1f}%)"
    elif failed_experiment:
        # Show the model name/F1 but add a warning that it's a failed experiment
        best_str = f"{best_model} (F1: {best_f1})" if best_f1 else best_model
        best_str += "<br><small style='color: #c0392b;'>⚠️ This is a known failed experiment — see model descriptions</small>"
    else:
        best_str = f"{best_model} (F1: {best_f1})" if best_f1 else best_model

    landing = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Rain Analysis — Model Performance Reports</title>
    {head_tags("Automated performance tracking for rain prediction models, scored against real precipitation data.")}
    <link rel="stylesheet" href="assets/style.css">
</head>
<body>
    <header>
        <h1>🌧️ Rain Prediction Model Analysis</h1>
        <p>Automated performance tracking and reports</p>
        <div id="live-rain-widget"></div>
    </header>

    <nav>
        <a href="index.html" class="active">Home</a>
        <a href="current/index.html">Latest Report</a>
        <a href="history/index.html">History</a>
        <a href="metrics/index.html">Metrics Timeline</a>
        <a href="docs/GLOSSARY.html">Glossary</a>
    </nav>

    <main>
        <section class="intro">
            <h2>About This Project</h2>
            <p>This site tracks the performance of multiple rain prediction models, comparing their accuracy against real precipitation data from multiple sources.</p>

            <h3>Current Models{fallback_note}</h3>
            <ul>
{model_items}
            </ul>
        </section>

        <section class="latest">
            <h2>Latest Results</h2>
            <div class="report-card">
                <h3>Daily Report — {date}</h3>
                <p>{"⚠️ <strong>Low ground truth coverage</strong> — model rankings may be unreliable.<br>" if low_coverage else ""}Best model: <strong>{best_str}</strong></p>
                <a href="current/index.html" class="btn">View Full Report →</a>
            </div>
        </section>

        <section class="quick-links">
            <h2>Quick Links</h2>
            <div class="cards">
                <div class="card">
                    <h3>📊 Current Performance</h3>
                    <p>Latest model metrics and comparisons</p>
                    <a href="current/index.html">View →</a>
                </div>
                <div class="card">
                    <h3>📅 Historical Reports</h3>
                    <p>Browse past analysis results</p>
                    <a href="history/index.html">Browse →</a>
                </div>
                <div class="card">
                    <h3>📈 Metrics Timeline</h3>
                    <p>Track performance trends over time</p>
                    <a href="metrics/index.html">Explore →</a>
                </div>
            </div>
        </section>

        <section class="documentation">
            <h2>📚 Documentation</h2>
            <div class="cards">
                <div class="card">
                    <h3>📖 Glossary</h3>
                    <p>ML metrics definitions (Precision, Recall, F1, F2, Confusion Matrix)</p>
                    <a href="docs/GLOSSARY.html">Read →</a>
                </div>
                <div class="card">
                    <h3>📝 Changelog</h3>
                    <p>What changed in the analysis pipeline, and which results it invalidated</p>
                    <a href="docs/CHANGELOG.html">Read →</a>
                </div>
                <div class="card">
                    <h3>🤖 Models</h3>
                    <p>All rain prediction models and their performance</p>
                    <a href="docs/MODELS.html">Read →</a>
                </div>
                <div class="card">
                    <h3>📊 Baseline Model</h3>
                    <p>Current production model analysis</p>
                    <a href="docs/BASELINE_MODEL.html">Read →</a>
                </div>
                <div class="card">
                    <h3>⚙️ CLI Runner</h3>
                    <p>Complete CLI usage guide</p>
                    <a href="docs/CLI_RUNNER.html">Read →</a>
                </div>
                <div class="card">
                    <h3>💾 Data Sources</h3>
                    <p>Ground truth data sources and quality</p>
                    <a href="docs/DATA_SOURCES.html">Read →</a>
                </div>
                <div class="card">
                    <h3>🔧 Contributing</h3>
                    <p>Development workflow</p>
                    <a href="https://github.com/Kickoman/rain-analysis/blob/master/CONTRIBUTING.md">Read →</a>
                </div>
            </div>
        </section>
    </main>

    <footer>
        <p>Auto-generated from <a href="https://github.com/Kickoman/rain-analysis">rain-analysis</a> repository</p>
        <p>Last updated: <span id="last-update">{date}</span></p>
    </footer>
    <script src="assets/live-widget.js" defer></script>
</body>
</html>'''

    Path("index.html").write_text(landing)
    print(f"✅ Generated landing page — {date}, best: {best_str}")


if __name__ == '__main__':
    main()
