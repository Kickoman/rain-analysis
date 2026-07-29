#!/usr/bin/env python3
"""Generate root index.html (landing page) from the latest daily report.

Reads current/index.html, extracts the best model + date, and produces
a landing page with up-to-date model descriptions and latest results.
"""

from pathlib import Path
import re
from datetime import datetime


# Single source of truth for model descriptions
MODEL_DESCRIPTIONS = {
    "original":           "Baseline v0.1 — dew-point spread + trend (F1=0.440)",
    "tuned":              "Grid-search optimized parameters (F1=0.441)",
    "trend_dominant":     "❌ Failed experiment — trend-primary (F1=0.115, worst)",
    "ha_live_actual":     "✅ Production — actual HA sensor (F1=0.484)",
    "ha_live_replica":   "🔄 Replica backtest of production formula",
    "ha_live":            "✅ Production — deployed in Home Assistant (F1=0.484) — legacy",
    "pressure_aware":     "Pressure-corrected baseline",
    "pressure_absolute":  "Absolute pressure + trend",
    "pressure_long_window": "12h pressure window",
    "pressure_lagged":    "Pressure lagged by 6h",
    "pressure_combined":  "Combined pressure signals",
    "combined":           "✅ Fully combined — temp + humidity + pressure signals",
}

# Models that should not be declared "best" (failed experiments)
FAILED_MODELS = {"trend_dominant"}


def _strip_tags(html: str) -> str:
    """Remove HTML tags for plain-text regex matching."""
    return re.sub(r'<[^>]+>', '', html)


def _extract_report_meta(html: str) -> dict[str, str | None]:
    """Parse current/index.html for date, best model info, and coverage."""
    text = _strip_tags(html)

    # Title: "Daily Model Analysis — YYYY-MM-DD" or "<h1>…"
    meta: dict[str, str | None] = {
        "date": None,
        "best_model": None,
        "best_f1": None,
        "coverage_pct": None,
        "rain_hours": None,
        "dry_hours": None,
        "unknown_hours": None,
    }

    m = re.search(r'Daily Model Analysis[^—]*[—–-]\s*(\d{4}-\d{2}-\d{2})', text)
    if m:
        meta["date"] = m.group(1)

    # Best model from the "Best overall (F-beta=N): model @ T%" line
    m = re.search(r'Best overall[^:]*:\s*([\w_]+)', text)
    if m:
        meta["best_model"] = m.group(1)
        # Extract F1 from leaderboard table: <td>model_name</td><td>X.XXX</td>
        f1_m = re.search(
            rf'{re.escape(m.group(1))}</td>\s*<td>([0-9.]+)', html
        )
        if f1_m:
            meta["best_f1"] = f1_m.group(1)

    # Extract ground truth coverage
    # Pattern: "Ground truth distribution:\n- Rain hours: N (X.X%)\n- Dry hours: M (Y.Y%)\n- Unknown: K (Z.Z%)"
    rain_m = re.search(r'Rain hours:\s*(\d+)\s*\(([0-9.]+)%\)', text)
    dry_m = re.search(r'Dry hours:\s*(\d+)\s*\(([0-9.]+)%\)', text)
    unknown_m = re.search(r'Unknown:\s*(\d+)\s*\(([0-9.]+)%\)', text)
    
    if rain_m and dry_m:
        meta["rain_hours"] = int(rain_m.group(1))
        meta["dry_hours"] = int(dry_m.group(1))
        rain_pct = float(rain_m.group(2))
        dry_pct = float(dry_m.group(2))
        meta["coverage_pct"] = rain_pct + dry_pct
    
    if unknown_m:
        meta["unknown_hours"] = int(unknown_m.group(1))

    return meta


def _detect_models(html: str) -> list[str]:
    """Find which models appear in the leaderboard table.
    
    Parses the actual table structure to extract model names dynamically,
    rather than relying on a hardcoded list.
    """
    # Look for table rows with model names
    # Pattern: <tr><td>model_name</td><td>score</td>...
    model_pattern = r'<tr>\s*<td[^>]*>([a-z_]+)</td>\s*<td[^>]*>([0-9.]+)</td>'
    matches = re.findall(model_pattern, html, re.IGNORECASE)
    
    if matches:
        # Return unique model names in order of appearance
        models = []
        seen = set()
        for model_name, _ in matches:
            if model_name not in seen:
                models.append(model_name)
                seen.add(model_name)
        return models
    
    # Fallback: no models found in table
    return []


def _format_best_model_string(meta: dict[str, str | None]) -> str:
    """Format the 'best model' string with appropriate warnings."""
    best_model = meta["best_model"] or "N/A"
    best_f1 = meta["best_f1"]
    coverage = meta.get("coverage_pct")
    
    # Base string
    if best_f1:
        result = f"{best_model} (F1: {best_f1})"
    else:
        result = best_model
    
    # Add warnings
    warnings = []
    
    if best_model in FAILED_MODELS:
        warnings.append("⚠️ This is a known failed experiment")
    
    if coverage is not None and coverage < 10.0:
        warnings.append(f"⚠️ Low coverage ({coverage:.1f}%) — results may be unreliable")
    
    if warnings:
        result += "<br><small style='color: #ff9800;'>" + " • ".join(warnings) + "</small>"
    
    return result


def main():
    current_html = Path("current/index.html")
    if not current_html.exists():
        print("❌ current/index.html not found — skipping landing page")
        return

    html_content = current_html.read_text()
    meta = _extract_report_meta(html_content)

    date = meta["date"] or datetime.utcnow().strftime("%Y-%m-%d")
    best_model = meta["best_model"] or "N/A"
    
    # Format best model with warnings
    best_str = _format_best_model_string(meta)

    # Model list (only models that exist in the report)
    models_in_report = _detect_models(html_content)
    if not models_in_report:
        # Fallback: use known models but mark as stale
        models_in_report = list(MODEL_DESCRIPTIONS.keys())
        fallback_note = ' <em>(using fallback model list — table parsing failed)</em>'
    else:
        fallback_note = ''

    model_items = "\n".join(
        f'                <li><strong>{m}</strong> — {MODEL_DESCRIPTIONS.get(m, "New model — no description yet")}</li>'
        for m in models_in_report
    )

    landing = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Rain Analysis — Model Performance Reports</title>
    <link rel="stylesheet" href="assets/style.css">
</head>
<body>
    <header>
        <h1>🌧️ Rain Prediction Model Analysis</h1>
        <p>Automated performance tracking and reports</p>
    </header>

    <nav>
        <a href="index.html" class="active">Home</a>
        <a href="current/index.html">Latest Report</a>
        <a href="history/index.html">History</a>
        <a href="metrics/index.html">Metrics Timeline</a>
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
                <p>Best model: <strong>{best_str}</strong></p>
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
                    <h3>📖 GLOSSARY.md</h3>
                    <p>ML metrics definitions (Precision, Recall, F1, F2, Confusion Matrix)</p>
                    <a href="docs/GLOSSARY.html">Read →</a>
                </div>
                <div class="card">
                    <h3>🤖 MODELS.md</h3>
                    <p>All rain prediction models and their performance</p>
                    <a href="https://github.com/Kickoman/rain-analysis/blob/master/docs/MODELS.md">Read →</a>
                </div>
                <div class="card">
                    <h3>📊 BASELINE_MODEL.md</h3>
                    <p>Current production model analysis</p>
                    <a href="https://github.com/Kickoman/rain-analysis/blob/master/docs/BASELINE_MODEL.md">Read →</a>
                </div>
                <div class="card">
                    <h3>⚙️ CLI_RUNNER.md</h3>
                    <p>Complete CLI usage guide</p>
                    <a href="https://github.com/Kickoman/rain-analysis/blob/master/docs/CLI_RUNNER.md">Read →</a>
                </div>
                <div class="card">
                    <h3>💾 DATA_SOURCES.md</h3>
                    <p>Ground truth data sources and quality</p>
                    <a href="https://github.com/Kickoman/rain-analysis/blob/master/docs/DATA_SOURCES.md">Read →</a>
                </div>
                <div class="card">
                    <h3>🔧 CONTRIBUTING.md</h3>
                    <p>Development workflow</p>
                    <a href="https://github.com/Kickoman/rain-analysis/blob/master/docs/CONTRIBUTING.md">Read →</a>
                </div>
            </div>
        </section>
    </main>

    <footer>
        <p>Auto-generated from <a href="https://github.com/Kickoman/rain-analysis">rain-analysis</a> repository</p>
        <p>Last updated: <span id="last-update">{date}</span></p>
    </footer>
</body>
</html>'''

    Path("index.html").write_text(landing)
    
    # Log the result with any warnings
    coverage_str = f"{meta.get('coverage_pct', 0):.1f}%" if meta.get('coverage_pct') is not None else "unknown"
    print(f"✅ Generated landing page — {date}, best: {meta['best_model']} (coverage: {coverage_str})")
    
    if meta.get("best_model") in FAILED_MODELS:
        print(f"⚠️  WARNING: Best model '{meta['best_model']}' is a known failed experiment")
    
    if meta.get("coverage_pct") is not None and meta["coverage_pct"] < 10.0:
        print(f"⚠️  WARNING: Low coverage ({meta['coverage_pct']:.1f}%) — results may be unreliable")


if __name__ == '__main__':
    main()
